import argparse
import json
import logging
from typing import Dict, Any, List

import yaml

from .exporter import export_records
from .logging_config import setup_logging
from .models import Product
from .scrape_static import StaticScraper
from .scrape_playwright import PlaywrightScraper
from .utils import fetch_html, soup_from_html
from .autodetect import detect_selectors_from_soup


logger = logging.getLogger(__name__)


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def decide_static_possible(config: Dict[str, Any]) -> bool:
    url = config.get("site", {}).get("category_url")
    selectors = config.get("selectors", {})
    card_sel = selectors.get("product_card")
    if not url:
        return False
    html = fetch_html(url)
    if not html:
        return False
    soup = soup_from_html(html)
    if not card_sel:
        detected = detect_selectors_from_soup(soup)
        if detected and detected.get("product_card"):
            # Stash detected selectors into config so static scraper can use them
            merged = {**detected, **{k: v for k, v in selectors.items() if v}}
            config["selectors"] = merged
            card_sel = merged.get("product_card")
    if not card_sel:
        return False
    cards = soup.select(card_sel)
    return len(cards) > 0


def run(config: Dict[str, Any], output_prefix: str) -> None:
    # Choose strategy
    if decide_static_possible(config):
        logger.info("Using static scraping (requests + BeautifulSoup)")
        scraper = StaticScraper(config)
        products = scraper.run()
        pages_visited = scraper.pages_visited
    else:
        logger.info("Using dynamic scraping (Playwright)")
        scraper = PlaywrightScraper(config)
        products = scraper.run()
        pages_visited = scraper.pages_visited

    # Export
    records = [p.to_record() for p in products]
    export_records(records, output_prefix)

    # Logging summary
    logger.info("Exported %d products from %d pages to %s.(csv|xlsx)", len(products), pages_visited, output_prefix)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configurable e-commerce category scraper")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--output-prefix", required=True, help="Output file prefix (without extension)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    config = load_config(args.config)

    run(config=config, output_prefix=args.output_prefix)


if __name__ == "__main__":
    main()