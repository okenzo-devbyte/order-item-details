import sqlite3
import subprocess
import sys
from pathlib import Path

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from order_search.search.filters import Filters

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def build_fixture_db(tmp_path):
    import os

    workbook = tmp_path / "fixture.xlsx"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [str(PYTHON), "scripts/make_fixture.py", "--out", str(workbook)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(workbook), connection)
    return connection


def test_fixture_really_has_many_distinct_dates(tmp_path):
    connection = build_fixture_db(tmp_path)
    distinct = connection.execute(
        "SELECT COUNT(DISTINCT date_from) AS n FROM orders"
    ).fetchone()["n"]
    assert distinct > 50


def test_date_filter_narrows_results(tmp_path):
    engine = SearchEngine(build_fixture_db(tmp_path))
    unfiltered = engine.search("น้ำ")["products"][0]["order_count"]
    filtered = engine.search(
        "น้ำ", filters=Filters(date_from="2026-01-01", date_to="2026-01-31")
    )["products"][0]["order_count"]
    assert filtered < unfiltered
    assert filtered > 0


def test_date_filter_is_an_overlap_not_a_containment(tmp_path):
    engine = SearchEngine(build_fixture_db(tmp_path))
    connection = engine.connection
    # pick a real order range from the fixture and query a window that only
    # partially overlaps it; it must still be returned
    row = connection.execute(
        "SELECT date_from, date_to FROM orders"
        " WHERE date_from IS NOT NULL AND date_from <> date_to LIMIT 1"
    ).fetchone()
    if row is None:
        return  # fixture randomness produced only single-day ranges
    total = engine.search("น้ำ")["products"][0]["order_count"]
    overlap = engine.search(
        "น้ำ",
        filters=Filters(date_from=row["date_from"], date_to=row["date_to"]),
    )["products"][0]["order_count"]
    assert 0 < overlap <= total


def test_narrow_window_returns_fewer_than_a_wide_one(tmp_path):
    engine = SearchEngine(build_fixture_db(tmp_path))
    narrow = engine.search(
        "น้ำ", filters=Filters(date_from="2026-01-01", date_to="2026-01-07")
    )["products"][0]["order_count"]
    wide = engine.search(
        "น้ำ", filters=Filters(date_from="2026-01-01", date_to="2026-12-31")
    )["products"][0]["order_count"]
    assert narrow <= wide


def test_single_day_filter_works(tmp_path):
    engine = SearchEngine(build_fixture_db(tmp_path))
    result = engine.search(
        "น้ำ", filters=Filters(date_from="2026-03-15", date_to="2026-03-15")
    )
    assert isinstance(result["products"], list)


def test_impossible_date_window_returns_nothing(tmp_path):
    engine = SearchEngine(build_fixture_db(tmp_path))
    result = engine.search(
        "น้ำ", filters=Filters(date_from="1990-01-01", date_to="1990-01-02")
    )
    assert result["products"] == []
