import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from crawling.ai_extractor import merge_ai_extraction, parse_ai_json
from crawling import ai_extractor


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


def test_extract_with_ollama_sends_num_ctx_option(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": """
                    {
                      "tipo_maquina": "coffee",
                      "imagen_url": null,
                      "especificaciones_fisicas": {},
                      "especificaciones_electricas": {},
                      "componentes_hardware": {},
                      "confidence": 0.8,
                      "uncertain_fields": []
                    }
                    """
                }
            }

    def fake_post(endpoint, json, timeout):
        captured["endpoint"] = endpoint
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ai_extractor.requests, "post", fake_post)

    result = ai_extractor.extract_with_ollama(
        base_url="http://localhost:11434",
        model="llama3.1:8b",
        fabricante="Azkoyen",
        modelo="Vitro X5 Touch",
        url="https://example.com",
        page_text="High 865 mm",
        current={},
        timeout=30,
        num_ctx=4096,
    )

    assert result["tipo_maquina"] == "coffee"
    assert captured["json"]["options"]["temperature"] == 0
    assert captured["json"]["options"]["num_ctx"] == 4096
