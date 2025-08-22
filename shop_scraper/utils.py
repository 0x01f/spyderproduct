import logging
import re
import time
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


_PRICE_RE = re.compile(r"([\d\s.,]+)")


def parse_price(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    text = value.strip()
    # Replace non-breaking space
    text = text.replace("\xa0", " ")
    m = _PRICE_RE.search(text)
    if not m:
        return None
    num = m.group(1)
    # Normalize number like "1 234,56" or "1,234.56"
    num = num.replace(" ", "")
    if "," in num and "." in num:
        # Assume comma is thousands sep
        num = num.replace(",", "")
    elif "," in num and "." not in num:
        # Assume comma is decimal sep
        num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def fetch_html(url: str, timeout: int = 20) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        logger.warning("GET %s returned status %s", url, resp.status_code)
        return None
    except Exception as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


def bs_select_text(node, selector: str, attr: Optional[str]) -> Optional[str]:
    if not node:
        return None
    el = node.select_one(selector) if selector else None
    if not el:
        return None
    if attr and attr != "text":
        return el.get(attr)
    return el.get_text(strip=True)


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def sleep_ms(ms: int) -> None:
    time.sleep(max(ms, 0) / 1000.0)