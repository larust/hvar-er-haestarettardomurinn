from bs4 import BeautifulSoup

from get_new_verdicts import (
    decide_status,
    extract_verdict_date,
    first_appeals_link,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_extract_verdict_date_icelandic_month():
    text = "Úrskurður kveðinn upp 15. maí 2025 að morgni dags."
    assert extract_verdict_date(text) == "15. maí 2025"


def test_extract_verdict_date_missing_returns_empty():
    assert extract_verdict_date("Engin dagsetning hér") == ""


def test_decide_status_reads_lykilord_list():
    html = """
    <main>
      <h2>Lykilorð</h2>
      <ul><li>Samþykkt nefndarinnar</li></ul>
    </main>
    """
    soup = _soup(html)
    assert decide_status(soup, soup.get_text(" ", strip=True)) == "Samþykkt"


def test_decide_status_falls_back_to_page_text():
    html = "<main><p>Umsókninni var hafnað samkvæmt ákvæði.</p></main>"
    soup = _soup(html)
    assert decide_status(soup, soup.get_text(" ", strip=True)) == "Hafnað"


def test_first_appeals_link_extracts_expected_url():
    html = """
      <div>
        <a href="https://landsrettur.is/domar-og-urskurdir/domur-urskurdur/some-case">
          Sjá Landsrétt
        </a>
      </div>
    """
    assert (
        first_appeals_link(html)
        == "https://landsrettur.is/domar-og-urskurdir/domur-urskurdur/some-case"
    )
