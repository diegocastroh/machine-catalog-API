from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .text_utils import comparable_model


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
    if not is_collection_index and not is_collection_listing and not is_family_page:
        return url
    try:
        response = requests.get(url, timeout=30, headers={"user-agent": "MachineCatalogImporter/1.0"})
        response.raise_for_status()
    except Exception:
        return url
    soup = BeautifulSoup(response.text, "html.parser")
    wanted = comparable_model(modelo)
    tokens = _model_tokens(modelo)
    candidates: list[tuple[float, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(url, anchor["href"])
        href_parsed = urlparse(href)
        link_host = href_parsed.netloc
        if link_host and link_host != parsed.netloc:
            continue
        if _is_document_or_asset(href_parsed.path):
            continue
        if not _is_candidate_link(parsed.path, href_parsed.path, href_parsed.fragment):
            continue
        haystack = comparable_model(f"{label} {href_parsed.path} {href_parsed.fragment}")
        if not haystack:
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
        if href_parsed.path.rstrip("/") != parsed.path.rstrip("/") and href_parsed.path.startswith(parsed.path.rstrip("/") + "/"):
            score += 0.35
        if href_parsed.fragment:
            score -= 0.05
        candidates.append((score, href, label))
    candidates.sort(reverse=True, key=lambda item: item[0])
    if candidates and candidates[0][0] >= 0.7:
        resolved = candidates[0][1]
        print(f"[resolver] {fabricante} / {modelo}: {url} -> {resolved} ({candidates[0][2]})")
        return resolved
    return url


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
