# Hvar er Hæstaréttardómurinn?

Static lookup app that connects Landsréttur (Iceland’s appeals court) case numbers to the matching Hæstiréttur (Supreme Court) verdicts and administrative decisions. Visitors type a Landsréttur case such as `37/2022` and immediately see every related Supreme Court document, with direct links to the original pages.

## Repository Layout
- `index.html`, `app.js` – The entire frontend. A plain HTML form that fetches `mapping.json`, shows loading/error states, and renders the verdict list client-side.
- `mapping.json` – Lookup table keyed by Landsréttur case number. Values are either a single verdict object or an array when multiple Supreme Court results exist.
- `allir_domar_og_akvardanir.csv` – Historical store of scraped verdict metadata, kept mainly so subsequent scrapes only append new rows.
- `get_new_verdicts.py` – Scraper/transformer. Collects all Supreme Court verdicts and decisions, extracts metadata (case numbers, hearing dates, Landsréttur backlinks, decision status) and regenerates the JSON and timestamp.
- `last_updated.txt` – Human-readable timestamp displayed on the site header.
- `cron_job.sh` – Convenience script for running the scraper on Render’s Cron Jobs and pushing updates back to GitHub.
- `requirements.txt` – Python dependencies used by the scraper (and optional tests).

## Refreshing The Data

```bash
python get_new_verdicts.py
```

The script will:
1. Fetch every Supreme Court verdict (`/domar/`) and decision (`/akvardanir/`), following backlinks to Landsréttur where available.
2. Build/update `allir_domar_og_akvardanir.csv`, deduplicating by Supreme Court case number.
3. Regenerate `mapping.json` grouped by Landsréttur case number.
4. Write a localized “Síðast uppfært …” stamp to `last_updated.txt`.

If the script encounters new HTML structures, check the regular expressions and keyword parsing around `extract_verdict_date`, `decide_status`, and `first_appeals_link`.

## Automation

`cron_job.sh` is tailored for Render’s Cron Jobs:

1. Clones the repository using a personal-access token supplied through `GITHUB_TOKEN`.
2. Runs `python3 get_new_verdicts.py` to refresh the artifacts.
3. Commits and pushes changes to `${BRANCH:-main}` (override with the `BRANCH` environment variable).

Required environment variables:
- `REPO_SLUG` – e.g. `username/hvar-er-haestarettardomurinn`
- `GITHUB_TOKEN` – Token with `repo` scope so pushes succeed
- Optional `BRANCH` if you publish from something other than `main`

## Data Sources & Caveats
- Supreme Court data: https://www.haestirettur.is/domar/ and https://www.haestirettur.is/akvardanir/
- Landsréttur backlinks: the scraper only trusts links on the `landsrettur.is` domain.
- Dates are parsed from Icelandic month names. Unexpected formats will leave the date field empty in the JSON.
- The frontend is static; hosting it from any CDN or static host works as long as `mapping.json` and `last_updated.txt` are deployed alongside it.
