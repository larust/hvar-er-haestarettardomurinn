import os
import re
import requests
import json
import pandas as pd
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

HEADERS = {"User-Agent": ( "Mozilla/5.0 (X11; Linux x86_64) ")}

# New Supreme Court case-number pattern, e.g. "2025-106"
SUPREME_RE = re.compile(r"\b(\d{4}-\d+)\b")

# Appeals-court link & number patterns (unchanged)
APPEALS_URL_RE = re.compile(
    r"https://landsrettur\.is/domar-og-urskurdir/domur-urskurdur/[^\s\"'<>]+"
)
APPEALS_NO_RE  = re.compile(r"\b(\d+)/(20\d{2})\b")

def appeals_case_number(url: str) -> str:
    print(f"  → fetching appeals page {url}")
    try:
        page = requests.get(url, headers=HEADERS, timeout=30).text
    except Exception:
        print(f"    ! failed to fetch appeals page")
        return ""
    for num, year in APPEALS_NO_RE.findall(page):
        if int(year) >= 2018:
            return f"{num}/{year}"
    return ""


def first_appeals_link(html: str) -> str:
    m = APPEALS_URL_RE.search(html)
    return m.group(0) if m else ""


def scrape_supreme(url: str) -> tuple[str, str, str, str]:
    html = requests.get(url, headers=HEADERS, timeout=30).text

    # Supreme-Court case number
    sup_no = ""
    for match in SUPREME_RE.findall(html):
        sup_no = match
        break

    # Find appeals link if any
    app_link = first_appeals_link(html) or ""
    app_no = ""
    if app_link:
        parsed = urlparse(app_link)
        dom = parsed.netloc.lower()
        if dom == "landsrettur.is" or dom.endswith(".landsrettur.is"):
            app_no = appeals_case_number(app_link)
        else:
            # wrong domain → drop
            app_link = ""
    return sup_no, url, app_no, app_link


def get_verdict_links() -> list[str]:
    base = "https://www.haestirettur.is"
    list_page = f"{base}/domar/"
    resp = requests.get(list_page, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # only the detail pages
        if href.startswith("/domar/_domur/"):
            links.add(urljoin(base, href))
    return sorted(links)


def get_decision_links() -> list[str]:
    base = "https://www.haestirettur.is"
    list_page = f"{base}/akvardanir/"
    resp = requests.get(list_page, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # adjust this prefix if the path pattern differs
        if href.startswith("/akvardanir/") and href != "/akvardanir/":
            links.add(urljoin(base, href))
    return sorted(links)


def main():
    csv_file = Path("allir_domar_og_akvardanir.csv")
    json_file = Path("mapping.json")
    cols = [
        "supreme_case_number",
        "supreme_case_link",
        "appeals_case_number",
        "appeals_case_link",
        "source_type",
    ]

    # Load existing data or init empty DF
    if os.path.exists(csv_file):
        df_existing = pd.read_csv(csv_file, dtype=str)
    else:
        df_existing = pd.DataFrame(columns=cols)

    all_rows = []

    # -- scrape dómar --
    verdict_links = get_verdict_links()
    print(f"Found {len(verdict_links)} dómar")
    for url in verdict_links:
        sup_no, link, app_no, app_link = scrape_supreme(url)
        all_rows.append((sup_no, link, app_no, app_link, "dóm"))

    # -- scrape ákvarðanir --
    decision_links = get_decision_links()
    print(f"Found {len(decision_links)} ákvarðanir")
    for url in decision_links:
        sup_no, link, app_no, app_link = scrape_supreme(url)
        all_rows.append((sup_no, link, app_no, app_link, "ákvörðun"))

    # Build new DataFrame; drop entries without appeals-case
    df_new = pd.DataFrame(all_rows, columns=cols)
    df_new = df_new[df_new["appeals_case_number"].str.strip().astype(bool)]

    # Concat, dedupe on supreme_case_number (keep existing first)
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(
        subset="supreme_case_number", keep="first"
    )

    # Save
    dir_name = os.path.dirname(csv_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    df_combined.to_csv(csv_file, index=False, encoding="utf-8")
    added = len(df_combined) - len(df_existing)
    print(f"Done → {csv_file} ({added} new rows, total {len(df_combined)})")

    # 1) Read and strip whitespace on all string columns
    df = pd.read_csv(csv_file, encoding="utf-8-sig", dtype=str)
    df.loc[df['appeals_case_link'].isnull(),'appeals_case_link'] = ''
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].str.strip()

    # 2) Build the mapping in one go, no groupby.apply
    mapping = {
        appeals_num: (
            # single-record → just the dict
            group.drop(columns="appeals_case_number")
                .to_dict(orient="records")[0]
            if len(group) == 1
            # multi-record → list of dicts
            else group.drop(columns="appeals_case_number")
                    .to_dict(orient="records")
        )
        for appeals_num, group in df.groupby("appeals_case_number")
    }

    # 3) Write JSON
    json_file.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 4) Print summary
    total = sum(
        1 if not isinstance(v, list) else len(v)
        for v in mapping.values()
    )
    print(f"Wrote {json_file} with {total:,} verdict links")

if __name__ == "__main__":
    main()
