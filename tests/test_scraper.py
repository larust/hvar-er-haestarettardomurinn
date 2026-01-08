import pytest
from bs4 import BeautifulSoup
from get_new_verdicts import Scraper, SUPREME_VERDICT_RE, SUPREME_DECISION_RE, APPEALS_NO_RE, DATE_RE

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

    # Supreme Decision
    m = SUPREME_DECISION_RE.search("Nr. 2023-12")
    assert m
    assert m.group(1) == "2023-12"

    # Appeals Number
    m = APPEALS_NO_RE.search("Mál þetta 45/2022")
    assert m
    assert m.group(1) == "45"
    assert m.group(2) == "2022"
