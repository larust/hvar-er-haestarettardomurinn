import os
import re
import json
import logging
import time
from typing import Optional, List, Set, Tuple, Dict, Any
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urljoin

import requests
import pandas as pd
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Configuration & Constants ---
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.haestirettur.is"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}

# Regex Patterns
SUPREME_DECISION_RE = re.compile(r"Nr\.\s*(\d{4}-\d+)")
SUPREME_VERDICT_RE  = re.compile(r"Mál nr\.\s*(\d+)/(20\d{2})")
APPEALS_URL_RE = re.compile(r"https://landsrettur\.is/domar-og-urskurdir/domur-urskurdur/[^\s\"'<>]+")
APPEALS_NO_RE  = re.compile(r"\b(\d+)/(20\d{2})\b")
MONTHS_PATTERN = "janúar|febrúar|mars|apríl|maí|júní|júlí|ágúst|september|október|nóvember|desember"
DATE_RE = re.compile(rf"\b(\d{{1,2}}\.\s+(?:{MONTHS_PATTERN})\s+20\d{{2}})\b", re.I)

class Scraper:
    def __init__(self, retries: int = 3, backoff_factor: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        retry_strategy = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_page(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def extract_verdict_date(self, text: str) -> str:
        if not text:
            return ""
        m = DATE_RE.search(text)
        return m.group(1) if m else ""

    def _iter_forward_for_list(self, label: Tag) -> List[str]:
        items: List[str] = []
        # Check siblings
        for sib in label.next_siblings:
            if isinstance(sib, Tag):
                if sib.name in {"h2", "h3", "h4"}:
                    break
                if sib.name in {"ul", "ol"}:
                    items.extend(li.get_text(" ", strip=True) for li in sib.find_all("li"))
                    return items # Found the list, return
        
        # Check parent's next sibling (sometimes structure is weird)
        parent = label.parent
        if isinstance(parent, Tag):
            nxt = parent.find_next(lambda t: isinstance(t, Tag) and t.name in {"ul", "ol"})
            if nxt:
                items.extend(li.get_text(" ", strip=True) for li in nxt.find_all("li"))
        return items

    def extract_keywords(self, soup: BeautifulSoup) -> List[str]:
        label = None
        for tag in soup.find_all(lambda t: isinstance(t, Tag) and t.name in {"h2", "h3", "h4", "strong", "b", "dt"}):
            txt = tag.get_text(" ", strip=True)
            if txt and "lykilorð" in txt.casefold():
                label = tag
                break
        
        if label:
            items = self._iter_forward_for_list(label)
            if items:
                return items
        
        # Fallback: all LIs in main
        main = soup.find("main") or soup
        return [li.get_text(strip=True) for li in main.find_all("li")]

    def decide_status(self, soup: BeautifulSoup, page_text: str) -> str:
        keywords = [k.casefold() for k in self.extract_keywords(soup)]
        if any("samþykkt" in k for k in keywords):
            return "Samþykkt"
        if any("hafnað" in k for k in keywords):
            return "Hafnað"
        
        # Text search fallback
        t_lower = page_text.casefold()
        i_s = t_lower.find("samþykkt")
        i_h = t_lower.find("hafnað")
        
        if i_s != -1 and (i_h == -1 or i_s < i_h):
            return "Samþykkt"
        if i_h != -1:
            return "Hafnað"
        return ""

    def get_appeals_case_number(self, url: str) -> str:
        logger.debug(f"Checking appeals link: {url}")
        html = self.fetch_page(url)
        if not html:
            return ""
        
        # Find all matches, filter for reasonable years (e.g. >= 2018)
        for num, year in APPEALS_NO_RE.findall(html):
            if int(year) >= 2018:
                return f"{num}/{year}"
        return ""

    def parse_supreme_page(self, url: str, source_type: str) -> Dict[str, str]:
        html = self.fetch_page(url)
        if not html:
            return {}
        
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)

        # 1. Supreme Case Number
        sup_no = ""
        if "/domar/" in url:
            m = SUPREME_VERDICT_RE.search(html)
            if m:
                sup_no = f"{m.group(1)}/{m.group(2)}"
        else: # decisions
            m = SUPREME_DECISION_RE.search(html)
            if m:
                sup_no = m.group(1)

        # 2. Date
        verdict_date = self.extract_verdict_date(page_text)

        # 3. Status (Decisions only)
        decision_status = ""
        if "ákvörðun" in source_type.casefold():
             decision_status = self.decide_status(soup, page_text)

        # 4. Appeals Link & Number
        app_link_match = APPEALS_URL_RE.search(html)
        app_link = app_link_match.group(0) if app_link_match else ""
        app_no = ""
        
        if app_link:
            parsed = urlparse(app_link)
            domain = parsed.netloc.lower()
            if domain == "landsrettur.is" or domain.endswith(".landsrettur.is"):
                app_no = self.get_appeals_case_number(app_link)
            else:
                app_link = "" # Discard invalid domain

        return {
            "supreme_case_number": sup_no,
            "supreme_case_link": url,
            "appeals_case_number": app_no,
            "appeals_case_link": app_link,
            "source_type": source_type,
            "verdict_date": verdict_date,
            "decision_status": decision_status,
        }

    def get_links(self, path: str) -> List[str]:
        full_url = urljoin(BASE_URL, path)
        html = self.fetch_page(full_url)
        if not html:
            return []
        
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Check for detail pages
            if href.startswith("/domar/_domur/") or (href.startswith("/akvardanir/") and href != "/akvardanir/"):
                links.add(urljoin(BASE_URL, href))
        return sorted(list(links))

class DataManager:
    def __init__(self, csv_path: str = "allir_domar_og_akvardanir.csv", json_path: str = "mapping.json"):
        self.csv_path = Path(csv_path)
        self.json_path = Path(json_path)
        self.columns = [
            "supreme_case_number",
            "supreme_case_link",
            "appeals_case_number",
            "appeals_case_link",
            "source_type",
            "verdict_date",
            "decision_status",
        ]

    def load_existing_data(self) -> pd.DataFrame:
        if self.csv_path.exists():
            df = pd.read_csv(self.csv_path, dtype=str)
            # Ensure all cols exist
            for col in self.columns:
                if col not in df.columns:
                    df[col] = ""
            return df[self.columns]
        return pd.DataFrame(columns=self.columns)

    def save_csv(self, new_rows: List[Dict[str, str]]):
        if not new_rows:
            logger.info("No new rows to save.")
            return

        df_existing = self.load_existing_data()
        df_new = pd.DataFrame(new_rows, columns=self.columns)
        
        # Filter rows that have an appeals case number
        df_new = df_new[df_new["appeals_case_number"].str.strip().astype(bool)]
        
        # Combine
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        # Deduplicate on supreme case number, keeping existing (oldest scrape might be better? or overwrite? 
        # The original script kept 'first' which implies existing. Let's stick to that.)
        df_combined = df_combined.drop_duplicates(subset="supreme_case_number", keep="first")
        
        df_combined.to_csv(self.csv_path, index=False, encoding="utf-8")
        added_count = len(df_combined) - len(df_existing)
        logger.info(f"Updated CSV. Total rows: {len(df_combined)}. New rows: {added_count}")

    def generate_json_mapping(self):
        if not self.csv_path.exists():
            logger.warning("No CSV file found to generate JSON mapping.")
            return

        df = pd.read_csv(self.csv_path, encoding="utf-8-sig", dtype=str)
        
        # Sanitization
        for col in self.columns:
             if col not in df.columns: df[col] = ""

        df["appeals_case_link"] = df["appeals_case_link"].fillna("")
        for col in df.select_dtypes(include="object"):
            df[col] = df[col].fillna("").str.strip()

        # Grouping
        mapping = {}
        grouped = df.groupby("appeals_case_number")
        for appeals_num, group in grouped:
            records = group.drop(columns="appeals_case_number").to_dict(orient="records")
            if len(records) == 1:
                mapping[appeals_num] = records[0]
            else:
                mapping[appeals_num] = records
        
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        
        total_linked = sum(len(v) if isinstance(v, list) else 1 for v in mapping.values())
        logger.info(f"Generated JSON mapping with {total_linked} links.")

    def update_timestamp(self):
        months = ["", "janúar", "febrúar", "mars", "apríl", "maí", "júní",
                  "júlí", "ágúst", "september", "október", "nóvember", "desember"]
        dt = datetime.now(ZoneInfo("Atlantic/Reykjavik"))
        ts_str = f"Síðast uppfært {dt.day}. {months[dt.month]} {dt.year}."
        Path("last_updated.txt").write_text(ts_str, encoding="utf-8")
        logger.info(f"Updated timestamp: {ts_str}")

def main():
    scraper = Scraper()
    manager = DataManager()

    all_data = []

    # 1. Scrape Verdicts
    verdict_links = scraper.get_links("/domar/")
    logger.info(f"Found {len(verdict_links)} verdict links.")
    for link in verdict_links:
        data = scraper.parse_supreme_page(link, "dóm")
        if data.get("supreme_case_number"): # precise validity check
            all_data.append(data)

    # 2. Scrape Decisions
    decision_links = scraper.get_links("/akvardanir/")
    logger.info(f"Found {len(decision_links)} decision links.")
    for link in decision_links:
        data = scraper.parse_supreme_page(link, "ákvörðun")
        if data.get("supreme_case_number"):
            all_data.append(data)

    # 3. Save
    manager.save_csv(all_data)
    manager.generate_json_mapping()
    manager.update_timestamp()

if __name__ == "__main__":
    main()
