#!/usr/bin/env python
"""Scrape a vending CSV and write results directly to Supabase.

Required CSV columns: Fabricante, Modelo. Optional: URL.
Required env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
Optional env: SERPER_API_KEY, FIRECRAWL_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib.util
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import requests
from bs4 import BeautifulSoup

try:
    from supabase import Client, create_client
except ModuleNotFoundError:  # pragma: no cover - startup dependency message
    print(
        "Falta instalar dependencias. Ejecuta: python -m pip install -r scripts/requirements-supabase-pipeline.txt",
        file=sys.stderr,
    )
    raise

from crawling import cache as page_cache
from crawling import http_client
from crawling.ai_extractor import extract_with_ollama, merge_ai_extraction
from crawling.http_client import pick_user_agent, polite_get, respect_per_host_delay
from crawling.images import choose_verified_image
from crawling.jsonld import extract_from_html as extract_jsonld_from_html, merge_into as merge_jsonld_into
from crawling.pdf_extractor import extract_from_pdf as extract_from_pdf_module
from crawling.quality import quality_report
from crawling.resolvers import (
    resolve_best_product_url as resolve_best_product_url_from_module,
    resolve_product_url as resolve_product_url_from_module,
)
from crawling.specs import (
    apply_sielaff_public_series_specs as apply_sielaff_public_series_specs_from_module,
    extract_specs_from_text as extract_specs_from_text_from_module,
)


CATEGORY_MAP = {
    "coffee": "coffee",
    "snack": "snack_drink",
    "combo": "snack_drink",
    "drink": "cold_beverage",
    "beverage": "cold_beverage",
    "frozen": "ice_cream",
    "locker": "smart_locker",
    "industrial": "industrial",
}

COOKIE_TEXT_MARKERS = [
    "gestionar el consentimiento",
    "política de cookies",
    "politica de cookies",
    "política de privacidad",
    "politica de privacidad",
    "almacenar y/o acceder",
    "consentimiento de las cookies",
    "utilizamos cookies",
    "we use cookies",
    "we value your privacy",
    "cookie consent",
    "privacy policy",
    "cookie settings",
    "cookie policy",
    "necessary cookies",
    "functional cookies",
    "analytics cookies",
    "analytical cookies",
    "advertisement cookies",
    "no cookies to display",
    "enable the basic features",
    "collecting feedback",
    "third-party features",
    "third party features",
    "close.svg",
    "notice you can freely give",
    "withdraw your consent",
    "preferences panel",
    "denying consent",
    "accept all",
    "reject all",
    "learn more",
    "notice",
    "necessary measurement",
    "0/1",
    "almacenamiento o acceso técnico",
    "almacenamiento o acceso tecnico",
    "abonado o usuario",
    "fines estadísticos",
    "fines estadisticos",
    "finalidad legítima",
    "finalidad legitima",
    "comunicación a través",
    "comunicacion a traves",
    "proveedores",
    "preferencias",
    "estadísticas",
    "estadisticas",
    "marketing",
]

PRODUCT_TEXT_MARKERS = [
    "vending",
    "machine",
    "snack",
    "drink",
    "coffee",
    "bluetec",
    "technical",
    "specifications",
    "features",
    "products",
    "modelo",
    "producto",
    "maquina",
]


@dataclass
class Counters:
    created: int = 0
    updated: int = 0
    skipped_duplicate: int = 0
    skipped_incomplete: int = 0
    skipped_low_quality: int = 0
    skipped_asset_url: int = 0
    failed: int = 0
    dry_run: int = 0


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return re.sub(r"-+", "-", slug) or "unknown"


def comparable_model(value: str) -> str:
    replacements = {
        "è": "e",
        "é": "e",
        "ê": "e",
        "à": "a",
        "á": "a",
        "ì": "i",
        "í": "i",
        "ò": "o",
        "ó": "o",
        "ù": "u",
        "ú": "u",
        "&": "and",
        "+": "plus",
    }
    lowered = value.lower()
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    return re.sub(r"[^a-z0-9]+", "", lowered)


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_json(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if hasattr(value, "dict"):
        value = value.dict()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def infer_tipo_maquina(text: str) -> str | None:
    lowered = text.lower()
    if any(x in lowered for x in ["snacks-and-drinks", "snack and drink", "snacks and drinks"]):
        return "combo"
    if any(x in lowered for x in ["combo", "comboplus", "easycombo"]):
        return "combo"
    if any(x in lowered for x in ["drink", "beverage", "bebida", "soda", "can", "bottle", "lata", "botella"]):
        return "drink"
    if any(x in lowered for x in ["snack", "spiral", "espiral", "chips", "chocolate", "candy", "dulces"]):
        return "snack"
    if any(x in lowered for x in ["coffee", "café", "cafe", "espresso", "capuccino", "cappuccino", "vitro"]):
        return "coffee"
    if any(x in lowered for x in ["frozen", "ice cream", "helado", "congelado"]):
        return "frozen"
    if "locker" in lowered:
        return "locker"
    if any(x in lowered for x in ["food", "fresh food", "comida", "meal"]):
        return "food"
    return None


def remove_cookie_noise(text: str | None) -> str:
    if not text:
        return ""
    cleaned_lines = []
    skipping_cookie_block = False
    for line in str(text).splitlines():
        compact = " ".join(line.split())
        lowered = compact.lower()
        if not compact:
            continue
        if skipping_cookie_block and not any(marker in lowered for marker in PRODUCT_TEXT_MARKERS):
            continue
        if skipping_cookie_block and any(marker in lowered for marker in PRODUCT_TEXT_MARKERS):
            skipping_cookie_block = False
        if any(marker in lowered for marker in COOKIE_TEXT_MARKERS):
            skipping_cookie_block = True
            continue
        if lowered in {"aceptar", "rechazar", "configurar", "guardar preferencias", "accept", "reject", "preferences"}:
            continue
        cleaned_lines.append(compact)
    return "\n".join(cleaned_lines)


def category_for(tipo: str | None, model_name: str, specs: dict[str, Any]) -> str:
    tipo_normalized = clean_text(tipo).lower()
    if tipo_normalized == "food":
        text = f"{model_name} {json.dumps(specs, ensure_ascii=False)}".lower()
        return "hot_food" if "hot" in text or "heated" in text else "fresh_food"
    return CATEGORY_MAP.get(tipo_normalized, "other")


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


def first_http_url(value: str | None) -> str | None:
    if not value:
        return None
    matches = re.findall(r"https?://[^\s\"'<>]+", value)
    if not matches:
        return value.strip() or None
    image_like = [match.rstrip(").,;") for match in matches if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", match, re.I)]
    return (image_like[0] if image_like else matches[0]).rstrip(").,;")


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
    if lowered.endswith((".jpg", ".jpeg", ".png", ".webp")):
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
            if not absolute:
                continue
            if not is_probably_bad_image(absolute):
                images.append(absolute)
    unique = list(dict.fromkeys(images))
    unique.sort(key=lambda item: score_image_url(item, fabricante, modelo), reverse=True)
    return unique[0] if unique else None


def search_url_with_serper(fabricante: str, modelo: str, serper_api_key: str | None) -> str | None:
    if not serper_api_key:
        return None
    payload = {
        "q": f'"{fabricante}" "{modelo}" vending machine technical specifications official',
        "gl": "us",
        "hl": "en",
        "num": 5,
    }
    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": serper_api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    organic = response.json().get("organic", [])
    if not organic:
        return None
    scored: list[tuple[int, str]] = []
    fabricante_clean = fabricante.lower().replace(" ", "")
    for item in organic:
        link = item.get("link")
        if not link:
            continue
        combined = f"{link} {item.get('title', '')} {item.get('snippet', '')}".lower()
        score = 0
        if fabricante.lower() in combined:
            score += 5
        if modelo.lower() in combined:
            score += 5
        if fabricante_clean in link.lower().replace("-", "").replace("_", ""):
            score += 5
        if any(x in combined for x in ["official", "specification", "technical", "datasheet", "brochure", "product"]):
            score += 2
        scored.append((score, link))
    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1] if scored else organic[0].get("link")


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


def is_sielaff_public_series_model(modelo: str) -> bool:
    lowered = modelo.lower()
    return lowered.startswith("siline ") and any(token in lowered for token in [" gf ", "snack", "combi", " rp", " lift "])


def _candidate_image_list(html: str | None, base_url: str, fabricante: str, modelo: str) -> list[str]:
    try:
        from crawling.images import collect_image_candidates

        return collect_image_candidates(html, base_url, fabricante, modelo)
    except Exception:
        return []


def scrape_with_firecrawl(url: str, fabricante: str, modelo: str, firecrawl_api_key: str | None) -> dict[str, Any] | None:
    if not firecrawl_api_key or importlib.util.find_spec("firecrawl") is None:
        return None
    from firecrawl import Firecrawl

    schema = {
        "type": "object",
        "properties": {
            "fabricante": {"type": ["string", "null"]},
            "modelo_base": {"type": ["string", "null"]},
            "tipo_maquina": {"type": ["string", "null"]},
            "imagen_url": {"type": ["string", "null"]},
            "versiones_disponibles": {"type": "array", "items": {"type": "string"}},
            "especificaciones_fisicas": {"type": "object"},
            "especificaciones_electricas": {"type": "object"},
            "componentes_hardware": {"type": "object"},
        },
    }
    prompt = f"""
