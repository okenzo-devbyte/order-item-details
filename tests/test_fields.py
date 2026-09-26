from datetime import date

from order_search.ingest.fields import (
    clean_str,
    parse_date_range,
    split_barcodes,
    to_int,
)


class TestCleanStr:
    def test_strips_surrounding_whitespace(self):
        assert clean_str("  abc  ") == "abc"

    def test_none_becomes_empty(self):
        assert clean_str(None) == ""

    def test_numbers_become_strings(self):
        assert clean_str(125) == "125"


class TestSplitBarcodes:
    def test_single_barcode(self):
        assert split_barcodes("8850250001234") == ["8850250001234"]

    def test_real_multi_barcode_cell(self):
        # this exact value exists in the source file
        assert split_barcodes("21464546 || 2500001464545") == [
            "21464546",
            "2500001464545",
        ]

    def test_strips_whitespace_around_each_part(self):
        assert split_barcodes("111 ||222") == ["111", "222"]

    def test_collapses_duplicates_inside_one_cell(self):
        assert split_barcodes("111 || 111") == ["111"]

    def test_empty_and_none_give_empty_list(self):
        assert split_barcodes("") == []
        assert split_barcodes(None) == []
        assert split_barcodes("   ") == []

    def test_preserves_order(self):
        assert split_barcodes("333 || 111 || 222") == ["333", "111", "222"]


class TestParseDateRange:
    def test_real_value_from_source_file(self):
        start, end = parse_date_range("26-Sep-2026 - 26-Sep-2026")
        assert start == date(2026, 9, 26)
        assert end == date(2026, 9, 26)

    def test_real_multi_day_range(self):
        start, end = parse_date_range("01-Sep-2026 - 05-Sep-2026")
        assert start == date(2026, 9, 1)
        assert end == date(2026, 9, 5)

    def test_single_date_is_used_for_both_ends(self):
        start, end = parse_date_range("26-Sep-2026")
        assert start == end == date(2026, 9, 26)

    def test_reversed_range_is_swapped_not_rejected(self):
        start, end = parse_date_range("05-Sep-2026 - 01-Sep-2026")
        assert start == date(2026, 9, 1)
        assert end == date(2026, 9, 5)

    def test_empty_gives_none_pair(self):
        assert parse_date_range("") == (None, None)
        assert parse_date_range(None) == (None, None)
        assert parse_date_range("   ") == (None, None)

    def test_unparseable_gives_none_pair(self):
        assert parse_date_range("not a date") == (None, None)
        assert parse_date_range("2026-09-26") == (None, None)

    def test_too_many_parts_gives_none_pair(self):
        assert parse_date_range("01-Sep-2026 - 02-Sep-2026 - 03-Sep-2026") == (
            None,
            None,
        )


class TestToInt:
    def test_parses_int(self):
        assert to_int(8) == 8

    def test_parses_numeric_string(self):
        assert to_int("312") == 312

    def test_parses_float_string(self):
        assert to_int("312.0") == 312

    def test_negative(self):
        assert to_int(-5) == -5

    def test_blank_gives_none(self):
        assert to_int("") is None
        assert to_int(None) is None
        assert to_int("  ") is None

    def test_non_numeric_gives_none(self):
        assert to_int("abc") is None
