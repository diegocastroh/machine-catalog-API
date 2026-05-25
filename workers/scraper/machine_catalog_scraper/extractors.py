import json
from bs4 import BeautifulSoup

from .normalizer import absolute_url, confidence_score, detect_category, detect_terms, extract_dimensions


def extract_page(url: str, html: str, source_config: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    jsonld = _extract_jsonld_product(soup)
    og = _extract_opengraph(soup)
    visible_text = " ".join(soup.stripped_strings)
    title = jsonld.get("name") or og.get("title") or _text(soup.find("h1"))
    manufacturer = _name_from_value(jsonld.get("manufacturer")) or _name_from_value(jsonld.get("brand")) or source_config.get("manufacturer")
    description = jsonld.get("description") or og.get("description") or visible_text[:500]
    text = f"{title or ''} {description or ''} {visible_text}"
    images = _extract_images(url, soup, og)
    documents = _extract_documents(url, soup)
    specs = {
        **extract_dimensions(text),
        "payment_protocols": detect_terms(text, ["MDB", "EVA-DTS", "cashless", "Nayax", "telemetry"]),
        "connectivity": detect_terms(text, ["WiFi", "Ethernet", "4G", "Bluetooth"]),
        "refrigerated": "refrigerated" in text.lower() or "cold" in text.lower(),
        "freezer": "freezer" in text.lower() or "frozen" in text.lower(),
        "heated": "heated" in text.lower() or "hot food" in text.lower(),
        "touchscreen": "touchscreen" in text.lower() or "touch screen" in text.lower(),
        "raw_specs": _extract_table_specs(soup),
    }
    category = detect_category(text)

    return {
        "manufacturer_name": manufacturer,
        "brand_name": _name_from_value(jsonld.get("brand")),
        "model_name": title,
        "category_code": category,
        "description": description,
        "specs": specs,
        "images": images,
        "documents": documents,
        "confidence_score": confidence_score(
            official=True,
            model_name=bool(title),
            category=category != "other",
            image=bool(images),
            document=bool(documents),
            specs=bool(specs),
        ),
        "validation_flags": [] if title else ["missing_model_name"],
    }


def _extract_jsonld_product(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            parsed = json.loads(script.string or "{}")
        except json.JSONDecodeError:
            continue
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                return candidate
    return {}


def _extract_opengraph(soup: BeautifulSoup) -> dict:
    def content(prop: str) -> str | None:
        tag = soup.find("meta", {"property": prop})
        return tag.get("content") if tag else None

    return {"title": content("og:title"), "description": content("og:description"), "image": content("og:image")}


def _extract_images(url: str, soup: BeautifulSoup, og: dict) -> list[dict]:
    images = []
    if og.get("image"):
        images.append({"source_image_url": absolute_url(url, og["image"]), "source_page_url": url, "image_type": "front_photo", "is_primary": True, "is_official": True, "license_status": "official_reference_only"})
    for image in soup.find_all("img"):
        src = absolute_url(url, image.get("src"))
        if src and all(item["source_image_url"] != src for item in images):
            images.append({"source_image_url": src, "source_page_url": url, "image_type": "gallery", "alt_text": image.get("alt"), "is_primary": False, "is_official": False, "license_status": "unknown"})
    return images


def _extract_documents(url: str, soup: BeautifulSoup) -> list[dict]:
    documents = []
    for link in soup.find_all("a"):
        href = link.get("href")
        if href and href.lower().endswith(".pdf"):
            documents.append({"source_url": absolute_url(url, href), "document_type": "brochure", "title": _text(link) or "PDF"})
    return documents


def _extract_table_specs(soup: BeautifulSoup) -> dict:
    specs = {}
    for row in soup.find_all("tr"):
        cells = [_text(cell) for cell in row.find_all(["th", "td"])]
        if len(cells) >= 2:
            specs[cells[0].lower()] = cells[1]
    return specs


def _name_from_value(value) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    return value if isinstance(value, str) else None


def _text(node) -> str | None:
    return node.get_text(" ", strip=True) if node else None
