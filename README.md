# Shop Scraper

A configurable Python scraper for e-commerce category pages. Uses requests+BeautifulSoup when possible and Playwright fallback for dynamic pages and infinite scroll.

## Quick start

1) Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

2) Copy and edit the example config:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml to match your target site selectors
```

3) Run:

```bash
python -m shop_scraper --config config.yaml --output-prefix output/products
```

This will create `output/products.csv` and `output/products.xlsx`.

## Config format

See `config.example.yaml` for a fully annotated example. You must provide:

- `site.category_url`: URL of the category to scrape
- `site.custom_label_0`: Category/label to set for products
- `site.currency`: Currency code or symbol to default when not found in price
- `selectors.product_card`: CSS selector for product cards
- Field selectors for `title`, `url`, `image`, `description`, `price`, `old_price`
- Optional pagination hints: `next_selector`, `show_more_selector`, `pagination_links_selector`, `scroll_container_selector`

## Notes

- The scraper auto-detects if static parsing suffices based on presence of product cards in the initial HTML fetched via requests. If not, it uses Playwright and chooses among show-more clicks, page links, or infinite scroll.
- Missing fields will be blank in the output.
- Logs include the number of pages visited and products extracted.