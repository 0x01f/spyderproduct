import logging
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin

from .models import Product
from .utils import fetch_html, soup_from_html, bs_select_text, parse_price


logger = logging.getLogger(__name__)


class StaticScraper:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.site = config.get("site", {})
        self.selectors = config.get("selectors", {})
        self.pagination = config.get("pagination", {})
        self.products: List[Product] = []
        self.pages_visited = 0
        self._next_id = 1

    def can_handle(self) -> bool:
        url = self.site["category_url"]
        html = fetch_html(url)
        if not html:
            return False
        soup = soup_from_html(html)
        card_sel = self.selectors.get("product_card")
        if not card_sel:
            return False
        cards = soup.select(card_sel)
        return len(cards) > 0

    def run(self) -> List[Product]:
        url = self.site["category_url"]
        visited_urls = set()
        queue: List[str] = []

        next_selector = self.pagination.get("next_selector")
        page_links_selector = self.pagination.get("pagination_links_selector")
        max_pages = int(self.pagination.get("max_pages", 0))

        def maybe_enqueue(u: Optional[str]):
            if not u:
                return
            abs_u = urljoin(url, u)
            if abs_u not in visited_urls:
                queue.append(abs_u)

        # Seed
        queue.append(url)

        while queue:
            page_url = queue.pop(0)
            if page_url in visited_urls:
                continue
            html = fetch_html(page_url)
            if not html:
                visited_urls.add(page_url)
                continue
            soup = soup_from_html(html)
            self.pages_visited += 1
            visited_urls.add(page_url)

            self._extract_from_soup(soup, base_url=page_url)

            if max_pages and self.pages_visited >= max_pages:
                break

            # Discover next pages
            if next_selector:
                next_el = soup.select_one(next_selector)
                if next_el:
                    maybe_enqueue(next_el.get("href"))
            if page_links_selector:
                for a in soup.select(page_links_selector):
                    maybe_enqueue(a.get("href"))

        logger.info("Static: visited %d pages, collected %d products", self.pages_visited, len(self.products))
        return self.products

    def _extract_from_soup(self, soup, base_url: str):
        card_sel = self.selectors.get("product_card")
        if not card_sel:
            return
        default_currency = self.site.get("currency")
        custom_label = self.site.get("custom_label_0")

        title_sel = self.selectors.get("title", {}).get("selector")
        title_attr = self.selectors.get("title", {}).get("attr", "text")
        url_sel = self.selectors.get("url", {}).get("selector")
        url_attr = self.selectors.get("url", {}).get("attr", "href")
        image_sel = self.selectors.get("image", {}).get("selector")
        image_attr = self.selectors.get("image", {}).get("attr", "src")
        desc_sel = self.selectors.get("description", {}).get("selector")
        desc_attr = self.selectors.get("description", {}).get("attr", "text")
        price_sel = self.selectors.get("price", {}).get("selector")
        price_attr = self.selectors.get("price", {}).get("attr", "text")
        old_price_sel = self.selectors.get("old_price", {}).get("selector")
        old_price_attr = self.selectors.get("old_price", {}).get("attr", "text")

        for card in soup.select(card_sel):
            title = bs_select_text(card, title_sel, title_attr) if title_sel else None
            href = bs_select_text(card, url_sel, url_attr) if url_sel else None
            image = bs_select_text(card, image_sel, image_attr) if image_sel else None
            description = bs_select_text(card, desc_sel, desc_attr) if desc_sel else None
            price_raw = bs_select_text(card, price_sel, price_attr) if price_sel else None
            old_price_raw = bs_select_text(card, old_price_sel, old_price_attr) if old_price_sel else None

            price = parse_price(price_raw)
            old_price = parse_price(old_price_raw)

            product = Product(
                id=self._next_id,
                title=title,
                url=urljoin(base_url, href) if href else None,
                image=urljoin(base_url, image) if image else None,
                description=description,
                price=price,
                old_price=old_price,
                currency=self.site.get("currency"),
                custom_label_0=custom_label,
            )
            self.products.append(product)
            self._next_id += 1