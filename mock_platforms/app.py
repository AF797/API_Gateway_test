"""가상 외부 플랫폼 서버.

실제 SaaS처럼 계정 키마다 요청 한도를 강제하고, 넘으면 429 + Retry-After 를 돌려준다.
플랫폼별로 받은 요청 수, 거절 수, 과금액을 계정별로 집계한다(= 플랫폼이 보내는 청구서).
"""
import asyncio
import math
import random
import time
import uuid
from collections import deque

from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from common.config import load_config
from common.platforms import calc_cost, describe_limit, describe_price

from . import fake_data

CFG = load_config()
PLATFORMS = CFG["platforms"]
ACCOUNT_BY_KEY = {key: name for name, key in CFG["mock_accounts"].items()}

app = FastAPI(title="가상 외부 플랫폼", description="시연용 가짜 SaaS API 모음", version="1.0")


class AccountLimiter:
    """계정 키 하나에 걸린 한도: 슬라이딩 윈도우 요청 수 + 동시 처리 수."""

    def __init__(self, limit: dict):
        self.max_requests = limit.get("max_requests")
        self.window_sec = limit.get("window_sec", 1)
        self.max_concurrent = limit.get("max_concurrent")
        self.hits: deque[float] = deque()
        self.in_flight = 0

    def try_acquire(self) -> float | None:
        """통과하면 None, 거절하면 기다려야 할 초."""
        now = time.monotonic()
        if self.max_concurrent is not None and self.in_flight >= self.max_concurrent:
            return 1.0
        if self.max_requests is not None:
            while self.hits and self.hits[0] <= now - self.window_sec:
                self.hits.popleft()
            if len(self.hits) >= self.max_requests:
                return self.hits[0] + self.window_sec - now
            self.hits.append(now)
        self.in_flight += 1
        return None

    def release(self):
        self.in_flight -= 1


def _new_stats() -> dict:
    return {"received": 0, "success": 0, "rejected_429": 0, "errors_500": 0, "billed_krw": 0.0}


class MockState:
    def __init__(self):
        self.reset()

    def reset(self, counters_only: bool = False):
        if not counters_only:
            self.limiters: dict[tuple[str, str], AccountLimiter] = {}
            self.error_rates = {pid: p.get("error_rate", 0.0) for pid, p in PLATFORMS.items()}
        self.stats = {pid: {acc: _new_stats() for acc in CFG["mock_accounts"]} for pid in PLATFORMS}

    def limiter(self, pid: str, account: str) -> AccountLimiter:
        key = (pid, account)
        if key not in self.limiters:
            self.limiters[key] = AccountLimiter(PLATFORMS[pid]["platform_limit"])
        return self.limiters[key]


state = MockState()


def _error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message}, headers=headers)


async def handle(pid: str, authorization: str | None, params: dict, produce):
    """모든 플랫폼 엔드포인트의 공통 처리: 인증 → 한도 → 지연 → (장애) → 응답·과금."""
    key = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    account = ACCOUNT_BY_KEY.get(key)
    if account is None:
        return _error(401, "invalid_api_key", "유효하지 않은 API 키입니다.")

    stats = state.stats[pid][account]
    stats["received"] += 1
    limiter = state.limiter(pid, account)
    wait = limiter.try_acquire()
    if wait is not None:
        stats["rejected_429"] += 1
        return _error(429, "rate_limit_exceeded",
                      f"요청 한도({describe_limit(PLATFORMS[pid]['platform_limit'])})를 초과했습니다.",
                      headers={"Retry-After": str(max(1, math.ceil(wait)))})
    try:
        await asyncio.sleep(random.uniform(*PLATFORMS[pid]["latency_sec"]))
        if random.random() < state.error_rates[pid]:
            stats["errors_500"] += 1
            return _error(500, "internal_error", "일시적인 플랫폼 오류입니다.")
        stats["success"] += 1
        stats["billed_krw"] += calc_cost(PLATFORMS[pid].get("price"), params)
        return {"request_id": f"req_{uuid.uuid4().hex[:12]}", **produce()}
    finally:
        limiter.release()


# ── 플랫폼 API ───────────────────────────────────────

class TextIn(BaseModel):
    text: str = Field(..., min_length=1)


class TranslateIn(BaseModel):
    text: str = Field(..., min_length=1)
    target_lang: str = "EN"


class OcrIn(BaseModel):
    filename: str = Field(..., min_length=1)


@app.post("/ai/summarize", tags=["AI 요약"])
async def ai_summarize(body: TextIn, authorization: str | None = Header(default=None)):
    return await handle("ai", authorization, body.model_dump(), lambda: fake_data.summarize(body.text))


@app.get("/biz/status", tags=["거래처 조회"])
async def biz_status(b_no: str = Query(..., pattern=r"^\d{10}$"),
                     authorization: str | None = Header(default=None)):
    return await handle("biz", authorization, {"b_no": b_no}, lambda: fake_data.biz_status(b_no))


@app.post("/translate", tags=["번역"])
async def translate(body: TranslateIn, authorization: str | None = Header(default=None)):
    return await handle("translate", authorization, body.model_dump(),
                        lambda: fake_data.translate(body.text, body.target_lang))


@app.get("/fx/rates", tags=["환율"])
async def fx_rates(currency: str = Query("USD", pattern=r"^[A-Z]{3}$"),
                   authorization: str | None = Header(default=None)):
    if currency not in fake_data.FX_BASE:
        return _error(404, "unsupported_currency", f"지원하지 않는 통화입니다: {currency}")
    return await handle("fx", authorization, {"currency": currency}, lambda: fake_data.fx_rate(currency))


@app.post("/ocr", tags=["문서 OCR"])
async def ocr(body: OcrIn, authorization: str | None = Header(default=None)):
    return await handle("ocr", authorization, body.model_dump(), lambda: fake_data.ocr(body.filename))


# ── 시연 제어용 ──────────────────────────────────────

class ResetIn(BaseModel):
    counters_only: bool = False


class ErrorRateIn(BaseModel):
    platform: str
    error_rate: float = Field(..., ge=0, le=1)


@app.get("/admin/stats", tags=["시연 제어"])
async def stats():
    return {
        "platforms": {
            pid: {
                "name": p["name"],
                "limit": describe_limit(p["platform_limit"]),
                "price": describe_price(p.get("price")),
                "error_rate": state.error_rates[pid],
                "accounts": state.stats[pid],
            }
            for pid, p in PLATFORMS.items()
        }
    }


@app.post("/admin/reset", tags=["시연 제어"])
async def reset(body: ResetIn | None = None):
    state.reset(counters_only=bool(body and body.counters_only))
    return {"ok": True}


@app.post("/admin/error-rate", tags=["시연 제어"])
async def set_error_rate(body: ErrorRateIn):
    if body.platform not in PLATFORMS:
        return _error(404, "unknown_platform", body.platform)
    state.error_rates[body.platform] = body.error_rate
    return {"ok": True, "platform": body.platform, "error_rate": body.error_rate}


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "가상 외부 플랫폼", "docs": "/docs", "platforms": list(PLATFORMS)}
