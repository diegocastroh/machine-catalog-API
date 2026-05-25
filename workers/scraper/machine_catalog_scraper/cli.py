import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from .dynamic import crawl_dynamic_single_page
from .spiders.catalog_spider import ConfigurableCatalogSpider


USER_AGENT = "MachineCatalogBot"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m machine_catalog_scraper.cli <config.json>", file=sys.stderr)
        return 2

    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output_path = Path(config["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("", encoding="utf-8")

    if config.get("dynamic_rendering"):
        crawl_dynamic_single_page(config, output_path)
        return 0

    settings = get_project_settings()
    settings.set("ROBOTSTXT_OBEY", True)
    settings.set("DOWNLOAD_DELAY", max(1, float(config.get("delay_seconds", 2))))
    settings.set("CONCURRENT_REQUESTS_PER_DOMAIN", 2)
    settings.set("AUTOTHROTTLE_ENABLED", True)
    settings.set("FEEDS", {str(output_path): {"format": "jsonlines", "encoding": "utf8", "overwrite": True}})
    settings.set("USER_AGENT", USER_AGENT)
    process = CrawlerProcess(settings)
    process.crawl(ConfigurableCatalogSpider, config=config)
    process.start()
    return 0


def _allowed_domain(url: str, domains: list[str]) -> bool:
    return urlparse(url).hostname in domains


if __name__ == "__main__":
    raise SystemExit(main())