Extrae informacion tecnica unicamente de este modelo de maquina expendedora.
Fabricante esperado: {fabricante}
Modelo esperado: {modelo}
No inventes datos. Si un valor no existe, usa null. La imagen debe ser una URL absoluta del producto, no logo.
"""
    client = Firecrawl(api_key=firecrawl_api_key)
    result = client.scrape(
        url,
        formats=["markdown", "html", {"type": "json", "schema": schema, "prompt": prompt}],
        only_main_content=False,
        wait_for=3000,
        timeout=120000,
    )
    json_data = normalize_json(getattr(result, "json", None) if not isinstance(result, dict) else result.get("json"))
    html = getattr(result, "html", None) if not isinstance(result, dict) else result.get("html")
    markdown = getattr(result, "markdown", None) if not isinstance(result, dict) else result.get("markdown")
    if not json_data:
        return None
    json_data["fabricante"] = json_data.get("fabricante") or fabricante
    json_data["modelo_base"] = json_data.get("modelo_base") or modelo
    json_data["tipo_maquina"] = json_data.get("tipo_maquina") or infer_tipo_maquina(f"{fabricante} {modelo} {markdown or ''}")
    image = json_data.get("imagen_url")
    if image:
        image = first_http_url(urljoin(url, image))
    json_data["imagen_url"] = image if image and not is_probably_bad_image(image) else choose_best_image_from_html(html, url, fabricante, modelo)
    candidates = _candidate_image_list(html, url, fabricante, modelo)
    if json_data["imagen_url"] and json_data["imagen_url"] not in candidates:
        candidates = [json_data["imagen_url"], *candidates]
    json_data["_image_candidates"] = candidates
    json_data.setdefault("versiones_disponibles", [])
    json_data.setdefault("especificaciones_fisicas", {})
    json_data.setdefault("especificaciones_electricas", {})
    json_data.setdefault("componentes_hardware", {})
    if html:
        try:
            page_cache.save(url, html=html, markdown=markdown, source="firecrawl")
        except Exception:
            pass
        jsonld = extract_jsonld_from_html(html, url, fabricante, modelo)
        if jsonld:
            merge_jsonld_into(json_data, jsonld)
    return json_data


def scrape_basic(
    url: str,
    fabricante: str,
    modelo: str,
    *,
    use_cache: bool = True,
    cache_ttl: int = page_cache.DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    html, fetch_source = basic_fetch_cached(url, use_cache=use_cache, ttl_seconds=cache_ttl)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = remove_cookie_noise(soup.get_text("\n", strip=True))[:12000]
    tipo = infer_tipo_maquina(f"{fabricante} {modelo} {title} {text}")
    payload: dict[str, Any] = {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": tipo,
        "imagen_url": first_http_url(choose_best_image_from_html(html, url, fabricante, modelo)),
        "_image_candidates": _candidate_image_list(html, url, fabricante, modelo),
        "versiones_disponibles": [],
        **extract_specs_from_text_from_module(text),
        "_basic_extract": {"title": title, "text_sample": text[:2000], "fetch_source": fetch_source},
    }
    jsonld = extract_jsonld_from_html(html, url, fabricante, modelo)
    if jsonld:
        merge_jsonld_into(payload, jsonld)
    return payload


async def crawl4ai_fetch(url: str) -> tuple[str | None, str | None]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    respect_per_host_delay(url)
    browser_config = BrowserConfig(headless=True, user_agent=pick_user_agent())
    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, markdown_generator=DefaultMarkdownGenerator())
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "error_message", "Crawl4AI crawl failed"))
    markdown = getattr(result, "markdown", None)
    if hasattr(markdown, "raw_markdown"):
        markdown_text = markdown.raw_markdown
    elif hasattr(markdown, "fit_markdown"):
        markdown_text = markdown.fit_markdown
    else:
        markdown_text = str(markdown or "")
    html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
    return markdown_text, html


def crawl4ai_fetch_cached(url: str, *, use_cache: bool, ttl_seconds: int) -> tuple[str | None, str | None, str]:
    """Wrap crawl4ai_fetch with a disk cache. Returns (markdown, html, source)."""
    if use_cache:
        cached = page_cache.load(url, ttl_seconds=ttl_seconds)
        if cached is not None:
            return cached.markdown, cached.html, f"cache(age={int(cached.age_seconds)}s)"
    markdown, html = asyncio.run(crawl4ai_fetch(url))
    if use_cache:
        page_cache.save(url, html=html, markdown=markdown, source="crawl4ai")
    return markdown, html, "crawl4ai"


def basic_fetch_cached(url: str, *, use_cache: bool, ttl_seconds: int) -> tuple[str, str]:
    """Wrap a polite_get with the same disk cache. Returns (html, source)."""
    if use_cache:
        cached = page_cache.load(url, ttl_seconds=ttl_seconds)
        if cached is not None and cached.html:
            return cached.html, f"cache(age={int(cached.age_seconds)}s)"
    response = polite_get(url, timeout=30)
    response.raise_for_status()
    html = response.text
    if use_cache:
        page_cache.save(url, html=html, markdown=None, source="requests")
    return html, "requests"


def scrape_with_crawl4ai(
    url: str,
    fabricante: str,
    modelo: str,
    *,
    use_cache: bool = True,
    cache_ttl: int = page_cache.DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    if importlib.util.find_spec("crawl4ai") is None:
        raise RuntimeError(
            "Crawl4AI no esta instalado. Ejecuta: python -m pip install -r scripts/requirements-supabase-pipeline.txt"
        )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    markdown, html, fetch_source = crawl4ai_fetch_cached(url, use_cache=use_cache, ttl_seconds=cache_ttl)
    markdown = remove_cookie_noise(markdown)
    html_text = remove_cookie_noise(BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True))
    extraction_text = f"{markdown}\n{html_text}".strip()
    combined = f"{fabricante} {modelo} {extraction_text}"
    specs = extract_specs_from_text_from_module(extraction_text)
    if "sielaff" in fabricante.lower() and is_sielaff_public_series_model(modelo):
        apply_sielaff_public_series_specs_from_module(modelo, extraction_text, specs)
    payload: dict[str, Any] = {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": infer_tipo_maquina(combined),
        "imagen_url": first_http_url(choose_best_image_from_html(html, url, fabricante, modelo)),
        "_image_candidates": _candidate_image_list(html, url, fabricante, modelo),
        "versiones_disponibles": [],
        **specs,
        "_crawl4ai_extract": {
            "markdown_sample": extraction_text[:60000],
            "fetch_source": fetch_source,
        },
    }
    jsonld = extract_jsonld_from_html(html or "", url, fabricante, modelo)
    if jsonld:
        merge_jsonld_into(payload, jsonld)
    return payload


def extract_specs_from_text(text: str | None) -> dict[str, dict[str, Any]]:
    cleaned = remove_cookie_noise(text)
    lowered = cleaned.lower()

    def number_after(label: str) -> int | None:
        match = re.search(rf"{label}\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*mm", lowered)
        if not match:
            return None
        return int(float(match.group(1).replace(",", ".")))

    def first_match(pattern: str) -> str | None:
        match = re.search(pattern, cleaned, re.I)
        return " ".join(match.group(1).split()) if match else None

    screen_match = re.search(r"(?:touch\s*(?:screen|panel)|screen)\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:\"|”|inches|inch)", cleaned, re.I)
    cups_match = re.search(r"cups/day\s*[:\-]?\s*(?:up to\s*)?([0-9]+)", cleaned, re.I)
    selections_match = re.search(r"direct selections\s*[:\-]?\s*(?:up to\s*)?([0-9]+)", cleaned, re.I)
    dimensions_match = re.search(
        r"dimensions(?:[^:\n\r]*)?\s*[:\-]?\s*([0-9.,]+)\s*x\s*([0-9.,]+)\s*x\s*([0-9.,]+)\s*mm",
        cleaned,
        re.I,
    )
    weight_match = re.search(r"weight(?:[^:\n\r]*)?\s*[:\-]?\s*(?:approx\.\s*)?([0-9.,]+)\s*kg", cleaned, re.I)
    power_match = re.search(r"(?:power consumption|output|power)\s*[:\-]?\s*([0-9.,]+(?:\s*-\s*[0-9.,]+)?\s*w)", cleaned, re.I)

    return {
        "especificaciones_fisicas": {
            "alto_mm": number_after("height") or number_from_match(dimensions_match, 1),
            "ancho_mm": number_after("width") or number_from_match(dimensions_match, 2),
            "profundidad_mm": number_after("depth") or number_from_match(dimensions_match, 3),
            "peso_kg": number_from_match(weight_match, 1),
        },
        "especificaciones_electricas": {
            "voltaje": first_match(r"electrical (?:supply|connection values)\s*[:\-]?\s*([^\n\r]+)"),
            "potencia_watts": power_match.group(1) if power_match else None,
            "gas_refrigerante": None,
        },
        "componentes_hardware": {
            "grupo_infusor": first_match(r"(variflex\s*[0-9]+(?:\s*o\s*[0-9]+)?)"),
            "mecanica_extraccion": None,
            "capacidad_vasos": int(cups_match.group(1)) if cups_match else None,
            "capacidad_canales_o_espirales": f"direct selections: {selections_match.group(1)}" if selections_match else None,
            "telemetria_integrada": True if "rhealive" in lowered or "wi-fi" in lowered or "remote management" in lowered else None,
            "touchscreen_pulgadas": float(screen_match.group(1).replace(",", ".")) if screen_match else None,
        },
    }


def apply_sielaff_public_series_specs(modelo: str, text: str, specs: dict[str, dict[str, Any]]) -> None:
    blocks = []
    pattern = re.compile(
        r"dimensions(?:[^:\n\r]*)?\s*[:\-]?\s*([0-9.,]+)\s*x\s*([0-9.,]+)\s*x\s*([0-9.,]+)\s*mm(?P<context>.{0,500})",
        re.I | re.S,
    )
    for match in pattern.finditer(text):
        height = number_from_match(match, 1)
        width = number_from_match(match, 2)
        depth = number_from_match(match, 3)
        context = match.group("context")
        weight_match = re.search(r"weight(?:[^:\n\r]*)?\s*[:\-]?\s*(?:approx\.\s*)?([0-9.,]+)\s*kg", context, re.I)
        voltage_match = re.search(r"electrical connection values\s*[:\-]?\s*([^\n\r]+)", context, re.I)
        power_match = re.search(r"(?:power consumption|output)\s*[:\-]?\s*([0-9.,]+(?:\s*-\s*[0-9.,]+)?\s*w)", context, re.I)
        blocks.append(
            {
                "height": height,
                "width": width,
                "depth": depth,
                "weight": number_from_match(weight_match, 1),
                "voltage": " ".join(voltage_match.group(1).split()) if voltage_match else None,
                "power": " ".join(power_match.group(1).split()) if power_match else None,
            }
        )
    if not blocks:
        return

    lowered = f" {modelo.lower()} "
    target_width = None
    target_depth = None
    if " gf l " in lowered:
        target_width, target_depth = 1149, 904
    elif " gf m " in lowered:
        target_width, target_depth = 999, 904
    elif " m rp" in lowered or " m " in lowered:
        target_width, target_depth = 999, 907
    elif " s rp" in lowered or " s " in lowered:
        target_width, target_depth = 789, 907

    selected = None
    if target_width:
        selected = min(
            blocks,
            key=lambda block: abs((block["width"] or 0) - target_width) + abs((block["depth"] or 0) - target_depth),
        )
    else:
        selected = blocks[0]

    specs["especificaciones_fisicas"].update(
        {
            "alto_mm": selected["height"],
            "ancho_mm": selected["width"],
            "profundidad_mm": selected["depth"],
            "peso_kg": selected["weight"],
        }
    )
    specs["especificaciones_electricas"].update(
        {
            "voltaje": selected["voltage"] or specs["especificaciones_electricas"].get("voltaje"),
            "potencia_watts": selected["power"] or specs["especificaciones_electricas"].get("potencia_watts"),
        }
    )


def number_from_match(match: re.Match[str] | None, group_index: int) -> int | None:
    if not match:
        return None
    value = match.group(group_index).replace(",", "")
    try:
        return int(float(value))
    except ValueError:
        return None


def get_single(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) else None


def ensure_category_map(supabase: Client) -> dict[str, str]:
    response = supabase.table("machine_categories").select("id,code").execute()
    return {row["code"]: row["id"] for row in response.data or []}


def ensure_manufacturer(supabase: Client, name: str) -> dict[str, Any]:
    slug = slugify(name)
    existing = (
        supabase.table("machine_manufacturers")
        .select("*")
        .eq("slug", slug)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    found = get_single(existing.data)
    if found:
        return found
    created = (
        supabase.table("machine_manufacturers")
        .insert({"name": name, "slug": slug, "status": "active", "source_confidence": 0.9})
        .execute()
    )
    return get_single(created.data) or {}


def find_model(supabase: Client, manufacturer_id: str, model_name: str) -> dict[str, Any] | None:
    normalized = slugify(model_name)
    response = (
        supabase.table("machine_catalog_models")
        .select("*")
        .eq("manufacturer_id", manufacturer_id)
        .eq("normalized_model_name", normalized)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    return get_single(response.data)


def spec_payload(machine_model_id: str, specs: dict[str, Any]) -> dict[str, Any]:
    physical = specs.get("especificaciones_fisicas") or {}
    energy = specs.get("especificaciones_electricas") or {}
    hardware = specs.get("componentes_hardware") or {}
    return {
        "machine_model_id": machine_model_id,
        "height_mm": physical.get("alto_mm"),
        "width_mm": physical.get("ancho_mm"),
        "depth_mm": physical.get("profundidad_mm"),
        "weight_kg": physical.get("peso_kg"),
        "capacity_units": hardware.get("capacidad_vasos"),
        "capacity_description": hardware.get("capacidad_canales_o_espirales"),
        "voltage": energy.get("voltaje"),
        "power_requirements": str(energy.get("potencia_watts")) if energy.get("potencia_watts") else None,
        "refrigerated": True if energy.get("gas_refrigerante") else None,
        "raw_specs": specs,
    }


def image_exists(supabase: Client, model_id: str, image_url: str) -> bool:
    response = (
        supabase.table("machine_model_images")
        .select("id")
        .eq("machine_model_id", model_id)
        .eq("source_image_url", image_url)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def save_to_supabase(
    supabase: Client,
    categories: dict[str, str],
    fabricante: str,
    modelo: str,
    url: str,
    datos: dict[str, Any],
    row_number: int,
    mode: str,
    *,
    upload_bucket: Optional[str] = None,
) -> str:
    manufacturer = ensure_manufacturer(supabase, fabricante)
    existing = find_model(supabase, manufacturer["id"], modelo)
    category_code = category_for(datos.get("tipo_maquina"), modelo, datos)
    category_id = categories.get(category_code)
    normalized = slugify(modelo)
    quality = datos.get("_quality") or {}
    quality_score = quality.get("score")
    review_below = datos.get("_review_below_quality", 0.55)
    model_status = "approved"
    if isinstance(quality_score, (int, float)) and quality_score < review_below:
        model_status = "pending_review"
    model_payload = {
        "manufacturer_id": manufacturer["id"],
        "model_name": modelo,
        "normalized_model_name": normalized,
        "model_slug": normalized,
        "short_description": None,
        "primary_category_id": category_id,
        "status": model_status,
        "lifecycle_status": "unknown",
        "source_url": url or None,
        "official_product_url": url or None,
        "confidence_score": quality_score if isinstance(quality_score, (int, float)) else 0.82,
    }
    datos = {
        **datos,
        "_import": {
            "source": "local_csv_supabase_pipeline",
            "csv_row": row_number,
            "mode": mode,
        },
    }
    if existing and mode == "skip":
        return "skipped_duplicate"
    if existing:
        model_id = existing["id"]
        supabase.table("machine_catalog_models").update(model_payload).eq("id", model_id).execute()
        status = "updated"
    else:
        created = supabase.table("machine_catalog_models").insert(model_payload).execute()
        model = get_single(created.data)
        if not model:
            raise RuntimeError("Supabase did not return created model")
        model_id = model["id"]
        status = "created"
        if category_id:
            supabase.table("machine_model_categories").insert(
                {"machine_model_id": model_id, "category_id": category_id, "is_primary": True}
            ).execute()

    supabase.table("machine_model_specs").upsert(spec_payload(model_id, datos), on_conflict="machine_model_id").execute()

    raw_image_url = datos.get("imagen_url")
    is_local = bool(raw_image_url and str(raw_image_url).startswith("file://"))
    image_fetch_url = raw_image_url if is_local else (first_http_url(raw_image_url) if raw_image_url else None)
    # For PDF-extracted images we use the PDF URL as provenance instead
    # of the file:// path, because source_image_url must be a real URL.
    pdf_info = datos.get("_pdf_extract") or {}
    if is_local and pdf_info.get("source_url"):
        recorded_source_url = pdf_info["source_url"]
    else:
        recorded_source_url = image_fetch_url

    if image_fetch_url and recorded_source_url and not image_exists(supabase, model_id, recorded_source_url):
        row: dict[str, Any] = {
            "machine_model_id": model_id,
            "source_image_url": recorded_source_url,
            "source_page_url": url or None,
            "image_type": "front_photo",
            "alt_text": f"{fabricante} {modelo}",
            "is_primary": True,
            "is_official": True,
            "license_status": "official_reference_only",
        }
        if upload_bucket:
            upload = _upload_verified_image(
                supabase,
                bucket=upload_bucket,
                model_id=model_id,
                image_url=image_fetch_url,
            )
            if upload:
                row["storage_url"] = upload.storage_url
                row["hash_sha256"] = upload.sha256
                row["width_px"] = upload.width
                row["height_px"] = upload.height
            elif is_local:
                # We could not upload AND there is no public URL we can
                # point to. Skip the image row entirely; the model row
                # still made it in.
                print(
                    f"[{row_number}] {fabricante} / {modelo}: storage upload "
                    f"failed for a PDF image, skipping image row"
                )
                return status
        elif is_local:
            print(
                f"[{row_number}] {fabricante} / {modelo}: PDF image not stored "
                f"(use --upload-images-bucket to enable Supabase Storage upload)"
            )
            return status
        supabase.table("machine_model_images").insert(row).execute()
    return status


def _upload_verified_image(
    supabase: Client,
    *,
    bucket: str,
    model_id: str,
    image_url: str,
):
    """Fetch the verified image bytes and upload them to Supabase Storage.
    Returns the StorageUpload metadata or `None` on failure."""
    try:
        from crawling.image_verifier import fetch_image_bytes
        from crawling.supabase_storage import upload_image
    except Exception as exc:  # pragma: no cover - optional deps
        print(f"[storage] dependencies missing, skipping upload: {exc}", file=sys.stderr)
        return None
    image_bytes = fetch_image_bytes(image_url)
    if not image_bytes:
        print(f"[storage] could not fetch bytes for {image_url}", file=sys.stderr)
        return None
    return upload_image(
        supabase,
        image_bytes=image_bytes,
        model_id=model_id,
        source_url=image_url,
        bucket=bucket,
    )


def print_extraction_preview(row_number: int, fabricante: str, modelo: str, url: str, datos: dict[str, Any]) -> None:
    print("-" * 80)
    print(f"[{row_number}] Fabricante: {fabricante}")
    print(f"[{row_number}] Modelo: {modelo}")
    print(f"[{row_number}] URL: {url}")
    resolution = datos.get("_resolution") or {}
    if resolution:
        sitemap_info = resolution.get("sitemap") or {}
        print(
            f"[{row_number}] Resolver: chose={resolution.get('chose')} "
            f"nav_changed={resolution.get('nav_changed')} "
            f"sitemap_score={sitemap_info.get('score')}"
        )
    print(f"[{row_number}] Tipo: {datos.get('tipo_maquina')}")
    print(f"[{row_number}] Categoria Supabase: {category_for(datos.get('tipo_maquina'), modelo, datos)}")
    print(f"[{row_number}] Imagen: {datos.get('imagen_url')}")
    physical = datos.get("especificaciones_fisicas") or {}
    energy = datos.get("especificaciones_electricas") or {}
    hardware = datos.get("componentes_hardware") or {}
    if physical:
        print(f"[{row_number}] Fisicas: {json.dumps(physical, ensure_ascii=False)}")
    if energy:
        print(f"[{row_number}] Electricas: {json.dumps(energy, ensure_ascii=False)}")
    if hardware:
        print(f"[{row_number}] Hardware: {json.dumps(hardware, ensure_ascii=False)}")
    quality = datos.get("_quality") or {}
    if quality:
        print(
            f"[{row_number}] Calidad: {quality.get('score')} "
            f"warnings={json.dumps(quality.get('warnings') or [], ensure_ascii=False)}"
        )
    jsonld_info = datos.get("_jsonld_extract") or {}
    if jsonld_info:
        print(
            f"[{row_number}] JSON-LD ({jsonld_info.get('source')}): "
            f"filled={json.dumps(jsonld_info.get('filled_fields') or [], ensure_ascii=False)}"
        )
    crawl_meta = datos.get("_crawl4ai_extract") or {}
    if crawl_meta.get("fetch_source"):
        print(f"[{row_number}] Fetch: {crawl_meta.get('fetch_source')}")
    basic_meta = datos.get("_basic_extract") or {}
    if basic_meta.get("fetch_source") and not crawl_meta.get("fetch_source"):
        print(f"[{row_number}] Fetch: {basic_meta.get('fetch_source')}")
    verification = datos.get("_image_verification") or {}
    if verification:
        chosen = verification.get("chosen")
        if chosen:
            print(
                f"[{row_number}] Imagen verificada: score={chosen.get('clip_score')} "
                f"label={chosen.get('best_label')} size={chosen.get('width')}x{chosen.get('height')}"
            )
        else:
            print(
                f"[{row_number}] Imagen no verificada: candidates={verification.get('candidate_count')} "
                f"rejected={json.dumps([r.get('best_label') or r.get('error') for r in (verification.get('rejected') or [])], ensure_ascii=False)}"
            )
    ai = datos.get("_ai_extract") or {}
    if ai:
        print(
            f"[{row_number}] IA: confidence={ai.get('confidence')} "
            f"uncertain={json.dumps(ai.get('uncertain_fields') or [], ensure_ascii=False)}"
        )
    basic = datos.get("_basic_extract") or {}
    crawl4ai = datos.get("_crawl4ai_extract") or {}
    sample = basic.get("text_sample") or crawl4ai.get("markdown_sample")
    if sample:
        compact = relevant_sample(str(sample), modelo)
        print(f"[{row_number}] Extracto: {compact[:700]}")


def relevant_sample(text: str, modelo: str) -> str:
    lines = []
    for line in text.splitlines():
        compact_line = " ".join(line.split())
        lowered_line = compact_line.lower()
        if not compact_line:
            continue
        if compact_line.startswith(("* [", "* Products", "* About Rhea", "* Rhea Evolution", "[ ![", "![", "Toggle navigation")):
            continue
        if compact_line in {"×", "#", "Menu"}:
            continue
        if lowered_line.startswith(("spare parts", "corporation", "history", "contact", "news")):
            continue
        if compact_line.count("http") >= 2 or compact_line.count("](") >= 2:
            continue
        lines.append(compact_line)
    compact = " ".join(lines) if lines else " ".join(text.split())
    lowered = compact.lower()
    model_candidates = [modelo.lower()]
    model_candidates.extend(
        word.lower()
        for word in re.split(r"[^a-zA-Z0-9]+", modelo)
        if len(word) >= 4 and word.lower() not in {"siline", "series", "public", "machine", "machines"}
    )
    generic_candidates = ["### description", "description", "measures", "product details", "technical", "specifications", "features"]
    generic_candidates.extend(["#### general information", "general information", "#### overview", "overview", "dimensions:"])
    model_positions = [lowered.find(candidate) for candidate in model_candidates if candidate and lowered.find(candidate) >= 0]
    generic_positions = [lowered.find(candidate) for candidate in generic_candidates if lowered.find(candidate) >= 0]
    if model_positions and generic_positions:
        first_model = min(model_positions)
        later_generic = [position for position in generic_positions if position > first_model]
        positions = later_generic or model_positions
    else:
        positions = model_positions or generic_positions
    if not positions:
        return compact
    start = max(min(positions) - 220, 0)
    return compact[start:]


def _interleave_by_host(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Round-robin rows by their URL host so consecutive ones hit different
    servers. This spreads load and reduces the chance any single host
    rate-limits us."""
    from collections import defaultdict, deque

    buckets: dict[str, deque] = defaultdict(deque)
    leftovers: deque = deque()
    for row in rows:
        url = (row.get("URL") or "").strip()
        if not url:
            leftovers.append(row)
            continue
        host = urlparse(url).netloc.lower() or "_unknown"
        buckets[host].append(row)
    ordered: list[dict[str, str]] = []
    while buckets:
        for host in list(buckets.keys()):
            if buckets[host]:
                ordered.append(buckets[host].popleft())
            if not buckets[host]:
                del buckets[host]
    ordered.extend(leftovers)
    return ordered


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"Fabricante", "Modelo"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        return list(reader)


