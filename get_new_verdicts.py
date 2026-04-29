import argparse
import concurrent.futures
import re
import json
import logging
import math
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from html import unescape
from typing import Optional, List, Set, Tuple, Dict, Any
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse, urljoin

import requests
import pandas as pd
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Configuration & Constants ---
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

ISLAND_BASE_URL = "https://island.is"
VERDICT_LISTING_URL = f"{ISLAND_BASE_URL}/domar?court=H%C3%A6stir%C3%A9ttur"
DECISION_LISTING_URL = f"{ISLAND_BASE_URL}/s/haestirettur/akvardanir"
GRAPHQL_URL = f"{ISLAND_BASE_URL}/api/graphql"
SUPREME_COURT_LEVEL = "Hæstiréttur"
LANDSRETTUR_COURT_FILTER = "Landsrettur"
LANDSRETTUR_COURT_LEVEL = "Landsréttur"
DEFAULT_DECISION_PAGE_LIMIT = 200
SCRAPE_REPORT_PATH = Path("scrape_report.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
ICELANDIC_MONTHS = {
    "janúar": 1,
    "febrúar": 2,
    "mars": 3,
    "apríl": 4,
    "maí": 5,
    "júní": 6,
    "júlí": 7,
    "ágúst": 8,
    "september": 9,
    "október": 10,
    "nóvember": 11,
    "desember": 12,
}

VERDICTS_QUERY = """
query GetVerdicts($input: WebVerdictsInput!) {
    webVerdicts(input: $input) {
        total
        items {
            id
            caseNumber
            court
            verdictDate
        }
    }
}
"""

# Regex Patterns
SUPREME_DECISION_RE = re.compile(r"(?:Mál\s+nr\.?|Nr\.?)\s*(\d{4}-\d+)", re.I)
SUPREME_VERDICT_RE  = re.compile(r"Mál\s+nr\.?\s*(\d+)/(20\d{2})", re.I)
APPEALS_URL_RE = re.compile(r"https?://(?:www\.)?landsrettur\.is/[^\s\"'<>]+", re.I)
APPEALS_NO_RE  = re.compile(r"\b(\d+)/(20\d{2})\b")
VERDICT_ID_RE = re.compile(r"^s-[A-Za-z0-9-]+$")
LOWER_COURT_ID_RE = re.compile(r"^g-[A-Za-z0-9-]+$")
VERDICT_PATH_RE = re.compile(r"^/domar/(s-[A-Za-z0-9-]+)/?$")
LOWER_COURT_PATH_RE = re.compile(r"^/domar/g-[A-Za-z0-9-]+/?$")
DECISION_PATH_RE = re.compile(r"^/s/haestirettur/akvardanir/[A-Fa-f0-9-]{36}/?$")
CASE_LABEL_RE = re.compile(r"\b(?:\d{4}-\d+|\d+/(?:19|20)\d{2})\b")
APPEALED_LANDSRETTUR_CASE_RE = re.compile(
    r"\bdómi\s+Landsréttar\b.{0,200}?\bí\s+máli\s+nr\.?\s*(\d+)/(20\d{2})",
    re.I,
)
MONTHS_PATTERN = "janúar|febrúar|mars|apríl|maí|júní|júlí|ágúst|september|október|nóvember|desember"
DATE_RE = re.compile(rf"\b(\d{{1,2}}\.\s+(?:{MONTHS_PATTERN})\s+20\d{{2}})\b", re.I)

def now_reykjavik_iso() -> str:
    return datetime.now(ZoneInfo("Atlantic/Reykjavik")).isoformat(timespec="seconds")

def parse_icelandic_date(value: str) -> Optional[date]:
    match = DATE_RE.search(value or "")
    if not match:
        return None

    day_text, month_text, year_text = match.group(1).replace(".", "").split()
    month = ICELANDIC_MONTHS.get(month_text.casefold())
    if not month:
        return None
    return date(int(year_text), month, int(day_text))

def is_island_url(value: str) -> bool:
    return urlparse(value or "").netloc.lower() == "island.is"

def has_domain(value: str, domain: str) -> bool:
    netloc = urlparse(value or "").netloc.lower()
    return netloc == domain or netloc.endswith(f".{domain}")

def query_id(value: str) -> str:
    parsed = urlparse(unescape(value or ""))
    return (parse_qs(parsed.query).get("id") or [""])[0].strip()

def legacy_supreme_link_to_island(value: str, source_type: str) -> str:
    item_id = query_id(value)
    if not item_id:
        return ""
    if "ákvörðun" in source_type.casefold():
        return urljoin(ISLAND_BASE_URL, f"/s/haestirettur/akvardanir/{item_id}")
    return urljoin(ISLAND_BASE_URL, f"/domar/s-{item_id}")

@dataclass
class SourceStats:
    listing_pages_fetched: int = 0
    listing_pages_failed: int = 0
    listing_pages_empty: int = 0
    listing_items_discovered: int = 0
    known_items_skipped: int = 0
    detail_pages_attempted: int = 0
    detail_pages_with_case_number: int = 0
    detail_pages_without_case_number: int = 0
    linked_rows: int = 0
    unlinked_rows: int = 0

@dataclass
class ScrapeReport:
    started_at: str = field(default_factory=now_reykjavik_iso)
    completed_at: str = ""
    mode: str = "incremental"
    max_pages: Optional[int] = None
    source_urls: Dict[str, str] = field(default_factory=lambda: {
        "verdicts": VERDICT_LISTING_URL,
        "decisions": DECISION_LISTING_URL,
    })
    sources: Dict[str, SourceStats] = field(default_factory=lambda: {
        "verdicts": SourceStats(),
        "decisions": SourceStats(),
    })
    skipped_cases: List[Dict[str, str]] = field(default_factory=list)
    source_failures: List[str] = field(default_factory=list)
    csv_rows_added: int = 0
    mapping_links_generated: int = 0
    artifacts_refreshed: bool = False
    failed: bool = False
    failure_reason: str = ""

    def source(self, name: str) -> SourceStats:
        if name not in self.sources:
            self.sources[name] = SourceStats()
        return self.sources[name]

    def add_skipped_case(self, source: str, row: Dict[str, str], reason: str) -> None:
        self.skipped_cases.append({
            "source": source,
            "reason": reason,
            "supreme_case_number": row.get("supreme_case_number", ""),
            "supreme_case_link": row.get("supreme_case_link", ""),
            "source_type": row.get("source_type", ""),
        })

    @property
    def total_listing_pages_fetched(self) -> int:
        return sum(stats.listing_pages_fetched for stats in self.sources.values())

    @property
    def total_listing_items_discovered(self) -> int:
        return sum(stats.listing_items_discovered for stats in self.sources.values())

    @property
    def total_detail_pages_attempted(self) -> int:
        return sum(stats.detail_pages_attempted for stats in self.sources.values())

    @property
    def total_valid_supreme_cases(self) -> int:
        return sum(stats.detail_pages_with_case_number for stats in self.sources.values())

    @property
    def total_linked_rows(self) -> int:
        return sum(stats.linked_rows for stats in self.sources.values())

    def mark_failed(self, reason: str) -> None:
        self.failed = True
        self.failure_reason = reason

    def mark_completed(self) -> None:
        self.completed_at = now_reykjavik_iso()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["totals"] = {
            "listing_pages_fetched": self.total_listing_pages_fetched,
            "listing_items_discovered": self.total_listing_items_discovered,
            "detail_pages_attempted": self.total_detail_pages_attempted,
            "valid_supreme_cases": self.total_valid_supreme_cases,
            "linked_rows": self.total_linked_rows,
        }
        return data

    def log_summary(self) -> None:
        logger.info(
            "Scrape report: %s listing items, %s detail pages, %s valid Supreme cases, "
            "%s linked rows, %s CSV rows added.",
            self.total_listing_items_discovered,
            self.total_detail_pages_attempted,
            self.total_valid_supreme_cases,
            self.total_linked_rows,
            self.csv_rows_added,
        )

def write_scrape_report(report: ScrapeReport, path: Path = SCRAPE_REPORT_PATH) -> None:
    report.mark_completed()
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info(f"Wrote scrape report: {path}")

def suspicious_run_reason(report: ScrapeReport, full: bool) -> str:
    if report.total_listing_pages_fetched == 0:
        return "No source listing pages were fetched successfully."

    if report.total_listing_items_discovered == 0:
        return "Source listing pages were fetched, but no listing items were discovered."

    if report.total_detail_pages_attempted > 0 and report.total_valid_supreme_cases == 0:
        return "Detail pages were queued, but none produced a Supreme Court case number."

    if full and report.total_valid_supreme_cases == 0:
        return "Full scrape did not produce any valid Supreme Court cases."

    if report.total_detail_pages_attempted >= 5:
        parse_success_rate = report.total_valid_supreme_cases / report.total_detail_pages_attempted
        if parse_success_rate < 0.5:
            return f"Detail parse success rate was unexpectedly low ({parse_success_rate:.0%})."

    return ""

class Scraper:
    def __init__(self, retries: int = 3, backoff_factor: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        retry_strategy = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
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

    def fetch_json(self, url: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as e:
            logger.error(f"Error fetching JSON from {url}: {e}")
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
            if isinstance(nxt, Tag):
                items.extend(li.get_text(" ", strip=True) for li in nxt.find_all("li"))
        return items

    def extract_keywords(self, soup: BeautifulSoup) -> List[str]:
        label: Optional[Tag] = None
        for tag in soup.find_all(lambda t: isinstance(t, Tag) and t.name in {"h2", "h3", "h4", "strong", "b", "dt"}):
            if not isinstance(tag, Tag):
                continue
            txt = tag.get_text(" ", strip=True)
            if txt and "lykilorð" in txt.casefold():
                label = tag
                break
        
        if label:
            items = self._iter_forward_for_list(label)
            if items:
                return items
        
        # Fallback: all LIs in main
        main = soup.find("main")
        if not isinstance(main, Tag):
            main = soup
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

    def is_trusted_appeals_url(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain == "landsrettur.is" or domain.endswith(".landsrettur.is"):
            return True
        return domain == "island.is" and bool(LOWER_COURT_PATH_RE.match(parsed.path))

    def extract_appeals_link(self, html: str) -> str:
        for match in APPEALS_URL_RE.finditer(html):
            candidate = unescape(match.group(0)).rstrip(".,)")
            if self.is_trusted_appeals_url(candidate):
                return candidate

        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            if not isinstance(anchor, Tag):
                continue
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            candidate = urljoin(ISLAND_BASE_URL, unescape(href))
            if self.is_trusted_appeals_url(candidate):
                return candidate
        return ""

    def get_appeals_case_number(self, url: str) -> str:
        url = unescape(url)
        if not self.is_trusted_appeals_url(url):
            return ""

        logger.debug(f"Checking appeals link: {url}")
        html = self.fetch_page(url)
        if not html:
            return ""
        
        # Find all matches, filter for reasonable years (e.g. >= 2018)
        for num, year in APPEALS_NO_RE.findall(html):
            if int(year) >= 2018:
                return f"{num}/{year}"
        return ""

    def extract_appeals_case_number_from_supreme_text(self, page_text: str, source_type: str) -> str:
        if "ákvörðun" not in source_type.casefold():
            return ""

        match = APPEALED_LANDSRETTUR_CASE_RE.search(page_text)
        return f"{match.group(1)}/{match.group(2)}" if match else ""

    def find_island_lower_court_link(self, case_number: str) -> str:
        return self.find_island_verdict_link(
            case_number=case_number,
            court_filter=LANDSRETTUR_COURT_FILTER,
            expected_court=LANDSRETTUR_COURT_LEVEL,
            id_pattern=LOWER_COURT_ID_RE,
        )

    def find_island_supreme_verdict_link(self, case_number: str) -> str:
        return self.find_island_verdict_link(
            case_number=case_number,
            court_filter=SUPREME_COURT_LEVEL,
            expected_court=SUPREME_COURT_LEVEL,
            id_pattern=VERDICT_ID_RE,
        )

    def find_island_verdict_link(
        self,
        case_number: str,
        court_filter: str,
        expected_court: str,
        id_pattern: re.Pattern,
    ) -> str:
        if not case_number:
            return ""

        payload = {
            "query": VERDICTS_QUERY,
            "variables": {
                "input": {
                    "searchTerm": None,
                    "caseCategories": None,
                    "caseTypes": None,
                    "keywords": None,
                    "page": 1,
                    "court": court_filter,
                    "laws": None,
                    "caseNumber": case_number,
                    "dateFrom": None,
                    "dateTo": None,
                    "caseContact": None,
                }
            },
        }
        data = self.fetch_json(GRAPHQL_URL, payload)
        web_verdicts = (data or {}).get("data", {}).get("webVerdicts") or {}
        for item in web_verdicts.get("items") or []:
            item_id = item.get("id") or ""
            if (
                item.get("court") == expected_court
                and (item.get("caseNumber") or "").strip() == case_number
                and id_pattern.match(item_id)
            ):
                return urljoin(ISLAND_BASE_URL, f"/domar/{item_id}")
        return ""

    def build_verdict_link_index(
        self,
        court_filter: str,
        expected_court: str,
        id_pattern: re.Pattern,
        since_date: date,
    ) -> Dict[str, str]:
        links: Dict[str, str] = {}
        page = 1
        while True:
            payload = {
                "query": VERDICTS_QUERY,
                "variables": {
                    "input": {
                        "searchTerm": None,
                        "caseCategories": None,
                        "caseTypes": None,
                        "keywords": None,
                        "page": page,
                        "court": court_filter,
                        "laws": None,
                        "caseNumber": None,
                        "dateFrom": None,
                        "dateTo": None,
                        "caseContact": None,
                    }
                },
            }
            data = self.fetch_json(GRAPHQL_URL, payload)
            web_verdicts = (data or {}).get("data", {}).get("webVerdicts") or {}
            items = web_verdicts.get("items") or []
            if not items:
                break

            page_dates: List[date] = []
            for item in items:
                item_id = item.get("id") or ""
                case_number = (item.get("caseNumber") or "").strip()
                verdict_date = (item.get("verdictDate") or "")[:10]
                parsed_date = date.fromisoformat(verdict_date) if verdict_date else None
                if parsed_date:
                    page_dates.append(parsed_date)
                if (
                    item.get("court") == expected_court
                    and case_number
                    and id_pattern.match(item_id)
                    and (not parsed_date or parsed_date >= since_date)
                ):
                    links.setdefault(case_number, urljoin(ISLAND_BASE_URL, f"/domar/{item_id}"))

            total = int(web_verdicts.get("total") or 0)
            if page_dates and max(page_dates) < since_date:
                break
            if total and page >= math.ceil(total / len(items)):
                break
            page += 1

        logger.info(f"Indexed {len(links)} {expected_court} Ísland.is verdict links from {since_date.isoformat()} onward.")
        return links

    def build_lower_court_link_index(self, since_date: date) -> Dict[str, str]:
        return self.build_verdict_link_index(
            court_filter=LANDSRETTUR_COURT_FILTER,
            expected_court=LANDSRETTUR_COURT_LEVEL,
            id_pattern=LOWER_COURT_ID_RE,
            since_date=since_date,
        )

    def resolve_lower_court_links(self, case_numbers: Set[str], max_workers: int = 8) -> Dict[str, str]:
        links: Dict[str, str] = {}
        ordered_case_numbers = sorted(case_numbers)
        if not ordered_case_numbers:
            return links

        thread_local = threading.local()

        def worker(case_number: str) -> Tuple[str, str]:
            if not hasattr(thread_local, "scraper"):
                thread_local.scraper = Scraper(retries=1, backoff_factor=0.1)
            return case_number, thread_local.scraper.find_island_lower_court_link(case_number)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, case_number) for case_number in ordered_case_numbers]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                case_number, link = future.result()
                if link:
                    links[case_number] = link
                if index % 100 == 0:
                    logger.info("Resolved %s/%s Landsréttur links.", index, len(ordered_case_numbers))

        logger.info("Resolved %s/%s Landsréttur case numbers to Ísland.is links.", len(links), len(ordered_case_numbers))
        return links

    def build_decision_link_index(
        self,
        since_year: int = 2018,
        page_limit: int = DEFAULT_DECISION_PAGE_LIMIT,
    ) -> Dict[str, str]:
        decision_links: Dict[str, str] = {}
        for page in range(1, page_limit + 1):
            items, ok = self.get_decision_listing_page(page)
            if not ok:
                logger.warning(f"Could not fetch decision listing page {page} during link migration.")
                break
            if not items:
                break

            page_years: List[int] = []
            for url, case_number in items:
                match = re.match(r"^(20\d{2})-\d+$", case_number or "")
                if not match:
                    continue
                case_year = int(match.group(1))
                page_years.append(case_year)
                if case_year >= since_year:
                    decision_links.setdefault(case_number, url)

            if page_years and max(page_years) < since_year:
                break

        logger.info(f"Indexed {len(decision_links)} Ísland.is decision links from {since_year} onward.")
        return decision_links

    def extract_supreme_case_number(self, html: str, page_text: str, source_type: str) -> str:
        search_text = f"{page_text} {html}"
        if "ákvörðun" in source_type.casefold():
            m = SUPREME_DECISION_RE.search(search_text)
            return m.group(1) if m else ""

        m = SUPREME_VERDICT_RE.search(search_text)
        return f"{m.group(1)}/{m.group(2)}" if m else ""

    def parse_supreme_page(self, url: str, source_type: str) -> Dict[str, str]:
        html = self.fetch_page(url)
        if not html:
            return {}
        
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)

        # 1. Supreme Case Number
        sup_no = self.extract_supreme_case_number(html, page_text, source_type)

        # 2. Date
        verdict_date = self.extract_verdict_date(page_text)

        # 3. Status (Decisions only)
        decision_status = ""
        if "ákvörðun" in source_type.casefold():
             decision_status = self.decide_status(soup, page_text)

        # 4. Appeals Link & Number
        app_link = self.extract_appeals_link(html)
        app_no = ""
        
        if app_link:
            app_no = self.get_appeals_case_number(app_link)

        if not app_no:
            fallback_no = self.extract_appeals_case_number_from_supreme_text(page_text, source_type)
            fallback_link = self.find_island_lower_court_link(fallback_no) if fallback_no else ""
            if fallback_no and fallback_link:
                app_no = fallback_no
                app_link = fallback_link

        return {
            "supreme_case_number": sup_no,
            "supreme_case_link": url,
            "appeals_case_number": app_no,
            "appeals_case_link": app_link,
            "source_type": source_type,
            "verdict_date": verdict_date,
            "decision_status": decision_status,
        }

    def _dedupe_items(self, items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        seen = set()
        deduped = []
        for url, case_number in items:
            if url in seen:
                continue
            seen.add(url)
            deduped.append((url, case_number))
        return deduped

    def extract_verdict_links_from_html(self, html: str) -> List[Tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        items: List[Tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = a.get("href")
            if not isinstance(href, str):
                continue
            url = urljoin(ISLAND_BASE_URL, unescape(href))
            path = urlparse(url).path
            if VERDICT_PATH_RE.match(path):
                label_match = CASE_LABEL_RE.search(a.get_text(" ", strip=True))
                items.append((url, label_match.group(0) if label_match else ""))

        for match in re.finditer(r'"id":"(s-[A-Za-z0-9-]+)"', html):
            items.append((urljoin(ISLAND_BASE_URL, f"/domar/{match.group(1)}"), ""))

        return self._dedupe_items(items)

    def extract_decision_links_from_html(self, html: str) -> List[Tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        items: List[Tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = a.get("href")
            if not isinstance(href, str):
                continue
            url = urljoin(ISLAND_BASE_URL, unescape(href))
            path = urlparse(url).path
            if not DECISION_PATH_RE.match(path):
                continue

            label_match = CASE_LABEL_RE.search(a.get_text(" ", strip=True))
            items.append((url, label_match.group(0) if label_match else ""))

        return self._dedupe_items(items)

    def get_verdict_listing_page(self, page: int) -> Tuple[List[Tuple[str, str]], int, bool]:
        payload = {
            "query": VERDICTS_QUERY,
            "variables": {
                "input": {
                    "searchTerm": None,
                    "caseCategories": None,
                    "caseTypes": None,
                    "keywords": None,
                    "page": page,
                    "court": SUPREME_COURT_LEVEL,
                    "laws": None,
                    "caseNumber": None,
                    "dateFrom": None,
                    "dateTo": None,
                    "caseContact": None,
                }
            },
        }
        data = self.fetch_json(GRAPHQL_URL, payload)
        web_verdicts = (data or {}).get("data", {}).get("webVerdicts")
        if web_verdicts:
            items = []
            for item in web_verdicts.get("items") or []:
                item_id = item.get("id") or ""
                if item.get("court") == SUPREME_COURT_LEVEL and VERDICT_ID_RE.match(item_id):
                    items.append((urljoin(ISLAND_BASE_URL, f"/domar/{item_id}"), (item.get("caseNumber") or "").strip()))
            return self._dedupe_items(items), int(web_verdicts.get("total") or 0), True

        if page == 1:
            logger.warning("Falling back to parsing the rendered verdict listing page.")
            html = self.fetch_page(VERDICT_LISTING_URL)
            if html:
                return self.extract_verdict_links_from_html(html), 0, True
        return [], 0, False

    def get_decision_listing_page(self, page: int) -> Tuple[List[Tuple[str, str]], bool]:
        url = DECISION_LISTING_URL if page == 1 else f"{DECISION_LISTING_URL}?page={page}"
        html = self.fetch_page(url)
        if not html:
            return [], False
        return self.extract_decision_links_from_html(html), True

    def _items_to_scrape(self, items: List[Tuple[str, str]], known_case_numbers: Set[str], full: bool) -> List[Tuple[str, str]]:
        if full:
            return items
        return [(url, case_number) for url, case_number in items if not case_number or case_number not in known_case_numbers]

    def scrape_verdicts(
        self,
        known_case_numbers: Set[str],
        full: bool = False,
        max_pages: Optional[int] = None,
        report: Optional[ScrapeReport] = None,
    ) -> Tuple[List[Dict[str, str]], bool]:
        rows: List[Dict[str, str]] = []
        page = 1
        source_ok = False
        stats = report.source("verdicts") if report else None

        while True:
            if max_pages and page > max_pages:
                logger.info(f"Stopping verdict scrape at configured page limit: {max_pages}")
                break

            items, total, ok = self.get_verdict_listing_page(page)
            source_ok = source_ok or ok
            if not ok:
                if stats:
                    stats.listing_pages_failed += 1
                if report:
                    report.source_failures.append(f"verdicts page {page}")
                logger.warning(f"Could not fetch verdict listing page {page}.")
                break
            if stats:
                stats.listing_pages_fetched += 1
                stats.listing_items_discovered += len(items)
            if not items:
                if stats:
                    stats.listing_pages_empty += 1
                logger.info(f"No verdict links found on page {page}; stopping.")
                break

            to_scrape = self._items_to_scrape(items, known_case_numbers, full)
            if stats:
                stats.known_items_skipped += len(items) - len(to_scrape)
            logger.info(f"Verdict page {page}: {len(items)} links, {len(to_scrape)} queued.")

            if not to_scrape and not full:
                logger.info(f"Stopping verdict scrape at page {page}; all visible cases are already known.")
                break

            for link, _ in to_scrape:
                if stats:
                    stats.detail_pages_attempted += 1
                data = self.parse_supreme_page(link, "dóm")
                if data.get("supreme_case_number"):
                    if stats:
                        stats.detail_pages_with_case_number += 1
                        if data.get("appeals_case_number"):
                            stats.linked_rows += 1
                        else:
                            stats.unlinked_rows += 1
                    if report and not data.get("appeals_case_number"):
                        report.add_skipped_case("verdicts", data, "missing_appeals_case_number")
                    rows.append(data)
                else:
                    if stats:
                        stats.detail_pages_without_case_number += 1
                    if report:
                        report.add_skipped_case(
                            "verdicts",
                            {"supreme_case_link": link, "source_type": "dóm"},
                            "missing_supreme_case_number",
                        )

            if not full and len(to_scrape) < len(items):
                logger.info(f"Stopping verdict scrape after page {page}; reached already-known cases.")
                break

            if total and items:
                page_count = math.ceil(total / len(items))
                if page >= page_count:
                    break

            page += 1

        return rows, source_ok

    def scrape_decisions(
        self,
        known_case_numbers: Set[str],
        full: bool = False,
        max_pages: Optional[int] = None,
        report: Optional[ScrapeReport] = None,
    ) -> Tuple[List[Dict[str, str]], bool]:
        rows: List[Dict[str, str]] = []
        page = 1
        source_ok = False
        seen_links: Set[str] = set()
        page_limit = max_pages or DEFAULT_DECISION_PAGE_LIMIT
        stats = report.source("decisions") if report else None

        while page <= page_limit:
            items, ok = self.get_decision_listing_page(page)
            source_ok = source_ok or ok
            if not ok:
                if stats:
                    stats.listing_pages_failed += 1
                if report:
                    report.source_failures.append(f"decisions page {page}")
                logger.warning(f"Could not fetch decision listing page {page}.")
                break
            if stats:
                stats.listing_pages_fetched += 1
                stats.listing_items_discovered += len(items)

            fresh_items = [(url, case_number) for url, case_number in items if url not in seen_links]
            seen_links.update(url for url, _ in fresh_items)
            if not fresh_items:
                if stats:
                    stats.listing_pages_empty += 1
                logger.info(f"No new decision links found on page {page}; stopping.")
                break

            to_scrape = self._items_to_scrape(fresh_items, known_case_numbers, full)
            if stats:
                stats.known_items_skipped += len(fresh_items) - len(to_scrape)
            logger.info(f"Decision page {page}: {len(fresh_items)} links, {len(to_scrape)} queued.")

            if not to_scrape and not full:
                logger.info(f"Stopping decision scrape at page {page}; all visible cases are already known.")
                break

            for link, _ in to_scrape:
                if stats:
                    stats.detail_pages_attempted += 1
                data = self.parse_supreme_page(link, "ákvörðun")
                if data.get("supreme_case_number"):
                    if stats:
                        stats.detail_pages_with_case_number += 1
                        if data.get("appeals_case_number"):
                            stats.linked_rows += 1
                        else:
                            stats.unlinked_rows += 1
                    if report and not data.get("appeals_case_number"):
                        report.add_skipped_case("decisions", data, "missing_appeals_case_number")
                    rows.append(data)
                else:
                    if stats:
                        stats.detail_pages_without_case_number += 1
                    if report:
                        report.add_skipped_case(
                            "decisions",
                            {"supreme_case_link": link, "source_type": "ákvörðun"},
                            "missing_supreme_case_number",
                        )

            if not full and len(to_scrape) < len(fresh_items):
                logger.info(f"Stopping decision scrape after page {page}; reached already-known cases.")
                break

            page += 1

        if page > page_limit:
            logger.warning(f"Stopped decision scrape at page limit {page_limit}.")

        return rows, source_ok

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
            df = pd.read_csv(self.csv_path, dtype=str).fillna("")
            # Ensure all cols exist
            for col in self.columns:
                if col not in df.columns:
                    df[col] = ""
            return df[self.columns]
        return pd.DataFrame(columns=self.columns)

    def save_csv(self, new_rows: List[Dict[str, str]]) -> int:
        if not new_rows:
            logger.info("No new rows to save.")
            return 0

        df_existing = self.load_existing_data()
        df_new = pd.DataFrame(new_rows, columns=self.columns).fillna("")
        
        # Filter rows that have an appeals case number
        df_new = df_new[df_new["appeals_case_number"].str.strip().astype(bool)]
        if df_new.empty:
            logger.info("Parsed cases did not include any Landsréttur links to save.")
            return 0
        
        # Combine
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        # Deduplicate on supreme case number, keeping existing (oldest scrape might be better? or overwrite? 
        # The original script kept 'first' which implies existing. Let's stick to that.)
        df_combined = df_combined.drop_duplicates(subset="supreme_case_number", keep="first")
        added_count = len(df_combined) - len(df_existing)

        if added_count == 0:
            logger.info(f"No new CSV rows after deduplication. Total rows: {len(df_combined)}")
            return 0
        
        df_combined.to_csv(self.csv_path, index=False, encoding="utf-8")
        logger.info(f"Updated CSV. Total rows: {len(df_combined)}. New rows: {added_count}")
        return added_count

    def write_data(self, df: pd.DataFrame) -> None:
        df[self.columns].to_csv(self.csv_path, index=False, encoding="utf-8")
        logger.info(f"Wrote CSV with {len(df)} rows.")

    def generate_json_mapping(self) -> int:
        if not self.csv_path.exists():
            logger.warning("No CSV file found to generate JSON mapping.")
            return 0

        df = pd.read_csv(self.csv_path, encoding="utf-8-sig", dtype=str)
        
        # Sanitization
        for col in self.columns:
             if col not in df.columns: df[col] = ""

        df = df.fillna("")
        for col in self.columns:
            df.loc[:, col] = df[col].astype(str).str.strip()

        df = df[df["appeals_case_number"].astype(bool)]

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
        return total_linked

    def update_timestamp(self):
        months = ["", "janúar", "febrúar", "mars", "apríl", "maí", "júní",
                  "júlí", "ágúst", "september", "október", "nóvember", "desember"]
        dt = datetime.now(ZoneInfo("Atlantic/Reykjavik"))
        ts_str = f"Síðast uppfært {dt.day}. {months[dt.month]} {dt.year}."
        Path("last_updated.txt").write_text(ts_str, encoding="utf-8")
        logger.info(f"Updated timestamp: {ts_str}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update Landsréttur to Hæstiréttur lookup data.")
    parser.add_argument("--full", action="store_true", help="Crawl available listing pages instead of stopping at known cases.")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional page limit for each source, useful for diagnostics.")
    parser.add_argument("--migrate-island-links", action="store_true", help="Rewrite stored links from 2018 onward to their Ísland.is equivalents.")
    parser.add_argument("--since-date", default="2018-01-01", help="Start date for --migrate-island-links, ISO format YYYY-MM-DD.")
    parser.add_argument("--decision-page-limit", type=int, default=DEFAULT_DECISION_PAGE_LIMIT, help="Decision listing page cap for --migrate-island-links.")
    parser.add_argument("--dry-run", action="store_true", help="Report migration changes without writing CSV, mapping, or timestamp files.")
    return parser.parse_args()

def run_link_migration(
    scraper: Scraper,
    manager: DataManager,
    since_date: date,
    decision_page_limit: int = DEFAULT_DECISION_PAGE_LIMIT,
    dry_run: bool = False,
) -> int:
    df = manager.load_existing_data().copy()
    if df.empty:
        logger.info("No CSV rows found to migrate.")
        return 0

    rows_since_date: Set[int] = set()
    needed_appeals_case_numbers: Set[str] = set()
    for idx, row in df.iterrows():
        parsed_date = parse_icelandic_date(str(row.get("verdict_date", "")))
        if not parsed_date or parsed_date < since_date:
            continue
        rows_since_date.add(idx)
        appeals_case_number = str(row.get("appeals_case_number", "")).strip()
        current_appeals_link = str(row.get("appeals_case_link", "")).strip()
        if appeals_case_number and (not current_appeals_link or not is_island_url(current_appeals_link)):
            needed_appeals_case_numbers.add(appeals_case_number)

    appeals_links = scraper.resolve_lower_court_links(needed_appeals_case_numbers)
    decision_links: Optional[Dict[str, str]] = None
    supreme_cache: Dict[str, str] = {}
    appeals_cache: Dict[str, str] = {}
    unresolved_supreme: List[str] = []
    unresolved_appeals: List[str] = []
    rows_considered = 0
    supreme_updates = 0
    appeals_updates = 0

    for idx, row in df.iterrows():
        if idx not in rows_since_date:
            continue

        rows_considered += 1
        supreme_case_number = str(row.get("supreme_case_number", "")).strip()
        appeals_case_number = str(row.get("appeals_case_number", "")).strip()
        source_type = str(row.get("source_type", ""))
        current_supreme_link = str(row.get("supreme_case_link", "")).strip()
        current_appeals_link = str(row.get("appeals_case_link", "")).strip()

        if current_supreme_link and not is_island_url(current_supreme_link):
            new_supreme_link = legacy_supreme_link_to_island(current_supreme_link, source_type)
            if not new_supreme_link and "ákvörðun" in source_type.casefold():
                if decision_links is None:
                    decision_links = scraper.build_decision_link_index(
                        since_year=since_date.year,
                        page_limit=decision_page_limit,
                    )
                new_supreme_link = decision_links.get(supreme_case_number, "")
            elif not new_supreme_link:
                if supreme_case_number not in supreme_cache:
                    supreme_cache[supreme_case_number] = scraper.find_island_supreme_verdict_link(supreme_case_number)
                new_supreme_link = supreme_cache[supreme_case_number]

            if new_supreme_link:
                if current_supreme_link != new_supreme_link:
                    df.loc[idx, "supreme_case_link"] = new_supreme_link
                    supreme_updates += 1
            elif has_domain(current_supreme_link, "haestirettur.is"):
                unresolved_supreme.append(supreme_case_number)

        should_resolve_appeals = bool(appeals_case_number) and (
            not current_appeals_link or not is_island_url(current_appeals_link)
        )
        if should_resolve_appeals:
            if appeals_case_number not in appeals_cache:
                appeals_cache[appeals_case_number] = appeals_links.get(appeals_case_number, "") or scraper.find_island_lower_court_link(appeals_case_number)
            new_appeals_link = appeals_cache[appeals_case_number]
            if new_appeals_link:
                if current_appeals_link != new_appeals_link:
                    df.loc[idx, "appeals_case_link"] = new_appeals_link
                    appeals_updates += 1
            elif current_appeals_link and has_domain(current_appeals_link, "landsrettur.is"):
                unresolved_appeals.append(appeals_case_number)

    unresolved_supreme = sorted(set(unresolved_supreme))
    unresolved_appeals = sorted(set(unresolved_appeals))
    logger.info(
        "Link migration checked %s rows from %s onward; updated %s Supreme links and %s Landsréttur links.",
        rows_considered,
        since_date.isoformat(),
        supreme_updates,
        appeals_updates,
    )

    if unresolved_supreme:
        logger.warning("Unresolved Supreme links: %s", ", ".join(unresolved_supreme[:20]))
    if unresolved_appeals:
        logger.warning("Unresolved Landsréttur links: %s", ", ".join(unresolved_appeals[:20]))

    if dry_run:
        logger.info("Dry run requested; leaving files unchanged.")
        return 1 if unresolved_supreme or unresolved_appeals else 0

    manager.write_data(df)
    manager.generate_json_mapping()
    manager.update_timestamp()
    return 1 if unresolved_supreme or unresolved_appeals else 0

def run_scrape(
    scraper: Scraper,
    manager: DataManager,
    full: bool = False,
    max_pages: Optional[int] = None,
    report_path: Path = SCRAPE_REPORT_PATH,
) -> int:
    report = ScrapeReport(mode="full" if full else "incremental", max_pages=max_pages)

    df_existing = manager.load_existing_data()
    known_case_numbers = set(df_existing["supreme_case_number"].dropna().str.strip())
    known_case_numbers.discard("")

    all_data: List[Dict[str, str]] = []

    verdict_rows, verdict_source_ok = scraper.scrape_verdicts(
        known_case_numbers,
        full=full,
        max_pages=max_pages,
        report=report,
    )
    all_data.extend(verdict_rows)
    known_case_numbers.update(row["supreme_case_number"] for row in verdict_rows if row.get("supreme_case_number"))

    decision_rows, decision_source_ok = scraper.scrape_decisions(
        known_case_numbers,
        full=full,
        max_pages=max_pages,
        report=report,
    )
    all_data.extend(decision_rows)

    source_ok = verdict_source_ok or decision_source_ok
    if not source_ok:
        reason = "No source listing pages were fetched successfully; leaving generated artifacts untouched."
        report.mark_failed(reason)
        report.log_summary()
        write_scrape_report(report, report_path)
        logger.error(reason)
        return 1

    suspicious_reason = suspicious_run_reason(report, full=full)
    if suspicious_reason:
        report.mark_failed(suspicious_reason)
        report.log_summary()
        write_scrape_report(report, report_path)
        logger.error(f"Suspicious scrape run; leaving generated artifacts untouched: {suspicious_reason}")
        return 1

    linked_rows = [row for row in all_data if row.get("appeals_case_number")]
    logger.info(
        f"Parsed {len(all_data)} valid Supreme Court pages; "
        f"{len(linked_rows)} include Landsréttur case numbers."
    )
    report.csv_rows_added = manager.save_csv(all_data)
    report.mapping_links_generated = manager.generate_json_mapping()
    manager.update_timestamp()
    report.artifacts_refreshed = True
    report.log_summary()
    write_scrape_report(report, report_path)
    return 0

def main() -> int:
    args = parse_args()
    scraper = Scraper()
    manager = DataManager()
    if args.migrate_island_links:
        return run_link_migration(
            scraper,
            manager,
            since_date=date.fromisoformat(args.since_date),
            decision_page_limit=args.decision_page_limit,
            dry_run=args.dry_run,
        )
    return run_scrape(scraper, manager, full=args.full, max_pages=args.max_pages)

if __name__ == "__main__":
    raise SystemExit(main())
