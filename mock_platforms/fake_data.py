"""가상 플랫폼이 돌려줄 그럴듯한 가짜 데이터. 같은 입력에는 항상 같은 결과를 낸다."""
import hashlib
import random
import re
from datetime import date, timedelta

from common.samples import TRANSLATIONS


def _rng(*parts) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:12], 16))


# ── 거래처(사업자) 상태 조회 ─────────────────────────────
PREFIXES = ["한빛", "대성", "미래", "세진", "동양", "새한", "태양", "청솔", "가온", "누리",
            "한결", "다온", "해오름", "푸른", "은하", "대륙", "신화", "금강"]
SUFFIXES = ["상사", "물산", "테크", "산업", "정밀", "유통", "솔루션", "전자", "건설", "식품", "무역", "소재"]
SURNAMES = "김이박최정강조윤장임한오서신권황안송"
GIVEN = ["민준", "서연", "도윤", "하은", "시우", "지우", "예준", "수아", "주원", "지호",
         "하준", "서윤", "지안", "은우", "유진", "현우", "채원", "건우", "다은", "준서"]


def biz_status(b_no: str) -> dict:
    r = _rng("biz", b_no)
    roll = r.random()
    if roll < 0.8:
        status, code, closed = "계속사업자", "01", ""
    elif roll < 0.9:
        status, code, closed = "휴업자", "02", ""
    else:
        status, code = "폐업자", "03"
        closed = (date.today() - timedelta(days=r.randint(30, 900))).strftime("%Y%m%d")
    return {
        "b_no": b_no,
        "company_name": f"(주){r.choice(PREFIXES)}{r.choice(SUFFIXES)}",
        "representative": r.choice(SURNAMES) + r.choice(GIVEN),
        "b_stt": status,
        "b_stt_cd": code,
        "tax_type": "부가가치세 간이과세자" if r.random() < 0.2 else "부가가치세 일반과세자",
        "opened_at": date(r.randint(1995, 2024), r.randint(1, 12), r.randint(1, 28)).isoformat(),
        "end_dt": closed,
    }


# ── 환율 ─────────────────────────────────────────────
FX_BASE = {  # 통화: (기준 환율, 단위, 이름)
    "USD": (1385.20, 1, "미국 달러"),
    "JPY": (921.40, 100, "일본 엔"),
    "EUR": (1502.80, 1, "유로"),
    "CNY": (191.60, 1, "중국 위안"),
    "GBP": (1768.30, 1, "영국 파운드"),
}


def fx_rate(currency: str) -> dict:
    today = date.today()
    base, unit, name = FX_BASE[currency]
    rate = base * (1 + _rng("fx", currency, today).uniform(-0.008, 0.008))
    return {
        "currency": currency,
        "currency_name": name,
        "unit": unit,
        "deal_base_rate": round(rate, 2),
        "ttb": round(rate * 0.99, 2),   # 송금 받을 때
        "tts": round(rate * 1.01, 2),   # 송금 보낼 때
        "date": today.isoformat(),
    }


# ── 번역 ─────────────────────────────────────────────
def translate(text: str, target_lang: str) -> dict:
    target = target_lang.upper()
    translated = TRANSLATIONS.get(target, {}).get(text) or f"[{target}] {text}"
    return {
        "source_lang": "KO",
        "target_lang": target,
        "translated_text": translated,
        "billed_characters": len(text),
    }


# ── AI 요약 ──────────────────────────────────────────
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def summarize(text: str) -> dict:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip() and not ln.startswith("[문서번호")]
    title = lines[0] if len(lines) > 1 else ""
    body = " ".join(lines[1:]) if len(lines) > 1 else " ".join(lines)
    sentences = [s.strip() for s in _SENTENCE.split(body) if s.strip()]
    summary = " ".join(sentences[:1] + sentences[-1:]) if len(sentences) > 1 else body
    key_points = [s for s in sentences[1:-1] if re.search(r"\d", s)][:3]
    return {
        "title": title,
        "summary": summary,
        "key_points": key_points,
        "usage": {"input_chars": len(text), "output_chars": len(summary) + sum(map(len, key_points))},
    }


# ── 문서 OCR (영수증) ─────────────────────────────────
STORES = [("스타커피 강남점", "214-86-10235"), ("한빛문구 역삼점", "120-81-55372"),
          ("든든한식당", "105-24-80913"), ("오피스마트 삼성점", "211-87-43120"),
          ("모범운수 택시", "314-12-67785"), ("그린주차장", "206-31-90244")]
ITEMS = [("아메리카노", 4500), ("카페라떼", 5000), ("A4 용지 1박스", 32000), ("볼펜 12입", 9600),
         ("점심 정식", 11000), ("택시 요금", 15800), ("주차 요금", 6000), ("회의용 다과", 23000)]


def ocr(filename: str) -> dict:
    r = _rng("ocr", filename)
    store, store_b_no = r.choice(STORES)
    items = []
    for name, price in r.sample(ITEMS, r.randint(1, 3)):
        qty = r.randint(1, 3)
        items.append({"name": name, "qty": qty, "amount": price * qty})
    total = sum(i["amount"] for i in items)
    return {
        "filename": filename,
        "document_type": "receipt",
        "store_name": store,
        "store_b_no": store_b_no,
        "date": (date.today() - timedelta(days=r.randint(0, 20))).isoformat(),
        "items": items,
        "total": total,
        "vat": round(total / 11),
        "confidence": round(r.uniform(0.91, 0.99), 3),
    }
