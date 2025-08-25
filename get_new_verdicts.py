import os
import re
import requests
import json
import pandas as pd
from pathlib import Path
from bs4 import BeautifulSoup, Tag
from urllib.parse import urlparse, urljoin
from datetime import datetime
from zoneinfo import ZoneInfo

HEADERS = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) ")}

# Supreme Court case-number patterns
#
#  * Decisions ("ákvarðanir") show the number after the prefix "Nr. ",
#    e.g. "Nr. 2025-106".
#  * Verdicts ("dómar") place the number after the prefix "Mál nr.",
#    e.g. "Mál nr. 5/2025".
SUPREME_DECISION_RE = re.compile(r"Nr\.\s*(\d{4}-\d+)")
SUPREME_VERDICT_RE  = re.compile(r"Mál nr\.\s*(\d+)/(20\d{2})")

# Appeals-court link & number patterns (unchanged)
APPEALS_URL_RE = re.compile(
    r"https://landsrettur\.is/domar-og-urskurdir/domur-urskurdur/[^\s\"'<>]+"
)
APPEALS_NO_RE  = re.compile(r"\b(\d+)/(20\d{2})\b")

# --- Date extraction (Icelandic months) ---
MONTHS = "janúar|febrúar|mars|apríl|maí|júní|júlí|ágúst|september|október|nóvember|desember"
DATE_RE = re.compile(rf"\b(\d{{1,2}}\.\s+(?:{MONTHS})\s+20\d{{2}})\b", re.I)

def extract_verdict_date(text: str) -> str:
    """Extract a date like '15. maí 2025' (Icelandic), else try ISO '2025-05-15' as a fallback."""
    if not text:
        return ""
    m = DATE_RE.search(text)
    if m:
        return m.group(1)
    return ""

# --- "Lykilorð" helpers for ákvarðanir status ---
def _iter_forward_for_list(label: Tag) -> list[str]:
    """From a 'Lykilorð' label tag, walk forward to the next UL/OL and return LI texts."""
    items: list[str] = []
    for sib in label.next_siblings:
        if isinstance(sib, Tag):
            name = sib.name.lower()
            if name in {"h2", "h3"}:
                break
            if name in {"ul", "ol"}:
                for li in sib.find_all("li"):
                    txt = li.get_text(" ", strip=True)
                    if txt:
                        items.append(txt)
                if items:
                    return items
    parent = label.parent
    if isinstance(parent, Tag):
        nxt = parent.find_next(lambda t: isinstance(t, Tag) and t.name.lower() in {"ul", "ol"})
        if nxt:
            for li in nxt.find_all("li"):
                txt = li.get_text(" ", strip=True)
                if txt:
                    items.append(txt)
    return items

def extract_keywords(soup: BeautifulSoup) -> list[str]:
    """
    Robustly find the Lykilorð list:
      1) look for a header-like tag containing 'Lykilorð'
      2) otherwise, fall back to all <li> in main content
    """
    label = None
    for tag in soup.find_all(lambda t: isinstance(t, Tag) and t.name in {"h2", "h3", "h4", "strong", "b", "dt"}):
        txt = tag.get_text(" ", strip=True)
        if txt and "lykilorð" in txt.casefold():
            label = tag
            break
    if label:
        items = _iter_forward_for_list(label)
        if items:
            return items
    main = soup.find("main") or soup
    return [li.get_text(strip=True) for li in main.find_all("li")]

def decide_status(soup: BeautifulSoup, page_text: str) -> str:
    """Return 'Samþykkt', 'Hafnað' or ''."""
    kws = [k.casefold() for k in extract_keywords(soup)]
    if any("samþykkt" in k for k in kws):
        return "Samþykkt"
    if any("hafnað" in k for k in kws):
        return "Hafnað"
    t = page_text.casefold()
    i_s = t.find("samþykkt")
    i_h = t.find("hafnað")
    if i_s != -1 and (i_h == -1 or i_s < i_h):
        return "Samþykkt"
    if i_h != -1:
        return "Hafnað"
    return ""

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

