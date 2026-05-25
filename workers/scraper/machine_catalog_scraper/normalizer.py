import re
from urllib.parse import urljoin


CATEGORY_KEYWORDS = {
    "coffee": ["coffee", "espresso", "bean-to-cup", "cafe", "hot drinks", "fresh milk", "instant"],
    "snack_drink": ["snack", "drink", "combo", "spiral", "glass front", "cold & snack"],
    "cold_beverage": ["beverage", "bottle", "can", "cold drink", "refrigerated"],
    "ice_cream": ["ice cream", "frozen", "freezer", "gelato", "frozen food"],
    "hot_food": ["hot food", "heated", "microwave", "pizza", "warm"],
    "fresh_food": ["fresh food", "salad", "sandwich", "fruit", "vegetable"],
    "smart_locker": ["locker", "pickup", "smart locker", "compartment"],
    "ice_water": ["ice", "water", "bagged ice", "water vending"],
    "industrial": ["industrial", "ppe", "tools", "mro", "inventory control"],
}


def detect_category(text: str) -> str:
    normalized = text.lower()
    for code, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return code
    return "other"


def extract_dimensions(text: str) -> dict:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|in|inch|inches)?", text.lower())
    if not match:
        return {}
    unit = match.group(4) or "mm"
    values = [float(match.group(index).replace(",", ".")) for index in range(1, 4)]
    return {
        "height_mm": to_mm(values[0], unit),
        "width_mm": to_mm(values[1], unit),
        "depth_mm": to_mm(values[2], unit),
    }


def to_mm(value: float, unit: str) -> int:
    if unit == "cm":
        return round(value * 10)
    if unit in {"in", "inch", "inches"}:
        return round(value * 25.4)
    return round(value)


def detect_terms(text: str, terms: list[str]) -> list[str]:
    normalized = text.lower()
    return [term for term in terms if term.lower() in normalized]


def absolute_url(base_url: str, value: str | None) -> str | None:
    return urljoin(base_url, value) if value else None


def confidence_score(*, official: bool, model_name: bool, category: bool, image: bool, document: bool, specs: bool) -> float:
    score = 0
    if official:
        score += 30
    if model_name:
        score += 15
    if category:
        score += 10
    if image:
        score += 10
    if document:
        score += 10
    if specs:
        score += 10
    if not model_name:
        score -= 30
    return max(0, min(1, score / 100))
