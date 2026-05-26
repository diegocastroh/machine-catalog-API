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
from typing import Any
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
    json_data.setdefault("versiones_disponibles", [])
    json_data.setdefault("especificaciones_fisicas", {})
    json_data.setdefault("especificaciones_electricas", {})
    json_data.setdefault("componentes_hardware", {})
    return json_data


def scrape_basic(url: str, fabricante: str, modelo: str) -> dict[str, Any]:
    response = requests.get(url, timeout=30, headers={"user-agent": "MachineCatalogImporter/1.0"})
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = remove_cookie_noise(soup.get_text("\n", strip=True))[:12000]
    tipo = infer_tipo_maquina(f"{fabricante} {modelo} {title} {text}")
    return {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": tipo,
        "imagen_url": first_http_url(choose_best_image_from_html(html, url, fabricante, modelo)),
        "versiones_disponibles": [],
        **extract_specs_from_text(text),
        "_basic_extract": {"title": title, "text_sample": text[:2000]},
    }


async def crawl4ai_fetch(url: str) -> tuple[str | None, str | None]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    browser_config = BrowserConfig(headless=True)
    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, markdown_generator=DefaultMarkdownGenerator())
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "error_message", "Crawl4AI crawl failed"))
    markdown = getattr(result, "markdown", None)
    if hasattr(markdown, "fit_markdown"):
        markdown_text = markdown.fit_markdown or getattr(markdown, "raw_markdown", None)
    elif hasattr(markdown, "raw_markdown"):
        markdown_text = markdown.raw_markdown
    else:
        markdown_text = str(markdown or "")
    html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
    return markdown_text, html


def scrape_with_crawl4ai(url: str, fabricante: str, modelo: str) -> dict[str, Any]:
    if importlib.util.find_spec("crawl4ai") is None:
        raise RuntimeError(
            "Crawl4AI no esta instalado. Ejecuta: python -m pip install -r scripts/requirements-supabase-pipeline.txt"
        )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    markdown, html = asyncio.run(crawl4ai_fetch(url))
    markdown = remove_cookie_noise(markdown)
    combined = f"{fabricante} {modelo} {markdown}"
    return {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": infer_tipo_maquina(combined),
        "imagen_url": first_http_url(choose_best_image_from_html(html, url, fabricante, modelo)),
        "versiones_disponibles": [],
        **extract_specs_from_text(markdown),
        "_crawl4ai_extract": {
            "markdown_sample": (markdown or "")[:12000],
        },
    }


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

    return {
        "especificaciones_fisicas": {
            "alto_mm": number_after("height"),
            "ancho_mm": number_after("width"),
            "profundidad_mm": number_after("depth"),
            "peso_kg": None,
        },
        "especificaciones_electricas": {
            "voltaje": first_match(r"electrical supply\s*[:\-]?\s*([^\n\r]+)"),
            "potencia_watts": None,
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
) -> str:
    manufacturer = ensure_manufacturer(supabase, fabricante)
    existing = find_model(supabase, manufacturer["id"], modelo)
    category_code = category_for(datos.get("tipo_maquina"), modelo, datos)
    category_id = categories.get(category_code)
    normalized = slugify(modelo)
    model_payload = {
        "manufacturer_id": manufacturer["id"],
        "model_name": modelo,
        "normalized_model_name": normalized,
        "model_slug": normalized,
        "short_description": None,
        "primary_category_id": category_id,
        "status": "approved",
        "lifecycle_status": "unknown",
        "source_url": url or None,
        "official_product_url": url or None,
        "confidence_score": 0.82,
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

    image_url = datos.get("imagen_url")
    image_url = first_http_url(image_url)
    if image_url and not image_exists(supabase, model_id, image_url):
        supabase.table("machine_model_images").insert(
            {
                "machine_model_id": model_id,
                "source_image_url": image_url,
                "source_page_url": url or None,
                "image_type": "front_photo",
                "alt_text": f"{fabricante} {modelo}",
                "is_primary": True,
                "is_official": True,
                "license_status": "official_reference_only",
            }
        ).execute()
    return status


def print_extraction_preview(row_number: int, fabricante: str, modelo: str, url: str, datos: dict[str, Any]) -> None:
    print("-" * 80)
    print(f"[{row_number}] Fabricante: {fabricante}")
    print(f"[{row_number}] Modelo: {modelo}")
    print(f"[{row_number}] URL: {url}")
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
    model_candidates.extend(word.lower() for word in re.split(r"[^a-zA-Z0-9]+", modelo) if len(word) >= 4)
    generic_candidates = ["### description", "description", "measures", "product details", "technical", "specifications", "features"]
    model_positions = [lowered.find(candidate) for candidate in model_candidates if candidate and lowered.find(candidate) >= 0]
    positions = model_positions or [lowered.find(candidate) for candidate in generic_candidates if lowered.find(candidate) >= 0]
    if not positions:
        return compact
    start = max(min(positions) - 220, 0)
    return compact[start:]


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"Fabricante", "Modelo"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        return list(reader)


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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("Faltan SUPABASE_URL y/o SUPABASE_SERVICE_ROLE_KEY en .env o entorno.", file=sys.stderr)
        return 2

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"No existe el CSV: {csv_path}", file=sys.stderr)
        return 2

    rows = read_rows(csv_path)
    selected = rows[args.start_row - 1 :]
    if args.limit is not None:
        selected = selected[: args.limit]

    supabase = create_client(supabase_url, supabase_key)
    categories = ensure_category_map(supabase)
    counters = Counters()
    serper_key = os.environ.get("SERPER_API_KEY")
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY")

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
            url = resolve_product_url(url, fabricante, modelo)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                raise RuntimeError(f"Invalid URL scheme: {url}")
            if args.extractor == "firecrawl":
                datos = scrape_with_firecrawl(url, fabricante, modelo, firecrawl_key) or scrape_basic(url, fabricante, modelo)
            elif args.extractor == "crawl4ai":
                datos = scrape_with_crawl4ai(url, fabricante, modelo)
            else:
                datos = scrape_basic(url, fabricante, modelo)
            if args.verbose:
                print_extraction_preview(offset, fabricante, modelo, url, datos)
            if args.dry_run:
                counters.dry_run += 1
                status = "dry_run"
            else:
                status = save_to_supabase(supabase, categories, fabricante, modelo, url, datos, offset, args.mode)
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
