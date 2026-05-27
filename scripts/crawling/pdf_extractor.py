"""Extract product specs from a PDF catalog.

Many manufacturer CSVs point at a single multi-product catalog PDF
instead of an HTML product page. This module pulls the relevant slice
out of that PDF for one specific model:

1. Download the PDF (using polite_get + the disk cache).
2. Extract text per page. PyMuPDF (`fitz`) gives the best results and
   also surfaces embedded images; we fall back to `pypdf` for text
   only when PyMuPDF is missing.
3. Locate pages where the model code appears. Build a windowed text
   sample (the matched pages plus their neighbours).
4. Reuse the existing rule-based spec extractor on that window.
5. Optionally surface embedded image bytes so the CLIP verifier can
   pick the best product render even when there is no HTTP URL.

The result has the same shape as the HTML extractors so the rest of
the pipeline does not need to know the origin was a PDF.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import cache as page_cache
from . import http_client
from .specs import extract_specs_from_text
from .text_utils import infer_tipo_maquina, remove_cookie_noise

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60
_WINDOW_PAGES = int(os.environ.get("PDF_MODEL_WINDOW_PAGES", "1"))
_IMAGE_CACHE_DIR = Path(
    os.environ.get("MACHINE_CATALOG_PDF_IMAGE_DIR")
    or (Path.home() / ".cache" / "machine-catalog" / "pdf-images")
)


@dataclass
class PdfPage:
    number: int
    text: str
    images: list[tuple[str, bytes]]  # (image_id, bytes)


def extract_from_pdf(
    url: str,
    fabricante: str,
    modelo: str,
    *,
    use_cache: bool = True,
    cache_ttl: int = page_cache.DEFAULT_TTL_SECONDS,
) -> Optional[dict]:
    """Return a payload extracted from `url` (must be a PDF) or `None` if
    extraction failed entirely. Uses the on-disk page cache for the raw
    bytes and a separate folder for extracted images.
    """
    data = _download_pdf(url, use_cache=use_cache, cache_ttl=cache_ttl)
    if not data:
        return None

    pages = _read_pages(data)
    if not pages:
        return None

    matched = _locate_model_pages(pages, modelo)
    if not matched:
        logger.warning(
            "model %r not found in PDF %s (%d pages); refusing to extract from arbitrary pages",
            modelo,
            url,
            len(pages),
        )
        return {
            "_pdf_extract": {
                "source_url": url,
                "total_pages": len(pages),
                "matched_pages": [],
                "selected_pages": [],
                "engine": _engine_name(),
                "error": "model_not_found_in_pdf",
            }
        }
    selected = _window(pages, matched)
    combined_text = "\n".join(remove_cookie_noise(p.text) for p in selected)
    if not combined_text.strip():
        return None

    specs = extract_specs_from_text(combined_text)
    tipo = infer_tipo_maquina(f"{fabricante} {modelo} {combined_text[:2000]}")
    image_paths, image_candidates = _persist_images(selected, url, modelo)

    payload: dict = {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": tipo,
        "imagen_url": None,  # PDFs have no public image URL; storage upload is a separate step
        "_image_candidates": image_candidates,  # file:// URIs consumed by image_verifier
        "_image_local_paths": image_paths,
        "versiones_disponibles": [],
        **specs,
        "_pdf_extract": {
            "source_url": url,
            "total_pages": len(pages),
            "matched_pages": [p.number for p in matched],
            "selected_pages": [p.number for p in selected],
            "text_sample": combined_text[:8000],
            "image_count": len(image_paths),
            "engine": _engine_name(),
        },
    }
    return payload


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _download_pdf(url: str, *, use_cache: bool, cache_ttl: int) -> Optional[bytes]:
    cache_key = f"pdf::{url}"
    if use_cache:
        cached_path = _cached_pdf_path(cache_key)
        if cached_path.exists() and _is_fresh(cached_path, cache_ttl):
            try:
                return cached_path.read_bytes()
            except OSError:
                pass
    try:
        response = http_client.polite_get(
            url,
            timeout=_DEFAULT_TIMEOUT,
            extra_headers={"accept": "application/pdf,*/*;q=0.8"},
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("PDF download failed for %s: %s", url, exc)
        return None
    content = response.content
    if not content[:4] == b"%PDF":
        logger.warning("URL %s did not return a PDF (magic bytes mismatch)", url)
        return None
    if use_cache:
        try:
            cached_path = _cached_pdf_path(cache_key)
            cached_path.parent.mkdir(parents=True, exist_ok=True)
            cached_path.write_bytes(content)
        except OSError:
            pass
    return content


def _cached_pdf_path(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return page_cache.DEFAULT_CACHE_DIR / "pdfs" / digest[:2] / f"{digest}.pdf"


def _is_fresh(path: Path, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    try:
        age = path.stat().st_mtime
    except OSError:
        return False
    import time

    return (time.time() - age) <= ttl_seconds


def _read_pages(data: bytes) -> list[PdfPage]:
    try:
        import fitz  # PyMuPDF

        return _read_pages_pymupdf(data)
    except ImportError:
        pass
    try:
        from pypdf import PdfReader

        return _read_pages_pypdf(data)
    except ImportError:
        logger.warning("No PDF library available. Install pymupdf or pypdf.")
        return []


def _read_pages_pymupdf(data: bytes) -> list[PdfPage]:
    import fitz

    pages: list[PdfPage] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            images: list[tuple[str, bytes]] = []
            for img_idx, img_info in enumerate(page.get_images(full=True)):
                xref = img_info[0]
                try:
                    base = doc.extract_image(xref)
                except Exception:
                    continue
                img_bytes = base.get("image")
                ext = base.get("ext") or "png"
                width = base.get("width") or 0
                height = base.get("height") or 0
                if not img_bytes or min(width, height) < 200:
                    continue
                image_id = f"p{i:03d}_i{img_idx:02d}.{ext}"
                images.append((image_id, img_bytes))
            pages.append(PdfPage(number=i, text=text, images=images))
    return pages


def _read_pages_pypdf(data: bytes) -> list[PdfPage]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[PdfPage] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(PdfPage(number=i, text=text, images=[]))
    return pages


def _locate_model_pages(pages: list[PdfPage], modelo: str) -> list[PdfPage]:
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", modelo) if len(t) >= 2]
    if not tokens:
        return []
    strong_tokens = [t.lower() for t in tokens if any(c.isdigit() for c in t) or len(t) >= 3]
    if not strong_tokens:
        strong_tokens = [t.lower() for t in tokens]
    matched: list[PdfPage] = []
    for page in pages:
        lowered = page.text.lower()
        # Require ALL strong tokens to appear on the same page, otherwise
        # a page with the word "Coffee" would match a coffee-named model
        # that lives on a totally different page.
        if all(t in lowered for t in strong_tokens):
            matched.append(page)
    return matched


def _window(pages: list[PdfPage], matched: list[PdfPage]) -> list[PdfPage]:
    """Return matched pages plus _WINDOW_PAGES neighbours on each side."""
    if not matched:
        return []
    indices = {p.number - 1 for p in matched}
    expanded: set[int] = set()
    for idx in indices:
        for offset in range(-_WINDOW_PAGES, _WINDOW_PAGES + 1):
            j = idx + offset
            if 0 <= j < len(pages):
                expanded.add(j)
    return [pages[i] for i in sorted(expanded)]


def _persist_images(selected: list[PdfPage], source_url: str, modelo: str) -> tuple[list[str], list[str]]:
    if not any(page.images for page in selected):
        return [], []
    pdf_digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
    model_slug = re.sub(r"[^a-zA-Z0-9]+", "-", modelo).strip("-").lower() or "model"
    target = _IMAGE_CACHE_DIR / pdf_digest / model_slug
    target.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    uris: list[str] = []
    for page in selected:
        for image_id, payload in page.images:
            path = target / image_id
            try:
                path.write_bytes(payload)
            except OSError as exc:
                logger.debug("could not write extracted image %s: %s", path, exc)
                continue
            saved.append(str(path))
            uris.append(path.resolve().as_uri())
    return saved, uris


def _engine_name() -> str:
    try:
        import fitz  # noqa: F401

        return "pymupdf"
    except ImportError:
        pass
    try:
        import pypdf  # noqa: F401

        return "pypdf"
    except ImportError:
        return "none"
