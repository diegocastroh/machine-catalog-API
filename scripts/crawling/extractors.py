from __future__ import annotations

import asyncio
import importlib.util
import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .images import choose_best_image_from_html, is_probably_bad_image
from .resolvers import is_sielaff_public_series_model
from .specs import apply_sielaff_public_series_specs, extract_specs_from_text
from .text_utils import first_http_url, infer_tipo_maquina, remove_cookie_noise


def normalize_json(value):
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


def scrape_with_firecrawl(url: str, fabricante: str, modelo: str, firecrawl_api_key: str | None) -> dict | None:
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


def scrape_basic(url: str, fabricante: str, modelo: str) -> dict:
    response = requests.get(url, timeout=30, headers={"user-agent": "MachineCatalogImporter/1.0"})
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = remove_cookie_noise(soup.get_text("\n", strip=True))[:12000]
    return {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": infer_tipo_maquina(f"{fabricante} {modelo} {title} {text}"),
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
    if hasattr(markdown, "raw_markdown"):
        markdown_text = markdown.raw_markdown
    elif hasattr(markdown, "fit_markdown"):
        markdown_text = markdown.fit_markdown
    else:
        markdown_text = str(markdown or "")
    html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
    return markdown_text, html


def scrape_with_crawl4ai(url: str, fabricante: str, modelo: str) -> dict:
    if importlib.util.find_spec("crawl4ai") is None:
        raise RuntimeError(
            "Crawl4AI no esta instalado. Ejecuta: python -m pip install -r scripts/requirements-supabase-pipeline.txt"
        )
    markdown, html = asyncio.run(crawl4ai_fetch(url))
    markdown = remove_cookie_noise(markdown)
    html_text = remove_cookie_noise(BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True))
    extraction_text = f"{markdown}\n{html_text}".strip()
    combined = f"{fabricante} {modelo} {extraction_text}"
    specs = extract_specs_from_text(extraction_text)
    if "sielaff" in fabricante.lower() and is_sielaff_public_series_model(modelo):
        apply_sielaff_public_series_specs(modelo, extraction_text, specs)
    return {
        "fabricante": fabricante,
        "modelo_base": modelo,
        "tipo_maquina": infer_tipo_maquina(combined),
        "imagen_url": first_http_url(choose_best_image_from_html(html, url, fabricante, modelo)),
        "versiones_disponibles": [],
        **specs,
        "_crawl4ai_extract": {
            "markdown_sample": extraction_text[:60000],
        },
    }
