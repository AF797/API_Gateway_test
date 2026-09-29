"""시나리오 실행기. 같은 계획을 두 방식(직접 호출 / 게이트웨이)으로 동시에 실행하고 결과를 모은다."""
import asyncio
import random
import statistics
import time
from collections import Counter, defaultdict

import httpx

from common.config import gateway_base_url, mock_base_url
from common.platforms import ENDPOINTS, calc_cost

from .scenarios import SCENARIOS, Actor, Scenario

LANES = ("direct", "gateway")


class RunState:
    def __init__(self, scenario: Scenario, plan: list[Actor], focus_user: dict | None):
        self.scenario = scenario
        self.total = sum(len(a.steps) for a in plan)
        self.focus_user = focus_user
        self.records: list[dict] = []
        self.status = "running"
        self.error: str | None = None
        self.started = time.monotonic()
        self.finished: float | None = None


class ScenarioRunner:
    def __init__(self, cfg: dict, store, on_start=None):
        self.cfg = cfg
        self.store = store
        self.on_start = on_start  # 시나리오마다 게이트웨이의 한도·서킷 상태를 비우는 콜백
        self.mock_url = mock_base_url(cfg)
        self.gateway_url = gateway_base_url(cfg)
        self.direct_key = cfg["mock_accounts"]["direct"]
        # 게이트웨이의 플랫폼 호출과 연결 풀을 나눠 쓰지 않도록 별도 클라이언트를 쓴다
        self.client = httpx.AsyncClient(
            timeout=90, limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200))
        self.state: RunState | None = None
        self.users: list[dict] = []
        self._task: asyncio.Task | None = None
        self._background: list[asyncio.Task] = []

    @property
    def running(self) -> bool:
        return self.state is not None and self.state.status == "running"

    async def close(self):
        if self._task:
            self._task.cancel()
        await self.client.aclose()

    def clear(self):
        if not self.running:
            self.state = None

    async def set_error_rate(self, platform: str, rate: float):
        await self.client.post(f"{self.mock_url}/admin/error-rate", json={"platform": platform, "error_rate": rate})

    def background(self, coro):
        """시나리오 도중 상황을 바꾸는 작업(예: 장애 단계 전환). 시나리오가 끝나면 취소된다."""
        self._background.append(asyncio.create_task(coro))

    def start(self, scenario_id: str):
        if self.running:
            raise RuntimeError("이미 실행 중인 시나리오가 있습니다.")
        scenario = SCENARIOS[scenario_id]
        self.users = sorted(self.store.all(), key=lambda u: u["id"])
        plan = scenario.build(self.users, random.Random())
        focus = self.users[scenario.focus_index] if scenario.focus_index is not None else None
        self.state = RunState(scenario, plan, focus)
        self._task = asyncio.create_task(self._run(scenario, plan))

    async def _run(self, scenario: Scenario, plan: list[Actor]):
        state = self.state
        try:
            # 앞 시나리오의 한도 소진·서킷 차단이 다음 시나리오에 번지지 않도록 비운다 (캐시는 유지)
            await self.client.post(f"{self.mock_url}/admin/reset", json={"counters_only": False})
            if self.on_start:
                self.on_start()
            if scenario.before:
                await scenario.before(self)
            state.started = time.monotonic()
            await asyncio.gather(*(self._actor(lane, a) for lane in LANES for a in plan))
        except Exception as exc:  # 시연 화면에 그대로 보여준다
            state.error = f"{type(exc).__name__}: {exc}"
        finally:
            for task in self._background:
                task.cancel()
            self._background.clear()
            if scenario.after:
                try:
                    await scenario.after(self)
                except Exception as exc:
                    state.error = state.error or f"정리 단계 실패: {exc}"
            state.finished = time.monotonic()
            state.status = "done"

    async def _actor(self, lane: str, actor: Actor):
        for delay, (pid, params) in actor.steps:
            if delay:
                await asyncio.sleep(delay)
            await self._send(lane, actor.user, pid, params)

    async def _send(self, lane: str, user: dict, pid: str, params: dict):
        method, path = ENDPOINTS[pid]
        if lane == "direct":
            url, headers = self.mock_url + path, {"Authorization": f"Bearer {self.direct_key}"}
        else:
            url, headers = f"{self.gateway_url}/v1{path}", {"X-API-Key": user["api_key"]}

        state = self.state
        t0 = time.monotonic()
        status, body = 0, {}
        try:
            resp = await self.client.request(
                method, url, headers=headers,
                params=params if method == "GET" else None,
                json=params if method != "GET" else None)
            status = resp.status_code
            try:
                body = resp.json()
            except ValueError:
                body = {}
        except httpx.HTTPError:
            pass

        ok = 200 <= status < 300
        meta = body.get("meta") or {} if isinstance(body, dict) else {}
        error = None
        if not ok:
            error = str(status)
            if lane == "gateway" and isinstance(body.get("error"), dict):
                error = body["error"].get("code") or error
        state.records.append({
            "lane": lane, "t": time.monotonic() - state.started,
            "user_id": user["id"], "platform": pid, "status": status, "ok": ok, "error": error,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "queued_ms": meta.get("queued_ms", 0), "source": meta.get("source"),
            "list_price": calc_cost(self.cfg["platforms"][pid].get("price"), params),
        })

    # ── 결과 요약 ──────────────────────────────────

    def snapshot(self, mock_stats: dict | None) -> dict:
        state = self.state
        if state is None:
            return {"status": "idle"}
        scn = state.scenario
        end = state.finished or time.monotonic()
        lanes = {}
        for lane in LANES:
            recs = [r for r in state.records if r["lane"] == lane]
            lanes[lane] = _lane_summary(recs)
            lanes[lane]["platform"] = _platform_side(mock_stats, lane) if mock_stats else None
        return {
            "status": state.status, "error": state.error,
            "id": scn.id, "title": scn.title, "summary": scn.summary, "look_for": scn.look_for,
            "elapsed": round(end - state.started, 1), "total": state.total,
            "lanes": lanes, "timeline": _timeline(state.records),
            "focus": _focus(state, scn),
        }


