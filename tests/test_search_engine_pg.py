from order_search.db import Tables
from order_search.search.engine import SearchEngine


class RecordingReader:
    def __init__(self, one=None, all_rows=None):
        self._one = one
        self._all = all_rows or []
        self.seen = []
        self.seen_params = []

    def one(self, sql, params=()):
        self.seen.append(sql)
        self.seen_params.append(params)
        return self._one

    def all(self, sql, params=()):
        self.seen.append(sql)
        self.seen_params.append(params)
        return self._all


def make(reader):
    return SearchEngine(reader, Tables.from_schemas("t_item", "t_sales"))


def test_the_engine_no_longer_mentions_fts():
    reader = RecordingReader(one=None, all_rows=[])
    make(reader).search("น้ำดื่มสิงห์ 600 มล. x 12")
    assert not any("MATCH" in sql for sql in reader.seen)


def test_a_short_query_falls_back_to_a_prefix_scan():
    reader = RecordingReader(one=None, all_rows=[])
    make(reader).search("น้ำ")
    assert any("LIKE %s" in sql and "ESCAPE" in sql for sql in reader.seen)


def test_the_trigram_query_passes_pattern_prefix_limit():
    reader = RecordingReader(
        one=None, all_rows=[{"id": 3}, {"id": 4}]
    )
    engine = make(reader)
    found = engine._product_ids_by_trigram("น้ำดื่ม", "name_norm", limit=50)
    trigram_sql = reader.seen[-1]
    trigram_params = reader.seen_params[-1]
    assert found == [3, 4]
    assert "LIKE %s ESCAPE" in trigram_sql
    assert "LIMIT %s" in trigram_sql
    assert trigram_params == ("%น้ำดื่ม%", "น้ำดื่ม%", 50)


def test_the_trigram_query_prefers_prefix_matches_first():
    reader = RecordingReader(
        one=None, all_rows=[{"id": 9}, {"id": 1}, {"id": 5}]
    )
    engine = make(reader)
    assert engine._product_ids_by_trigram("น้ำ", "name_norm") == [9, 1, 5]


def test_cursor_survives_a_round_trip():
    from order_search.search.engine import _decode_cursor, _encode_cursor

    assert _decode_cursor(_encode_cursor(40)) == 40
    assert _decode_cursor("not-a-cursor") == 0
    assert _decode_cursor(None) == 0


def test_an_empty_query_returns_an_empty_payload():
    payload = make(RecordingReader()).search("   ")
    assert payload["mode"] == "none"
    assert payload["customers"] == []
    assert payload["products"] == []