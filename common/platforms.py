"""가상 플랫폼과 게이트웨이가 함께 쓰는 정의: 엔드포인트, 과금 계산, 한도 설명."""

# 플랫폼 ID -> (HTTP 메서드, 경로). 게이트웨이 경로는 앞에 /v1 이 붙는다.
ENDPOINTS = {
    "ai": ("POST", "/ai/summarize"),
    "biz": ("GET", "/biz/status"),
    "translate": ("POST", "/translate"),
    "fx": ("GET", "/fx/rates"),
    "ocr": ("POST", "/ocr"),
}


def calc_cost(price: dict | None, params: dict) -> float:
    """요청 한 건의 과금액(원)."""
    if not price:
        return 0.0
    text = params.get("text") or ""
    if "per_1000_chars" in price:
        return round(len(text) / 1000 * price["per_1000_chars"], 2)
    if "per_char" in price:
        return round(len(text) * price["per_char"], 2)
    if "per_call" in price:
        return float(price["per_call"])
    return 0.0


def describe_price(price: dict | None) -> str:
    if not price:
        return "무료"
    if "per_1000_chars" in price:
        return f"1,000자당 {price['per_1000_chars']:g}원"
    if "per_char" in price:
        return f"글자당 {price['per_char']:g}원"
    if "per_call" in price:
        return f"건당 {price['per_call']:g}원"
    return "-"


def describe_limit(limit: dict | None) -> str:
    if not limit:
        return "제한 없음"
    parts = []
    if limit.get("max_concurrent"):
        parts.append(f"동시 {limit['max_concurrent']}건")
    if limit.get("max_requests"):
        window = limit.get("window_sec", 1)
        unit = {1: "초당", 60: "분당", 3600: "시간당", 86400: "하루"}.get(window, f"{window:g}초당")
        parts.append(f"{unit} {limit['max_requests']}회")
    return " · ".join(parts) or "제한 없음"