def extraction_text_for_ai(datos: dict[str, Any], max_chars: int) -> str:
    crawl4ai = datos.get("_crawl4ai_extract") or {}
    basic = datos.get("_basic_extract") or {}
    text = crawl4ai.get("markdown_sample") or basic.get("text_sample") or ""
    return str(text)[:max_chars]


def should_use_ai(mode: str, quality: dict[str, Any], fallback_below: float) -> bool:
    if mode == "always":
        return True
    if mode == "fallback":
        score = quality.get("score")
        return isinstance(score, (int, float)) and score < fallback_below
    return False


def apply_image_verification(
    datos: dict[str, Any],
    *,
    verifier,
    max_candidates: int,
) -> dict[str, Any]:
    """Re-pick the canonical image using a CLIP verifier.

    Mutates `datos` in-place: overwrites `imagen_url` with the first
    candidate that passes verification, and stores a diagnostic block
    under `_image_verification` for review/auditing.
    """
    if verifier is None:
        return datos
    candidates: list[str] = list(datos.get("_image_candidates") or [])
    if datos.get("imagen_url") and datos["imagen_url"] not in candidates:
        candidates.insert(0, datos["imagen_url"])
    if not candidates:
        datos["_image_verification"] = {"skipped": "no_candidates"}
        return datos
    rejected: list[dict] = []
    chosen: str | None = None
    chosen_info: dict | None = None
    for candidate in candidates[:max_candidates]:
        try:
            result = verifier(candidate)
        except Exception as exc:
            rejected.append({"url": candidate, "error": str(exc)})
            continue
        info = result.to_dict() if hasattr(result, "to_dict") else {}
        info["url"] = candidate
        if getattr(result, "is_vending", False):
            chosen = candidate
            chosen_info = info
            break
        rejected.append(info)
    datos["imagen_url"] = chosen
    datos["_image_verification"] = {
        "chosen": chosen_info,
        "rejected": rejected,
        "candidate_count": len(candidates),
    }
    return datos


