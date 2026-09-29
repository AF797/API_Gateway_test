"""시연 시나리오.

각 시나리오는 '가상 직원(Actor)이 어떤 요청을 어떤 간격으로 보내는지'의 계획을 만든다.
같은 계획을 '직접 호출'과 '게이트웨이 경유' 두 방식으로 동시에 실행해 결과를 비교한다.
"""
import asyncio
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from common.samples import CURRENCIES, NOTICE, REPORTS, SHORT_TEXTS

# 한 단계 = (앞 요청이 끝난 뒤 기다릴 초, (플랫폼 ID, 요청 파라미터))
Step = tuple[float, tuple[str, dict]]


@dataclass
class Actor:
    user: dict
    steps: list[Step]


@dataclass
class Scenario:
    id: str
    title: str
    summary: str
    look_for: list[str]
    build: Callable[[list[dict], random.Random], list[Actor]]
    focus_index: int | None = None       # 따로 결과를 보여줄 직원 (users 목록의 순번)
    focus_label: str | None = None
    before: Callable[..., Awaitable] | None = None
    after: Callable[..., Awaitable] | None = None
    tags: list[str] = field(default_factory=list)


# ── 요청 생성 도우미 ─────────────────────────────────

def biz(rng):
    return "biz", {"b_no": str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(9))}


def fx(currency="USD"):
    return "fx", {"currency": currency}


def translate(text, target="EN"):
    return "translate", {"text": text, "target_lang": target}


def ai(rng):
    report = rng.choice(REPORTS)
    return "ai", {"text": f"[문서번호 DOC-2026-{rng.randint(1000, 9999)}]\n{report}"}


def ocr(rng):
    return "ocr", {"filename": f"receipt_{rng.randint(100000, 999999)}.jpg"}


# ── 시나리오 ────────────────────────────────────────

def build_rush(users, rng):
    return [Actor(u, [(0, biz(rng)), (0, biz(rng))]) for u in users[:15]]


def build_same(users, rng):
    def steps(delay):
        return [(delay, fx("USD")), (0, translate(NOTICE, "EN"))]
    return [Actor(u, steps(0)) for u in users[:20]] + [Actor(u, steps(3)) for u in users[20:30]]


def build_ai(users, rng):
    return [Actor(u, [(0, ai(rng))]) for u in users[:10]]


def build_heavy(users, rng):
    heavy = users[0]
    # 자동화 스크립트: 작업자 10개가 0.15초 간격으로 30건씩 쏟아낸다
    actors = [Actor(heavy, [(0.15 if i else 0, biz(rng)) for i in range(30)]) for _ in range(10)]
    for u in users[1:11]:
        actors.append(Actor(u, [(0.5 + rng.uniform(0, 0.5), biz(rng)), (1.5, biz(rng)), (1.5, biz(rng))]))
    return actors


OUTAGE_PHASES = [(0.3, 10), (1.0, 7), (0.0, None)]  # (오류율, 유지 시간): 불안정 → 완전 장애 → 복구


async def outage_before(ctx):
    async def phases():
        for rate, hold in OUTAGE_PHASES:
            await ctx.set_error_rate("ocr", rate)
            if hold is None:
                return
            await asyncio.sleep(hold)
    ctx.background(phases())


async def outage_after(ctx):
    await ctx.set_error_rate("ocr", ctx.cfg["platforms"]["ocr"].get("error_rate", 0.0))


def build_outage(users, rng):
    actors = []
    for i, u in enumerate(users[:4]):
        steps, elapsed = [(i * 0.6, ocr(rng))], i * 0.6
        while elapsed < 30:
            gap = rng.uniform(1.5, 2.5)
            elapsed += gap + 1.0  # OCR 응답 시간(약 1초)만큼 더 걸린다
            steps.append((gap, ocr(rng)))
        actors.append(Actor(u, steps))
    return actors


RETIREE_INDEX = 5


async def revoke_before(ctx):
    ctx.store.set_active(ctx.users[RETIREE_INDEX]["id"], False)


async def revoke_after(ctx):
    ctx.store.set_active(ctx.users[RETIREE_INDEX]["id"], True)


def build_revoke(users, rng):
    actors = []
    for i, u in enumerate(users[:6]):
        first, second = SHORT_TEXTS[i % 5][0], SHORT_TEXTS[(i + 2) % 5][0]
        actors.append(Actor(u, [(0, translate(first)), (1.0, translate(second))]))
    return actors


def build_daily(users, rng):
    kinds = ["biz", "fx", "translate", "ai", "ocr"]
    weights = [35, 20, 25, 10, 10]

    def action():
        kind = rng.choices(kinds, weights)[0]
        if kind == "biz":
            return biz(rng)
        if kind == "fx":
            return fx(rng.choice(CURRENCIES))
        if kind == "translate":
            return translate(rng.choice(SHORT_TEXTS)[0], rng.choice(["EN", "JA"]))
        if kind == "ai":
            return ai(rng)
        return ocr(rng)

    actors = []
    for u in users:
        first = rng.uniform(0, 3)
        steps, elapsed = [(first, action())], first
        while elapsed < 20:
            gap = rng.uniform(1.5, 5)
            elapsed += gap
            steps.append((gap, action()))
        actors.append(Actor(u, steps))
    return actors


