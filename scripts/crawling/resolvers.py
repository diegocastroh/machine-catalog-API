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
    if not is_collection_index and not is_collection_listing:
        return url
    try:
        response = requests.get(url, timeout=30, headers={"user-agent": "MachineCatalogImporter/1.0"})
        response.raise_for_status()
    except Exception:
        return url
    soup = BeautifulSoup(response.text, "html.parser")
    wanted = comparable_model(modelo)
    candidates: list[tuple[float, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(url, anchor["href"])
        link_host = urlparse(href).netloc
        if link_host and link_host != parsed.netloc:
            continue
        haystack = comparable_model(f"{label} {href}")
        if not haystack or "/collection/" not in href:
            continue
        score = SequenceMatcher(None, wanted, haystack).ratio()
        if wanted and wanted in haystack:
            score += 1
        for token in re.split(r"[^a-zA-Z0-9]+", modelo):
            token_cmp = comparable_model(token)
            if len(token_cmp) >= 3 and token_cmp in haystack:
                score += 0.2
        candidates.append((score, href, label))
    candidates.sort(reverse=True, key=lambda item: item[0])
    if candidates and candidates[0][0] >= 0.7:
        resolved = candidates[0][1]
        print(f"[resolver] {fabricante} / {modelo}: {url} -> {resolved} ({candidates[0][2]})")
        return resolved
    return url
