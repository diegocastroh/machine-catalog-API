from __future__ import annotations

import re
from typing import Any

from .text_utils import remove_cookie_noise


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
        context = match.group("context")
        weight_match = re.search(r"weight(?:[^:\n\r]*)?\s*[:\-]?\s*(?:approx\.\s*)?([0-9.,]+)\s*kg", context, re.I)
        voltage_match = re.search(r"electrical connection values\s*[:\-]?\s*([^\n\r]+)", context, re.I)
        power_match = re.search(r"(?:power consumption|output)\s*[:\-]?\s*([0-9.,]+(?:\s*-\s*[0-9.,]+)?\s*w)", context, re.I)
        blocks.append(
            {
                "height": number_from_match(match, 1),
                "width": number_from_match(match, 2),
                "depth": number_from_match(match, 3),
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

    selected = blocks[0]
    if target_width:
        selected = min(
            blocks,
            key=lambda block: abs((block["width"] or 0) - target_width) + abs((block["depth"] or 0) - target_depth),
        )

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
