from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import sitemap as sitemap_module
from .text_utils import comparable_model

_GENERIC_PATHS = {"/en/collection/", "/collection/", "/en/products/", "/products/", "/en/gallery/", "/gallery/"}


def is_sielaff_public_series_model(modelo: str) -> bool:
    lowered = modelo.lower()
    return lowered.startswith("siline ") and any(token in lowered for token in [" gf ", "snack", "combi", " rp", " lift "])


def resolve_product_url(url: str, fabricante: str, modelo: str) -> str:
    if "sielaff" in fabricante.lower() and is_sielaff_public_series_model(modelo):
        resolved = "https://sielaff.de/en/products/vending-machines/siline-public-series"
        if url.rstrip("/") != resolved.rstrip("/"):
            print(f"[resolver] {fabricante} / {modelo}: {url} -> {resolved} (Sielaff Public series)")
        return resolved

    parsed = urlparse(url)
    generic_paths = {"/en/collection/", "/collection/", "/en/products/", "/products/", "/en/gallery/", "/gallery/"}
    is_collection_index = parsed.path in generic_paths
    is_collection_listing = "/collection/categories/" in parsed.path or "/collection/families/" in parsed.path
    is_family_page = _looks_like_family_page(parsed.path, modelo)

    try:
        from . import http_client

        response = http_client.polite_get(url, timeout=30)
        response.raise_for_status()
    except Exception:
        return url
    soup = BeautifulSoup(response.text, "html.parser")
    same_host_links = [
        anchor
        for anchor in soup.find_all("a", href=True)
        if not urlparse(urljoin(url, anchor["href"])).netloc
        or urlparse(urljoin(url, anchor["href"])).netloc == parsed.netloc
    ]

    looks_like_card_grid = _looks_like_card_grid(same_host_links)
    if (
        not is_collection_index
        and not is_collection_listing
        and not is_family_page
        and not looks_like_card_grid
    ):
        return url

    wanted = comparable_model(modelo)
    tokens = _model_tokens(modelo)
    strong_tokens = [t for t in tokens if any(c.isdigit() for c in t) or len(t) >= 3]
    candidates: list[tuple[float, str, str]] = []
    for anchor in same_host_links:
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(url, anchor["href"])
        href_parsed = urlparse(href)
        if _is_document_or_asset(href_parsed.path):
            continue
        img = anchor.find("img")
        alt_text = (img.get("alt") if img and img.get("alt") else "") or ""
        title_text = anchor.get("title") or ""
        haystack = comparable_model(
            f"{label} {alt_text} {title_text} {href_parsed.path} {href_parsed.fragment}"
        )
        if not haystack:
            continue
        all_strong = bool(strong_tokens) and all(t in haystack for t in strong_tokens)
        prefix_ok = _is_candidate_link(parsed.path, href_parsed.path, href_parsed.fragment)
        if not all_strong and not prefix_ok:
            continue
        score = SequenceMatcher(None, wanted, haystack).ratio()
        if wanted and wanted in haystack:
            score += 1
        matched_tokens = 0
        for token in tokens:
            if token in haystack:
                matched_tokens += 1
                score += 0.45 if len(token) <= 2 else 0.25
        if matched_tokens == 0:
            continue
        if (
            href_parsed.path.rstrip("/") != parsed.path.rstrip("/")
            and href_parsed.path.startswith(parsed.path.rstrip("/") + "/")
        ):
            score += 0.35
        if all_strong:
            score += 0.6
        if href_parsed.fragment:
            score -= 0.05
        candidates.append((score, href, label))
    candidates.sort(reverse=True, key=lambda item: item[0])
    if candidates and candidates[0][0] >= 0.7:
        resolved = candidates[0][1]
        print(f"[resolver] {fabricante} / {modelo}: {url} -> {resolved} ({candidates[0][2]})")
        return resolved
    return url


def _looks_like_card_grid(same_host_links) -> bool:
    """Heuristic: a product listing typically has many anchors with an inner <img>."""
    cards = [a for a in same_host_links if a.find("img") is not None]
    return len(cards) >= 8


