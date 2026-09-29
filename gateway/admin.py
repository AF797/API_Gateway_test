"""관리자 API: 키 발급·폐기, 사용량 조회, 시나리오 실행, 대시보드 데이터."""
import httpx
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from common.config import mock_base_url
from common.platforms import describe_limit, describe_price
from common.samples import REPORTS, SHORT_TEXTS
from simulator.scenarios import SCENARIOS

from .errors import GatewayError


def require_admin(request: Request, x_admin_key: str | None = Header(default=None)):
    if x_admin_key != request.app.state.cfg["admin_key"]:
        raise GatewayError(401, "ADMIN_ONLY", "관리자 키(X-Admin-Key)가 필요합니다.")


router = APIRouter(prefix="/admin", tags=["관리자 API"], dependencies=[Depends(require_admin)])


class NewKeyIn(BaseModel):
    name: str = Field(..., min_length=1, examples=["홍길동"])
    dept: str = Field(..., min_length=1, examples=["영업1팀"])


class SimulateIn(BaseModel):
    scenario: str = Field(..., examples=["rush"])


def _user_view(s, user: dict, with_key: bool = False) -> dict:
    view = {k: user[k] for k in ("id", "name", "dept", "active")}
    if with_key:
        view["api_key"] = user["api_key"]
    view["today"] = s.usage.today(user["id"])
    view["budget_krw"] = s.cfg["users"]["daily_budget_krw"]
    return view


# ── 키 관리 ─────────────────────────────────────────

@router.get("/users", summary="직원 목록 (키 포함)")
async def list_users(request: Request):
    s = request.app.state
    return [_user_view(s, u, with_key=True) for u in sorted(s.store.all(), key=lambda u: u["id"])]


@router.post("/keys", summary="직원에게 내부 API 키 발급")
async def issue_key(body: NewKeyIn, request: Request):
    s = request.app.state
    return _user_view(s, s.store.create(body.name, body.dept), with_key=True)


@router.delete("/keys/{user_id}", summary="키 폐기 (퇴사자 등)")
async def revoke_key(user_id: str, request: Request):
    user = request.app.state.store.set_active(user_id, False)
    if user is None:
        raise GatewayError(404, "USER_NOT_FOUND", f"직원을 찾을 수 없습니다: {user_id}")
    return {"ok": True, "id": user_id, "active": False}


@router.post("/keys/{user_id}/activate", summary="폐기한 키 다시 활성화")
async def activate_key(user_id: str, request: Request):
    user = request.app.state.store.set_active(user_id, True)
    if user is None:
        raise GatewayError(404, "USER_NOT_FOUND", f"직원을 찾을 수 없습니다: {user_id}")
    return {"ok": True, "id": user_id, "active": True}


# ── 현황 ───────────────────────────────────────────

def _platforms(s, mock: dict | None = None) -> list[dict]:
    status = s.proxy.status()
    mock_platforms = (mock or {}).get("platforms", {})
    return [{
        "id": pid, "name": p["name"],
        "platform_limit": describe_limit(p["platform_limit"]),
        "gateway_limit": describe_limit(p.get("gateway_limit")),
        "price": describe_price(p.get("price")),
        "cache_ttl_sec": p.get("cache_ttl_sec", 0),
        "error_rate": mock_platforms.get(pid, {}).get("error_rate"),  # 가상 플랫폼의 현재 오류율
        **status[pid],
    } for pid, p in s.cfg["platforms"].items()]


def _users(s, limit: int | None = None) -> list[dict]:
    users = [_user_view(s, u) for u in s.store.all()]
    users.sort(key=lambda u: (-u["today"]["calls"], u["id"]))
    return users[:limit] if limit else users


async def _mock_stats(s) -> dict | None:
    try:
        resp = await s.http.get(f"{mock_base_url(s.cfg)}/admin/stats", timeout=2)
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


@router.get("/usage", summary="직원별 사용량")
async def usage(request: Request):
    s = request.app.state
    return {"totals": s.usage.totals(), "users": _users(s)}


@router.get("/platforms", summary="플랫폼별 상태 (대기열, 서킷, 캐시)")
async def platforms(request: Request):
    return _platforms(request.app.state)


@router.get("/dashboard", summary="대시보드용 전체 현황")
async def dashboard(request: Request):
    s = request.app.state
    mock = await _mock_stats(s)
    return {
        "mock_online": mock is not None,
        "scenario": s.runner.snapshot(mock),
        "platforms": _platforms(s, mock),
        "users": _users(s, limit=12),
        "user_count": len(s.store.all()),
        "totals": s.usage.totals(),
        "logs": list(reversed(s.usage.recent))[:40],
    }


# ── 시연 ───────────────────────────────────────────

@router.get("/samples", summary="소개 화면에서 쓰는 샘플 문장")
async def samples():
    return {"short_texts": [ko for ko, _, _ in SHORT_TEXTS], "reports": REPORTS}


@router.get("/scenarios", summary="시나리오 목록")
async def scenarios():
    return [{"id": sc.id, "title": sc.title, "summary": sc.summary, "look_for": sc.look_for, "tags": sc.tags}
            for sc in SCENARIOS.values()]


@router.post("/simulate", summary="시나리오 실행")
async def simulate(body: SimulateIn, request: Request):
    runner = request.app.state.runner
    if body.scenario not in SCENARIOS:
        raise GatewayError(404, "UNKNOWN_SCENARIO", f"없는 시나리오입니다: {body.scenario}")
    try:
        runner.start(body.scenario)
    except RuntimeError as exc:
        raise GatewayError(409, "SIMULATION_RUNNING", str(exc)) from None
    return {"ok": True, "scenario": body.scenario}


@router.get("/simulation", summary="실행 중이거나 마지막으로 실행한 시나리오 결과")
async def simulation(request: Request):
    s = request.app.state
    return s.runner.snapshot(await _mock_stats(s))


@router.post("/reset", summary="시연 데이터 초기화")
async def reset(request: Request):
    s = request.app.state
    if s.runner.running:
        raise GatewayError(409, "SIMULATION_RUNNING", "시나리오가 끝난 뒤 초기화해 주세요.")
    s.proxy.reset()
    s.user_limiter.reset()
    s.usage.reset()
    s.runner.clear()
    for user in s.store.all():
        if not user["active"]:
            s.store.set_active(user["id"], True)
    try:
        await s.http.post(f"{mock_base_url(s.cfg)}/admin/reset", json={"counters_only": False}, timeout=2)
    except httpx.HTTPError:
        pass
    return {"ok": True}
