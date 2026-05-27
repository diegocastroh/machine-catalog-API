"""CLIP-based image verification for vending machine catalog images.

The verifier is optional: if `open_clip_torch`, `torch` or `Pillow` are not
installed, every helper degrades to a no-op so the pipeline keeps working
with the previous heuristic-only behaviour.

Two levels of checking are provided:

* `is_vending_image(image_bytes)` — zero-shot CLIP classification against a
  curated set of positive (vending-related) and negative (logo, banner,
  person, placeholder, etc.) text prompts. Good default to filter logos and
  random photos out of the candidate pool.

* `classify_machine_type(image_bytes)` — finer-grained zero-shot tagging
  (snack, drink, coffee, combo, locker, fresh food, ice cream). Useful as a
  cross-check against the text-derived `tipo_maquina`.

Both helpers return rich diagnostic info so callers can store the CLIP
score alongside the image in Supabase for later auditing.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_CLIP_MODEL_NAME = os.environ.get("CLIP_MODEL", "ViT-B-32")
_CLIP_PRETRAINED = os.environ.get("CLIP_PRETRAINED", "laion2b_s34b_b79k")
_REQUEST_TIMEOUT = float(os.environ.get("CLIP_FETCH_TIMEOUT", "20"))

POSITIVE_PROMPTS: tuple[str, ...] = (
    "a photo of a vending machine",
    "a product render of a vending machine on a white background",
    "a refrigerated vending machine with glass front",
    "a snack and drink vending machine",
    "a coffee vending machine",
    "a smart fridge vending kiosk",
    "an automated retail locker",
    "an ice cream or frozen vending machine",
)

NEGATIVE_PROMPTS: tuple[str, ...] = (
    "a company logo",
    "a website icon or button",
    "a portrait photo of a person",
    "a generic marketing banner",
    "an empty placeholder image",
    "a screenshot of a website header",
    "a social media icon",
    "a stock photo of an office",
    "a chart or infographic",
    "a payment terminal not attached to a vending machine",
)

MACHINE_TYPE_PROMPTS: dict[str, tuple[str, ...]] = {
    "snack": (
        "a snack vending machine with spirals",
        "a vending machine dispensing chips and candy bars",
    ),
    "drink": (
        "a drink vending machine with bottles and cans",
        "a refrigerated beverage vending machine",
    ),
    "coffee": (
        "an espresso or coffee vending machine",
        "a hot beverage vending machine with a cup dispenser",
    ),
    "combo": (
        "a combo vending machine with snacks and drinks together",
    ),
    "locker": (
        "an automated pickup locker with multiple compartments",
        "a smart locker for parcel or product pickup",
    ),
    "frozen": (
        "an ice cream vending machine",
        "a frozen food vending machine",
    ),
    "food": (
        "a fresh food vending machine with sandwiches and meals",
        "a hot food vending machine",
    ),
}


@dataclass
class VerifierResult:
    is_vending: bool
    score: float
    best_label: str
    width: int
    height: int
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_vending": self.is_vending,
            "clip_score": round(self.score, 4),
            "best_label": self.best_label,
            "width": self.width,
            "height": self.height,
            "error": self.error,
        }


_state_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load_clip():
    """Load CLIP lazily. Returns (model, preprocess, tokenizer, device) or None."""
    try:
        import torch
        import open_clip
    except Exception as exc:  # pragma: no cover - depends on optional deps
        logger.info("CLIP not available, skipping image verification: %s", exc)
        return None
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            _CLIP_MODEL_NAME, pretrained=_CLIP_PRETRAINED, device=device
        )
        model.eval()
        tokenizer = open_clip.get_tokenizer(_CLIP_MODEL_NAME)
        return model, preprocess, tokenizer, device
    except Exception as exc:  # pragma: no cover - first download failures
        logger.warning("Failed to initialise CLIP: %s", exc)
        return None


def _encode_text(prompts: tuple[str, ...]):
    bundle = _load_clip()
    if bundle is None:
        return None
    import torch

    model, _preprocess, tokenizer, device = bundle
    tokens = tokenizer(list(prompts)).to(device)
    with torch.no_grad():
        feats = model.encode_text(tokens)
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats


@lru_cache(maxsize=8)
def _cached_text_embeddings(group_key: str):
    if group_key == "vending":
        return _encode_text(POSITIVE_PROMPTS + NEGATIVE_PROMPTS)
    if group_key.startswith("type:"):
        kind = group_key.split(":", 1)[1]
        prompts = MACHINE_TYPE_PROMPTS.get(kind)
        return _encode_text(prompts) if prompts else None
    return None


def _open_image(image_bytes: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def fetch_image_bytes(url: str) -> Optional[bytes]:
    try:
        from . import http_client

        response = http_client.polite_get(
            url,
            timeout=int(_REQUEST_TIMEOUT),
            extra_headers={"accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8"},
        )
        response.raise_for_status()
        content = response.content
        if not content:
            return None
        return content
    except Exception as exc:
        logger.debug("fetch failed for %s: %s", url, exc)
        return None


def _quick_reject(image, min_side: int = 220, min_variance: float = 80.0) -> Optional[str]:
    """Cheap OpenCV-free checks: too small, monochrome or empty."""
    width, height = image.size
    if min(width, height) < min_side:
        return f"too_small:{width}x{height}"
    try:
        import numpy as np

        arr = np.asarray(image.convert("L"))
        if float(arr.var()) < min_variance:
            return "low_variance"
    except Exception:
        return None
    return None


def is_vending_image(image_bytes: bytes, threshold: float = 0.55) -> VerifierResult:
    """Run CLIP zero-shot classification on a single image.

    `threshold` is the minimum positive-prompt mass (softmax sum over the
    POSITIVE_PROMPTS bucket). Tune downwards if you want to be permissive,
    upwards to be stricter. Defaults are calibrated for catalog-style
    renders with a small amount of marketing imagery mixed in.
    """
    bundle = _load_clip()
    if bundle is None:
        return VerifierResult(True, 0.0, "clip_unavailable", 0, 0, error="clip_unavailable")
    try:
        image = _open_image(image_bytes)
    except Exception as exc:
        return VerifierResult(False, 0.0, "unreadable_image", 0, 0, error=str(exc))
    width, height = image.size
    rejection = _quick_reject(image)
    if rejection:
        return VerifierResult(False, 0.0, rejection, width, height, error=rejection)

    import torch

    model, preprocess, _tokenizer, device = bundle
    text_feats = _cached_text_embeddings("vending")
    if text_feats is None:
        return VerifierResult(True, 0.0, "clip_text_unavailable", width, height, error="clip_text_unavailable")
    with _state_lock:
        tensor = preprocess(image).unsqueeze(0).to(device)
        with torch.no_grad():
            img_feat = model.encode_image(tensor)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            logits = (100.0 * img_feat @ text_feats.T).softmax(dim=-1)[0]
    probs = logits.detach().cpu().tolist()
    positive_count = len(POSITIVE_PROMPTS)
    pos_mass = float(sum(probs[:positive_count]))
    all_prompts = POSITIVE_PROMPTS + NEGATIVE_PROMPTS
    best_idx = max(range(len(probs)), key=lambda i: probs[i])
    best_label = all_prompts[best_idx]
    is_vending = pos_mass >= threshold and best_idx < positive_count
    return VerifierResult(is_vending, pos_mass, best_label, width, height)


def classify_machine_type(image_bytes: bytes) -> Optional[Tuple[str, float]]:
    """Pick the most likely tipo_maquina label among MACHINE_TYPE_PROMPTS.

    Returns `(label, confidence)` or `None` if CLIP is not available.
    """
    bundle = _load_clip()
    if bundle is None:
        return None
    try:
        image = _open_image(image_bytes)
    except Exception:
        return None

    import torch

    model, preprocess, _tokenizer, device = bundle
    scores: dict[str, float] = {}
    with _state_lock:
        tensor = preprocess(image).unsqueeze(0).to(device)
        with torch.no_grad():
            img_feat = model.encode_image(tensor)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            for kind in MACHINE_TYPE_PROMPTS:
                feats = _cached_text_embeddings(f"type:{kind}")
                if feats is None:
                    continue
                sims = (img_feat @ feats.T)[0]
                scores[kind] = float(sims.max().item())
    if not scores:
        return None
    label = max(scores, key=lambda k: scores[k])
    return label, scores[label]


def verify_image_url(url: str, threshold: float = 0.55) -> VerifierResult:
    """High-level helper: download and verify a single URL."""
    data = fetch_image_bytes(url)
    if not data:
        return VerifierResult(False, 0.0, "fetch_failed", 0, 0, error="fetch_failed")
    return is_vending_image(data, threshold=threshold)
