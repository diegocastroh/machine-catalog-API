"""Persistent on-disk cache for crawled pages.

Each entry is a JSON file keyed by sha256 of the URL. Stores `html`,
`markdown`, the original `url`, the `fetched_at` timestamp and the source
extractor that produced it. This makes iteration over the extractor /
adapter logic cheap: the second run on the same URL skips the browser
entirely until the TTL expires.

Environment variables:
    MACHINE_CATALOG_CACHE_DIR  override the default cache location
    MACHINE_CATALOG_CACHE_TTL  override the default TTL in seconds (24h)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_TTL_SECONDS = int(os.environ.get("MACHINE_CATALOG_CACHE_TTL", 24 * 60 * 60))
DEFAULT_CACHE_DIR = Path(
    os.environ.get("MACHINE_CATALOG_CACHE_DIR")
    or (Path.home() / ".cache" / "machine-catalog" / "pages")
)


@dataclass
class CachedPage:
    url: str
    html: Optional[str]
    markdown: Optional[str]
    fetched_at: float
    source: str

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "html": self.html,
            "markdown": self.markdown,
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


def _slug(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _entry_path(url: str, cache_dir: Path) -> Path:
    digest = _slug(url)
    return cache_dir / digest[:2] / f"{digest}.json"


def load(
    url: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Optional[CachedPage]:
    path = _entry_path(url, cache_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = float(raw.get("fetched_at") or 0)
    if ttl_seconds <= 0:
        return None
    if time.time() - fetched_at > ttl_seconds:
        return None
    return CachedPage(
        url=str(raw.get("url") or url),
        html=raw.get("html"),
        markdown=raw.get("markdown"),
        fetched_at=fetched_at,
        source=str(raw.get("source") or "unknown"),
    )


def save(
    url: str,
    *,
    html: Optional[str],
    markdown: Optional[str],
    source: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    path = _entry_path(url, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = CachedPage(
        url=url,
        html=html,
        markdown=markdown,
        fetched_at=time.time(),
        source=source,
    ).to_dict()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def invalidate(url: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> bool:
    path = _entry_path(url, cache_dir)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def purge(cache_dir: Path = DEFAULT_CACHE_DIR) -> int:
    """Remove the entire cache directory. Returns number of files deleted."""
    if not cache_dir.exists():
        return 0
    count = sum(1 for _ in cache_dir.rglob("*.json"))
    shutil.rmtree(cache_dir, ignore_errors=True)
    return count
