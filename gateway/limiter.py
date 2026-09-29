"""트래픽 제어.

- PlatformGate : 플랫폼으로 나가는 요청을 한도에 맞춰 대기열에서 순서대로 내보낸다.
- UserLimiter  : 직원 한 명이 요청을 독점하지 못하게 막는다(초과 시 즉시 거절).
"""
import asyncio
import math
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from .errors import GatewayError


class SlidingWindow:
    """최근 window_sec 동안 max_requests 건까지 허용."""

    def __init__(self, max_requests: int, window_sec: float):
        self.max_requests = max_requests
        self.window_sec = window_sec
        self.hits: deque[float] = deque()

    def _trim(self, now: float):
        while self.hits and self.hits[0] <= now - self.window_sec:
            self.hits.popleft()

    def try_acquire(self) -> float:
        """자리가 있으면 기록하고 0을, 없으면 기다려야 할 초를 반환."""
        now = time.monotonic()
        self._trim(now)
        if len(self.hits) < self.max_requests:
            self.hits.append(now)
            return 0.0
        return self.hits[0] + self.window_sec - now

    def used(self) -> int:
        self._trim(time.monotonic())
        return len(self.hits)


async def _wait_until(awaitable, deadline: float):
    try:
        await asyncio.wait_for(awaitable, timeout=max(deadline - time.monotonic(), 0.001))
    except TimeoutError:
        raise GatewayError(503, "QUEUE_TIMEOUT", "대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
                           retry_after=1) from None


class PlatformGate:
    """플랫폼 하나의 출구. 동시 실행 수(세마포어)와 요청 속도(슬라이딩 윈도우)를 지킨다.

    asyncio.Lock 은 먼저 온 순서대로 깨우므로, 윈도우가 찰 때까지 락을 쥔 채 기다리면
    그 자체가 FIFO 대기열이 된다.
    """

    def __init__(self, limit: dict | None, max_queue: int):
        limit = limit or {}
        self.window = SlidingWindow(limit["max_requests"], limit.get("window_sec", 1)) \
            if limit.get("max_requests") else None
        self.max_concurrent = limit.get("max_concurrent")
        self.semaphore = asyncio.Semaphore(self.max_concurrent) if self.max_concurrent else None
        self.lock = asyncio.Lock()
        self.max_queue = max_queue
        self.waiting = 0
        self.in_flight = 0

    @asynccontextmanager
    async def slot(self, deadline: float):
        if self.waiting >= self.max_queue:
            raise GatewayError(503, "QUEUE_FULL", "대기 중인 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                               retry_after=1)
        self.waiting += 1
        holding = False
        try:
            if self.semaphore:
                await _wait_until(self.semaphore.acquire(), deadline)
                holding = True
            if self.window:
                await self._take_window(deadline)
        except BaseException:
            if holding:
                self.semaphore.release()
            raise
        finally:
            self.waiting -= 1

        self.in_flight += 1
        try:
            yield
        finally:
            self.in_flight -= 1
            if self.semaphore:
                self.semaphore.release()

    async def _take_window(self, deadline: float):
        await _wait_until(self.lock.acquire(), deadline)
        try:
            while True:
                wait = self.window.try_acquire()
                if wait <= 0:
                    return
                if time.monotonic() + wait > deadline:
                    if wait > 60:
                        raise GatewayError(503, "PLATFORM_QUOTA_EXHAUSTED",
                                           "플랫폼 사용 한도를 모두 사용했습니다.", retry_after=math.ceil(wait))
                    raise GatewayError(503, "QUEUE_TIMEOUT", "대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
                                       retry_after=math.ceil(wait))
                await asyncio.sleep(wait)
        finally:
            self.lock.release()

    def status(self) -> dict:
        return {
            "waiting": self.waiting,
            "in_flight": self.in_flight,
            "window_used": self.window.used() if self.window else None,
            "window_max": self.window.max_requests if self.window else None,
            "max_concurrent": self.max_concurrent,
        }


class UserLimiter:
    """직원별 분당 요청 수와 동시 요청 수 제한. 넘으면 기다리게 하지 않고 바로 429."""

    def __init__(self, rate_per_minute: int, max_concurrent: int):
        self.rate_per_minute = rate_per_minute
        self.max_concurrent = max_concurrent
        self.reset()

    def reset(self):
        self.windows: dict[str, SlidingWindow] = defaultdict(lambda: SlidingWindow(self.rate_per_minute, 60))
        self.in_flight: dict[str, int] = defaultdict(int)

    def acquire(self, user_id: str):
        if self.in_flight[user_id] >= self.max_concurrent:
            raise GatewayError(429, "USER_CONCURRENCY_LIMIT",
                               f"동시에 보낼 수 있는 요청은 최대 {self.max_concurrent}건입니다.", retry_after=1)
        wait = self.windows[user_id].try_acquire()
        if wait > 0:
            raise GatewayError(429, "USER_RATE_LIMIT",
                               f"개인 한도(분당 {self.rate_per_minute}회)를 초과했습니다.", retry_after=math.ceil(wait))
        self.in_flight[user_id] += 1

    def release(self, user_id: str):
        self.in_flight[user_id] -= 1
