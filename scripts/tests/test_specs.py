import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from crawling.specs import extract_specs_from_text


def test_extracts_azkoyen_high_width_depth_and_weight():
    specs = extract_specs_from_text(
        """
        Specifications
        Dimensions and weight
        High 865 mm
        Width 480 mm
        Depth 610 mm
        Weight 63 kg
        """
    )

    assert specs["especificaciones_fisicas"]["alto_mm"] == 865
    assert specs["especificaciones_fisicas"]["ancho_mm"] == 480
    assert specs["especificaciones_fisicas"]["profundidad_mm"] == 610
    assert specs["especificaciones_fisicas"]["peso_kg"] == 63
