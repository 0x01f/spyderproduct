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

3) Run single page:

```bash
python -m shop_scraper --config config.yaml --output-prefix output/products
```

4) Crawl catalog (auto-discover subcategories and scrape each product page):

```bash
python -m shop_scraper --config config.yaml --output-prefix output/catalog --crawl
```

This will create CSV/XLSX at the given output prefix.

## Config format

See `config.example.yaml` for a fully annotated example. You must provide:

- `site.category_url`: URL of the category (or catalog root when using `--crawl`)
- `site.custom_label_0`: Default label/category to set for products
- `site.currency`: Currency code or symbol to default when not found in price
- `selectors.*`: Optional; if omitted or null, the scraper will autodetect
- `pagination.*`: Optional hints; leave null to auto-detect strategy
- `discovery.category_links_selector`: Optional CSS for category links on catalog pages
- `discovery.max_category_pages`: Optional limit to number of catalog pages to visit

## Notes

- The scraper auto-detects if static parsing suffices based on presence of product cards in the initial HTML fetched via requests. If not, it uses Playwright and chooses among show-more clicks, page links, or infinite scroll.
- Missing fields will be blank in the output.
- Logs include the number of pages visited and products extracted.