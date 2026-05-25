import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from .extractors import extract_page


def crawl_dynamic_single_page(config: dict, output_path: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent="MachineCatalogBot")
        page.goto(config["base_url"], wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()

    normalized = extract_page(config["base_url"], html, config)
    payload = {
        "url": config["base_url"],
        "manufacturer_id": config.get("manufacturer_id"),
        "source_type": "product_page",
        "crawl_allowed": True,
        "raw": {
            "raw_html": html,
            "raw_text": " ".join(html.split())[:20000],
            "raw_json": {"renderer": "playwright"},
            "detected_images": normalized.get("images", []),
            "detected_links": normalized.get("documents", []),
        },
        "normalized": normalized,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
