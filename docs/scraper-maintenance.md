# Scraper Maintenance Guide

This guide is for future scraper changes in `hvar-er-haestarettardomurinn`. The repository is intentionally small, but the scraper touches several external pages and generated files, so this is the map.

## Runtime Flow

`get_new_verdicts.py` does the full refresh pipeline:

1. Load existing `allir_domar_og_akvardanir.csv` and build a set of known `supreme_case_number` values.
2. Discover Hæstiréttur verdict detail links from Ísland.is GraphQL `webVerdicts` pagination.
3. Discover Hæstiréttur decision detail links from the HTML decisions listing pages.
4. For each queued detail page, parse Supreme metadata and find the trusted Landsréttur backlink.
5. Fetch the Landsréttur backlink and extract the first reasonable `sequence/year` case number from 2018 or later.
6. Append only linked rows to the CSV and deduplicate by `supreme_case_number`, keeping existing rows.
7. Check the scrape health report for suspicious source/parser breakage before refreshing generated lookup artifacts.
8. Regenerate `mapping.json` from the CSV, update `last_updated.txt`, and write `scrape_report.json` for diagnostics.

The scheduled workflow uses the default incremental mode. A manual local run can use `--full` for backfills and `--max-pages N` for bounded smoke tests.

## Sources

### Verdicts

- Listing page: `https://island.is/domar?court=Hæstiréttur`
- Programmatic endpoint: `https://island.is/api/graphql`
- Query: `GetVerdicts` with `webVerdicts(input: WebVerdictsInput!)`
- Detail path shape: `/domar/s-<uuid>`
- Case number shape: `37/2025`

The server-rendered page only exposes the first page, so pagination should use GraphQL. Keep the rendered HTML fallback for page 1 because it gives a cheap resilience path if GraphQL briefly changes.

### Ákvarðanir

- Listing page: `https://island.is/s/haestirettur/akvardanir`
- Pagination shape: `?page=N`
- Detail path shape: `/s/haestirettur/akvardanir/<uuid>`
- Case number shape: `2026-27`
- Status comes from keywords/body text, usually `Samþykkt` or `Hafnað`.

### Landsréttur

Detail pages usually link to Landsréttur as an “Úrlausn Landsréttar / Héraðsdóms” URL. The scraper only trusts `landsrettur.is` and `www.landsrettur.is` domains, then extracts the first `sequence/year` match with year `>= 2018`.

## Generated Files

### `allir_domar_og_akvardanir.csv`

Persistent scraped store. Required columns:

```text
supreme_case_number,supreme_case_link,appeals_case_number,appeals_case_link,source_type,verdict_date,decision_status
```

Rows without `appeals_case_number` are intentionally not saved because the site is a Landsréttur-to-Hæstiréttur lookup.

Existing historical rows may point to old `www.haestirettur.is` URLs. Do not rewrite them as part of normal refreshes; link migration should be a separate, reviewable data-cleanup task.

### `mapping.json`

Generated from the CSV and loaded directly by `app.js`. The top-level key is `appeals_case_number`.

If one Supreme item maps to an appeals case, the value is one object. If more than one maps to the same appeals case, the value is a list of objects. Preserve this object-or-list contract unless the frontend is updated too.

### `last_updated.txt`

Human-readable Icelandic timestamp shown by the frontend. It is updated after a successful scrape pass.

### `scrape_report.json`

Generated diagnostic report for the most recent scraper run. It includes source URLs, scrape mode, per-source counters, skipped/unlinked cases, guard failures, and generated-artifact counts.

This file is ignored by git and uploaded as a GitHub Actions artifact for scheduled/manual scrapes. It should not be committed unless historical scrape reports become an explicit requirement.

## Frontend Contract

`app.js` expects each mapping record to include:

- `supreme_case_number`
- `supreme_case_link`
- `appeals_case_link`
- `source_type`
- `verdict_date`
- `decision_status`

`source_type` should include `ákvörðun` for decisions so status styling works. `decision_status` may be empty for verdicts.

The frontend normalizes common Landsréttur case-number inputs before lookup, including `Mál nr. 123/2024`, `123 / 2024`, and `123-2024`. Result rendering uses DOM text nodes and validated HTTP(S) links instead of inserting scraped fields as raw HTML.

## Testing Checklist

Run from the repository root:

```bash
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python -m pytest tests/test_scraper.py
```

Run all tests, including generated-data contract checks:

```bash
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python -m pytest tests
```

Useful live smoke test:

```bash
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python get_new_verdicts.py --max-pages 1
```

After a live run, inspect diffs for:

- CSV row additions and duplicate behavior.
- Ísland.is links for newly appended Supreme rows.
- `mapping.json` shape for new and multi-match appeals cases.
- `last_updated.txt` timestamp changes.
- `scrape_report.json` counts and any skipped/unlinked cases.

## Common Failure Points

- Ísland.is detail headings may omit whitespace after `Mál nr.`.
- Landsréttur URLs can contain HTML-escaped `&amp;`; unescape before fetching or storing.
- Decision pages can contain old-looking labels in late pagination pages; rely on parsed detail pages for canonical Supreme case number.
- If GraphQL changes, check the current Next.js page chunk for the `GetVerdicts` query and adjust `VERDICTS_QUERY` or the payload shape.
- Suspicious runs fail before updating `mapping.json` or `last_updated.txt`. Check `scrape_report.json` first when a scheduled scrape fails.
