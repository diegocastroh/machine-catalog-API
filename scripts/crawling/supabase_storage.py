"""Upload verified catalog images to Supabase Storage.

The `machine_model_images` table already has both `source_image_url`
(where the image came from) and `storage_url` (the rehosted public
URL). This module fills the second one so the catalog keeps working
when manufacturers rotate their CDNs or take pages offline. It also
makes PDF-extracted images consumable by the frontend: those have no
public HTTP URL of their own, only file:// paths on the scraper host.

Key properties:

* Deterministic paths: `{model_id}/{sha256[:16]}.{ext}` so the same
  image bytes always land in the same key. Re-uploading is a no-op
  the second time around.
* Public bucket: the helper creates the bucket on first use with
  `public=True`. Callers can pre-create it in the dashboard if they
  want stricter ACLs — `ensure_bucket` swallows "already exists".
* Source of truth: returns `(storage_url, storage_path, sha256, width,
  height, content_type, size_bytes)` so the caller can also fill
  `hash_sha256`, `width_px`, `height_px` on the row.

Bucket name is configurable via the env var `SUPABASE_IMAGES_BUCKET`
or the `--upload-images-bucket` CLI flag (default
`machine-catalog-images`).
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


DEFAULT_BUCKET = os.environ.get("SUPABASE_IMAGES_BUCKET", "machine-catalog-images")
MAX_IMAGE_BYTES = int(os.environ.get("SUPABASE_IMAGES_MAX_BYTES", str(8 * 1024 * 1024)))  # 8 MB


_CONTENT_TYPE_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


@dataclass
class StorageUpload:
    storage_url: str
    storage_path: str
    sha256: str
    content_type: str
    size_bytes: int
    width: Optional[int]
    height: Optional[int]


def ensure_bucket(supabase, bucket: str = DEFAULT_BUCKET) -> None:
    """Create the bucket as public if it does not exist. Idempotent."""
    try:
        existing = supabase.storage.list_buckets()
    except Exception as exc:
        logger.debug("could not list buckets, will try to create: %s", exc)
        existing = []
    names = {_bucket_name(b) for b in existing}
    if bucket in names:
        return
    try:
        supabase.storage.create_bucket(bucket, options={"public": True})
        logger.info("created Supabase Storage bucket %r (public)", bucket)
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "duplicate" in message:
            return
        raise


def _bucket_name(obj) -> str:
    if isinstance(obj, dict):
        return obj.get("name") or obj.get("id") or ""
    return getattr(obj, "name", "") or getattr(obj, "id", "")


def upload_image(
    supabase,
    *,
    image_bytes: bytes,
    model_id: str,
    source_url: str,
    bucket: str = DEFAULT_BUCKET,
    filename_hint: Optional[str] = None,
) -> Optional[StorageUpload]:
    """Upload `image_bytes` and return metadata, or `None` on failure.

    `source_url` is only used to derive an extension when we cannot
    infer it from bytes. The upload itself is keyed by the SHA-256
    of the content so it is fully deterministic.
    """
    if not image_bytes:
        return None
    if len(image_bytes) > MAX_IMAGE_BYTES:
        logger.warning("image too large (%d bytes), skipping upload", len(image_bytes))
        return None

    content_type, ext = _detect_content_type(image_bytes, source_url, filename_hint)
    if content_type is None:
        logger.warning("could not detect image content type for %s", source_url)
        return None

    width, height = _detect_size(image_bytes)
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    storage_path = f"{model_id}/{sha256[:16]}{ext}"

    try:
        supabase.storage.from_(bucket).upload(
            path=storage_path,
            file=image_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )
    except Exception as exc:
        message = str(exc)
        if "already exists" in message.lower() or "duplicate" in message.lower():
            # Treat as success; deterministic path means this is the same content.
            pass
        else:
            logger.warning("storage upload failed for %s: %s", source_url, exc)
            return None

    try:
        public = supabase.storage.from_(bucket).get_public_url(storage_path)
    except Exception as exc:
        logger.warning("could not resolve public URL for %s: %s", storage_path, exc)
        return None

    storage_url = _normalise_public_url(public)
    return StorageUpload(
        storage_url=storage_url,
        storage_path=storage_path,
        sha256=sha256,
        content_type=content_type,
        size_bytes=len(image_bytes),
        width=width,
        height=height,
    )


def _normalise_public_url(value) -> str:
    if isinstance(value, dict):
        for key in ("publicUrl", "public_url"):
            if value.get(key):
                return str(value[key])
        nested = value.get("data") or {}
        return str(nested.get("publicUrl") or nested.get("public_url") or "")
    return str(value or "").strip().rstrip("?")


def _detect_content_type(
    image_bytes: bytes, source_url: str, filename_hint: Optional[str]
) -> tuple[Optional[str], str]:
    """Return `(content_type, extension)` with leading dot in the extension."""
    head = image_bytes[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif", ".gif"
    if head.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head.startswith(b"BM"):
        return "image/bmp", ".bmp"
    # Fallback to filename hint or URL extension
    for hint in (filename_hint or "", source_url):
        lowered = hint.lower()
        for ext, ct in _CONTENT_TYPE_BY_EXT.items():
            if lowered.endswith(ext) or f"{ext}?" in lowered:
                return ct, ext
    return None, ""


def _detect_size(image_bytes: bytes) -> tuple[Optional[int], Optional[int]]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            return int(img.width), int(img.height)
    except Exception:
        return None, None
