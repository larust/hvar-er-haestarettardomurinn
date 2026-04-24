# Hvar er Hæstaréttardómurinn — Agent Notes

## Project Purpose

Static lookup site that maps Landsréttur case numbers to related Hæstiréttur verdicts and ákvarðanir. The frontend is plain HTML/CSS/JavaScript and reads generated `mapping.json` plus `last_updated.txt`.

## Primary Files

- `get_new_verdicts.py` — scraper, parser, CSV merge, `mapping.json` generation, timestamp update.
- `allir_domar_og_akvardanir.csv` — persistent source-of-truth store for scraped links and metadata.
- `mapping.json` — generated lookup table keyed by Landsréttur case number; keep its shape stable for `app.js`.
- `app.js`, `index.html`, `style.css` — static frontend; no build step.
- `tests/test_scraper.py` — parser and scraper unit tests.
- `tests/test_data_contract.py` — generated CSV and `mapping.json` contract tests.
- `.github/workflows/scrape_and_test.yml` — scheduled/manual data refresh automation.

## Data Sources

- Hæstiréttur verdicts: `https://island.is/domar?court=Hæstiréttur`, discovered through Ísland.is GraphQL endpoint `/api/graphql` with `webVerdicts` pagination.
- Hæstiréttur decisions: `https://island.is/s/haestirettur/akvardanir`, discovered from HTML pages with `?page=N` pagination.
- Landsréttur backlinks: only trust `landsrettur.is` / `www.landsrettur.is` URLs.

## Data Contract

CSV columns must remain:

`supreme_case_number`, `supreme_case_link`, `appeals_case_number`, `appeals_case_link`, `source_type`, `verdict_date`, `decision_status`

`mapping.json` groups by `appeals_case_number`. Each value is either one object or a list of objects. Do not change this shape unless `app.js` is updated at the same time.

Existing historical rows may still point to `www.haestirettur.is`; preserve them unless explicitly asked to run a link migration. New rows should use Ísland.is URLs.

## Scraper Behavior

- Default run is incremental: stop once listing pages reach already-known `supreme_case_number` values.
- `--full` disables incremental stopping for diagnostics/backfills.
- `--max-pages N` caps each source and is useful for smoke tests.
- `last_updated.txt` is a generated artifact and is updated by successful scraper runs.
- `scrape_report.json` is an ignored diagnostic artifact written by scraper runs and uploaded by GitHub Actions.

## Common Commands

Run from the repository root:

```bash
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python -m pytest tests/test_scraper.py
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python -m pytest tests
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python get_new_verdicts.py --max-pages 1
/Users/larust/Documents/hvar-er-haestarettardomurinn/.venv/bin/python get_new_verdicts.py --full --max-pages 3
```

Use the repo venv if available. In GitHub Actions, the workflow installs `requirements.txt` and runs the same test file.

## Editing Guidance

- Keep the frontend dependency-free unless the user asks for a larger redesign.
- Treat `allir_domar_og_akvardanir.csv`, `mapping.json`, and `last_updated.txt` as generated but review their diffs after live scraper runs.
- Check `scrape_report.json` first when a live scraper run fails suspicious-source guards.
- Prefer mocked parser/listing tests over network-dependent tests.
- Be careful with Icelandic text and case-number formats: verdicts use `sequence/year`, decisions use `year-sequence`.
