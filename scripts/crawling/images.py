from __future__ import annotations

import logging
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .text_utils import first_http_url

logger = logging.getLogger(__name__)


def is_probably_bad_image(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    bad_keywords = [
        "logo",
        "favicon",
        "icon",
        "sprite",
        "placeholder",
        "trademark",
        "brandmark",
        "header",
        "blank",
        "spinner",
        "loading",
        "whatsapp",
        "facebook",
        "instagram",
        "linkedin",
        "youtube",
        "twitter",
        "x-twitter",
    ]
    return lowered.startswith("data:") or lowered.endswith((".svg", ".ico")) or any(x in lowered for x in bad_keywords)


def score_image_url(url: str, fabricante: str, modelo: str) -> int:
    lowered = url.lower()
    score = 0
    for word in fabricante.replace("-", " ").split():
        if len(word) > 2 and word.lower() in lowered:
            score += 4
    for word in modelo.replace("-", " ").split():
        if len(word) > 1 and word.lower() in lowered:
            score += 5
    for keyword in ["product", "machine", "maquina", "vending", "catalog", "render", "photo", "image"]:
        if keyword in lowered:
            score += 2
    if any(ext in lowered for ext in [".jpg", ".jpeg", ".png", ".webp"]):
        score += 2
    return score


def collect_image_candidates(
    html: str | None, base_url: str, fabricante: str, modelo: str
) -> list[str]:
    """Return URL candidates sorted by heuristic score (best first, deduped)."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    images: list[str] = []
    for img in soup.find_all("img"):
        candidates = [img.get("src"), img.get("data-src"), img.get("data-lazy-src"), img.get("data-original")]
        srcset = img.get("srcset")
        if srcset:
            candidates.extend(part.strip().split(" ")[0] for part in srcset.split(",") if part.strip())
        for src in candidates:
            if not src:
                continue
            absolute = first_http_url(urljoin(base_url, src))
            if absolute and not is_probably_bad_image(absolute):
                images.append(absolute)
    # also surface OpenGraph / twitter card images, often the canonical product render
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if prop in {"og:image", "og:image:url", "og:image:secure_url", "twitter:image"}:
            absolute = first_http_url(urljoin(base_url, meta.get("content") or ""))
            if absolute and not is_probably_bad_image(absolute):
                images.append(absolute)
    unique = list(dict.fromkeys(images))
    unique.sort(key=lambda item: score_image_url(item, fabricante, modelo), reverse=True)
    return unique


def choose_best_image_from_html(
    html: str | None, base_url: str, fabricante: str, modelo: str
) -> str | None:
    candidates = collect_image_candidates(html, base_url, fabricante, modelo)
    return candidates[0] if candidates else None


def choose_verified_image(
    html: str | None,
    base_url: str,
    fabricante: str,
    modelo: str,
    verifier: Optional[Callable[[str], object]] = None,
    *,
    max_candidates: int = 6,
) -> tuple[Optional[str], Optional[dict]]:
    """Pick the first candidate that passes the (optional) verifier.

    `verifier(url)` must return an object with `is_vending: bool` and
    `to_dict()` (see `image_verifier.VerifierResult`). When no verifier is
    given, fall back to the heuristic top-1 candidate and return
    `(url, None)`.
    """
    candidates = collect_image_candidates(html, base_url, fabricante, modelo)
    if not candidates:
        return None, None
    if verifier is None:
        return candidates[0], None

    rejected: list[dict] = []
    for candidate in candidates[:max_candidates]:
        try:
            result = verifier(candidate)
        except Exception as exc:  # pragma: no cover - verifier should be robust
            logger.warning("image verifier failed for %s: %s", candidate, exc)
            rejected.append({"url": candidate, "error": str(exc)})
            continue
        if getattr(result, "is_vending", False):
            info = result.to_dict() if hasattr(result, "to_dict") else {}
            info["url"] = candidate
            info["rejected"] = rejected
            return candidate, info
        rejected.append({"url": candidate, **(result.to_dict() if hasattr(result, "to_dict") else {})})
    # nothing passed; surface the diagnostic but do NOT return a bad image
    return None, {"url": None, "rejected": rejected, "is_vending": False}
