"""통합 API 게이트웨이.

직원은 발급받은 내부 키(X-API-Key)로 /v1/* 를 호출한다.
게이트웨이는 인증 → 개인 한도 → 예산 → 캐시 → 대기열 → 플랫폼 호출 순서로 처리하고 사용량을 기록한다.
"""
import sqlite3
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from common.config import ROOT, load_config
from simulator.runner import ScenarioRunner

from . import admin
from .auth import UserStore
from .errors import GatewayError
from .limiter import UserLimiter
from .proxy import PlatformProxy
from .usage import UsageTracker

CFG = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    db = sqlite3.connect(data_dir / "gateway.db", check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    http = httpx.AsyncClient(limits=httpx.Limits(max_connections=500, max_keepalive_connections=100))
    store = UserStore(db)
    store.seed(CFG["users"]["count"])

    s = app.state
    s.cfg = CFG
    s.http = http
    s.store = store
    s.usage = UsageTracker(db)
    s.user_limiter = UserLimiter(CFG["users"]["rate_per_minute"], CFG["users"]["max_concurrent"])
    s.proxy = PlatformProxy(CFG, http)

    def reset_limits():
        s.proxy.reset_limits()
        s.user_limiter.reset()

    s.runner = ScenarioRunner(CFG, store, on_start=reset_limits)
    yield
    await s.runner.close()
    await http.aclose()
    db.close()


app = FastAPI(
    title="통합 API 게이트웨이",
    description="사내 직원이 하나의 내부 키로 여러 외부 플랫폼을 사용하는 중앙 API 서버 (프로토타입)",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(admin.router)


@app.exception_handler(GatewayError)
async def gateway_error_handler(request: Request, exc: GatewayError):
    return exc.to_response()


# ── 인증 ───────────────────────────────────────────

def current_user(request: Request, x_api_key: str | None = Header(default=None, description="발급받은 내부 API 키")):
    s = request.app.state
    user = s.store.by_key(x_api_key)
    if user is None:
        raise GatewayError(401, "INVALID_KEY", "유효하지 않은 API 키입니다.")
    if not user["active"]:
        s.usage.record(user, "-", 401, {}, "KEY_REVOKED")
        raise GatewayError(401, "KEY_REVOKED", "폐기된 API 키입니다. 관리자에게 문의하세요.")
    return user


async def serve(request: Request, user: dict, pid: str, params: dict) -> dict:
    s = request.app.state
    started = time.monotonic()
    try:
        s.user_limiter.acquire(user["id"])
    except GatewayError as exc:
        s.usage.record(user, pid, exc.status, {"latency_ms": 0}, exc.code)
        raise

    try:
        if CFG["platforms"][pid].get("price") and \
                s.usage.spent_today(user["id"]) >= CFG["users"]["daily_budget_krw"]:
            raise GatewayError(429, "BUDGET_EXCEEDED",
                               f"오늘 사용 예산({CFG['users']['daily_budget_krw']:,}원)을 모두 사용했습니다.")
        data, meta = await s.proxy.request(pid, params, started)
        meta["latency_ms"] = int((time.monotonic() - started) * 1000)
        s.usage.record(user, pid, 200, meta)
        if request.headers.get("x-trace"):  # 소개 화면에서 '게이트웨이가 대신 보낸 요청'을 보여줄 때
            meta["caller"] = {"id": user["id"], "name": user["name"], "dept": user["dept"]}
        else:
            meta.pop("upstream", None)
        return {"success": True, "data": data, "meta": meta}
    except GatewayError as exc:
        # 병합된 요청들은 같은 에러 객체를 공유하므로 복사본에 meta 를 붙인다
        meta = {"platform": pid, "latency_ms": int((time.monotonic() - started) * 1000)}
        s.usage.record(user, pid, exc.status, meta, exc.code)
        err = GatewayError(exc.status, exc.code, exc.message, exc.retry_after)
        err.meta = meta
        raise err from None
    finally:
        s.user_limiter.release(user["id"])


# ── 직원용 API ──────────────────────────────────────

class SummarizeIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000, description="요약할 문서 본문")


class TranslateIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="번역할 문장")
    target_lang: str = Field("EN", pattern=r"^[A-Za-z]{2}$", description="대상 언어 (EN, JA 등)")


class OcrIn(BaseModel):
    filename: str = Field(..., min_length=1, description="인식할 문서 파일 이름")


TAG = "직원용 API"


@app.post("/v1/ai/summarize", tags=[TAG], summary="문서 요약 (AI)")
async def ai_summarize(body: SummarizeIn, request: Request, user=Depends(current_user)):
    return await serve(request, user, "ai", body.model_dump())


@app.get("/v1/biz/status", tags=[TAG], summary="거래처 사업자 상태 조회")
async def biz_status(request: Request, b_no: str = Query(..., pattern=r"^\d{10}$", description="사업자번호 10자리"),
                     user=Depends(current_user)):
    return await serve(request, user, "biz", {"b_no": b_no})


@app.post("/v1/translate", tags=[TAG], summary="번역")
async def translate(body: TranslateIn, request: Request, user=Depends(current_user)):
    params = body.model_dump()
    params["target_lang"] = params["target_lang"].upper()
    return await serve(request, user, "translate", params)


@app.get("/v1/fx/rates", tags=[TAG], summary="환율 조회")
async def fx_rates(request: Request, currency: str = Query("USD", pattern=r"^[A-Z]{3}$", description="통화 코드"),
                   user=Depends(current_user)):
    return await serve(request, user, "fx", {"currency": currency})


@app.post("/v1/ocr", tags=[TAG], summary="문서 인식 (OCR)")
async def ocr(body: OcrIn, request: Request, user=Depends(current_user)):
    return await serve(request, user, "ocr", body.model_dump())


@app.get("/v1/me/usage", tags=[TAG], summary="내 오늘 사용량과 남은 예산")
async def my_usage(request: Request, user=Depends(current_user)):
    s = request.app.state
    today = s.usage.today(user["id"])
    budget = CFG["users"]["daily_budget_krw"]
    return {"user": {"id": user["id"], "name": user["name"], "dept": user["dept"]},
            "today": today, "budget_krw": budget, "remaining_krw": round(max(budget - today["cost"], 0), 1)}


# ── 대시보드 ────────────────────────────────────────

def _page(name: str) -> HTMLResponse:
    html = (ROOT / "dashboard" / name).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__ADMIN_KEY__", CFG["admin_key"]))  # 시연용: 관리자 키를 페이지에 주입


@app.get("/intro", include_in_schema=False)
async def intro():
    return _page("intro.html")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return _page("index.html")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/intro")