def _lane_summary(recs: list[dict]) -> dict:
    ok = [r for r in recs if r["ok"]]
    lat = sorted(r["latency_ms"] for r in recs)
    cached = [r for r in recs if r["source"] in ("cache", "coalesced")]
    return {
        "done": len(recs),
        "success": len(ok),
        "failed": len(recs) - len(ok),
        "success_rate": round(len(ok) / len(recs) * 100, 1) if recs else None,
        "avg_ms": int(statistics.fmean(lat)) if lat else None,
        "p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
        "max_ms": lat[-1] if lat else None,
        "cached": len(cached),
        "saved_krw": round(sum(r["list_price"] for r in cached), 1),  # 캐시가 없었다면 청구됐을 금액
        "avg_queued_ms": int(statistics.fmean(r["queued_ms"] for r in ok)) if ok else 0,
        "errors": dict(Counter(r["error"] for r in recs if r["error"]).most_common()),
    }


def _platform_side(mock_stats: dict, lane: str) -> dict:
    total = {"calls": 0, "success": 0, "rejected": 0, "errors": 0, "billed": 0.0}
    for p in mock_stats["platforms"].values():
        acc = p["accounts"].get(lane)
        if not acc:
            continue
        total["calls"] += acc["received"]
        total["success"] += acc["success"]
        total["rejected"] += acc["rejected_429"]
        total["errors"] += acc["errors_500"]
        total["billed"] += acc["billed_krw"]
    total["billed"] = round(total["billed"], 1)
    return total


def _timeline(records: list[dict]) -> list[dict]:
    buckets: dict[int, dict] = defaultdict(lambda: {"direct_ok": 0, "direct_fail": 0,
                                                    "gateway_ok": 0, "gateway_fail": 0})
    for r in records:
        buckets[int(r["t"])][f"{r['lane']}_{'ok' if r['ok'] else 'fail'}"] += 1
    if not buckets:
        return []
    return [{"t": s, **buckets[s]} for s in range(max(buckets) + 1)]


def _focus(state: RunState, scn: Scenario) -> dict | None:
    if not state.focus_user:
        return None
    uid = state.focus_user["id"]
    result = {"label": scn.focus_label, "name": state.focus_user["name"], "dept": state.focus_user["dept"]}
    for lane in LANES:
        mine = [r for r in state.records if r["lane"] == lane and r["user_id"] == uid]
        others = [r for r in state.records if r["lane"] == lane and r["user_id"] != uid]
        result[lane] = {
            "user": {"total": len(mine), "success": sum(r["ok"] for r in mine)},
            "others": {"total": len(others), "success": sum(r["ok"] for r in others)},
        }
    return result
