# Hvar er Hæstaréttardómurinn?

Static lookup app that connects Landsréttur (Iceland’s appeals court) case numbers to the matching Hæstiréttur (Supreme Court) verdicts and administrative decisions. Visitors type a Landsréttur case such as `37/2022` and immediately see every related Supreme Court document, with direct links to the original pages.

The site supports **Deep Linking**: sharing a URL like `.../?case=731/2022` automatically performs a lookup for that case. The URL also updates dynamically as you search.

## Repository Layout
- `index.html`, `app.js` – The entire frontend. A plain HTML form that fetches `mapping.json`, shows loading/error states, and renders the verdict list client-side.
- `mapping.json` – Lookup table keyed by Landsréttur case number. Values are either a single verdict object or an array when multiple Supreme Court results exist.
- `allir_domar_og_akvardanir.csv` – Historical store of scraped verdict metadata, kept mainly so subsequent scrapes only append new rows.
- `get_new_verdicts.py` – Scraper/transformer. Collects all Supreme Court verdicts and decisions, extracts metadata (case numbers, hearing dates, Landsréttur backlinks, decision status) and regenerates the JSON and timestamp.
- `last_updated.txt` – Human-readable timestamp displayed on the site header.
- `requirements.txt` – Python dependencies used by the scraper (and optional tests).
- `scrape_report.json` – Ignored local diagnostic report written by scraper runs and uploaded by GitHub Actions.
- `docs/scraper-maintenance.md` – Detailed scraper/data-contract notes for future maintenance.
- `.github/copilot-instructions.md` – Repo-specific notes for GitHub Copilot agent sessions.

## Developer Notes

Read `docs/scraper-maintenance.md` before changing scraper behavior, generated data artifacts, or the `mapping.json` contract. It documents the current Ísland.is sources, incremental refresh behavior, generated files, and the frontend expectations.

## Refreshing The Data

```bash
python get_new_verdicts.py
```

The script will:
1. Fetch new Supreme Court verdicts from Ísland.is Dómasafn and new decisions from the Hæstiréttur decisions page, following backlinks to Landsréttur where available.
2. Build/update `allir_domar_og_akvardanir.csv`, deduplicating by Supreme Court case number.
3. Write a local `scrape_report.json` with source, parsing, skipped-case, and generated-artifact counts.
4. Regenerate `mapping.json` grouped by Landsréttur case number.
5. Write a localized “Síðast uppfært …” stamp to `last_updated.txt`.

By default, scheduled refreshes are incremental: the scraper walks the newest listing pages and stops once it reaches Supreme Court case numbers already present in the CSV. Existing historical `haestirettur.is` links are preserved; newly appended rows use Ísland.is links.

For diagnostics or a controlled backfill, pass `--full` to ignore the known-case stopping rule. You can combine it with `--max-pages N` to cap each source while testing:

```bash
python get_new_verdicts.py --full --max-pages 3
```

If the script encounters new HTML structures, it may fail before updating generated lookup files. Check `scrape_report.json`, then inspect the regular expressions and parsing around `extract_verdict_date`, `decide_status`, `extract_appeals_link`, and the listing extractors.

## Automation

The repository uses GitHub Actions (`.github/workflows/scrape_and_test.yml`) to run tests and refresh data. The scheduled/manual scrape job runs `python get_new_verdicts.py` after tests pass, uploads `scrape_report.json` as a diagnostic artifact, then commits changes to `allir_domar_og_akvardanir.csv`, `mapping.json`, and `last_updated.txt`.

## Data Sources & Caveats
- Supreme Court verdicts: https://island.is/domar?court=Hæstiréttur
- Supreme Court decisions: https://island.is/s/haestirettur/akvardanir
- Landsréttur backlinks: the scraper only trusts links on the `landsrettur.is` domain.
- Dates are parsed from Icelandic month names. Unexpected formats will leave the date field empty in the JSON.
- The frontend is static; hosting it from any CDN or static host works as long as `mapping.json` and `last_updated.txt` are deployed alongside it.
