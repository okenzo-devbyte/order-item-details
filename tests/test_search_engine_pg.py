from order_search.db import Tables
from order_search.search.engine import SearchEngine


class RecordingReader:
    def __init__(self, one=None, all_rows=None):
        self._one = one
        self._all = all_rows or []
        self.seen = []

    def one(self, sql, params=()):
        self.seen.append(sql)
        return self._one

    def all(self, sql, params=()):
        self.seen.append(sql)
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