def _is_generic_or_listing(url: str, modelo: str) -> bool:
    parsed = urlparse(url)
    # An in-page anchor (#mistral-h85, #section-3) is the navigation
    # resolver telling us "the product lives here in the page". Treat
    # that as specific so the sitemap does not overwrite it.
    if parsed.fragment:
        fragment_slug = comparable_model(parsed.fragment)
        model_slug = comparable_model(modelo)
        if model_slug and any(c.isdigit() for c in model_slug) and model_slug in fragment_slug:
            return False
        if fragment_slug:
            return False
    if parsed.path in _GENERIC_PATHS:
        return True
    if "/collection/categories/" in parsed.path or "/collection/families/" in parsed.path:
        return True
    if _looks_like_family_page(parsed.path, modelo):
        return True
    slug = comparable_model(parsed.path)
    model_slug = comparable_model(modelo)
    if not model_slug or not any(c.isdigit() for c in model_slug):
        return False
    # If the URL slug does not contain the model code at all, treat it as
    # generic. This catches `/smartfridgevending` for `TCN-FFZ-1000`.
    return model_slug not in slug


def resolve_best_product_url(
    url: str,
    fabricante: str,
    modelo: str,
    *,
    use_sitemap: bool = True,
    sitemap_min_score: float = 1.4,
) -> tuple[str, dict]:
    """Two-pronged resolution. Tries navigation-based first, then the
    sitemap of the same host, and picks the better candidate.

    Returns `(final_url, trace_dict)` where `trace_dict` is suitable for
    storing on the normalised extraction for auditing.
    """
    nav_url = resolve_product_url(url, fabricante, modelo)
    nav_changed = nav_url.rstrip("/") != url.rstrip("/")
    nav_specific = not _is_generic_or_listing(nav_url, modelo)

    sitemap_result: Optional[sitemap_module.SitemapResolution] = None
    if use_sitemap and not nav_specific:
        try:
            sitemap_result = sitemap_module.resolve_via_sitemap(
                url, fabricante, modelo, min_score=sitemap_min_score
            )
        except Exception:
            sitemap_result = None

    final_url = nav_url
    chose = "navigation" if nav_changed else "csv"
    if sitemap_result and not nav_specific:
        final_url = sitemap_result.url
        chose = "sitemap"
        print(
            f"[resolver] {fabricante} / {modelo}: sitemap pick -> {sitemap_result.url} "
            f"(score={sitemap_result.score:.2f} matched={sitemap_result.matched_tokens})"
        )

    trace = sitemap_module.ResolutionTrace(
        final_url=final_url,
        nav_attempted=True,
        sitemap=sitemap_result,
        nav_changed=nav_changed,
        chose=chose,
    ).to_dict()
    return final_url, trace


def _looks_like_family_page(path: str, modelo: str) -> bool:
    parts = [part for part in path.strip("/").split("/") if part and len(part) > 2]
    if not parts:
        return False
    if parts[0] in {"en", "es", "fr", "de", "it", "pt"}:
        parts = parts[1:]
    if len(parts) != 1:
        return False
    return comparable_model(parts[0]) in comparable_model(modelo)


def _model_tokens(modelo: str) -> list[str]:
    ignored = {"machine", "machines", "vending", "touchscreen"}
    tokens = []
    for token in re.split(r"[^a-zA-Z0-9]+", modelo):
        token_cmp = comparable_model(token)
        if len(token_cmp) >= 2 and token_cmp not in ignored:
            tokens.append(token_cmp)
    return list(dict.fromkeys(tokens))


def _is_candidate_link(base_path: str, href_path: str, fragment: str) -> bool:
    normalized_base = base_path.rstrip("/") + "/"
    normalized_href = href_path.rstrip("/") + "/"
    if fragment and normalized_href == normalized_base:
        return True
    return normalized_href.startswith(normalized_base) and normalized_href != normalized_base


def _is_document_or_asset(path: str) -> bool:
    return bool(re.search(r"\.(?:pdf|zip|jpg|jpeg|png|webp|svg|ico)(?:$|\?)", path, re.I))
