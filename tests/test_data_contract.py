import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "allir_domar_og_akvardanir.csv"
MAPPING_PATH = ROOT / "mapping.json"

EXPECTED_COLUMNS = [
    "supreme_case_number",
    "supreme_case_link",
    "appeals_case_number",
    "appeals_case_link",
    "source_type",
    "verdict_date",
    "decision_status",
]
FRONTEND_FIELDS = [
    "supreme_case_number",
    "supreme_case_link",
    "appeals_case_link",
    "source_type",
    "verdict_date",
    "decision_status",
]
KNOWN_LEGACY_BLANK_APPEALS_LINKS = {"2019-271", "2020-118", "24/2019", "2020-156"}
LANDSRETTUR_CASE_RE = re.compile(r"^\d{1,4}/(?:19|20)\d{2}$")
ISLAND_VERDICT_RE = re.compile(r"^/domar/s-[A-Za-z0-9-]+/?$")
ISLAND_DECISION_RE = re.compile(r"^/s/haestirettur/akvardanir/[A-Fa-f0-9-]{36}/?$")


def load_csv_rows():
    with CSV_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames or [], list(reader)


def iter_mapping_records(mapping):
    for appeals_case_number, value in mapping.items():
        records = value if isinstance(value, list) else [value]
        for record in records:
            yield appeals_case_number, record


def assert_supported_supreme_url(url):
    parsed = urlparse(url)
    assert parsed.scheme in {"http", "https"}
    assert parsed.netloc in {"island.is", "www.haestirettur.is", "haestirettur.is"}

    if parsed.netloc == "island.is":
        assert ISLAND_VERDICT_RE.match(parsed.path) or ISLAND_DECISION_RE.match(parsed.path)


def test_csv_schema_and_unique_supreme_case_numbers():
    columns, rows = load_csv_rows()

    assert columns == EXPECTED_COLUMNS
    assert rows

    supreme_case_numbers = [row["supreme_case_number"].strip() for row in rows]
    assert all(supreme_case_numbers)
    assert len(supreme_case_numbers) == len(set(supreme_case_numbers))


def test_csv_rows_keep_required_links_and_supported_url_shapes():
    _, rows = load_csv_rows()

    for row in rows:
        if row["appeals_case_number"].strip():
            if row["appeals_case_link"].strip():
                appeals_host = urlparse(row["appeals_case_link"]).netloc
                assert appeals_host == "landsrettur.is" or appeals_host.endswith(".landsrettur.is")
            else:
                assert row["supreme_case_number"] in KNOWN_LEGACY_BLANK_APPEALS_LINKS

        assert_supported_supreme_url(row["supreme_case_link"])


def test_mapping_shape_and_frontend_fields():
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))

    assert mapping

    for appeals_case_number, value in mapping.items():
        assert appeals_case_number
        assert LANDSRETTUR_CASE_RE.match(appeals_case_number)
        assert isinstance(value, (dict, list))

        if isinstance(value, list):
            assert value
            assert all(isinstance(item, dict) for item in value)
        else:
            assert isinstance(value, dict)

    for _, record in iter_mapping_records(mapping):
        for field in FRONTEND_FIELDS:
            assert field in record

        assert record["supreme_case_number"].strip()
        assert record["supreme_case_link"].strip()
        assert record["source_type"].strip()
        if not record["appeals_case_link"].strip():
            assert record["supreme_case_number"] in KNOWN_LEGACY_BLANK_APPEALS_LINKS
        assert_supported_supreme_url(record["supreme_case_link"])
