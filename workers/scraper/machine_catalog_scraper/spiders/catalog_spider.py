from urllib.parse import urlparse

import scrapy

from machine_catalog_scraper.extractors import extract_page


class ConfigurableCatalogSpider(scrapy.Spider):
    name = "catalog_configurable"

    def __init__(self, config: dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.start_urls = [config["base_url"]]
        self.allowed_domains = config["allowed_domains"]
        self.max_pages = int(config.get("max_pages_per_run", 50))
        self.pages_seen = 0

    def parse(self, response):
        if self.pages_seen >= self.max_pages:
            return
        self.pages_seen += 1
        normalized = extract_page(response.url, response.text, self.config)
        yield {
            "url": response.url,
            "manufacturer_id": self.config.get("manufacturer_id"),
            "source_type": "product_page",
            "crawl_allowed": True,
            "raw": {
                "raw_html": response.text,
                "raw_text": " ".join(response.css("body *::text").getall())[:20000],
                "raw_json": {"status_code": response.status},
                "detected_images": normalized.get("images", []),
                "detected_links": normalized.get("documents", []),
            },
            "normalized": normalized,
        }

        for href in response.css("a::attr(href)").getall():
            next_url = response.urljoin(href)
            if self._should_follow(next_url):
                yield response.follow(next_url, callback=self.parse)

    def _should_follow(self, url: str) -> bool:
        if self.pages_seen >= self.max_pages:
            return False
        parsed = urlparse(url)
        if parsed.hostname not in self.allowed_domains:
            return False
        if any(pattern in url for pattern in self.config.get("exclude_patterns", [])):
            return False
        return any(pattern in url for pattern in self.config.get("product_url_patterns", []))
