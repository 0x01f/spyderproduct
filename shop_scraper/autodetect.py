import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"(?i)(?:^|\b)(?:[$€£₽₴₸]|руб|грн|byn|uah|kzt|eur|usd)?\s*[\d\s.,]{2,}(?:\s*(?:[$€£₽₴₸]|руб|грн|byn|uah|kzt|eur|usd))?")


def _looks_like_price(text: str) -> bool:
    if not text:
        return False
    t = text.strip().replace("\xa0", " ")
    if len(t) > 64:
        return False
    return bool(_PRICE_RE.search(t))


def _css_for_tag(el: Tag) -> str:
    name = el.name or "div"
    classes = el.get("class") or []
    # Limit to 3 classes for conciseness
    cls = ".".join([c for c in classes if c][:3])
    return f"{name}{('.' + cls) if cls else ''}"


def _most_common(seq: List[str]) -> Optional[str]:
    if not seq:
        return None
    counts: Dict[str, int] = {}
    for s in seq:
        counts[s] = counts.get(s, 0) + 1
    best = max(counts.items(), key=lambda x: x[1])[0]
    return best


def _ancestor_candidates_with_media_and_link(el: Tag) -> List[Tag]:
    out: List[Tag] = []
    cur = el
    depth = 0
    while cur and isinstance(cur, Tag) and depth < 7:
        try:
            if cur.find("img") and cur.find("a"):
                out.append(cur)
        except Exception:
            pass
        cur = cur.parent if hasattr(cur, "parent") else None
        depth += 1
    return out


def _find_product_card_selector(soup: BeautifulSoup) -> Optional[str]:
    price_nodes = []
    for el in soup.find_all(text=True):
        try:
            if _looks_like_price(str(el)) and isinstance(el.parent, Tag):
                price_nodes.append(el.parent)
        except Exception:
            continue
    if not price_nodes:
        # fallback: any element with class containing 'price'
        price_nodes = [e for e in soup.select("[class*='price']")]
    selectors: List[str] = []
    for pn in price_nodes:
        for anc in _ancestor_candidates_with_media_and_link(pn):
            css = _css_for_tag(anc)
            # ensure it repeats on page
            try:
                if len(soup.select(css)) >= 3:
                    selectors.append(css)
            except Exception:
                continue
    sel = _most_common(selectors)
    return sel


def _relative_selector_for_title(card: Tag) -> Optional[str]:
    # Prefer heading or anchor with title-like class
    candidates = []
    for sel in ["h1", "h2", "h3", "h4", "a", "div", "span"]:
        for el in card.select(sel):
            text = el.get_text(strip=True)
            if 3 <= len(text) <= 200:
                cl = " ".join(el.get("class") or [])
                score = 0
                if sel in ("h1", "h2", "h3", "h4"): score += 2
                if "title" in cl or "name" in cl: score += 3
                if el.name == "a": score += 1
                if score > 0 and text and not _looks_like_price(text):
                    candidates.append((score, el))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    el = candidates[0][1]
    return _css_for_tag(el)


def _relative_selector_for_price(card: Tag, old: bool = False) -> Optional[str]:
    candidates = []
    for el in card.find_all(True):
        try:
            text = el.get_text(strip=True)
        except Exception:
            continue
        if _looks_like_price(text):
            cl = " ".join(el.get("class") or [])
            score = 1
            if "price" in cl: score += 2
            if old and any(k in cl for k in ["old", "was", "strike", "through"]):
                score += 3
            if not old and any(k in cl for k in ["new", "current", "final", "now"]):
                score += 2
            candidates.append((score, el))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return _css_for_tag(candidates[0][1])


def _relative_selector_for_image(card: Tag) -> Tuple[Optional[str], Optional[str]]:
    img = card.find("img")
    if not img:
        return None, None
    sel = _css_for_tag(img)
    # Provide attr fallbacks
    return sel, "src|data-src|data-original|data-lazy|data-image"


def _relative_selector_for_url(card: Tag, title_sel: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    # Prefer link that wraps the title element
    if title_sel:
        try:
            title_el = card.select_one(title_sel)
            if title_el:
                parent_link = title_el.find_parent("a")
                if parent_link and parent_link.get("href"):
                    return _css_for_tag(parent_link), "href"
                link_inside = title_el.find("a")
                if link_inside and link_inside.get("href"):
                    return _css_for_tag(link_inside), "href"
        except Exception:
            pass
    # Fallback to first anchor
    a = card.find("a", href=True)
    if a:
        return _css_for_tag(a), "href"
    return None, None


def _relative_selector_for_description(card: Tag) -> Optional[str]:
    for el in card.find_all(True):
        cl = " ".join(el.get("class") or [])
        if any(k in cl for k in ["desc", "description", "short", "summary"]):
            txt = el.get_text(strip=True)
            if txt and len(txt) >= 10:
                return _css_for_tag(el)
    return None


def detect_selectors_from_soup(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    product_card = _find_product_card_selector(soup)
    if not product_card:
        return None
    # Take first card element to derive fields
    card = soup.select_one(product_card)
    if not card:
        return None
    title_sel = _relative_selector_for_title(card)
    price_sel = _relative_selector_for_price(card, old=False)
    old_price_sel = _relative_selector_for_price(card, old=True)
    image_sel, image_attr = _relative_selector_for_image(card)
    url_sel, url_attr = _relative_selector_for_url(card, title_sel)
    desc_sel = _relative_selector_for_description(card)

    selectors: Dict[str, Any] = {
        "product_card": product_card,
        "title": {"selector": title_sel, "attr": "text"} if title_sel else {"selector": None, "attr": "text"},
        "url": {"selector": url_sel, "attr": url_attr or "href"} if url_sel else {"selector": None, "attr": "href"},
        "image": {"selector": image_sel, "attr": image_attr or "src"} if image_sel else {"selector": None, "attr": "src"},
        "description": {"selector": desc_sel, "attr": "text"} if desc_sel else {"selector": None, "attr": "text"},
        "price": {"selector": price_sel, "attr": "text"} if price_sel else {"selector": None, "attr": "text"},
        "old_price": {"selector": old_price_sel, "attr": "text"} if old_price_sel else {"selector": None, "attr": "text"},
    }
    logger.info("Autodetected selectors: %s", selectors)
    return selectors


def detect_selectors_from_html(html: str) -> Optional[Dict[str, Any]]:
    try:
        soup = BeautifulSoup(html, "lxml")
        return detect_selectors_from_soup(soup)
    except Exception as e:
        logger.debug("Autodetect failed: %s", e)
        return None