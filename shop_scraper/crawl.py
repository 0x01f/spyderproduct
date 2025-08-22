import logging
from typing import Dict, Any, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .utils import fetch_html, soup_from_html
from .autodetect import detect_selectors_from_soup
from .scrape_static import StaticScraper
from .scrape_playwright import PlaywrightScraper
from .models import Product


logger = logging.getLogger(__name__)


def _same_host(url: str, base: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(base).netloc
    except Exception:
        return True


def _is_catalog_path(url: str) -> bool:
    try:
        return "/catalog/" in urlparse(url).path
    except Exception:
        return True


def _discover_category_links(soup: BeautifulSoup, base_url: str, selector_hint: Optional[str]) -> List[str]:
    links: List[str] = []
    if selector_hint:
        try:
            for a in soup.select(selector_hint):
                href = a.get("href")
                if href:
                    links.append(urljoin(base_url, href))
        except Exception:
            pass
    # Heuristic fallback: anchors inside blocks with classes that look like catalog/section/category
    try:
        candidates = soup.select("[class*='catalog'], [class*='section'], [class*='category'] a[href]")
        for a in candidates:
            href = a.get("href")
            if href:
                links.append(urljoin(base_url, href))
    except Exception:
        pass
    # Filter
    out: List[str] = []
    seen: Set[str] = set()
    for u in links:
        if not _same_host(u, base_url):
            continue
        if not _is_catalog_path(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _derive_label(soup: BeautifulSoup, page_url: str, default_label: Optional[str]) -> Optional[str]:
    try:
        h1 = soup.select_one("h1")
        if h1:
            text = h1.get_text(strip=True)
            if text:
                return text
    except Exception:
        pass
    # Fallback to last URL segment
    try:
        path = urlparse(page_url).path.rstrip("/")
        seg = path.split("/")[-1]
        if seg:
            return seg
    except Exception:
        pass
    return default_label


class CategoryCrawler:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.site = config.get("site", {})
        self.discovery = config.get("discovery", {})
        self.max_category_pages = int(self.discovery.get("max_category_pages", 0))
        self.category_links_selector = self.discovery.get("category_links_selector")
        self.products: List[Product] = []
        self.category_pages_visited = 0
        self.product_pages_visited = 0

    def run(self) -> List[Product]:
        start_url = self.site["category_url"]
        default_label = self.site.get("custom_label_0")

        queue: List[str] = [start_url]
        visited: Set[str] = set()

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            html = fetch_html(url)
            if not html:
                visited.add(url)
                continue
            soup = soup_from_html(html)
            visited.add(url)

            # Try to detect if this is a product listing page
            detected = detect_selectors_from_soup(soup)
            card_sel = detected.get("product_card") if detected else None
            has_cards = False
            try:
                has_cards = bool(card_sel and soup.select(card_sel))
            except Exception:
                has_cards = False

            if has_cards:
                # Prepare a page-specific config
                page_config = {
                    **self.config,
                    "site": {
                        **self.site,
                        "category_url": url,
                        "custom_label_0": _derive_label(soup, url, default_label),
                    },
                    "selectors": {**(detected or {}), **self.config.get("selectors", {})},
                }
                logger.info("Scraping product page: %s", url)
                products = self._scrape_page(page_config)
                self.products.extend(products)
                self.product_pages_visited += 1
                continue

            # Otherwise, treat as category index and enqueue child links
            self.category_pages_visited += 1
            children = _discover_category_links(soup, url, self.category_links_selector)
            for child in children:
                if child not in visited and child not in queue:
                    queue.append(child)
            if self.max_category_pages and self.category_pages_visited >= self.max_category_pages:
                break

        # Reassign sequential IDs
        for i, p in enumerate(self.products, start=1):
            p.id = i
        logger.info(
            "Crawler: visited %d category pages, %d product pages, collected %d products",
            self.category_pages_visited,
            self.product_pages_visited,
            len(self.products),
        )
        return self.products

    def _scrape_page(self, page_config: Dict[str, Any]) -> List[Product]:
        # Try static first
        try:
            static_scraper = StaticScraper(page_config)
            if static_scraper.can_handle():
                return static_scraper.run()
        except Exception:
            pass
        # Fallback to Playwright
        try:
            playwright_scraper = PlaywrightScraper(page_config)
            return playwright_scraper.run()
        except Exception:
            return []