SCENARIOS: dict[str, Scenario] = {s.id: s for s in [
    Scenario(
        "rush", "출근 시간 몰림",
        "15명이 동시에 거래처 조회(초당 5회 제한)를 2건씩 요청합니다.",
        ["직접 호출은 한도를 넘는 요청이 곧바로 429 에러로 실패합니다.",
         "게이트웨이는 초과분을 대기열에 넣어 전부 성공시키고, 일부만 몇 초 늦게 응답합니다."],
        build_rush, tags=["속도 제한", "대기열"]),
    Scenario(
        "same", "같은 요청 반복",
        "30명이 오늘의 USD 환율과 같은 사내 공지 번역을 요청합니다. 10명은 3초 뒤에 요청합니다.",
        ["직접 호출은 30명 모두 플랫폼을 호출해서 번역 요금이 30번 청구됩니다.",
         "게이트웨이는 요청 병합과 캐시로 환율과 번역을 각각 한 번만 호출합니다."],
        build_same, tags=["캐시", "요청 병합", "비용 절감"]),
    Scenario(
        "ai", "AI 요약 폭주",
        "10명이 동시에 보고서 요약을 요청합니다. (동시 3건 제한, 응답 2~3초)",
        ["직접 호출은 3건만 처리되고 나머지 7건은 거절됩니다.",
         "게이트웨이는 동시 3건을 유지하며 순서대로 처리해서 모두 성공시킵니다.",
         "게이트웨이 쪽 청구액이 더 큰 것은 거절 없이 10건을 모두 처리했기 때문입니다. "
         "누가 얼마를 썼는지는 아래 직원별 사용량에서 확인할 수 있습니다."],
        build_ai, tags=["동시 실행 제한", "비용 집계"]),
    Scenario(
        "heavy", "과다 사용자",
        "한 명이 자동화 스크립트로 300건을 쏟아내는 동안 다른 10명이 평소처럼 거래처를 조회합니다.",
        ["직접 호출은 한 사람이 플랫폼 한도를 독점해서 다른 직원들까지 실패합니다.",
         "게이트웨이는 과다 사용자만 개인 한도로 막고 다른 직원은 정상 처리합니다."],
        build_heavy, focus_index=0, focus_label="과다 사용자", tags=["사용자별 한도", "공정성"]),
    Scenario(
        "outage", "플랫폼 장애",
        "4명이 약 30초 동안 영수증 인식을 요청하는 중에 OCR 플랫폼이 "
        "불안정(0~10초, 오류율 30%) → 완전 장애(10~17초) → 복구(17초~) 순으로 바뀝니다.",
        ["불안정 구간: 게이트웨이는 실패한 요청을 자동으로 재시도해서 대부분 성공시킵니다.",
         "완전 장애 구간: 서킷 브레이커가 열려 장애 플랫폼을 더 두드리지 않고, 직원에게는 기다리게 하지 않고 "
         "바로 실패를 알려줍니다. 로그의 '서킷 차단(빠른 실패)'을 확인해 보세요.",
         "복구 구간: 차단 시간이 지나면 서킷이 스스로 복구를 확인하고 정상으로 돌아옵니다."],
        build_outage, before=outage_before, after=outage_after, tags=["재시도", "서킷 브레이커"]),
    Scenario(
        "revoke", "퇴사자 키 폐기",
        "퇴사자 한 명의 키를 폐기한 뒤, 퇴사자를 포함한 6명이 번역을 요청합니다.",
        ["직접 호출은 공유 키를 알고 있는 퇴사자도 계속 호출할 수 있습니다.",
         "게이트웨이는 해당 직원의 키만 즉시 차단하고, 원본 플랫폼 키는 바꿀 필요가 없습니다."],
        build_revoke, focus_index=RETIREE_INDEX, focus_label="퇴사자",
        before=revoke_before, after=revoke_after, tags=["키 관리", "보안"]),
    Scenario(
        "daily", "평상시 업무 (종합)",
        "50명이 약 25초 동안 5개 플랫폼을 무작위로 사용합니다.",
        ["성공률과 플랫폼 호출 수를 비교해 보세요. 게이트웨이는 더 적게 호출하고도 더 많이 성공합니다.",
         "청구액은 게이트웨이 쪽이 더 클 수 있습니다. 거절되지 않고 실제로 처리된 유료 요청이 많기 때문이며, "
         "'캐시로 아낀 비용'이 중복 호출을 막아 절약한 금액입니다."],
        build_daily, tags=["종합"]),
]}
