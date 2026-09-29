"""플랫폼 호출기.

캐시 → 요청 병합 → 서킷 확인 → 대기열(PlatformGate) → 호출 → 실패 시 재시도.
원본 플랫폼 키는 여기서만 붙는다. 직원은 이 키를 볼 수 없다.
"""
import asyncio
import json
import time

import httpx

from common.config import mock_base_url
from common.platforms import ENDPOINTS, calc_cost

from .cache import ResponseCache
from .errors import GatewayError
from .limiter import PlatformGate
from .resilience import CircuitBreaker


def _new_stats() -> dict:
    return {"origin_calls": 0, "cache_hits": 0, "coalesced": 0, "retries": 0,
            "platform_429": 0, "platform_errors": 0}


def _retry_after(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("Retry-After", 1))
    except ValueError:
        return 1.0


def _message(resp: httpx.Response) -> str:
    try:
        return resp.json().get("message") or resp.text
    except ValueError:
        return resp.text


class PlatformProxy:
    def __init__(self, cfg: dict, client: httpx.AsyncClient):
        gw = cfg["gateway"]
        self.cfg = cfg
        self.client = client
        self.base_url = mock_base_url(cfg)
        self.api_key = cfg["mock_accounts"]["gateway"]
        self.timeout = gw["request_timeout_sec"]
        self.max_wait = gw["queue_max_wait_sec"]
        self.max_retries = gw["retry"]["max_retries"]
        self.backoff = gw["retry"]["backoff_sec"]
        self.max_retry_after = gw["retry"]["max_retry_after_sec"]
        self.reset()

    def reset(self):
        """캐시와 통계까지 모두 초기화."""
        self.cache = ResponseCache()
        self.stats = {pid: _new_stats() for pid in self.cfg["platforms"]}
        self.reset_limits()

    def reset_limits(self):
        """대기열·한도 윈도우·서킷만 초기화 (캐시는 유지)."""
        gw = self.cfg["gateway"]
        self.gates = {pid: PlatformGate(p.get("gateway_limit"), gw["queue_max_size"])
                      for pid, p in self.cfg["platforms"].items()}
        self.breakers = {pid: CircuitBreaker(gw["circuit_breaker"]["failure_threshold"],
                                             gw["circuit_breaker"]["open_sec"])
                         for pid in self.cfg["platforms"]}

    async def request(self, pid: str, params: dict, started: float) -> tuple[dict, dict]:
        pcfg = self.cfg["platforms"][pid]
        key = f"{pid}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
        result, source = await self.cache.get_or_fetch(
            key, pcfg.get("cache_ttl_sec", 0), pcfg.get("coalesce", False),
            lambda: self._fetch(pid, params, started),
        )
        if source == "cache":
            self.stats[pid]["cache_hits"] += 1
        elif source == "coalesced":
            self.stats[pid]["coalesced"] += 1

        own = source == "origin"  # 비용과 대기 시간은 실제로 호출한 요청에만 매긴다
        meta = {
            "platform": pid,
            "source": source,
            "cached": not own,
            "queued_ms": result["queued_ms"] if own else 0,
            "retries": result["retries"] if own else 0,
            "cost_krw": result["cost"] if own else 0.0,
            "upstream": result["upstream"] if own else None,  # 추적 요청일 때만 직원에게 보여준다
        }
        return result["data"], meta

    async def _send(self, method: str, path: str, params: dict):
        try:
            resp = await self.client.request(
                method, self.base_url + path,
                params=params if method == "GET" else None,
                json=params if method != "GET" else None,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            return resp, None
        except httpx.TimeoutException:
            return None, GatewayError(504, "PLATFORM_TIMEOUT", "플랫폼 응답 시간이 초과되었습니다.")
        except httpx.HTTPError:
            return None, GatewayError(502, "PLATFORM_UNREACHABLE", "플랫폼에 연결할 수 없습니다.")

    async def _fetch(self, pid: str, params: dict, started: float) -> dict:
        method, path = ENDPOINTS[pid]
        gate, breaker, stats = self.gates[pid], self.breakers[pid], self.stats[pid]
        deadline = started + self.max_wait
        queued = 0.0
        error: GatewayError | None = None
        attempts = []

        for attempt in range(self.max_retries + 1):
            if attempt:
                stats["retries"] += 1
            breaker.check()  # 차단 중이면 대기열에 들어가지 않고 바로 실패
            t0 = time.monotonic()
            async with gate.slot(deadline):
                queued += time.monotonic() - t0
                breaker.check()  # 기다리는 동안 서킷이 열렸을 수 있다
                stats["origin_calls"] += 1
                t1 = time.monotonic()
                resp, error = await self._send(method, path, params)
                attempts.append({"status": resp.status_code if resp is not None else error.code,
                                 "ms": int((time.monotonic() - t1) * 1000)})

            if resp is not None and resp.status_code < 400:
                breaker.record_success()
                return {
                    "data": resp.json(),
                    "cost": calc_cost(self.cfg["platforms"][pid].get("price"), params),
                    "retries": attempt,
                    "queued_ms": int(queued * 1000),
                    "upstream": {
                        "method": method,
                        "url": self.base_url + path,
                        "params": params,
                        "authorization": f"Bearer {self.api_key[:11]}****",  # 원본 키는 가려서 보여준다
                        "attempts": attempts,
                    },
                }

            if resp is not None and resp.status_code == 429:
                stats["platform_429"] += 1
                wait = _retry_after(resp)
                if wait > self.max_retry_after:
                    raise GatewayError(503, "PLATFORM_QUOTA_EXHAUSTED", "플랫폼 사용 한도를 모두 사용했습니다.",
                                       retry_after=int(wait))
                error = GatewayError(503, "PLATFORM_RATE_LIMITED", "플랫폼이 요청을 거절했습니다.",
                                     retry_after=int(wait))
            elif resp is not None and resp.status_code < 500:
                raise GatewayError(resp.status_code, "PLATFORM_BAD_REQUEST", _message(resp))
            else:
                # 5xx, 타임아웃, 연결 실패 → 장애로 보고 서킷에 기록
                breaker.record_failure()
                stats["platform_errors"] += 1
                if resp is not None:
                    error = GatewayError(502, "PLATFORM_ERROR", "플랫폼에서 오류가 발생했습니다.")
                wait = self.backoff[min(attempt, len(self.backoff) - 1)]

            if attempt == self.max_retries or time.monotonic() + wait > deadline:
                break
            await asyncio.sleep(wait)

        raise error

    def status(self) -> dict:
        return {
            pid: {**self.gates[pid].status(), "circuit": self.breakers[pid].status(), **self.stats[pid]}
            for pid in self.cfg["platforms"]
        }
