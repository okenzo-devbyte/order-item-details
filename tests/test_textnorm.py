import unicodedata

import pytest

from order_search.textnorm import (
    digits_only,
    fold_heavy,
    fold_light,
    is_barcode_like,
    norm,
    parse_pack_size,
)

WATER = "น้ำดื่มสิงห์ 600 มล. x 12"


class TestNorm:
    def test_removes_spaces_and_punctuation(self):
        assert norm(WATER) == "น้ำดื่มสิงห์600มลx12"

    def test_keeps_combining_marks(self):
        # norm() must NOT strip Thai tone marks. FTS5 trigram counts characters,
        # so a 3-character query such as 'น้ำ' collapses below the 3-character
        # minimum if the marks are removed, and the query silently finds nothing.
        assert norm("น้ำ") == "น้ำ"
        assert len(norm("น้ำ")) == 3

    def test_trigram_minimum_length_survives_normalisation(self):
        assert len(norm("โค้ก")) >= 3
        assert len(norm("น้ำ")) >= 3

    def test_case_insensitive(self):
        assert norm("ABC") == norm("abc") == "abc"

    def test_latin_digits_survive(self):
        assert norm("3 in 1") == "3in1"

    def test_none_and_empty_become_empty_string(self):
        assert norm(None) == ""
        assert norm("") == ""

    def test_drops_emoji_and_symbols(self):
        assert norm("a★b") == "ab"


class TestFoldLight:
    def test_removes_thanthakhat(self):
        assert fold_light("สิงห์") == "สิงห"

    def test_removes_tone_marks(self):
        assert fold_light("น้ำ") == "นำ"
        assert fold_light("ดื่ม") == "ดืม"
        assert fold_light("ข้าว") == "ขาว"

    def test_keeps_vowels(self):
        # light fold exists precisely so that distinct vowels stay distinct.
        assert "า" in fold_light("กาแฟ")
        assert "แ" in fold_light("กาแฟ")

    def test_matches_user_who_omits_thanthakhat(self):
        assert fold_light("สิงห์") == fold_light("สิงห")

    def test_matches_user_who_omits_tone_mark(self):
        assert fold_light("ข้าวหอมมะลิ") == fold_light("ขาวหอมมะลิ")

    def test_does_not_collapse_different_words(self):
        # over-folding regression guard
        assert fold_light("ปลา") != fold_light("ป่า")

    def test_none_and_empty(self):
        assert fold_light(None) == ""
        assert fold_light("") == ""


class TestFoldHeavy:
    def test_removes_every_non_spacing_mark(self):
        assert fold_heavy("สิงห์") == "สงห"
        assert fold_heavy("น้ำดื่ม") == "นาดม"

    def test_uses_category_not_combining_class(self):
        # These six all report a canonical combining class of 0 while being
        # category Mn, which is exactly why combining() must not be used.
        for mark in "\u0E31\u0E34\u0E36\u0E47\u0E4C\u0E4D":
            assert unicodedata.combining(mark) == 0
            assert unicodedata.category(mark) == "Mn"
        assert fold_heavy("กั่น") == "กน"
        assert fold_heavy("เก็บ") == "เกบ"
        assert fold_heavy("ซีอิ๊ว") == "ซอว"
        # 'ช' is a spacing consonant and must survive the fold. Without this
        # case the assertions above would only prove deletion, which any
        # broken over-aggressive implementation would also satisfy.
        assert fold_heavy("เชิญ") == "เชญ"

    def test_matches_wrong_vowel_and_tone(self):
        assert fold_heavy("สิงห์") == fold_heavy("สึงห์")
        assert fold_heavy("น้ำดื่ม") == fold_heavy("นำดม")

    def test_keeps_spacing_vowels(self):
        assert fold_heavy("กาแฟ") == "กาแฟ"

    def test_sara_am_is_split_so_a_plain_vowel_substitution_matches(self):
        # 'ำ' (U+0E33) is a spacing character whose decomposition is a
        # compatibility mapping, so NFD leaves it intact and a user who types
        # 'า' instead would not match. NFKD splits it and the fold absorbs the
        # non-spacing half.
        assert fold_heavy("น้ำดื่ม") == "นาดม"
        assert fold_heavy("นาดื่ม") == fold_heavy("น้ำดื่ม")

    def test_heavy_fold_does_not_merge_the_real_distinct_products(self):
        # Guards the over-fold risk: the pool widener must not collapse
        # genuinely different product names into one key. The same risk
        # applies to the light and base forms, so all three are checked.
        import openpyxl
        from conftest import DATA_FILE

        workbook = openpyxl.load_workbook(DATA_FILE, read_only=True)
        names = {
            row[2]
            for row in workbook["Order Data"].iter_rows(
                min_row=2, values_only=True
            )
        }
        workbook.close()
        # Pin the product count so a workbook change that shrinks the set
        # cannot make this test pass vacuously.
        assert len(names) == 15
        for fold in (norm, fold_light, fold_heavy):
            keys = {fold(name) for name in names}
            assert len(keys) == len(names), fold.__name__

    def test_none_and_empty(self):
        assert fold_heavy(None) == ""
        assert fold_heavy("") == ""


