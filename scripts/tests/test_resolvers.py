import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from crawling.resolvers import resolve_product_url


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def test_resolves_family_page_to_nested_model_url(monkeypatch):
    html = """
    <html><body>
      <a href="https://azkoyenvending.com/vitro/#vitro-s1-instant">Vitro S1 Instant</a>
      <a href="https://azkoyenvending.com/vitro/vitro-s1-instant/">See details</a>
      <a href="https://azkoyenvending.com/vitro/#vitro-x5">Vitro X5</a>
      <a href="https://azkoyenvending.com/vitro/vitro-x5/">See details</a>
    </body></html>
    """

    def fake_get(url, timeout, headers):
        assert url == "https://azkoyenvending.com/vitro/"
        return FakeResponse(html)

    monkeypatch.setattr("crawling.resolvers.requests.get", fake_get)

    resolved = resolve_product_url(
        "https://azkoyenvending.com/vitro/",
        "Azkoyen",
        "Vitro X5 Touch",
    )

    assert resolved == "https://azkoyenvending.com/vitro/vitro-x5/"
