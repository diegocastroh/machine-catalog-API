from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

import requests

from .text_utils import first_http_url


AI_SCHEMA = {
    "type": "object",
    "properties": {
        "fabricante": {"type": ["string", "null"]},
        "modelo_base": {"type": ["string", "null"]},
        "tipo_maquina": {"type": ["string", "null"]},
        "imagen_url": {"type": ["string", "null"]},
        "versiones_disponibles": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": ["number", "null"]},
        "uncertain_fields": {"type": "array", "items": {"type": "string"}},
        "especificaciones_fisicas": {
            "type": "object",
            "properties": {
                "alto_mm": {"type": ["number", "integer", "null"]},
                "ancho_mm": {"type": ["number", "integer", "null"]},
                "profundidad_mm": {"type": ["number", "integer", "null"]},
                "peso_kg": {"type": ["number", "integer", "null"]},
            },
        },
        "especificaciones_electricas": {
            "type": "object",
            "properties": {
                "voltaje": {"type": ["string", "null"]},
                "potencia_watts": {"type": ["number", "integer", "string", "null"]},
                "gas_refrigerante": {"type": ["string", "null"]},
            },
        },
        "componentes_hardware": {
            "type": "object",
            "properties": {
                "grupo_infusor": {"type": ["string", "null"]},
                "mecanica_extraccion": {"type": ["string", "null"]},
                "capacidad_vasos": {"type": ["number", "integer", "null"]},
                "capacidad_canales_o_espirales": {"type": ["string", "null"]},
                "telemetria_integrada": {"type": ["boolean", "null"]},
                "touchscreen_pulgadas": {"type": ["number", "integer", "null"]},
            },
        },
    },
    "required": [
        "tipo_maquina",
        "imagen_url",
        "especificaciones_fisicas",
        "especificaciones_electricas",
        "componentes_hardware",
        "confidence",
        "uncertain_fields",
    ],
}


def parse_ai_json(content: str) -> dict[str, Any]:
    text = content.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("AI response did not contain a JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON must be an object")
    return parsed


def build_prompt(fabricante: str, modelo: str, url: str, page_text: str, current: dict[str, Any]) -> str:
    return f"""
Eres un extractor tecnico para un catalogo de maquinas vending.

Objetivo:
- Extrae solo datos del modelo indicado.
- No inventes valores. Si no esta claro, usa null y agrega el campo a uncertain_fields.
- Convierte dimensiones a milimetros y peso a kilogramos cuando el texto lo permita.
- Para tipo_maquina usa solo: coffee, snack, drink, combo, food, frozen, locker, industrial u otro.
- La imagen_url debe ser una URL absoluta de la maquina, no logo, icono, banner ni placeholder.
- Si hay varios modelos en la pagina, prioriza el modelo esperado.

Fabricante esperado: {fabricante}
Modelo esperado: {modelo}
URL: {url}

Extraccion previa por reglas:
{json.dumps(current, ensure_ascii=False)[:6000]}

Contenido de la pagina:
{page_text}

Responde unicamente JSON valido con el schema solicitado.
""".strip()


def extract_with_ollama(
    *,
    base_url: str,
    model: str,
    fabricante: str,
    modelo: str,
    url: str,
    page_text: str,
    current: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/api/chat"
    prompt = build_prompt(fabricante, modelo, url, page_text, current)
    response = requests.post(
        endpoint,
        json={
            "model": model,
            "stream": False,
            "format": AI_SCHEMA,
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": "Devuelve solo JSON valido. No uses markdown.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload.get("message") or {}
    content = message.get("content") or payload.get("response") or ""
    return normalize_ai_extraction(parse_ai_json(content))


def normalize_ai_extraction(data: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(data)
    normalized.setdefault("especificaciones_fisicas", {})
    normalized.setdefault("especificaciones_electricas", {})
    normalized.setdefault("componentes_hardware", {})
    normalized.setdefault("versiones_disponibles", [])
    normalized.setdefault("uncertain_fields", [])

    image = normalized.get("imagen_url")
    normalized["imagen_url"] = first_http_url(image) if isinstance(image, str) else None

    confidence = normalized.get("confidence")
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = None
    if isinstance(confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = None
    normalized["confidence"] = confidence
    return normalized


def merge_ai_extraction(base: dict[str, Any], ai: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = deepcopy(base)
    normalized_ai = normalize_ai_extraction(ai)
    warnings: list[str] = []

    for key in ["tipo_maquina", "imagen_url"]:
        _merge_scalar(merged, normalized_ai, key, warnings)

    for group in ["especificaciones_fisicas", "especificaciones_electricas", "componentes_hardware"]:
        merged.setdefault(group, {})
        source_group = normalized_ai.get(group) or {}
        for key, value in source_group.items():
            if _is_empty(value):
                continue
            target = merged[group].get(key)
            if _is_empty(target):
                merged[group][key] = value
            elif not _values_equivalent(target, value):
                warnings.append(f"ai_conflict:{group}.{key}")

    existing_versions = merged.get("versiones_disponibles") or []
    ai_versions = normalized_ai.get("versiones_disponibles") or []
    merged["versiones_disponibles"] = list(dict.fromkeys([*existing_versions, *ai_versions]))
    merged["_ai_extract"] = {
        "confidence": normalized_ai.get("confidence"),
        "uncertain_fields": normalized_ai.get("uncertain_fields") or [],
        "raw": normalized_ai,
    }
    return merged, warnings


def _merge_scalar(target: dict[str, Any], source: dict[str, Any], key: str, warnings: list[str]) -> None:
    value = source.get(key)
    if _is_empty(value):
        return
    current = target.get(key)
    if _is_empty(current):
        target[key] = value
    elif not _values_equivalent(current, value):
        warnings.append(f"ai_conflict:{key}")


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _values_equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return " ".join(left.lower().split()) == " ".join(right.lower().split())
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 0.001
    return left == right
