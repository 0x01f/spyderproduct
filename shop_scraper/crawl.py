import logging
from typing import Dict, Any, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .utils import fetch_html, soup_from_html
from .autodetect import detect_selectors_from_soup, looks_like_price_text
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


def _extract_links_from_cards(soup: BeautifulSoup, card_selector: str, url_selector: Optional[str]) -> List[str]:
    links: List[str] = []
    try:
        cards = soup.select(card_selector)
    except Exception:
        cards = []
    for card in cards:
        href = None
        if url_selector:
            a = card.select_one(url_selector)
            if a:
                href = a.get("href")
        if not href:
            a = card.find("a", href=True)
            if a:
                href = a.get("href")
        if href:
            links.append(href)
    return links


def _selector_indicates_tiles(card_selector: str) -> bool:
    sel = card_selector or ""
    return ("section-list" in sel) or ("section_list" in sel) or ("list-item" in sel)


def _selector_indicates_listing(card_selector: str) -> bool:
    sel = card_selector or ""
    return ("section-item" in sel) or ("catalog-section-item" in sel) or ("product" in sel)


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
    detected = detect_selectors_from_soup(soup)
    if detected and detected.get("product_card"):
        card_sel = detected["product_card"]
        # Treat as tiles when selector name suggests list tiles OR no prices in cards
        treat_as_tiles = False
        if _selector_indicates_tiles(card_sel) and not _selector_indicates_listing(card_sel):
            treat_as_tiles = True
        else:
            try:
                cards = soup.select(card_sel)
            except Exception:
                cards = []
            prices_in_cards = 0
            for card in cards:
                try:
                    text = card.get_text(" ", strip=True)
                    if looks_like_price_text(text):
                        prices_in_cards += 1
                except Exception:
                    continue
            if prices_in_cards == 0:
                treat_as_tiles = True
        if treat_as_tiles:
            inner_links = _extract_links_from_cards(soup, card_sel, (detected.get("url") or {}).get("selector"))
            for href in inner_links:
                links.append(urljoin(base_url, href))
    # Fallback: anchors inside catalog-like blocks
    try:
        candidates = soup.select("[class*='catalog'], [class*='section'], [class*='category'] a[href]")
        for a in candidates:
            href = a.get("href")
            if href:
                links.append(urljoin(base_url, href))
    except Exception:
        pass
    # Filter and dedupe
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

            detected = detect_selectors_from_soup(soup)
            card_sel = detected.get("product_card") if detected else None

            is_listing = False
            if card_sel:
                if _selector_indicates_listing(card_sel) and not _selector_indicates_tiles(card_sel):
                    is_listing = True
                else:
                    try:
                        cards = soup.select(card_sel)
                    except Exception:
                        cards = []
                    prices_in_cards = 0
                    for card in cards:
                        try:
                            text = card.get_text(" ", strip=True)
                            if looks_like_price_text(text):
                                prices_in_cards += 1
                        except Exception:
                            continue
                    if prices_in_cards >= 2 or (cards and prices_in_cards / max(len(cards), 1) >= 0.25):
                        is_listing = True

            if is_listing and card_sel:
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
            else:
                self.category_pages_visited += 1
                children = _discover_category_links(soup, url, self.category_links_selector)
                for child in children:
                    if child not in visited and child not in queue:
                        queue.append(child)
                if self.max_category_pages and self.category_pages_visited >= self.max_category_pages:
                    break

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
        try:
            static_scraper = StaticScraper(page_config)
            if static_scraper.can_handle():
                return static_scraper.run()
        except Exception:
            pass
        try:
            playwright_scraper = PlaywrightScraper(page_config)
            return playwright_scraper.run()
        except Exception:
            return []