"""Extract structured product data from JSON-LD, microdata and OpenGraph.

When manufacturers publish proper Schema.org Product markup, every field
we extract comes straight from the source of truth: no regex, no LLM,
no ambiguity. This module is the *first* extractor we try.

Coverage:

* JSON-LD `Product` (single or `@graph` list), including nested
  `additionalProperty` (PropertyValue) and `offers`.
* Microdata `itemprop` attributes on `Product` scopes.
* OpenGraph / Twitter meta tags as a last-resort image fallback.

Returns a dict shaped like the rest of the pipeline expects:

    {
        "fabricante": str | None,
        "modelo_base": str | None,
        "tipo_maquina": str | None,
        "imagen_url": str | None,
        "especificaciones_fisicas": {...},
        "especificaciones_electricas": {...},
        "componentes_hardware": {...},
        "_jsonld_extract": {
            "source": "json_ld" | "microdata" | "mixed",
            "filled_fields": [...],
            "raw": <subset of source JSON>,
        },
    }

If nothing useful was found, returns `None` so the caller knows to fall
back to the next extractor in the cascade.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .text_utils import first_http_url, infer_tipo_maquina

logger = logging.getLogger(__name__)


# Schema.org PropertyValue names we know how to map. Comparison is done
# case-insensitively after stripping punctuation.
_DIMENSION_KEYS = {
    "height": "alto_mm",
    "altura": "alto_mm",
    "alto": "alto_mm",
    "width": "ancho_mm",
    "ancho": "ancho_mm",
    "depth": "profundidad_mm",
    "profundidad": "profundidad_mm",
    "fondo": "profundidad_mm",
    "weight": "peso_kg",
    "peso": "peso_kg",
    "netweight": "peso_kg",
    "net_weight": "peso_kg",
}

_ELECTRICAL_KEYS = {
    "voltage": "voltaje",
    "voltaje": "voltaje",
    "supply": "voltaje",
    "power": "potencia_watts",
    "powerconsumption": "potencia_watts",
    "power_consumption": "potencia_watts",
    "potencia": "potencia_watts",
    "wattage": "potencia_watts",
    "refrigerant": "gas_refrigerante",
    "refrigerante": "gas_refrigerante",
    "gas_refrigerante": "gas_refrigerante",
}

_HARDWARE_KEYS = {
    "capacity": "capacidad_canales_o_espirales",
    "selections": "capacidad_canales_o_espirales",
    "channels": "capacidad_canales_o_espirales",
    "espirales": "capacidad_canales_o_espirales",
    "trays": "capacidad_canales_o_espirales",
    "cups": "capacidad_vasos",
    "vasos": "capacidad_vasos",
    "screen": "touchscreen_pulgadas",
    "touchscreen": "touchscreen_pulgadas",
    "display": "touchscreen_pulgadas",
    "telemetry": "telemetria_integrada",
    "telemetria": "telemetria_integrada",
    "brewer": "grupo_infusor",
    "brewunit": "grupo_infusor",
    "brew_unit": "grupo_infusor",
}


def extract_from_html(
    html: str,
    base_url: str,
    fabricante: str,
    modelo: str,
) -> Optional[dict[str, Any]]:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    nodes = _collect_product_nodes(soup)
    if not nodes:
        microdata = _extract_microdata_product(soup, base_url)
        if not microdata:
            return None
        nodes = [microdata]
        source_tag = "microdata"
    else:
        microdata = _extract_microdata_product(soup, base_url)
        if microdata:
            nodes.append(microdata)
            source_tag = "mixed"
        else:
            source_tag = "json_ld"

    best = _pick_best_product(nodes, fabricante, modelo)
    if not best:
        return None

    result = _build_payload(best, base_url, fabricante, modelo)
    if not _has_any_useful_field(result):
        return None
    result["_jsonld_extract"] = {
        "source": source_tag,
        "filled_fields": _filled_fields(result),
        "raw": _raw_subset(best),
    }
    return result


# ---------------------------------------------------------------------------
# JSON-LD collection
# ---------------------------------------------------------------------------


def _collect_product_nodes(soup: BeautifulSoup) -> list[dict]:
    products: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        text = tag.string or tag.get_text() or ""
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            cleaned = _try_repair_json(text)
            if cleaned is None:
                continue
            data = cleaned
        for node in _walk_for_products(data):
            products.append(node)
    return products


def _try_repair_json(text: str) -> Any:
    # Some sites embed multiple JSON objects separated by newlines; try one by one.
    try:
        return json.loads(text.strip().rstrip(","))
    except Exception:
        pass
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)  # trailing commas
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def _walk_for_products(data: Any) -> Iterable[dict]:
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                yield from _walk_for_products(node)
            return
        type_value = data.get("@type")
        if _matches_product_type(type_value):
            yield data
        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from _walk_for_products(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_for_products(item)


_PRODUCT_TYPES = {"product", "individualproduct", "productmodel", "vehicle", "offer"}


def _matches_product_type(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower().replace(" ", "") in _PRODUCT_TYPES
    if isinstance(value, list):
        return any(_matches_product_type(item) for item in value)
    return False


def _pick_best_product(nodes: list[dict], fabricante: str, modelo: str) -> Optional[dict]:
    if not nodes:
        return None
    tokens = [t.lower() for t in re.split(r"[^a-zA-Z0-9]+", modelo) if len(t) >= 3]
    fab_tokens = [t.lower() for t in re.split(r"[^a-zA-Z0-9]+", fabricante) if len(t) >= 3]

    def score(node: dict) -> int:
        s = 0
        name = (node.get("name") or "").lower()
        sku = (node.get("sku") or "").lower()
        mpn = (node.get("mpn") or "").lower()
        haystack = f"{name} {sku} {mpn}"
        for token in tokens:
            if token in haystack:
                s += 3
        for token in fab_tokens:
            if token in haystack:
                s += 1
        if node.get("additionalProperty"):
            s += 2
        if node.get("image"):
            s += 1
        return s

    nodes_sorted = sorted(nodes, key=score, reverse=True)
    return nodes_sorted[0]


# ---------------------------------------------------------------------------
# Microdata fallback
# ---------------------------------------------------------------------------


def _extract_microdata_product(soup: BeautifulSoup, base_url: str) -> Optional[dict]:
    scope = soup.find(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)})
    if not scope:
        return None
    payload: dict[str, Any] = {"@type": "Product"}
    props: list[dict] = []
    for el in scope.find_all(attrs={"itemprop": True}):
        prop = (el.get("itemprop") or "").strip()
        value = el.get("content") or el.get("href") or el.get_text(" ", strip=True)
        if not prop or not value:
            continue
        if prop.lower() in {"image", "url"}:
            value = urljoin(base_url, value)
        if prop in payload:
            existing = payload[prop]
            if isinstance(existing, list):
                existing.append(value)
            else:
                payload[prop] = [existing, value]
        else:
            payload[prop] = value
    # promote additionalProperty children into a list so the rest of the
    # mapping code can reuse the same logic.
    for el in scope.select('[itemtype*="schema.org/PropertyValue"]'):
        name_el = el.find(attrs={"itemprop": "name"})
        value_el = el.find(attrs={"itemprop": "value"})
        if name_el and value_el:
            props.append(
                {
                    "@type": "PropertyValue",
                    "name": name_el.get_text(" ", strip=True),
                    "value": value_el.get("content") or value_el.get_text(" ", strip=True),
                }
            )
    if props:
        payload["additionalProperty"] = props
    return payload if (payload.get("name") or props) else None


# ---------------------------------------------------------------------------
# Mapping JSON-LD product → catalog payload
# ---------------------------------------------------------------------------


def _build_payload(
    node: dict,
    base_url: str,
    fabricante: str,
    modelo: str,
) -> dict[str, Any]:
    physical: dict[str, Any] = {"alto_mm": None, "ancho_mm": None, "profundidad_mm": None, "peso_kg": None}
    electrical: dict[str, Any] = {"voltaje": None, "potencia_watts": None, "gas_refrigerante": None}
    hardware: dict[str, Any] = {
        "grupo_infusor": None,
        "mecanica_extraccion": None,
        "capacidad_vasos": None,
        "capacidad_canales_o_espirales": None,
        "telemetria_integrada": None,
        "touchscreen_pulgadas": None,
    }

    # Schema.org top-level dimensional properties
    _apply_dimension(physical, "alto_mm", node.get("height"))
    _apply_dimension(physical, "ancho_mm", node.get("width"))
    _apply_dimension(physical, "profundidad_mm", node.get("depth"))
    _apply_weight(physical, node.get("weight"))

    # additionalProperty[] is where vending sites usually put real specs
    for prop in _iter_additional_properties(node):
        name = (prop.get("name") or prop.get("propertyID") or "").strip()
        value = prop.get("value")
        if name is None or value in (None, ""):
            continue
        key = _normalize_key(name)
        if key in _DIMENSION_KEYS:
            target = _DIMENSION_KEYS[key]
            if target == "peso_kg":
                _apply_weight(physical, value)
            else:
                _apply_dimension(physical, target, value)
        elif key in _ELECTRICAL_KEYS:
            target = _ELECTRICAL_KEYS[key]
            if target == "potencia_watts":
                electrical[target] = _stringify(value)
            else:
                electrical[target] = _stringify(value)
        elif key in _HARDWARE_KEYS:
            target = _HARDWARE_KEYS[key]
            if target == "telemetria_integrada":
                hardware[target] = _to_bool(value)
            elif target == "touchscreen_pulgadas":
                hardware[target] = _to_inches(value)
            elif target == "capacidad_vasos":
                hardware[target] = _to_int(value)
            else:
                hardware[target] = _stringify(value)

    image = _pick_image(node, base_url)
    name = node.get("name") or ""
    brand = _brand_name(node) or fabricante
    description = node.get("description") or ""
    combined_text = f"{brand} {name} {description}".strip()
    tipo = infer_tipo_maquina(combined_text) or infer_tipo_maquina(f"{fabricante} {modelo}")

    return {
        "fabricante": brand or fabricante,
        "modelo_base": _pick_model_name(node, modelo),
        "tipo_maquina": tipo,
        "imagen_url": image,
        "versiones_disponibles": [],
        "especificaciones_fisicas": physical,
        "especificaciones_electricas": electrical,
        "componentes_hardware": hardware,
    }


def _iter_additional_properties(node: dict) -> Iterable[dict]:
    props = node.get("additionalProperty") or node.get("additionalProperties") or []
    if isinstance(props, dict):
        props = [props]
    if not isinstance(props, list):
        return []
    return [p for p in props if isinstance(p, dict)]


def _brand_name(node: dict) -> Optional[str]:
    brand = node.get("brand") or node.get("manufacturer")
    if isinstance(brand, dict):
        return brand.get("name") or brand.get("legalName")
    if isinstance(brand, list):
        for item in brand:
            if isinstance(item, dict) and item.get("name"):
                return item["name"]
            if isinstance(item, str):
                return item
    if isinstance(brand, str):
        return brand
    return None


def _pick_model_name(node: dict, fallback: str) -> str:
    return (
        _stringify(node.get("model"))
        or _stringify(node.get("mpn"))
        or _stringify(node.get("sku"))
        or _stringify(node.get("name"))
        or fallback
    )


def _pick_image(node: dict, base_url: str) -> Optional[str]:
    image = node.get("image")
    if isinstance(image, list):
        image = next((i for i in image if i), None)
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if isinstance(image, str) and image.strip():
        absolute = first_http_url(urljoin(base_url, image.strip()))
        return absolute
    return None


def _normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        # QuantitativeValue {"value": 220, "unitText": "V"}
        v = value.get("value")
        unit = value.get("unitText") or value.get("unitCode")
        if v is None:
            return None
        return f"{v} {unit}".strip() if unit else str(v)
    return str(value).strip() or None


def _to_int(value: Any) -> Optional[int]:
    text = _stringify(value)
    if not text:
        return None
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else None


def _to_inches(value: Any) -> Optional[float]:
    text = _stringify(value)
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(match.group(1).replace(",", ".")) if match else None


def _to_bool(value: Any) -> Optional[bool]:
    text = _stringify(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "yes", "si", "sí", "1", "enabled", "available"}:
        return True
    if lowered in {"false", "no", "0", "disabled", "n/a"}:
        return False
    return None


def _apply_dimension(target: dict, key: str, value: Any) -> None:
    mm = _to_millimetres(value)
    if mm is not None:
        target[key] = mm


def _apply_weight(target: dict, value: Any) -> None:
    kg = _to_kilograms(value)
    if kg is not None:
        target["peso_kg"] = kg


def _to_millimetres(value: Any) -> Optional[int]:
    text = _stringify(value)
    if not text:
        return None
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(mm|cm|m|in|inches)?", text, re.I)
    if not match:
        return None
    raw = float(match.group(1).replace(",", "."))
    unit = (match.group(2) or "mm").lower()
    if unit == "mm":
        return int(round(raw))
    if unit == "cm":
        return int(round(raw * 10))
    if unit == "m":
        return int(round(raw * 1000))
    if unit in {"in", "inches"}:
        return int(round(raw * 25.4))
    return int(round(raw))


def _to_kilograms(value: Any) -> Optional[float]:
    text = _stringify(value)
    if not text:
        return None
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(kg|g|lbs?|lb|pounds?)?", text, re.I)
    if not match:
        return None
    raw = float(match.group(1).replace(",", "."))
    unit = (match.group(2) or "kg").lower()
    if unit == "kg":
        return raw
    if unit == "g":
        return raw / 1000.0
    if unit in {"lb", "lbs", "pound", "pounds"}:
        return round(raw * 0.45359237, 2)
    return raw


def _filled_fields(payload: dict) -> list[str]:
    filled: list[str] = []
    for group_key in ("especificaciones_fisicas", "especificaciones_electricas", "componentes_hardware"):
        for field, value in (payload.get(group_key) or {}).items():
            if value not in (None, "", [], {}):
                filled.append(f"{group_key}.{field}")
    for key in ("fabricante", "modelo_base", "tipo_maquina", "imagen_url"):
        if payload.get(key):
            filled.append(key)
    return filled


def _has_any_useful_field(payload: dict) -> bool:
    return bool(_filled_fields(payload))


def _raw_subset(node: dict) -> dict:
    interesting = {
        k: node.get(k)
        for k in (
            "@type",
            "name",
            "sku",
            "mpn",
            "model",
            "brand",
            "manufacturer",
            "height",
            "width",
            "depth",
            "weight",
        )
        if k in node
    }
    props = list(_iter_additional_properties(node))
    if props:
        interesting["additionalProperty"] = props[:30]
    return interesting


# ---------------------------------------------------------------------------
# Merging helpers used by the main scraper
# ---------------------------------------------------------------------------


def merge_into(base: dict[str, Any], jsonld: dict[str, Any]) -> dict[str, Any]:
    """Overlay JSON-LD values onto an existing payload only when the base
    field is empty. The base wins by default because the rule-based
    extractor may have already merged finer-grained per-block specs.
    """
    if not jsonld:
        return base
    for top_key in ("fabricante", "modelo_base", "tipo_maquina", "imagen_url"):
        if not base.get(top_key) and jsonld.get(top_key):
            base[top_key] = jsonld[top_key]
    for group_key in ("especificaciones_fisicas", "especificaciones_electricas", "componentes_hardware"):
        base.setdefault(group_key, {})
        for field, value in (jsonld.get(group_key) or {}).items():
            if value in (None, "", [], {}):
                continue
            if base[group_key].get(field) in (None, "", [], {}):
                base[group_key][field] = value
    if jsonld.get("_jsonld_extract"):
        base["_jsonld_extract"] = jsonld["_jsonld_extract"]
    return base
