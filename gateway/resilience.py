"""서킷 브레이커: 플랫폼이 연속으로 실패하면 잠시 호출을 멈추고 즉시 실패 응답을 준다.

closed(정상) → 연속 실패 N회 → open(차단) → open_sec 경과 → half_open(복구 확인)
half_open 에서 성공하면 closed, 실패하면 다시 open.
"""
import math
import time

from .errors import GatewayError


class CircuitBreaker:
    def __init__(self, failure_threshold: int, open_sec: float):
        self.failure_threshold = failure_threshold
        self.open_sec = open_sec
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.open_count = 0

    def _remaining(self) -> float:
        return self.opened_at + self.open_sec - time.monotonic()

    def check(self):
        if self.state == "open":
            remaining = self._remaining()
            if remaining > 0:
                raise GatewayError(503, "CIRCUIT_OPEN", "플랫폼 장애로 호출을 일시 중단했습니다.",
                                   retry_after=math.ceil(remaining))
            self.state = "half_open"

    def record_success(self):
        self.state = "closed"
        self.failures = 0

    def record_failure(self):
        self.failures += 1
        if self.state == "half_open" or (self.state == "closed" and self.failures >= self.failure_threshold):
            self.state = "open"
            self.opened_at = time.monotonic()
            self.open_count += 1

    def status(self) -> dict:
        remaining = max(0, math.ceil(self._remaining())) if self.state == "open" else 0
        return {"state": self.state, "remaining_sec": remaining, "failures": self.failures,
                "open_count": self.open_count}
