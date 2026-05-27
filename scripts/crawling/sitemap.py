"""Sitemap-based URL resolution.

For most manufacturer sites, `/sitemap.xml` exposes every product URL the
search engines should see. That makes it the single best place to look
up "the canonical URL for model X" without doing any HTML navigation at
all. This module:

* Discovers candidate sitemap URLs (robots.txt + a small list of common
  defaults).
* Recursively expands sitemap indexes (`<sitemapindex>`).
* Caches the resulting URL set per host with the same on-disk cache the
  rest of the pipeline uses (24h TTL by default).
* Scores URLs against `(fabricante, modelo)` tokens and returns the best
  match — or `None` if nothing beats the score threshold.

The XML parser is plain `xml.etree.ElementTree` — no extra dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests

from . import cache as page_cache
from . import http_client
from .text_utils import comparable_model

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 20
_MAX_NESTED_SITEMAPS = 25
_MAX_URLS_PER_SITEMAP = 20000

# Sitemap entries that are clearly assets, not product pages. WordPress
# in particular publishes uploads/, image, and document URLs alongside
# real pages; without this filter the resolver gladly picks a PNG whose
# filename happens to contain the model code.
_ASSET_PATH_RE = re.compile(
    r"\.(?:png|jpe?g|webp|gif|bmp|svg|ico|pdf|zip|rar|7z|tar|gz|bz2|mp4|webm|mov|avi"
    r"|css|js|map|xml|rss|atom|woff2?|ttf|eot|otf)(?:$|\?)",
    re.IGNORECASE,
)
_ASSET_PATH_HINTS = (
    "/wp-content/uploads/",
    "/wp-json/",
    "/feed/",
    "/cdn-cgi/",
    "/static/",
    "/assets/",
)

# Common locations to try when robots.txt does not advertise a sitemap.
_FALLBACK_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/wp-sitemap.xml",
    "/page-sitemap.xml",
    "/product-sitemap.xml",
    "/products-sitemap.xml",
    "/sitemap1.xml",
)


@dataclass
class SitemapResolution:
    url: str
    score: float
    matched_tokens: list[str]
    source_sitemap: str

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "score": round(self.score, 4),
            "matched_tokens": self.matched_tokens,
            "source_sitemap": self.source_sitemap,
        }


def resolve_via_sitemap(
    seed_url: str,
    fabricante: str,
    modelo: str,
    *,
    min_score: float = 1.2,
    cache_ttl: int = page_cache.DEFAULT_TTL_SECONDS,
    timeout: int = _DEFAULT_TIMEOUT,
) -> Optional[SitemapResolution]:
    """Look up the best URL for (fabricante, modelo) on the same host as
    `seed_url`. If that host has no sitemap or no useful matches, try the
    registered domain (strip a single subdomain). Returns `None` if
    nothing scores above `min_score`."""
    parsed = urlparse(seed_url)
    if not parsed.netloc or parsed.scheme not in {"http", "https"}:
        return None

    hosts_to_try: list[str] = [parsed.netloc]
    # If host has more than 2 dots (subdomain.example.com), also try the
    # registered domain. This unlocks cases like shop.jetinno.com -> jetinno.com.
    parts = parsed.netloc.split(".")
    if len(parts) >= 3:
        bare = ".".join(parts[-2:])
        if bare not in hosts_to_try:
            hosts_to_try.append(bare)
        with_www = f"www.{bare}"
        if with_www not in hosts_to_try:
            hosts_to_try.append(with_www)

    urls: list[dict] = []
    for host in hosts_to_try:
        host_root = f"{parsed.scheme}://{host}"
        found = _collect_host_urls(host_root, cache_ttl=cache_ttl, timeout=timeout)
        if found:
            urls = found
            break
    if not urls:
        return None

    tokens = _model_tokens(modelo)
    fab_tokens = _model_tokens(fabricante)
    if not tokens:
        return None

    wanted = comparable_model(modelo)
    best: Optional[SitemapResolution] = None
    for entry in urls:
        candidate_url = entry["loc"]
        candidate_path = urlparse(candidate_url).path
        if _is_asset_url(candidate_path):
            continue
        slug = comparable_model(candidate_path)
        if not slug:
            continue
        matched = [t for t in tokens if t in slug]
        if not matched:
            continue
        # Strong-token requirement: at least one numeric token or one
        # 3+ char token must be present to avoid generic matches.
        if not any(any(c.isdigit() for c in t) or len(t) >= 3 for t in matched):
            continue
        score = SequenceMatcher(None, wanted, slug).ratio() * 2
        for token in matched:
            score += 0.6 if any(c.isdigit() for c in token) else 0.3
        if wanted and wanted in slug:
            score += 1.5
        if any(token in slug for token in fab_tokens):
            score += 0.4
        # Penalise listing-ish URLs (very short paths) when there are
        # deeper alternatives.
        path = urlparse(candidate_url).path.strip("/")
        depth = len([p for p in path.split("/") if p])
        score += min(0.4, 0.1 * depth)
        if best is None or score > best.score:
            best = SitemapResolution(
                url=candidate_url,
                score=score,
                matched_tokens=matched,
                source_sitemap=entry["sitemap"],
            )
    if best and best.score >= min_score:
        return best
    return None


# ---------------------------------------------------------------------------
# Sitemap discovery + parsing
# ---------------------------------------------------------------------------


def _collect_host_urls(host_root: str, *, cache_ttl: int, timeout: int) -> list[dict]:
    cache_key = f"{host_root}/__sitemap_urls__"
    cached = page_cache.load(cache_key, ttl_seconds=cache_ttl)
    if cached and cached.html:
        try:
            return json.loads(cached.html)
        except json.JSONDecodeError:
            pass

    sitemap_urls = list(_discover_sitemap_urls(host_root, timeout=timeout))
    seen: set[str] = set()
    collected: list[dict] = []
    queue: list[str] = []
    for url in sitemap_urls:
        if url not in seen:
            seen.add(url)
            queue.append(url)

    expanded = 0
    while queue and expanded < _MAX_NESTED_SITEMAPS:
        current = queue.pop(0)
        expanded += 1
        children, urls = _fetch_and_parse_sitemap(current, timeout=timeout)
        for child in children:
            if child not in seen:
                seen.add(child)
                queue.append(child)
        for loc in urls:
            collected.append({"loc": loc, "sitemap": current})
            if len(collected) >= _MAX_URLS_PER_SITEMAP:
                break
        if len(collected) >= _MAX_URLS_PER_SITEMAP:
            break

    if collected:
        try:
            page_cache.save(cache_key, html=json.dumps(collected), markdown=None, source="sitemap")
        except Exception:
            pass
    return collected


def _discover_sitemap_urls(host_root: str, *, timeout: int) -> Iterable[str]:
    discovered: list[str] = []
    robots_url = f"{host_root}/robots.txt"
    try:
        response = http_client.polite_get(robots_url, timeout=timeout)
        if response.ok:
            for line in response.text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    _, _, value = line.partition(":")
                    candidate = value.strip()
                    if candidate:
                        discovered.append(candidate)
    except Exception as exc:
        logger.debug("robots.txt fetch failed for %s: %s", host_root, exc)
    for path in _FALLBACK_SITEMAP_PATHS:
        discovered.append(urljoin(host_root, path))
    # de-dupe preserving order
    seen: set[str] = set()
    for url in discovered:
        if url not in seen:
            seen.add(url)
            yield url


def _fetch_and_parse_sitemap(url: str, *, timeout: int) -> tuple[list[str], list[str]]:
    """Returns (nested_sitemaps, urls)."""
    try:
        response = http_client.polite_get(
            url,
            timeout=timeout,
            extra_headers={"accept": "application/xml,text/xml,*/*"},
        )
        if not response.ok or not response.content:
            return [], []
        content = response.content
        # Handle gzip-encoded sitemaps that requests did not auto-decompress.
        if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
            import gzip

            try:
                content = gzip.decompress(content)
            except OSError:
                return [], []
        text = content.decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("sitemap fetch failed for %s: %s", url, exc)
        return [], []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], []

    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    nested: list[str] = []
    urls: list[str] = []
    if tag == "sitemapindex":
        for child in root.findall(".//"):
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "loc" and child.text:
                nested.append(child.text.strip())
    elif tag == "urlset":
        for child in root.findall(".//"):
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "loc" and child.text:
                urls.append(child.text.strip())
    else:
        # Some sites publish a non-standard root but still use <loc>.
        for child in root.iter():
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "loc" and child.text:
                urls.append(child.text.strip())
    return nested, urls


def _is_asset_url(path: str) -> bool:
    if not path:
        return False
    if _ASSET_PATH_RE.search(path):
        return True
    lowered = path.lower()
    return any(hint in lowered for hint in _ASSET_PATH_HINTS)


def _model_tokens(value: str) -> list[str]:
    ignored = {"machine", "machines", "vending", "the", "and", "for", "with"}
    tokens: list[str] = []
    for raw in re.split(r"[^a-zA-Z0-9]+", value or ""):
        normalized = comparable_model(raw)
        if len(normalized) >= 2 and normalized not in ignored:
            tokens.append(normalized)
    return list(dict.fromkeys(tokens))


# ---------------------------------------------------------------------------
# Helpers for integration with the navigation-based resolver
# ---------------------------------------------------------------------------


@dataclass
class ResolutionTrace:
    final_url: str
    nav_attempted: bool
    sitemap: Optional[SitemapResolution]
    nav_changed: bool
    chose: str  # "csv" | "navigation" | "sitemap"

    def to_dict(self) -> dict:
        return {
            "final_url": self.final_url,
            "nav_attempted": self.nav_attempted,
            "nav_changed": self.nav_changed,
            "chose": self.chose,
            "sitemap": self.sitemap.to_dict() if self.sitemap else None,
        }