def scrape_supreme(url: str, source_type: str) -> tuple[str, str, str, str, str, str]:
    """
    Fetch one Supreme Court page and return:
      (supreme_case_number, supreme_case_link, appeals_case_number, appeals_case_link, verdict_date, decision_status)
    decision_status is only filled for ákvarðanir; empty for dómar.
    """
    html = requests.get(url, headers=HEADERS, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # Supreme-Court case number
    sup_no = ""
    if "/domar/" in url:
        m = SUPREME_VERDICT_RE.search(html)
        if m:
            sup_no = f"{m.group(1)}/{m.group(2)}"
    else:
        m = SUPREME_DECISION_RE.search(html)
        if m:
            sup_no = m.group(1)

    # Date (common to both)
    verdict_date = extract_verdict_date(page_text)

    # Status (only for ákvarðanir)
    source_cf = source_type.casefold()
    is_decision = any(x in source_cf for x in ["ákvörðun", "akvörðun", "akvordun"])
    decision_status = decide_status(soup, page_text) if is_decision else ""

    # Find appeals link if any
    app_link = first_appeals_link(html) or ""
    app_no = ""
    if app_link:
        parsed = urlparse(app_link)
        dom = parsed.netloc.lower()
        if dom == "landsrettur.is" or dom.endswith(".landsrettur.is"):
            app_no = appeals_case_number(app_link)
        else:
            app_link = ""  # wrong domain → drop

    return sup_no, url, app_no, app_link, verdict_date, decision_status

def get_verdict_links() -> list[str]:
    base = "https://www.haestirettur.is"
    list_page = f"{base}/domar/"
    resp = requests.get(list_page, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/domar/_domur/"):  # only detail pages
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
        "verdict_date",
        "decision_status",
    ]

    # Load existing data or init empty DF
    if os.path.exists(csv_file):
        df_existing = pd.read_csv(csv_file, dtype=str)
        # Ensure new columns exist in old files
        for c in cols:
            if c not in df_existing.columns:
                df_existing[c] = ""
        df_existing = df_existing[cols]
    else:
        df_existing = pd.DataFrame(columns=cols)

    all_rows = []

    # -- scrape dómar --
    verdict_links = get_verdict_links()
    print(f"Found {len(verdict_links)} dómar")
    for url in verdict_links:
        sup_no, link, app_no, app_link, verdict_date, decision_status = scrape_supreme(url, "dóm")
        all_rows.append((sup_no, link, app_no, app_link, "dóm", verdict_date, decision_status))

    # -- scrape ákvarðanir --
    decision_links = get_decision_links()
    print(f"Found {len(decision_links)} ákvarðanir")
    for url in decision_links:
        sup_no, link, app_no, app_link, verdict_date, decision_status = scrape_supreme(url, "ákvörðun")
        all_rows.append((sup_no, link, app_no, app_link, "ákvörðun", verdict_date, decision_status))

    # Build new DataFrame; drop entries without appeals-case
    df_new = pd.DataFrame(all_rows, columns=cols)
    df_new = df_new[df_new["appeals_case_number"].str.strip().astype(bool)]

    # Concat, dedupe on supreme_case_number (keep existing first)
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset="supreme_case_number", keep="first")

    # Save combined CSV
    dir_name = os.path.dirname(csv_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    df_combined.to_csv(csv_file, index=False, encoding="utf-8")
    added = len(df_combined) - len(df_existing)
    print(f"Done → {csv_file} ({added} new rows, total {len(df_combined)})")

    # 1) Read and strip whitespace on all string columns
    df = pd.read_csv(csv_file, encoding="utf-8-sig", dtype=str)

    # Ensure the two new columns are present (for safety if other tools touch the CSV)
    for c in ["verdict_date", "decision_status"]:
        if c not in df.columns:
            df[c] = ""

    df.loc[df['appeals_case_link'].isnull(), 'appeals_case_link'] = ''
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].fillna("").str.strip()

    # 2) Build the mapping in one go, no groupby.apply
    mapping = {
        appeals_num: (
            group.drop(columns="appeals_case_number").to_dict(orient="records")[0]
            if len(group) == 1
            else group.drop(columns="appeals_case_number").to_dict(orient="records")
        )
        for appeals_num, group in df.groupby("appeals_case_number")
    }

    # 3) Write JSON
    json_file.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 4) Print summary
    total = sum(1 if not isinstance(v, list) else len(v) for v in mapping.values())
    print(f"Wrote {json_file} with {total:,} verdict links")

    # 5) Write timestamp in Icelandic locale format
    months = [
        "", "janúar", "febrúar", "mars", "apríl", "maí", "júní",
        "júlí", "ágúst", "september", "október", "nóvember", "desember",
    ]
    dt = datetime.now(ZoneInfo("Atlantic/Reykjavik"))
    ts_str = f"Síðast uppfært {dt.day}. {months[dt.month]} {dt.year}."
    Path("last_updated.txt").write_text(ts_str, encoding="utf-8")
    print(f"Wrote last_updated.txt: {ts_str}")

if __name__ == "__main__":
    main()
