from __future__ import annotations

import re
import unicodedata
from typing import Any


COOKIE_TEXT_MARKERS = [
    "gestionar el consentimiento",
    "politica de cookies",
    "politica de privacidad",
    "almacenar y/o acceder",
    "consentimiento de las cookies",
    "utilizamos cookies",
    "we use cookies",
    "we value your privacy",
    "cookie consent",
    "privacy policy",
    "cookie settings",
    "cookie policy",
    "necessary cookies",
    "functional cookies",
    "analytics cookies",
    "analytical cookies",
    "advertisement cookies",
    "no cookies to display",
    "enable the basic features",
    "collecting feedback",
    "third-party features",
    "third party features",
    "close.svg",
    "notice you can freely give",
    "withdraw your consent",
    "preferences panel",
    "denying consent",
    "accept all",
    "reject all",
    "learn more",
    "notice",
    "necessary measurement",
    "almacenamiento o acceso tecnico",
    "abonado o usuario",
    "fines estadisticos",
    "finalidad legitima",
    "comunicacion a traves",
    "proveedores",
    "preferencias",
    "estadisticas",
    "marketing",
]

PRODUCT_TEXT_MARKERS = [
    "vending",
    "machine",
    "snack",
    "drink",
    "coffee",
    "bluetec",
    "technical",
    "specifications",
    "features",
    "products",
    "modelo",
    "producto",
    "maquina",
]


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )


def slugify(value: str) -> str:
    normalized = strip_accents(value)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.strip().lower()).strip("-")
    return re.sub(r"-+", "-", slug) or "unknown"


def comparable_model(value: str) -> str:
    normalized = strip_accents(value).lower().replace("&", "and").replace("+", "plus")
    return re.sub(r"[^a-z0-9]+", "", normalized)


def remove_cookie_noise(text: str | None) -> str:
    if not text:
        return ""
    cleaned_lines = []
    skipping_cookie_block = False
    for line in str(text).splitlines():
        compact = " ".join(line.split())
        lowered = strip_accents(compact.lower())
        if not compact:
            continue
        if skipping_cookie_block and not any(marker in lowered for marker in PRODUCT_TEXT_MARKERS):
            continue
        if skipping_cookie_block and any(marker in lowered for marker in PRODUCT_TEXT_MARKERS):
            skipping_cookie_block = False
        if any(marker in lowered for marker in COOKIE_TEXT_MARKERS):
            skipping_cookie_block = True
            continue
        if lowered in {"aceptar", "rechazar", "configurar", "guardar preferencias", "accept", "reject", "preferences"}:
            continue
        cleaned_lines.append(compact)
    return "\n".join(cleaned_lines)


def first_http_url(value: str | None) -> str | None:
    if not value:
        return None
    matches = re.findall(r"https?://[^\s\"'<>]+", value)
    if not matches:
        return value.strip() or None
    image_like = [
        match.rstrip(").,;")
        for match in matches
        if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", match, re.I)
    ]
    return (image_like[0] if image_like else matches[0]).rstrip(").,;")


def infer_tipo_maquina(text: str) -> str | None:
    lowered = strip_accents(text.lower())
    if any(x in lowered for x in ["snacks-and-drinks", "snack and drink", "snacks and drinks"]):
        return "combo"
    if any(x in lowered for x in ["combo", "comboplus", "easycombo"]):
        return "combo"
    if any(x in lowered for x in ["drink", "beverage", "bebida", "soda", "can", "bottle", "lata", "botella"]):
        return "drink"
    if any(x in lowered for x in ["snack", "spiral", "espiral", "chips", "chocolate", "candy", "dulces"]):
        return "snack"
    if any(x in lowered for x in ["coffee", "cafe", "espresso", "capuccino", "cappuccino", "vitro"]):
        return "coffee"
    if any(x in lowered for x in ["frozen", "ice cream", "helado", "congelado"]):
        return "frozen"
    if "locker" in lowered:
        return "locker"
    if any(x in lowered for x in ["food", "fresh food", "comida", "meal"]):
        return "food"
    return None


def relevant_sample(text: str, modelo: str) -> str:
    lines = []
    for line in text.splitlines():
        compact_line = " ".join(line.split())
        lowered_line = strip_accents(compact_line.lower())
        if not compact_line:
            continue
        if compact_line.startswith(("* [", "* Products", "* About Rhea", "* Rhea Evolution", "[ ![", "![", "Toggle navigation")):
            continue
        if compact_line in {"x", "×", "#", "Menu"}:
            continue
        if lowered_line.startswith(("spare parts", "corporation", "history", "contact", "news")):
            continue
        if compact_line.count("http") >= 2 or compact_line.count("](") >= 2:
            continue
        lines.append(compact_line)
    compact = " ".join(lines) if lines else " ".join(text.split())
    lowered = strip_accents(compact.lower())
    model_candidates = [strip_accents(modelo.lower())]
    model_candidates.extend(
        word.lower()
        for word in re.split(r"[^a-zA-Z0-9]+", modelo)
        if len(word) >= 4 and word.lower() not in {"siline", "series", "public", "machine", "machines"}
    )
    generic_candidates = [
        "### description",
        "description",
        "measures",
        "product details",
        "technical",
        "specifications",
        "features",
        "#### general information",
        "general information",
        "#### overview",
        "overview",
        "dimensions:",
    ]
    model_positions = [lowered.find(candidate) for candidate in model_candidates if candidate and lowered.find(candidate) >= 0]
    generic_positions = [lowered.find(candidate) for candidate in generic_candidates if lowered.find(candidate) >= 0]
    if model_positions and generic_positions:
        first_model = min(model_positions)
        later_generic = [position for position in generic_positions if position > first_model]
        positions = later_generic or model_positions
    else:
        positions = model_positions or generic_positions
    if not positions:
        return compact
    start = max(min(positions) - 220, 0)
    return compact[start:]
