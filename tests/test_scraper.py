import json

import pytest
from bs4 import BeautifulSoup
from get_new_verdicts import (
    APPEALS_NO_RE,
    DATE_RE,
    DataManager,
    Scraper,
    SUPREME_DECISION_RE,
    SUPREME_VERDICT_RE,
    run_scrape,
)

@pytest.fixture
def scraper():
    return Scraper()

def test_extract_verdict_date(scraper):
    assert scraper.extract_verdict_date("Dómur uppkveðinn 15. maí 2025") == "15. maí 2025"
    assert scraper.extract_verdict_date("1. janúar 2023 var dagurinn") == "1. janúar 2023"
    assert scraper.extract_verdict_date("No date here") == ""
    assert scraper.extract_verdict_date("") == ""

def test_decide_status_keywords(scraper):
    html = """
    <html>
        <body>
            <h2>Lykilorð</h2>
            <ul>
                <li>Frávísun</li>
                <li>Hafnað</li>
            </ul>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert scraper.decide_status(soup, "") == "Hafnað"

    html_approved = """
    <html>
        <body>
            <h3>Lykilorð</h3>
            <ul>
                <li>Samþykkt</li>
            </ul>
        </body>
    </html>
    """
    soup_approved = BeautifulSoup(html_approved, "html.parser")
    assert scraper.decide_status(soup_approved, "") == "Samþykkt"

def test_decide_status_text_fallback(scraper):
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert scraper.decide_status(soup, "Beiðni um áfrýjunarleyfi var hafnað.") == "Hafnað"
    assert scraper.decide_status(soup, "Fallist var á beiðnini (samþykkt).") == "Samþykkt"
    # "Samþykkt" comes before "Hafnað" (if both somehow present in text differently)
    assert scraper.decide_status(soup, "Samþykkt í dag, ekki hafnað.") == "Samþykkt"

def test_regex_patterns():
    # Supreme Verdict
    m = SUPREME_VERDICT_RE.search("Mál nr. 123/2023")
    assert m
    assert m.group(1) == "123"
    assert m.group(2) == "2023"

    m = SUPREME_VERDICT_RE.search("## Mál nr.37/2025")
    assert m
    assert m.group(1) == "37"
    assert m.group(2) == "2025"

    # Supreme Decision
    m = SUPREME_DECISION_RE.search("Nr. 2023-12")
    assert m
    assert m.group(1) == "2023-12"

    m = SUPREME_DECISION_RE.search("Mál nr.2026-27")
    assert m
    assert m.group(1) == "2026-27"

    # Appeals Number
    m = APPEALS_NO_RE.search("Mál þetta 45/2022")
    assert m
    assert m.group(1) == "45"
    assert m.group(2) == "2022"

def test_extract_listing_links(scraper):
    html = """
    <main>
      <a href="/domar/s-688E1AF4-FCCC-4B6C-A0C5-D3613D701D6D">37/2025 Hæstiréttur</a>
      <a href="/domar">Sjá alla dóma</a>
      <a href="/s/haestirettur/akvardanir/B6876E63-7F67-4945-8C8F-B29E7E3C7E2C">2026-27</a>
      <a href="/s/haestirettur/akvardanir">Ákvarðanir</a>
    </main>
    """

    assert scraper.extract_verdict_links_from_html(html) == [
        ("https://island.is/domar/s-688E1AF4-FCCC-4B6C-A0C5-D3613D701D6D", "37/2025")
    ]
    assert scraper.extract_decision_links_from_html(html) == [
        ("https://island.is/s/haestirettur/akvardanir/B6876E63-7F67-4945-8C8F-B29E7E3C7E2C", "2026-27")
    ]

def test_get_verdict_listing_page_from_graphql(scraper, monkeypatch):
    def fake_fetch_json(url, payload):
        assert payload["variables"]["input"]["page"] == 2
        return {
            "data": {
                "webVerdicts": {
                    "total": 12,
                    "items": [
                        {
                            "id": "s-D9223705-6188-4590-9209-079CB613C5D2",
                            "caseNumber": "14/2026",
                            "court": "Hæstiréttur",
                        },
                        {
                            "id": "s-IGNORED",
                            "caseNumber": "1/2026",
                            "court": "Landsréttur",
                        },
                    ],
                }
            }
        }

    monkeypatch.setattr(scraper, "fetch_json", fake_fetch_json)

    items, total, ok = scraper.get_verdict_listing_page(2)

    assert ok is True
    assert total == 12
    assert items == [
        ("https://island.is/domar/s-D9223705-6188-4590-9209-079CB613C5D2", "14/2026")
    ]

def test_extract_appeals_link_unescapes_landsrettur_url(scraper):
    html = """
    <a href="https://landsrettur.is/domar-og-urskurdir/domur-urskurdur/?id=abc&amp;verdictid=def">
      Úrlausn Landsréttar / Héraðsdóms
    </a>
    """

    assert scraper.extract_appeals_link(html) == (
        "https://landsrettur.is/domar-og-urskurdir/domur-urskurdur/?id=abc&verdictid=def"
    )

def test_parse_supreme_page_new_decision_shape(scraper, monkeypatch):
    decision_url = "https://island.is/s/haestirettur/akvardanir/B6876E63-7F67-4945-8C8F-B29E7E3C7E2C"
    appeals_url = "https://landsrettur.is/domar-og-urskurdir/domur-urskurdur/?id=abc&verdictid=def"
    pages = {
        decision_url: f"""
        <main>
          <h2>Mál nr.2026-27</h2>
          <p>Miðvikudagurinn 15. apríl 2026</p>
          <h3>Lykilorð</h3>
          <ul><li>Hafnað</li></ul>
          <a href="{appeals_url}">Úrlausn Landsréttar / Héraðsdóms</a>
        </main>
        """,
        appeals_url: "Mál nr. 102/2025",
    }

    monkeypatch.setattr(scraper, "fetch_page", lambda url: pages[url])

    data = scraper.parse_supreme_page(decision_url, "ákvörðun")

    assert data["supreme_case_number"] == "2026-27"
    assert data["verdict_date"] == "15. apríl 2026"
    assert data["decision_status"] == "Hafnað"
    assert data["appeals_case_number"] == "102/2025"
    assert data["appeals_case_link"] == appeals_url

def test_scrape_decisions_stops_after_known_cases(scraper, monkeypatch):
    new_url = "https://island.is/s/haestirettur/akvardanir/11111111-1111-4111-8111-111111111111"
    known_url = "https://island.is/s/haestirettur/akvardanir/22222222-2222-4222-8222-222222222222"
    older_url = "https://island.is/s/haestirettur/akvardanir/33333333-3333-4333-8333-333333333333"
    pages = {
        1: [(new_url, "2026-31"), (known_url, "2026-30")],
        2: [(older_url, "2026-29")],
    }

    monkeypatch.setattr(scraper, "get_decision_listing_page", lambda page: (pages.get(page, []), page in pages))

    parsed_urls = []

    def fake_parse(url, source_type):
        parsed_urls.append(url)
        return {
            "supreme_case_number": "2026-31",
            "supreme_case_link": url,
            "appeals_case_number": "1/2026",
            "appeals_case_link": "https://landsrettur.is/domar-og-urskurdir/domur-urskurdur/?id=abc",
            "source_type": source_type,
            "verdict_date": "1. apríl 2026",
            "decision_status": "Samþykkt",
        }

    monkeypatch.setattr(scraper, "parse_supreme_page", fake_parse)

    rows, ok = scraper.scrape_decisions({"2026-30", "2026-29"}, full=False)

    assert ok is True
    assert parsed_urls == [new_url]
    assert [row["supreme_case_number"] for row in rows] == ["2026-31"]

def test_run_scrape_blocks_suspicious_detail_parse_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = DataManager(csv_path="allir_domar_og_akvardanir.csv", json_path="mapping.json")
    report_path = tmp_path / "scrape_report.json"
    (tmp_path / "allir_domar_og_akvardanir.csv").write_text(",".join(manager.columns) + "\n", encoding="utf-8")
    (tmp_path / "mapping.json").write_text('{"unchanged": true}\n', encoding="utf-8")
    (tmp_path / "last_updated.txt").write_text("Síðast uppfært áður.\n", encoding="utf-8")

    class BrokenScraper:
        def scrape_verdicts(self, known_case_numbers, full=False, max_pages=None, report=None):
            stats = report.source("verdicts")
            stats.listing_pages_fetched += 1
            stats.listing_items_discovered += 1
            stats.detail_pages_attempted += 1
            stats.detail_pages_without_case_number += 1
            report.add_skipped_case(
                "verdicts",
                {"supreme_case_link": "https://island.is/domar/s-broken", "source_type": "dóm"},
                "missing_supreme_case_number",
            )
            return [], True

        def scrape_decisions(self, known_case_numbers, full=False, max_pages=None, report=None):
            return [], False

    exit_code = run_scrape(BrokenScraper(), manager, max_pages=1, report_path=report_path)

    assert exit_code == 1
    assert (tmp_path / "mapping.json").read_text(encoding="utf-8") == '{"unchanged": true}\n'
    assert (tmp_path / "last_updated.txt").read_text(encoding="utf-8") == "Síðast uppfært áður.\n"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["failed"] is True
    assert "none produced" in report["failure_reason"]
    assert report["artifacts_refreshed"] is False
    assert report["totals"]["detail_pages_attempted"] == 1

def test_run_scrape_allows_incremental_no_change_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = DataManager(csv_path="allir_domar_og_akvardanir.csv", json_path="mapping.json")
    report_path = tmp_path / "scrape_report.json"
    csv_text = "\n".join([
        ",".join(manager.columns),
        "1/2026,https://island.is/domar/s-known,2/2025,https://landsrettur.is/domur,dóm,1. janúar 2026,",
        "",
    ])
    (tmp_path / "allir_domar_og_akvardanir.csv").write_text(csv_text, encoding="utf-8")

    class NoChangeScraper:
        def scrape_verdicts(self, known_case_numbers, full=False, max_pages=None, report=None):
            stats = report.source("verdicts")
            stats.listing_pages_fetched += 1
            stats.listing_items_discovered += 1
            stats.known_items_skipped += 1
            assert "1/2026" in known_case_numbers
            return [], True

        def scrape_decisions(self, known_case_numbers, full=False, max_pages=None, report=None):
            return [], False

    exit_code = run_scrape(NoChangeScraper(), manager, max_pages=1, report_path=report_path)

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["failed"] is False
    assert report["artifacts_refreshed"] is True
    assert report["csv_rows_added"] == 0
    assert report["sources"]["verdicts"]["known_items_skipped"] == 1

    mapping = json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))
    assert mapping["2/2025"]["supreme_case_number"] == "1/2026"