def apply_ai_enrichment(
    datos: dict[str, Any],
    *,
    fabricante: str,
    modelo: str,
    url: str,
    provider: str,
    model: str | None,
    base_url: str,
    timeout: float,
    max_chars: int,
    num_ctx: int | None,
) -> tuple[dict[str, Any], list[str]]:
    if provider != "ollama":
        raise RuntimeError(f"Unsupported AI provider: {provider}")
    if not model:
        raise RuntimeError("AI model is required when AI mode is enabled. Use --ai-model.")
    page_text = extraction_text_for_ai(datos, max_chars)
    if not page_text.strip():
        return datos, ["ai_skipped:empty_page_text"]
    ai = extract_with_ollama(
        base_url=base_url,
        model=model,
        fabricante=fabricante,
        modelo=modelo,
        url=url,
        page_text=page_text,
        current=datos,
        timeout=timeout,
        num_ctx=num_ctx,
    )
    return merge_ai_extraction(datos, ai)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape CSV rows and save catalog models directly in Supabase.")
    parser.add_argument("--csv", default=r"C:\Users\diego\Downloads\vending-machines-formateado.csv")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--start-row", type=int, default=1, help="1-based CSV row number")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--mode", choices=["skip", "update"], default="update")
    parser.add_argument("--extractor", choices=["firecrawl", "crawl4ai", "basic"], default="firecrawl")
    parser.add_argument("--verbose", action="store_true", help="Print extracted URL, image, category and text sample per row")
    parser.add_argument("--ai-provider", choices=["ollama"], default="ollama")
    parser.add_argument("--ai-model", default=None, help="Local Ollama model, for example qwen2.5:7b-instruct")
    parser.add_argument("--ai-mode", choices=["off", "fallback", "always"], default="off")
    parser.add_argument("--ai-base-url", default="http://localhost:11434")
    parser.add_argument("--ai-timeout", type=float, default=90.0)
    parser.add_argument("--ai-max-chars", type=int, default=24000)
    parser.add_argument(
        "--ai-num-ctx",
        type=int,
        default=None,
        help="Ollama context window. Use 4096 or 8192 to reduce VRAM/RAM pressure.",
    )
    parser.add_argument(
        "--ai-fallback-below-quality",
        type=float,
        default=0.75,
        help="Run AI in fallback mode when the rule-based quality score is below this value.",
    )
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.0,
        help="Skip saving rows whose extraction quality score is below this value.",
    )
    parser.add_argument(
        "--review-below-quality",
        type=float,
        default=0.55,
        help="Save rows below this extraction quality score as pending_review instead of approved.",
    )
    parser.add_argument(
        "--verify-images",
        action="store_true",
        help="Use CLIP zero-shot classification to verify candidate images really show a vending machine.",
    )
    parser.add_argument(
        "--image-clip-threshold",
        type=float,
        default=0.55,
        help="Minimum CLIP positive-mass score required to keep an image. Lower = more permissive.",
    )
    parser.add_argument(
        "--image-candidates",
        type=int,
        default=12,
        help="Maximum number of image candidates to feed through the verifier per page.",
    )
    parser.add_argument(
        "--no-page-cache",
        action="store_true",
        help="Disable the on-disk page cache (always refetch).",
    )
    parser.add_argument(
        "--page-cache-ttl",
        type=int,
        default=page_cache.DEFAULT_TTL_SECONDS,
        help="Seconds before a cached page is considered stale. Default 24h.",
    )
    parser.add_argument(
        "--purge-cache",
        action="store_true",
        help="Delete the on-disk page cache and exit immediately.",
    )
    parser.add_argument(
        "--no-sitemap",
        action="store_true",
        help="Disable sitemap-based resolution (navigation-only).",
    )
    parser.add_argument(
        "--sitemap-min-score",
        type=float,
        default=1.4,
        help="Minimum score a sitemap candidate must beat to override the CSV URL.",
    )
    parser.add_argument(
        "--per-host-delay",
        type=float,
        default=None,
        help="Minimum seconds between requests to the same host. Defaults to HTTP_PER_HOST_DELAY env (4.0).",
    )
    parser.add_argument(
        "--request-jitter",
        type=float,
        default=None,
        help="Random extra delay (0..N seconds) added on top of --per-host-delay. Default 1.5s.",
    )
    parser.add_argument(
        "--http-max-retries",
        type=int,
        default=None,
        help="Backoff retries on 429/503/403 responses. Default 2.",
    )
    parser.add_argument(
        "--shuffle-by-host",
        action="store_true",
        help="Reorder rows so consecutive ones hit different hosts (spreads load).",
    )
    parser.add_argument(
        "--upload-images-bucket",
        default=os.environ.get("SUPABASE_IMAGES_BUCKET", ""),
        help=(
            "Supabase Storage bucket to upload verified images to. When set, "
            "machine_model_images.storage_url is populated with the public URL. "
            "Required to store PDF-extracted images. Defaults to env "
            "SUPABASE_IMAGES_BUCKET, otherwise disabled."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    if args.purge_cache:
        deleted = page_cache.purge()
        print(f"[cache] purged {deleted} entries from {page_cache.DEFAULT_CACHE_DIR}")
        return 0

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("Faltan SUPABASE_URL y/o SUPABASE_SERVICE_ROLE_KEY en .env o entorno.", file=sys.stderr)
        return 2

    use_page_cache = not args.no_page_cache
    if use_page_cache:
        print(f"[cache] enabled at {page_cache.DEFAULT_CACHE_DIR} (TTL {args.page_cache_ttl}s)")

    if args.per_host_delay is not None:
        http_client.PER_HOST_DELAY = args.per_host_delay
    if args.request_jitter is not None:
        http_client.JITTER_SECONDS = args.request_jitter
    if args.http_max_retries is not None:
        http_client.MAX_RETRIES = args.http_max_retries
    print(
        f"[http] per-host-delay={http_client.PER_HOST_DELAY}s "
        f"jitter={http_client.JITTER_SECONDS}s retries={http_client.MAX_RETRIES} "
        f"ua_pool={len(http_client.USER_AGENTS)}"
    )

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"No existe el CSV: {csv_path}", file=sys.stderr)
        return 2

    rows = read_rows(csv_path)
    selected = rows[args.start_row - 1 :]
    if args.limit is not None:
        selected = selected[: args.limit]

    if args.shuffle_by_host:
        selected = _interleave_by_host(selected)
        print(f"[http] shuffled {len(selected)} rows so consecutive ones target different hosts")

    supabase = create_client(supabase_url, supabase_key)
    categories = ensure_category_map(supabase)
    counters = Counters()
    serper_key = os.environ.get("SERPER_API_KEY")
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY")

    upload_bucket = (args.upload_images_bucket or "").strip() or None
    if upload_bucket:
        try:
            from crawling.supabase_storage import ensure_bucket

            ensure_bucket(supabase, upload_bucket)
            print(f"[storage] uploads enabled -> bucket {upload_bucket!r}")
        except Exception as exc:
            print(f"[storage] could not prepare bucket {upload_bucket!r}: {exc}", file=sys.stderr)
            upload_bucket = None

    image_verifier = None
    if args.verify_images:
        try:
            from crawling.image_verifier import verify_image_url

            image_verifier = lambda candidate_url: verify_image_url(
                candidate_url, threshold=args.image_clip_threshold
            )
            print("[image-verifier] CLIP zero-shot verification enabled")
        except Exception as exc:  # pragma: no cover - optional dependency wiring
            print(f"[image-verifier] disabled, could not load module: {exc}", file=sys.stderr)
            image_verifier = None

    for offset, row in enumerate(selected, start=args.start_row):
        fabricante = clean_text(row.get("Fabricante"))
        modelo = clean_text(row.get("Modelo"))
        url = clean_text(row.get("URL"))
        if not fabricante or not modelo:
            counters.skipped_incomplete += 1
            print(f"[{offset}] skipped_incomplete")
            continue
        try:
            if not url:
                url = search_url_with_serper(fabricante, modelo, serper_key) or ""
            if not url:
                raise RuntimeError("No URL found. Provide URL column or SERPER_API_KEY.")
            original_url = url
            url, resolution_trace = resolve_best_product_url_from_module(
                url,
                fabricante,
                modelo,
                use_sitemap=not args.no_sitemap,
                sitemap_min_score=args.sitemap_min_score,
            )
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                raise RuntimeError(f"Invalid URL scheme: {url}")
            if resolution_trace.get("chose") == "csv_asset_unresolved":
                counters.skipped_asset_url += 1
                print(
                    f"[{offset}] {fabricante} / {modelo} -> skipped_asset_url: "
                    f"seed URL is a binary asset and sitemap had no model match ({original_url})"
                )
                continue
            if resolution_trace.get("chose") == "csv_asset_pdf":
                datos = extract_from_pdf_module(
                    original_url,
                    fabricante,
                    modelo,
                    use_cache=use_page_cache,
                    cache_ttl=args.page_cache_ttl,
                )
                if not datos:
                    counters.skipped_asset_url += 1
                    print(
                        f"[{offset}] {fabricante} / {modelo} -> skipped_asset_url: "
                        f"PDF download or text extraction failed ({original_url})"
                    )
                    continue
                pdf_info = datos.get("_pdf_extract") or {}
                if pdf_info.get("error") == "model_not_found_in_pdf":
                    counters.skipped_asset_url += 1
                    print(
                        f"[{offset}] {fabricante} / {modelo} -> skipped_asset_url: "
                        f"model {modelo!r} not present in PDF ({original_url})"
                    )
                    continue
                datos["_resolution"] = resolution_trace
                if image_verifier is not None:
                    apply_image_verification(
                        datos,
                        verifier=image_verifier,
                        max_candidates=args.image_candidates,
                    )
                datos["_quality"] = quality_report(original_url, original_url, modelo, datos)
                datos["_review_below_quality"] = args.review_below_quality
                if args.verbose:
                    print_extraction_preview(offset, fabricante, modelo, original_url, datos)
                if args.dry_run:
                    counters.dry_run += 1
                    status = "dry_run"
                elif datos["_quality"]["score"] < args.min_quality:
                    counters.skipped_low_quality += 1
                    status = "skipped_low_quality"
                else:
                    status = save_to_supabase(
                        supabase, categories, fabricante, modelo, original_url, datos, offset, args.mode,
                        upload_bucket=upload_bucket,
                    )
                    setattr(counters, status, getattr(counters, status) + 1)
                print(f"[{offset}] {fabricante} / {modelo} -> {status} (pdf)")
                time.sleep(args.sleep)
                continue
            if args.extractor == "firecrawl":
                datos = scrape_with_firecrawl(url, fabricante, modelo, firecrawl_key) or scrape_basic(
                    url, fabricante, modelo, use_cache=use_page_cache, cache_ttl=args.page_cache_ttl
                )
            elif args.extractor == "crawl4ai":
                datos = scrape_with_crawl4ai(
                    url, fabricante, modelo, use_cache=use_page_cache, cache_ttl=args.page_cache_ttl
                )
            else:
                datos = scrape_basic(
                    url, fabricante, modelo, use_cache=use_page_cache, cache_ttl=args.page_cache_ttl
                )
            datos["_resolution"] = resolution_trace
            if image_verifier is not None:
                apply_image_verification(
                    datos,
                    verifier=image_verifier,
                    max_candidates=args.image_candidates,
                )
            pre_ai_quality = quality_report(original_url, url, modelo, datos)
            ai_warnings: list[str] = []
            if should_use_ai(args.ai_mode, pre_ai_quality, args.ai_fallback_below_quality):
                try:
                    datos, ai_warnings = apply_ai_enrichment(
                        datos,
                        fabricante=fabricante,
                        modelo=modelo,
                        url=url,
                        provider=args.ai_provider,
                        model=args.ai_model,
                        base_url=args.ai_base_url,
                        timeout=args.ai_timeout,
                        max_chars=args.ai_max_chars,
                        num_ctx=args.ai_num_ctx,
                    )
                except Exception as ai_exc:
                    ai_warnings = [f"ai_error:{ai_exc}"]
                    datos["_ai_extract"] = {"error": str(ai_exc), "confidence": None, "uncertain_fields": []}
                    print(f"[{offset}] {fabricante} / {modelo} -> ai_warning: {ai_exc}", file=sys.stderr)
            datos["_quality"] = quality_report(original_url, url, modelo, datos)
            if ai_warnings:
                datos["_quality"]["warnings"] = list(dict.fromkeys([*datos["_quality"]["warnings"], *ai_warnings]))
                if any(warning.startswith(("ai_conflict:", "ai_error:")) for warning in ai_warnings):
                    datos["_quality"]["score"] = min(datos["_quality"]["score"], max(args.review_below_quality - 0.01, 0))
            datos["_review_below_quality"] = args.review_below_quality
            if args.verbose:
                print_extraction_preview(offset, fabricante, modelo, url, datos)
            if args.dry_run:
                counters.dry_run += 1
                status = "dry_run"
            elif datos["_quality"]["score"] < args.min_quality:
                counters.skipped_low_quality += 1
                status = "skipped_low_quality"
            else:
                status = save_to_supabase(
                    supabase, categories, fabricante, modelo, url, datos, offset, args.mode,
                    upload_bucket=upload_bucket,
                )
                setattr(counters, status, getattr(counters, status) + 1)
            print(f"[{offset}] {fabricante} / {modelo} -> {status}")
            time.sleep(args.sleep)
        except Exception as exc:
            counters.failed += 1
            print(f"[{offset}] {fabricante} / {modelo} -> failed: {exc}", file=sys.stderr)

    print(json.dumps(counters.__dict__, ensure_ascii=False, indent=2))
    return 0 if counters.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
