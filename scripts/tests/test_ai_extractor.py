import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from crawling.ai_extractor import merge_ai_extraction, parse_ai_json


def test_parse_ai_json_accepts_wrapped_json_object():
    parsed = parse_ai_json(
        """
        Resultado:
        {
          "tipo_maquina": "drink",
          "confidence": 0.82,
          "especificaciones_fisicas": {"alto_mm": 1840}
        }
        """
    )

    assert parsed["tipo_maquina"] == "drink"
    assert parsed["confidence"] == 0.82
    assert parsed["especificaciones_fisicas"]["alto_mm"] == 1840


def test_merge_ai_extraction_fills_missing_fields_without_conflict():
    base = {
        "tipo_maquina": None,
        "imagen_url": None,
        "especificaciones_fisicas": {"alto_mm": None, "ancho_mm": 625},
        "especificaciones_electricas": {"voltaje": None},
        "componentes_hardware": {"telemetria_integrada": None},
    }
    ai = {
        "tipo_maquina": "drink",
        "imagen_url": "https://example.com/machine.png",
        "confidence": 0.91,
        "especificaciones_fisicas": {"alto_mm": 1840, "ancho_mm": 625},
        "especificaciones_electricas": {"voltaje": "230 V"},
        "componentes_hardware": {"telemetria_integrada": True},
    }

    merged, warnings = merge_ai_extraction(base, ai)

    assert merged["tipo_maquina"] == "drink"
    assert merged["imagen_url"] == "https://example.com/machine.png"
    assert merged["especificaciones_fisicas"]["alto_mm"] == 1840
    assert merged["especificaciones_fisicas"]["ancho_mm"] == 625
    assert merged["especificaciones_electricas"]["voltaje"] == "230 V"
    assert merged["componentes_hardware"]["telemetria_integrada"] is True
    assert merged["_ai_extract"]["confidence"] == 0.91
    assert warnings == []


def test_merge_ai_extraction_keeps_rule_value_and_reports_conflict():
    base = {
        "tipo_maquina": "snack",
        "imagen_url": "https://example.com/rule.png",
        "especificaciones_fisicas": {"alto_mm": 1800},
        "especificaciones_electricas": {},
        "componentes_hardware": {},
    }
    ai = {
        "tipo_maquina": "drink",
        "imagen_url": "https://example.com/ai.png",
        "confidence": 0.77,
        "especificaciones_fisicas": {"alto_mm": 1840},
    }

    merged, warnings = merge_ai_extraction(base, ai)

    assert merged["tipo_maquina"] == "snack"
    assert merged["imagen_url"] == "https://example.com/rule.png"
    assert merged["especificaciones_fisicas"]["alto_mm"] == 1800
    assert "ai_conflict:tipo_maquina" in warnings
    assert "ai_conflict:imagen_url" in warnings
    assert "ai_conflict:especificaciones_fisicas.alto_mm" in warnings
