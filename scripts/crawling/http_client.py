"""Polite HTTP client with per-host throttle, UA rotation and backoff.

The goal is to keep manufacturer sites from rate-limiting us. Three
things make the most difference in practice, in order of impact:

1. A real, varied User-Agent (most sites silently 403 unknown UAs).
2. A minimum delay between requests *to the same host* (not global —
   the global --sleep already serves all hosts together).
3. Exponential backoff on 429 / 503 / 403 responses, with optional
   retries.

All knobs are exposed via environment variables so the same defaults
apply whether the request is fired by `requests` (basic extractor) or
the Crawl4AI browser (which receives the chosen UA).

Environment variables:
    HTTP_PER_HOST_DELAY      minimum seconds between requests to the same host (default 4.0)
    HTTP_JITTER_SECONDS      random extra delay up to this value (default 1.5)
    HTTP_MAX_RETRIES         backoff retries on 429/503/403 (default 2)
    HTTP_USER_AGENT_OVERRIDE pin a single UA instead of rotating
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


# Curated list of recent, real desktop User-Agents. Updated periodically.
# Keep them realistic — exotic UAs trigger more bot detection, not less.
USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
)

# Common request headers that paired with a real UA cut the 403 rate on
# many sites. They have to look browser-ish, not script-ish.
DEFAULT_HEADERS_BASE: dict[str, str] = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9,es;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "upgrade-insecure-requests": "1",
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "cache-control": "no-cache",
    "pragma": "no-cache",
}


PER_HOST_DELAY = float(os.environ.get("HTTP_PER_HOST_DELAY", "4.0"))
JITTER_SECONDS = float(os.environ.get("HTTP_JITTER_SECONDS", "1.5"))
MAX_RETRIES = int(os.environ.get("HTTP_MAX_RETRIES", "2"))
UA_OVERRIDE = os.environ.get("HTTP_USER_AGENT_OVERRIDE")


_last_request_at: dict[str, float] = {}
_state_lock = threading.Lock()


def pick_user_agent() -> str:
    if UA_OVERRIDE:
        return UA_OVERRIDE
    return random.choice(USER_AGENTS)


def default_headers(user_agent: Optional[str] = None) -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS_BASE)
    headers["user-agent"] = user_agent or pick_user_agent()
    return headers


def _host_of(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or "").lower()


def respect_per_host_delay(url: str, *, per_host_delay: float = PER_HOST_DELAY, jitter: float = JITTER_SECONDS) -> None:
    """Block until enough time has passed since the last request to this host."""
    host = _host_of(url)
    if not host or per_host_delay <= 0:
        return
    with _state_lock:
        last = _last_request_at.get(host, 0.0)
    delta = time.time() - last
    target = per_host_delay + (random.uniform(0, jitter) if jitter > 0 else 0.0)
    if delta < target:
        time.sleep(target - delta)
    with _state_lock:
        _last_request_at[host] = time.time()


def polite_get(
    url: str,
    *,
    timeout: int = 30,
    per_host_delay: float = PER_HOST_DELAY,
    jitter: float = JITTER_SECONDS,
    max_retries: int = MAX_RETRIES,
    extra_headers: Optional[dict[str, str]] = None,
) -> requests.Response:
    """A `requests.get` that throttles per host, rotates UA, and backs off.

    On 429/503/403 it sleeps `Retry-After` (when present) or an
    exponentially growing window, then retries up to `max_retries`
    times. The last response (success or final failure) is returned;
    raises for unrecoverable network errors.
    """
    headers = default_headers()
    if extra_headers:
        headers.update(extra_headers)

    last_exc: Optional[Exception] = None
    response: Optional[requests.Response] = None
    for attempt in range(max_retries + 1):
        respect_per_host_delay(url, per_host_delay=per_host_delay, jitter=jitter)
        try:
            response = requests.get(url, timeout=timeout, headers=headers)
        except requests.RequestException as exc:
            last_exc = exc
            logger.debug("network error on %s (attempt %s): %s", url, attempt + 1, exc)
            time.sleep(_backoff_seconds(attempt))
            continue
        if response.status_code in {429, 503, 403}:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            wait = retry_after if retry_after is not None else _backoff_seconds(attempt)
            logger.info(
                "rate-limited (%s) on %s, backing off %.1fs (attempt %s/%s)",
                response.status_code,
                url,
                wait,
                attempt + 1,
                max_retries + 1,
            )
            time.sleep(wait)
            # rotate UA between retries — some sites bind the block to it
            headers["user-agent"] = pick_user_agent()
            continue
        return response

    if response is not None:
        return response
    raise last_exc or RuntimeError(f"polite_get failed for {url}")


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        # HTTP-date format; not bothering to parse it, fall back to backoff
        return None


def _backoff_seconds(attempt: int) -> float:
    base = min(2 ** attempt, 32)
    return base + random.uniform(0, 1.5)


def stats() -> dict:
    with _state_lock:
        return {
            "hosts_seen": len(_last_request_at),
            "per_host_delay": PER_HOST_DELAY,
            "jitter": JITTER_SECONDS,
            "max_retries": MAX_RETRIES,
            "ua_override": bool(UA_OVERRIDE),
        }
