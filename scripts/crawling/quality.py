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
    verification = datos.get("_image_verification") or {}
    if datos.get("imagen_url"):
        score += 0.15
        chosen = verification.get("chosen") or {}
        clip_score = chosen.get("clip_score")
        if isinstance(clip_score, (int, float)):
            # boost when CLIP is strongly confident; penalise borderline calls
            if clip_score >= 0.75:
                score += 0.05
            elif clip_score < 0.6:
                warnings.append("image_low_clip_confidence")
                score -= 0.05
    else:
        warnings.append("missing_image")
        if verification.get("rejected"):
            warnings.append("image_rejected_by_clip")
            score -= 0.05
    physical = datos.get("especificaciones_fisicas") or {}
    energy = datos.get("especificaciones_electricas") or {}
    hardware = datos.get("componentes_hardware") or {}
    spec_values = [value for group in [physical, energy, hardware] for value in group.values() if value not in [None, "", [], {}]]
    if spec_values:
        score += min(0.3, len(spec_values) * 0.05)
    else:
        warnings.append("missing_specs")
    jsonld = datos.get("_jsonld_extract") or {}
    if jsonld:
        filled = jsonld.get("filled_fields") or []
        # JSON-LD is the most trustworthy source we have. Reward it
        # proportionally to how many fields it filled, capped to avoid
        # drowning every other signal.
        score += min(0.2, 0.04 * len(filled))
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
