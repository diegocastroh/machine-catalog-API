from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .text_utils import first_http_url


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


def choose_best_image_from_html(html: str | None, base_url: str, fabricante: str, modelo: str) -> str | None:
    if not html:
        return None
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
    unique = list(dict.fromkeys(images))
    unique.sort(key=lambda item: score_image_url(item, fabricante, modelo), reverse=True)
    return unique[0] if unique else None
