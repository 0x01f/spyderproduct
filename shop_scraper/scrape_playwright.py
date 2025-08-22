import logging
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .models import Product
from .utils import parse_price
from .autodetect import detect_selectors_from_html


logger = logging.getLogger(__name__)


def _get_text_or_attr(locator, attr: Optional[str]) -> Optional[str]:
    try:
        if attr and attr != "text":
            # support fallbacks like "src|data-src|data-original"
            for a in attr.split("|"):
                val = locator.get_attribute(a)
                if val:
                    return val
            return None
        else:
            return locator.inner_text().strip()
    except Exception:
        return None


def _safe_locator_count(page, selector: Optional[str]) -> int:
    if not selector:
        return 0
    try:
        return page.locator(selector).count()
    except Exception:
        return 0


class PlaywrightScraper:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.site = config.get("site", {})
        self.selectors = config.get("selectors", {})
        self.pagination = config.get("pagination", {})
        self.playwright_cfg = config.get("playwright", {})
        self.products: List[Product] = []
        self.pages_visited = 0
        self._next_id = 1

    def run(self) -> List[Product]:
        category_url = self.site["category_url"]
        headless = bool(self.playwright_cfg.get("headless", True))
        timeout = int(self.playwright_cfg.get("timeout_ms", 30000))

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(timeout)

            try:
                page.goto(category_url)
                try:
                    page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
            except PlaywrightTimeoutError:
                logger.warning("Timeout navigating to %s", category_url)
            except Exception as e:
                logger.warning("Navigation error for %s: %s", category_url, e)

            # Autodetect selectors if missing
            if not self.selectors.get("product_card"):
                try:
                    html = page.content()
                    detected = detect_selectors_from_html(html)
                    if detected:
                        merged = {**detected, **{k: v for k, v in self.selectors.items() if v}}
                        self.selectors = merged
                        self.config["selectors"] = self.selectors
                        logger.info("Using autodetected selectors for Playwright scraping")
                except Exception:
                    pass

            # Decide pagination strategy
            show_more_selector = self.pagination.get("show_more_selector")
            next_selector = self.pagination.get("next_selector")
            pagination_links_selector = self.pagination.get("pagination_links_selector")
            scroll_container = self.pagination.get("scroll_container_selector")
            scroll_wait_ms = int(self.pagination.get("scroll_wait_ms", 600))
            max_pages = int(self.pagination.get("max_pages", 0))

            used_strategy = None
            if _safe_locator_count(page, show_more_selector) > 0:
                used_strategy = "show_more"
                self._run_show_more(page, show_more_selector, scroll_wait_ms)
                # Extract after all items are loaded on the same page
                self._extract_from_page(page, base_url=category_url)
                self.pages_visited = 1
            elif _safe_locator_count(page, pagination_links_selector) > 0:
                used_strategy = "pagination_links"
                self._run_pagination_links(page, pagination_links_selector, max_pages)
            elif _safe_locator_count(page, next_selector) > 0:
                used_strategy = "next_button"
                self._run_next_button(page, next_selector, max_pages)
            else:
                used_strategy = "infinite_scroll"
                self._run_infinite_scroll(page, scroll_container, scroll_wait_ms)
                self._extract_from_page(page, base_url=category_url)
                self.pages_visited = 1

            logger.info("Playwright strategy: %s", used_strategy)

            context.close()
            browser.close()

        logger.info("Playwright: visited %d pages, collected %d products", self.pages_visited, len(self.products))
        return self.products

    def _run_show_more(self, page, show_more_selector: str, wait_ms: int):
        while True:
            try:
                button = page.locator(show_more_selector).first
                if button.count() == 0:
                    break
                if not button.is_visible():
                    break
                before = _safe_locator_count(page, self.selectors.get("product_card"))
                button.click()
                page.wait_for_timeout(wait_ms)
                after = _safe_locator_count(page, self.selectors.get("product_card"))
                if after <= before:
                    break
            except Exception:
                break

    def _run_pagination_links(self, page, pagination_links_selector: str, max_pages: int):
        hrefs = []
        try:
            for el in page.locator(pagination_links_selector).all():
                try:
                    href = el.get_attribute("href")
                except Exception:
                    href = None
                if href:
                    hrefs.append(href)
        except Exception:
            hrefs = []
        seen = set()
        pages_count = 0
        for href in hrefs:
            if max_pages and pages_count >= max_pages:
                break
            abs_href = urljoin(page.url, href)
            if abs_href in seen:
                continue
            seen.add(abs_href)
            try:
                page.goto(abs_href)
                try:
                    page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
                self._extract_from_page(page, base_url=abs_href)
                pages_count += 1
            except Exception:
                continue
        self.pages_visited = pages_count

    def _run_next_button(self, page, next_selector: str, max_pages: int):
        pages_count = 1  # count the first page as visited once we extract it
        # Extract from the initial page first
        self._extract_from_page(page, base_url=page.url)
        while True:
            if max_pages and pages_count >= max_pages:
                break
            try:
                next_btn = page.locator(next_selector).first
                if next_btn.count() == 0 or not next_btn.is_visible():
                    break
                next_btn.click()
                try:
                    page.wait_for_load_state("networkidle")
                except Exception:
                    pass
                self._extract_from_page(page, base_url=page.url)
                pages_count += 1
            except Exception:
                break
        self.pages_visited = pages_count

    def _run_infinite_scroll(self, page, scroll_container_selector: Optional[str], wait_ms: int):
        last_count = 0
        stagnation_rounds = 0
        while True:
            try:
                current_count = _safe_locator_count(page, self.selectors.get("product_card"))
                if current_count > last_count:
                    last_count = current_count
                    stagnation_rounds = 0
                else:
                    stagnation_rounds += 1
                if stagnation_rounds >= 3:
                    break
                if scroll_container_selector:
                    try:
                        page.evaluate(
                            "(sel) => { const el = document.querySelector(sel); if (el) el.scrollTo(0, el.scrollHeight); }",
                            scroll_container_selector,
                        )
                    except Exception:
                        break
                else:
                    try:
                        page.evaluate("() => { window.scrollTo(0, document.body.scrollHeight); }")
                    except Exception:
                        break
                page.wait_for_timeout(wait_ms)
            except Exception:
                break

    def _extract_from_page(self, page, base_url: str):
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

        try:
            cards = page.locator(card_sel).all()
        except Exception:
            cards = []
        for card in cards:
            title = _get_text_or_attr(card.locator(title_sel).first, title_attr) if title_sel else None
            href = _get_text_or_attr(card.locator(url_sel).first, url_attr) if url_sel else None
            image = _get_text_or_attr(card.locator(image_sel).first, image_attr) if image_sel else None
            description = _get_text_or_attr(card.locator(desc_sel).first, desc_attr) if desc_sel else None
            price_raw = _get_text_or_attr(card.locator(price_sel).first, price_attr) if price_sel else None
            old_price_raw = _get_text_or_attr(card.locator(old_price_sel).first, old_price_attr) if old_price_sel else None

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
                currency=default_currency,
                custom_label_0=custom_label,
            )
            self.products.append(product)
            self._next_id += 1