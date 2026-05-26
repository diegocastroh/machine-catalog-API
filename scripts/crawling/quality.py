from __future__ import annotations

from urllib.parse import urlparse


GENERIC_PATHS = {"/en/collection/", "/collection/", "/en/products/", "/products/", "/en/gallery/", "/gallery/"}


def quality_report(original_url: str, resolved_url: str, modelo: str, datos: dict) -> dict:
    warnings: list[str] = []
    score = 0.35
    parsed = urlparse(resolved_url)
    if parsed.path in GENERIC_PATHS or "/collection/categories/" in parsed.path:
        warnings.append("generic_or_listing_url")
        score -= 0.2
    else:
        score += 0.15
    if datos.get("imagen_url"):
        score += 0.15
    else:
        warnings.append("missing_image")
    physical = datos.get("especificaciones_fisicas") or {}
    energy = datos.get("especificaciones_electricas") or {}
    hardware = datos.get("componentes_hardware") or {}
    spec_values = [value for group in [physical, energy, hardware] for value in group.values() if value not in [None, "", [], {}]]
    if spec_values:
        score += min(0.3, len(spec_values) * 0.05)
    else:
        warnings.append("missing_specs")
    sample = ((datos.get("_crawl4ai_extract") or {}).get("markdown_sample") or (datos.get("_basic_extract") or {}).get("text_sample") or "").lower()
    model_tokens = [token.lower() for token in modelo.replace("&", " ").replace("-", " ").split() if len(token) >= 3]
    if any(token in sample for token in model_tokens):
        score += 0.15
    else:
        warnings.append("model_not_found_in_text")
    score = max(0, min(1, round(score, 2)))
    return {
        "score": score,
        "warnings": warnings,
        "original_url": original_url,
        "resolved_url": resolved_url,
    }