class TestParallelLevels:
    def test_all_three_levels_are_space_free_and_parallel(self):
        for fn in (norm, fold_light, fold_heavy):
            out = fn(WATER)
            assert not any(ch.isspace() for ch in out), fn.__name__
        assert norm(WATER) == "น้ำดื่มสิงห์600มลx12"
        assert fold_light(WATER) == "นำดืมสิงห600มลx12"
        assert fold_heavy(WATER) == "นาดมสงห600มลx12"

    def test_light_and_heavy_are_genuinely_different_levels(self):
        assert fold_light(WATER) != fold_heavy(WATER)
        assert fold_light("กาแฟ") == "กาแฟ"
        assert fold_heavy("กาแฟ") == "กาแฟ"


class TestParsePackSize:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("น้ำดื่มสิงห์ 600 มล. x 12", 12),
            ("ข้าวหอมมะลิ 5 กก. x 4", 4),
            ("กาแฟสำเร็จรูป 3 in 1 17 ก. x 27", 27),
            ("มาม่า บะหมี่กึ่งสำเร็จรูป รสต้มยำกุ้ง 55 ก. x 30", 30),
            ("ช็อกโกแลต 45 ก. x 20", 20),
        ],
    )
    def test_reads_trailing_pack_size(self, name, expected):
        assert parse_pack_size(name) == expected

    def test_returns_none_when_absent(self):
        # real product 'ทิชชู่ม้วน 24 ม้วน' has no trailing 'x N'
        assert parse_pack_size("ทิชชู่ม้วน 24 ม้วน") is None

    def test_ignores_middle_x(self):
        # the 'x' in '3 in 1' style names must not be picked up
        assert parse_pack_size("ครีม xO ช็อก 1 กก.") is None

    def test_handles_none_and_empty(self):
        assert parse_pack_size(None) is None
        assert parse_pack_size("") is None

    @pytest.mark.parametrize(
        "name", ["Vitamin Max12", "Box24", "Detox 30", "Complex9"]
    )
    def test_latin_word_ending_in_x_is_not_a_pack_size(self, name):
        assert parse_pack_size(name) is None

    @pytest.mark.parametrize(
        "name,expected", [("6x12", 12), ("24x6", 6), ("x12", 12)]
    )
    def test_compact_pack_notation_still_parses(self, name, expected):
        assert parse_pack_size(name) == expected


class TestBarcodeHelpers:
    def test_digits_only_strips_separators(self):
        assert digits_only("2146-4546") == "21464546"
        assert digits_only("2146 4546") == "21464546"

    def test_digits_only_keeps_only_digits(self):
        assert digits_only("abc123") == "123"

    def test_digits_only_handles_empty(self):
        assert digits_only(None) == ""
        assert digits_only("") == ""

    @pytest.mark.parametrize("value", ["8850250001234", "21464546", "12345678"])
    def test_recognises_barcodes(self, value):
        assert is_barcode_like(value) is True

    def test_ignores_separators_when_measuring_length(self):
        assert is_barcode_like("8850-250001-234") is True

    @pytest.mark.parametrize("value", ["1234567", "123456789012345", "สิงห์", "", None, "12a45"])
    def test_rejects_non_barcodes(self, value):
        assert is_barcode_like(value) is False

    def test_anything_recognised_as_a_barcode_yields_a_usable_key(self):
        for value in ["8850250001234", "8850-250001-234", "2146 4546", "12345678"]:
            assert is_barcode_like(value) is True
        for value in ["８８５０２５０００１２３４", "٨٨٥٠２٥٠٠٠١٢٣٤", "²" * 8, "⑧" * 8]:
            assert is_barcode_like(value) is False
            assert digits_only(value) == ""

    def test_every_real_barcode_is_ascii_and_within_the_recognised_range(self):
        # The lookup column holds single barcodes, so the source cells must be
        # split on '||' before storage. This splits inline rather than reusing
        # split_barcodes(), which arrives with the ingest module in a later
        # task; that duplication is deliberate, not an oversight.
        import openpyxl

        from conftest import DATA_FILE

        workbook = openpyxl.load_workbook(DATA_FILE, read_only=True)
        raw = {
            row[7]
            for row in workbook["Order Data"].iter_rows(
                min_row=2, values_only=True
            )
        }
        workbook.close()

        barcodes = set()
        for cell in raw:
            for part in str(cell).split("||"):
                part = part.strip()
                if part:
                    barcodes.add(part)

        assert len(barcodes) == 127
        for barcode in barcodes:
            assert barcode.isascii() and barcode.isdigit(), barcode
            assert is_barcode_like(barcode) is True, barcode
