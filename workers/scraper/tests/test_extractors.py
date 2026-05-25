from pathlib import Path

from machine_catalog_scraper.extractors import extract_page
from machine_catalog_scraper.robots import is_allowed_by_robots


FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_jsonld_opengraph_html_specs_and_assets():
    html = (FIXTURES / "product.html").read_text(encoding="utf-8")

    result = extract_page(
        url="https://example.com/products/opera-touch",
        html=html,
        source_config={"manufacturer": "Necta"},
    )

    assert result["model_name"] == "Opera Touch"
    assert result["manufacturer_name"] == "Necta"
    assert result["category_code"] == "snack_drink"
    assert result["specs"]["height_mm"] == 1830
    assert result["images"][0]["source_image_url"] == "https://example.com/images/opera.jpg"
    assert result["documents"][0]["source_url"] == "https://example.com/docs/opera.pdf"
    assert result["confidence_score"] >= 0.85


def test_robots_allow_and_deny_rules():
    robots_txt = (FIXTURES / "robots.txt").read_text(encoding="utf-8")

    assert is_allowed_by_robots(robots_txt, "MachineCatalogBot", "https://example.com/products/opera-touch")
    assert not is_allowed_by_robots(robots_txt, "MachineCatalogBot", "https://example.com/private/opera-touch")
