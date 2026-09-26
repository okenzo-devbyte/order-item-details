# Order Search Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested data-import pipeline and a fast Thai-language search engine that answers "what has this customer bought?" and "who bought this product?" from the order Excel file.

**Architecture:** A single Python package `order_search` with two halves that do not depend on each other: `ingest/` turns the Excel file into a normalized SQLite database, and `search/` answers queries against that database. All search-relevant text is pre-normalized into three columns at import time (base form, light fold, heavy fold) so queries never pay normalization cost at runtime. No web server, no auth, no database server — this is the core that Plan 2 wraps in an API.

**Tech Stack:** Python 3.14, SQLite 3.50 with FTS5 `trigram` tokenizer, `openpyxl` 3.1.5, `rapidfuzz` 3.14.6, `pytest` 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-26-order-search-design.md`

---

## Errata — corrections found during execution

This plan is a living document. These deviations were found by executing it and are already applied below; they are listed here so a reader knows what changed and why.

| Where | What was wrong | Correction |
|-------|----------------|------------|
| Task 1 | No `.gitignore`, so `git add -A` would have committed the whole `.venv` | `.gitignore` added in the scaffold commit; it excludes `.venv/`, `build/`, `*.db`, `__pycache__/` and `.pytest_cache/` |
| Task 2 | `fold_light`/`fold_heavy` dropped only marks, leaving spaces and punctuation, so they were not parallel to `norm` and no normalized query could ever match them | all three levels now filter Unicode category `L/N/M`, via one shared `_letters_n_marks` helper |
| Task 2 | `fold_heavy` used NFD, so `ำ` (U+0E33, a spacing char with a *compatibility* decomposition) survived and a user typing `า` for `ำ` did not match | `fold_heavy` uses NFKD; verified `fold_heavy('น้ำดื่ม') == 'นาดม'` with zero new collisions across the 15 real products |
| Task 2 | `is_barcode_like` used `str.isdigit()`, which is true for 878 non-ASCII code points that `digits_only` discards, so such a query was classified as a barcode and then silently looked up nothing | the check now also requires `isascii()` |
| Task 2 | `_PACK_RE` had no left boundary and Unicode-aware `\d`, so `'Box24'` → 24 and `'packs ８９ x 12'` → 12 | `r"(?<![A-Za-z])x\s*([0-9]+)\s*$"` |
| Task 6 | `name_fold_light` and `name_fold_heavy` were both asserted as `นาดมสงห600มลx12`; the two levels must differ | light is `นำดืมสิงห600มลx12`, heavy is `นาดมสงห600มลx12` |
| Task 10 | `_product_ids_by_fts` passed a `norm()`-transformed query at the `name_fold_light` column, which returns zero rows because a mark-carrying query is not a substring of a tone-stripped column | each layer now transforms the query with the same function that built its column, the `MATCH` is scoped to that column, and the length guard is per column because light-folding can shorten a 3-character query to 2 |
| Task 10 | `name_fold_light` was asserted identical to `name_fold_heavy` in the README table | corrected, with the pairing rule stated |
| Task 3 | `to_int` raised `OverflowError` on `'inf'`/`'1e400'`, and returned ints too large to bind to a SQLite INTEGER column, defeating its "degrade to `None`" contract | bound to SQLite's signed 64-bit range; also restricted to plain decimal or integer-valued decimal text, so `312.9`, `1e3`, `1_000` and non-ASCII digits now return `None` instead of a plausible but wrong number |
| Task 4 | `is_blank` compared `str(value).strip()`, so `Bar_Code` — which is a **list** from `split_barcodes` — was never blank: `str([])` is `"[]"`, not `""`. `test_counts_rows_without_barcode` could not pass | `is_blank` also treats an empty list, tuple, set or dict as blank. `0` and `False` are correctly still non-blank |

Test count note: Task 2's suite is 53 tests, not the 44 stated in the original task text. Task 3's is 43, not 26.

---

## Scope of this plan

This plan covers spec sections 2, 4, 5 and the data half of 9. It produces a working, tested search engine that can be run from the command line.

**Deferred to Plan 2 (web, security and mobile):** spec sections 3, 6, 7, 8 — FastAPI service, AES-256-GCM snapshot encryption, JWT login, RBAC, audit log, rate limiting, PWA frontend, Docker, deployment.

**Why split:** the search core has zero security surface, so it can be built and proven with plain `pytest` and no running server. Plan 2 adds the parts that need a live HTTP process to test.

---

## File structure

All paths are relative to `D:\Project_AI\order-item-details`, which is the project root. The sample workbook sits directly in that root, and the Python package sits in `src/` beneath it.

```
├─ requirements.txt                  pinned dependencies
├─ pyproject.toml                    pytest config + package path
├─ src/order_search/
│  ├─ __init__.py                    empty package marker
│  ├─ textnorm.py                    norm / fold_light / fold_heavy / pack size
│  ├─ ingest/
│  │  ├─ __init__.py
│  │  ├─ fields.py                   source-format parsing (barcodes, date range, ints)
│  │  ├─ excel_reader.py             xlsx -> list[dict]
│  │  ├─ validate.py                 row rules + import report
│  │  ├─ schema.sql                  DDL
│  │  └─ build.py                    rows -> sqlite
│  └─ search/
│     ├─ __init__.py
│     ├─ filters.py                  Filters dataclass + order filter SQL
│     ├─ detect.py                   intention detection
│     ├─ fuzzy.py                    rapidfuzz customer and product matching
│     └─ engine.py                   SearchEngine.search()
├─ scripts/
│  ├─ import_excel.py                CLI: xlsx -> sqlite
│  ├─ query_cli.py                   CLI: run a search from the terminal
│  └─ make_fixture.py                synthetic xlsx with varied dates
└─ tests/
   ├─ conftest.py                    shared fixtures (built database)
   ├─ test_textnorm.py
   ├─ test_fields.py
   ├─ test_validate.py
   ├─ test_build.py
   ├─ test_detect.py
   ├─ test_filters.py
   ├─ test_engine_barcode.py
   ├─ test_engine_customer.py
   ├─ test_engine_product.py
   ├─ test_fuzzy.py
   └─ test_perf.py
```

**Responsibility of each file, one sentence each:**

- `textnorm.py` — every text-normalization rule, and nothing else. No database, no I/O.
- `ingest/fields.py` — turns raw Excel cell values into typed Python values. Knows the source file's formats, nothing about the database.
- `ingest/excel_reader.py` — opens the workbook, yields row dicts keyed by header name.
- `ingest/validate.py` — decides which rows are usable and produces the import report.
- `ingest/schema.sql` — the database shape, in one reviewable file.
- `ingest/build.py` — writes rows into the database and normalizes text on the way in.
- `search/filters.py` — the `Filters` value object and the one function that turns filters into SQL. Single source of truth for spec 4.1.1 semantics.
- `search/detect.py` — decides whether a query is a barcode, a customer, a product, or both.
- `search/fuzzy.py` — all rapidfuzz calls, isolated so the scorer choice is testable on its own.
- `search/engine.py` — composes the four search layers and shapes the response.

---

## Verified facts this plan depends on

Every item below was measured against the real data file and the installed libraries, not assumed. Do not "fix" these — they are the reason several tasks look the way they do.

| Fact | Value |
|------|-------|
| Rows in `Order Data` | 1000 |
| Distinct products / customers / stores | 15 / 20 / 15 |
| Distinct `Dept` / `Class` / `Subclass` | 9 / 14 / 15 |
| `Bar_Code` cells containing `\|\|` | 148 |
| Distinct barcode strings before split | 139 |
| Distinct barcodes after split on `\|\|` | **127** |
| Example multi-barcode cell | `21464546 \|\| 2500001464545` |
| `น้ำดื่มสิงห์ 600 มล. x 12` | 86 order lines, all 20 customers, `สุรชัย` 6 times, `เอกชัย` 9 times |
| Products containing `น้ำ` | 4 of 15 |
| `สุรชัย` | 65 order lines, 15 distinct products, 14 stores, all 4 VIP tiers |
| Barcode `8850250001234` | belongs to `น้ำดื่มสิงห์ 600 มล. x 12` |
| Customer with fewest orders | `วราภรณ์`, 32 |
| Product with no trailing `x N` | `ทิชชู่ม้วน 24 ม้วน` → `pack_size` must be `None` |
| Every `Original Expected Date` value | `26-Sep-2026 - 26-Sep-2026` (one single date for all 1000 rows) |
| Distinct (customer, product) pairs | 292 |

Library behaviours confirmed by running them:

| Fact | Consequence |
|------|-------------|
| `tokenize='trigram'` matches `MATCH 'น้ำ'` and `MATCH 'น้ำดื่ม'` | trigram is the correct tokenizer |
| default `unicode61` returns 0 rows for `MATCH 'สิงห์'` | unicode61 is unusable for Thai |
| trigram needs **3 or more** characters | shorter queries fall back to `LIKE 'q%'` |
| `unicodedata.combining('ิ')` returns `0` although category is `Mn` | never use `combining()` to strip Thai marks; use `category(ch) == 'Mn'` |
| `fuzz.ratio('สิงห์', 'น้ำดื่มสิงห์600มลx12')` scores below 70 | use `WRatio` or `partial_ratio`, never `ratio`, for substring queries |
| `process.extract` on a list of tuples scores every choice `0.0` | pass a list of strings and map back |
| `process.extract` returns 3-tuples: `(value, score, index)` for a list, `(value, score, key)` for a dict | destructure accordingly |
| FTS5 `MATCH` needs the query quoted to be treated as a literal phrase | wrap in `"` and double any inner `"` |
| `bm25()` is available on an FTS5 table | usable for relevance ordering |
| `PRAGMA query_only = ON` blocks writes | snapshot connection is genuinely read-only |
| `MAX()` over ISO `YYYY-MM-DD` strings is chronological | safe for "last seen" |
| customer fuzzy cutoff 70: 33/33 typo queries resolve to the intended customer, 0 false positives | non-name queries (`น้ำ`, `น้ำดื่ม`, `โค้ก`, `ทิชชู่`, `ซไบเตอร์`, `zzz`) never reach 70; lowest genuine typo scores 72.7 | 
| raising the customer cutoff to 75/80/85/90/95 drops correct matches from 33 to 32/30/29/21/10 with **no** precision gain | keep 70 |

---

## Task 1: Project scaffold

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `src/order_search/__init__.py`
- Create: `src/order_search/ingest/__init__.py`
- Create: `src/order_search/search/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create the virtual environment and install pinned dependencies**

```powershell
cd D:\Project_AI\order-item-details
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "openpyxl==3.1.5" "rapidfuzz==3.14.6" "pytest==9.1.1"
```

Expected: `Successfully installed ... rapidfuzz-3.14.6 ...` with no errors.

- [ ] **Step 2: Write `requirements.txt`**

```
openpyxl==3.1.5
rapidfuzz==3.14.6
pytest==9.1.1
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "order-search"
version = "0.1.0"
requires-python = ">=3.11"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
```

`pythonpath = ["src"]` is what lets tests import `order_search` without an editable install.

- [ ] **Step 4: Create the three package markers**

```powershell
New-Item -ItemType Directory -Force -Path src\order_search\ingest, src\order_search\search, tests, scripts | Out-Null
```

Create `src/order_search/__init__.py`, `src/order_search/ingest/__init__.py`, `src/order_search/search/__init__.py` — each containing only this line:

```python
```

An empty file. Do not add docstrings or version strings; nothing imports from them yet.

- [ ] **Step 5: Verify pytest can see the package**

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DATA_FILE = ROOT / "sample_order_data_1000_records.xlsx"
```

Run: `.\.venv\Scripts\python.exe -m pytest --collect-only`
Expected: `no tests ran` (exit code 5). That is success — it proves the config loads without error.

- [ ] **Step 6: Initialize git so every later task can commit**

```powershell
git init
git add requirements.txt pyproject.toml src tests
git commit -m "chore: scaffold project with pinned dependencies"
```

If the user does not want git, skip this step and every later commit step; the work itself is unaffected.

---

## Task 2: Text normalization

Every search behaviour depends on this file, and two of its rules were found to be wrong during design verification. Write the tests first.

**Files:**
- Create: `tests/test_textnorm.py`
- Create: `src/order_search/textnorm.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_textnorm.py`:

```python
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
        # unicodedata.combining() returns 0 for these characters, so an
        # implementation using it would leave the string untouched.
        for text in ["สิงห์", "สึงห์", "น้ำดื่ม", "กั่น", "เก็บ"]:
            assert fold_heavy(text) != text

    def test_matches_wrong_vowel_and_tone(self):
        assert fold_heavy("สิงห์") == fold_heavy("สึงห์")
        assert fold_heavy("น้ำดื่ม") == fold_heavy("นำดม")

    def test_keeps_spacing_vowels(self):
        assert fold_heavy("กาแฟ") == "กาแฟ"

    def test_none_and_empty(self):
        assert fold_heavy(None) == ""
        assert fold_heavy("") == ""


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_textnorm.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.textnorm'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/textnorm.py`:

```python
from __future__ import annotations

import re
import unicodedata

_KEEP_PREFIXES = ("L", "N", "M")
_TONE_MARKS = frozenset("\u0E48\u0E49\u0E4A\u0E4B")
_THANTHAKHAT = "\u0E4C"
_NIKHAHIT = "\u0E4D"
_LIGHT_DROP = _TONE_MARKS | {_THANTHAKHAT, _NIKHAHIT}
_PACK_RE = re.compile(r"x\s*(\d+)\s*$")
_DIGITS = frozenset("0123456789")
_BARCODE_SEPARATORS = " -"


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", str(text))


def norm(text: str | None) -> str:
    """Base search form: NFD, keep categories L/N/M, drop whitespace and
    punctuation, lowercase.

    Combining marks (category M) are kept on purpose. FTS5's trigram tokenizer
    works on character counts, so stripping marks would shorten 'น้ำ' from three
    characters to two and the query would silently return nothing.
    """
    if not text:
        return ""
    kept = [
        ch
        for ch in _nfd(text)
        if unicodedata.category(ch)[0] in _KEEP_PREFIXES
    ]
    return "".join(kept).lower()


def fold_light(text: str | None) -> str:
    """Drops Thai tone marks, thanthakhat and nikhahit but keeps vowels.

    This fixes the two most common typing mistakes — omitting thanthakhat and
    omitting a tone mark — without collapsing words that differ only by vowel.
    """
    if not text:
        return ""
    return "".join(ch for ch in _nfd(text) if ch not in _LIGHT_DROP).lower()


def fold_heavy(text: str | None) -> str:
    """Drops every non-spacing mark (category Mn), vowels included.

    Use this only to widen the candidate pool for fuzzy matching, never as the
    final decision: it can merge genuinely different Thai words.
    """
    if not text:
        return ""
    kept = [
        ch for ch in _nfd(text) if unicodedata.category(ch) != "Mn"
    ]
    return "".join(kept).lower()


def parse_pack_size(name: str | None) -> int | None:
    """Reads the trailing 'x 12' of a product name.

    This is the pack size, not the quantity sold. Returns None when absent.
    """
    if not name:
        return None
    match = _PACK_RE.search(str(name).strip())
    return int(match.group(1)) if match else None


def digits_only(text: str | None) -> str:
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ch in _DIGITS)


def is_barcode_like(query: str | None) -> bool:
    """True when the query is 8 to 14 digits, ignoring spaces and dashes."""
    if not query:
        return False
    compact = "".join(
        ch for ch in str(query) if ch not in _BARCODE_SEPARATORS
    )
    return compact.isdigit() and 8 <= len(compact) <= 14
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_textnorm.py`
Expected: PASS, 44 passed

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/textnorm.py tests/test_textnorm.py
git commit -m "feat(textnorm): three-level Thai normalization for search"
```

---

## Task 3: Source field parsing

**Files:**
- Create: `tests/test_fields.py`
- Create: `src/order_search/ingest/fields.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fields.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fields.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.ingest.fields'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/ingest/fields.py`:

```python
from __future__ import annotations

from datetime import date, datetime

BARCODE_SEPARATOR = "||"
DATE_FORMAT = "%d-%b-%Y"
DATE_RANGE_SEPARATOR = " - "


def clean_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def split_barcodes(value: object) -> list[str]:
    """'21464546 || 2500001464545' -> ['21464546', '2500001464545'].

    Order is preserved and repeats inside one cell are collapsed.
    """
    parts = [part.strip() for part in clean_str(value).split(BARCODE_SEPARATOR)]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def parse_date_range(value: object) -> tuple[date | None, date | None]:
    """'26-Sep-2026 - 26-Sep-2026' -> (date(2026, 9, 26), date(2026, 9, 26)).

    Returns (None, None) for empty or unparseable input. A reversed range is
    swapped rather than rejected, because the source system occasionally emits
    the later date first.
    """
    text = clean_str(value)
    if not text:
        return None, None

    parts = [
        part.strip()
        for part in text.split(DATE_RANGE_SEPARATOR)
        if part.strip()
    ]
    if not parts:
        return None, None
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    if len(parts) != 2:
        return None, None

    try:
        start = datetime.strptime(parts[0], DATE_FORMAT).date()
        end = datetime.strptime(parts[1], DATE_FORMAT).date()
    except ValueError:
        return None, None

    if start > end:
        start, end = end, start
    return start, end


def to_int(value: object) -> int | None:
    text = clean_str(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(float(text))
    except ValueError:
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fields.py`
Expected: PASS, 26 passed

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/ingest/fields.py tests/test_fields.py
git commit -m "feat(ingest): parse source barcodes, date ranges and integers"
```

---

## Task 4: Row validation and import report

**Files:**
- Create: `tests/test_validate.py`
- Create: `src/order_search/ingest/validate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_validate.py`:

```python
from order_search.ingest.validate import is_blank, validate_rows


def make_row(**overrides):
    row = {
        "Product Name": "น้ำดื่มสิงห์ 600 มล. x 12",
        "Customer Name": "สุรชัย",
        "Bar_Code": ["8850250001234"],
        "date_from": "2026-09-26",
        "date_to": "2026-09-26",
    }
    row.update(overrides)
    return row


class TestIsBlank:
    def test_blank_values(self):
        assert is_blank(None)
        assert is_blank("")
        assert is_blank("   ")

    def test_non_blank_values(self):
        assert not is_blank("x")
        assert not is_blank(0)


class TestValidateRows:
    def test_keeps_complete_rows(self):
        rows = [make_row(), make_row()]
        usable, skipped, report = validate_rows(rows)
        assert len(usable) == 2
        assert skipped == []
        assert report.rows_read == 2
        assert report.rows_imported == 2
        assert report.rows_skipped == 0

    def test_skips_row_without_product_name(self):
        rows = [make_row(), make_row(**{"Product Name": ""})]
        usable, skipped, report = validate_rows(rows)
        assert len(usable) == 1
        assert report.rows_skipped == 1
        assert report.rows_imported == 1

    def test_skips_row_without_customer_name(self):
        rows = [make_row(**{"Customer Name": None})]
        usable, skipped, _ = validate_rows(rows)
        assert usable == []
        assert len(skipped) == 1

    def test_skipped_positions_are_1_based_sheet_rows(self):
        # position 1 is the header, so the first data row is sheet row 2
        rows = [
            make_row(),
            make_row(**{"Product Name": ""}),
            make_row(),
            make_row(**{"Customer Name": "  "}),
        ]
        _usable, skipped, _report = validate_rows(rows)
        assert skipped == [3, 5]

    def test_counts_rows_without_barcode(self):
        rows = [make_row(**{"Bar_Code": []}), make_row()]
        _usable, _skipped, report = validate_rows(rows)
        assert report.missing_barcode_rows == 1

    def test_counts_rows_with_unparsed_date(self):
        rows = [make_row(date_from=None, date_to=None), make_row()]
        _usable, _skipped, report = validate_rows(rows)
        assert report.unparsed_date_rows == 1

    def test_warning_names_the_offending_column(self):
        rows = [make_row(**{"Product Name": "", "Customer Name": "กิตติ"})]
        _usable, _skipped, report = validate_rows(rows)
        assert any("Product Name" in w for w in report.warnings)

    def test_empty_input(self):
        usable, skipped, report = validate_rows([])
        assert usable == []
        assert skipped == []
        assert report.rows_read == 0
        assert report.rows_imported == 0

    def test_summary_mentions_every_counter(self):
        rows = [make_row(**{"Bar_Code": [], "date_from": None, "date_to": None})]
        _usable, _skipped, report = validate_rows(rows)
        summary = report.summary()
        for label in [
            "rows read",
            "rows imported",
            "rows skipped",
            "products",
            "customers",
            "orders",
            "barcodes",
            "no barcode",
            "bad date",
            "no pack size",
        ]:
            assert label in summary
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_validate.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.ingest.validate'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/ingest/validate.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REQUIRED_TEXT = ("Product Name", "Customer Name")


@dataclass
class ImportReport:
    """Counters produced by an import run. Every number here is asserted in the
    build tests, so a silent data loss cannot pass unnoticed."""

    rows_read: int = 0
    rows_imported: int = 0
    rows_skipped: int = 0
    products: int = 0
    customers: int = 0
    orders: int = 0
    barcodes: int = 0
    missing_barcode_rows: int = 0
    unparsed_date_rows: int = 0
    missing_pack_size_products: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return "\n".join(
            [
                f"rows read      : {self.rows_read}",
                f"rows imported  : {self.rows_imported}",
                f"rows skipped   : {self.rows_skipped}",
                f"products       : {self.products}",
                f"customers      : {self.customers}",
                f"orders         : {self.orders}",
                f"barcodes       : {self.barcodes}",
                f"no barcode     : {self.missing_barcode_rows}",
                f"bad date       : {self.unparsed_date_rows}",
                f"no pack size   : {self.missing_pack_size_products}",
            ]
        )


def is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def validate_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int], ImportReport]:
    """Splits rows into (usable, skipped_sheet_row_numbers, report).

    Row numbers are 1-based positions in the worksheet counting the header as
    row 1, so a reported number can be looked up directly in Excel.
    """
    report = ImportReport(rows_read=len(rows))
    usable: list[dict[str, Any]] = []
    skipped: list[int] = []

    for position, row in enumerate(rows, start=2):
        missing = [name for name in REQUIRED_TEXT if is_blank(row.get(name))]
        if missing:
            skipped.append(position)
            report.warnings.append(
                f"row {position}: missing {', '.join(missing)}"
            )
            continue
        if is_blank(row.get("Bar_Code")):
            report.missing_barcode_rows += 1
        if row.get("date_from") is None:
            report.unparsed_date_rows += 1
        usable.append(row)

    report.rows_skipped = len(skipped)
    report.rows_imported = len(usable)
    return usable, skipped, report
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_validate.py`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/ingest/validate.py tests/test_validate.py
git commit -m "feat(ingest): validate rows and report import counters"
```

---

## Task 5: Database schema

Write the schema before the code that uses it, so the shape is reviewable on its own.

**Files:**
- Create: `src/order_search/ingest/schema.sql`
- Create: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema.py`:

```python
import sqlite3

from order_search.ingest.build import apply_schema
from order_search.ingest.schema_path import SCHEMA_PATH


def fresh_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def table_names(connection):
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    return {row["name"] for row in rows}


class TestSchema:
    def test_schema_file_exists(self):
        assert SCHEMA_PATH.is_file()

    def test_creates_every_expected_table(self):
        connection = fresh_connection()
        apply_schema(connection)
        names = table_names(connection)
        for expected in [
            "products",
            "product_barcodes",
            "customers",
            "orders",
            "order_items",
            "products_fts",
            "meta",
        ]:
            assert expected in names, f"missing table {expected}"

    def test_products_has_all_search_columns(self):
        connection = fresh_connection()
        apply_schema(connection)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(products)")
        }
        for expected in [
            "id",
            "name",
            "name_norm",
            "name_fold_light",
            "name_fold_heavy",
            "dept",
            "class_code",
            "subclass_code",
            "pack_size",
            "unit",
        ]:
            assert expected in columns, f"missing column products.{expected}"

    def test_unit_defaults_to_null_not_a_guess(self):
        connection = fresh_connection()
        apply_schema(connection)
        connection.execute(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (1, 'x', 'x', 'x', 'x')"
        )
        row = connection.execute("SELECT unit FROM products WHERE id = 1").fetchone()
        assert row["unit"] is None

    def test_fts_table_uses_trigram(self):
        connection = fresh_connection()
        apply_schema(connection)
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'products_fts'"
        ).fetchone()["sql"]
        assert "trigram" in sql

    def test_fts_table_accepts_a_thai_substring_query(self):
        connection = fresh_connection()
        apply_schema(connection)
        connection.execute(
            "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
            " VALUES ('น้ำดื่มสิงห์600มลx12', 'นาดมสงห600มลx12', 1)"
        )
        found = connection.execute(
            "SELECT product_id FROM products_fts WHERE products_fts MATCH ?",
            ('"น้ำดื่ม"',),
        ).fetchall()
        assert [row["product_id"] for row in found] == [1]

    def test_barcode_index_is_not_unique(self):
        # a barcode may legitimately appear against two products in real data,
        # so the index must not be UNIQUE or the import would crash
        connection = fresh_connection()
        apply_schema(connection)
        connection.execute("INSERT INTO products (id, name) VALUES (1, 'a')")
        connection.execute("INSERT INTO products (id, name) VALUES (2, 'b')")
        connection.execute(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (1, '111')"
        )
        connection.execute(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (2, '111')"
        )
        rows = connection.execute(
            "SELECT product_id FROM product_barcodes WHERE barcode = '111'"
            " ORDER BY product_id"
        ).fetchall()
        assert [row["product_id"] for row in rows] == [1, 2]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_schema.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.ingest.build'`

- [ ] **Step 3: Write `src/order_search/ingest/schema_path.py`**

```python
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
```

A separate one-line module so both `build.py` and the tests can reach the path without importing each other.

- [ ] **Step 4: Write `src/order_search/ingest/schema.sql`**

```sql
-- Read-only snapshot of imported order data.
-- Every text column that the search engine touches has a pre-normalized
-- companion column; see src/order_search/textnorm.py for the rules.

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products_fts;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS product_barcodes;
DROP TABLE IF EXISTS meta;

CREATE TABLE products (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    name_norm       TEXT    NOT NULL,
    name_fold_light TEXT    NOT NULL,
    name_fold_heavy TEXT    NOT NULL,
    dept            INTEGER,
    class_code      INTEGER,
    subclass_code   INTEGER,
    pack_size       INTEGER,
    unit            TEXT
);

-- Standalone FTS5 table rather than an external-content table: the build runs
-- once, so there is no sync problem to get wrong. The product text is duplicated
-- but that is irrelevant at this data size.
CREATE VIRTUAL TABLE products_fts USING fts5(
    name_norm,
    name_fold_light,
    product_id UNINDEXED,
    tokenize='trigram'
);

CREATE TABLE product_barcodes (
    product_id INTEGER NOT NULL REFERENCES products(id),
    barcode    TEXT    NOT NULL,
    PRIMARY KEY (product_id, barcode)
) WITHOUT ROWID;

-- Deliberately NOT unique: a barcode may legitimately map to two products in
-- real data, and a UNIQUE index would abort the import.
CREATE INDEX idx_barcodes_barcode ON product_barcodes(barcode);

CREATE TABLE customers (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    name_norm       TEXT    NOT NULL,
    name_fold_light TEXT    NOT NULL,
    name_fold_heavy TEXT    NOT NULL
);

-- Names are the only customer key available in the source file, so two people
-- sharing a name would collide here. Documented as a known limitation.
CREATE UNIQUE INDEX idx_customers_name_norm ON customers(name_norm);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    order_no    TEXT,
    store_code  TEXT,
    customer_id INTEGER REFERENCES customers(id),
    order_type  TEXT,
    date_from   TEXT,
    date_to     TEXT,
    item_remark TEXT,
    vip_remark  TEXT,
    vip_group   TEXT
);

-- vip_group and vip_remark stay on the order line on purpose: in the real data
-- every one of the 20 customers carries several different tiers across their
-- own orders, so they cannot be lifted to the customer level.
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_store    ON orders(store_code);
CREATE INDEX idx_orders_type     ON orders(order_type);
CREATE INDEX idx_orders_vip      ON orders(vip_group);
CREATE INDEX idx_orders_dates    ON orders(date_from, date_to);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER,
    price      REAL,
    PRIMARY KEY (order_id, product_id)
) WITHOUT ROWID;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
) WITHOUT ROWID;
```

- [ ] **Step 5: Write `apply_schema` in `src/order_search/ingest/build.py`**

For now create `build.py` with only this function; Task 6 adds the rest:

```python
from __future__ import annotations

import sqlite3

from .schema_path import SCHEMA_PATH


def apply_schema(connection: sqlite3.Connection) -> None:
    """Drops and recreates every table. Callers pass an autocommit connection
    (isolation_level=None)."""
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_schema.py`
Expected: PASS, 8 passed

- [ ] **Step 7: Commit**

```powershell
git add src/order_search/ingest/schema.sql src/order_search/ingest/schema_path.py src/order_search/ingest/build.py tests/test_schema.py
git commit -m "feat(ingest): SQLite schema with FTS5 trigram index"
```

---

## Task 6: Build the database from rows

**Files:**
- Modify: `src/order_search/ingest/build.py`
- Modify: `tests/test_schema.py` (add a helper) — no, keep helpers in a new file
- Create: `tests/test_build.py`
- Create: `src/order_search/ingest/excel_reader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build.py`:

```python
import sqlite3

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from conftest import DATA_FILE


def fresh_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def scalar(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()[0]


class TestExcelReader:
    def test_reads_one_thousand_rows(self):
        rows = read_order_rows(DATA_FILE)
        assert len(rows) == 1000

    def test_keys_rows_by_header_name(self):
        row = read_order_rows(DATA_FILE)[0]
        for key in [
            "Store Code",
            "Order Type",
            "Product Name",
            "NO.",
            "Dept",
            "Class",
            "Subclass",
            "Bar_Code",
            "Customer Name",
            "Item Remark",
            "VIP Customer Remarks",
            "VIP Customer Groups",
            "Original Expected Date",
        ]:
            assert key in row

    def test_barcode_cell_becomes_a_list(self):
        rows = read_order_rows(DATA_FILE)
        multi = [r for r in rows if len(r["Bar_Code"]) > 1]
        assert len(multi) == 148
        for row in multi:
            assert isinstance(row["Bar_Code"], list)
            assert all(isinstance(b, str) for b in row["Bar_Code"])

    def test_numeric_columns_become_ints(self):
        row = read_order_rows(DATA_FILE)[0]
        assert isinstance(row["Dept"], int)
        assert isinstance(row["Class"], int)
        assert isinstance(row["Subclass"], int)
        assert isinstance(row["NO."], int)

    def test_date_column_becomes_two_dates(self):
        row = read_order_rows(DATA_FILE)[0]
        assert row["date_from"].isoformat() == "2026-09-26"
        assert row["date_to"].isoformat() == "2026-09-26"

    def test_blank_cells_become_empty_string(self):
        rows = read_order_rows(DATA_FILE)
        blanks = [r for r in rows if r["Item Remark"] == ""]
        assert len(blanks) == 386


class TestBuildDatabase:
    def test_counts_match_the_verified_ground_truth(self):
        connection = fresh_connection()
        report = build_database(read_order_rows(DATA_FILE), connection)
        assert report.rows_read == 1000
        assert report.rows_imported == 1000
        assert report.rows_skipped == 0
        assert report.products == 15
        assert report.customers == 20
        assert report.orders == 1000
        assert report.barcodes == 127

    def test_stores_every_order_row(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM orders") == 1000
        assert scalar(connection, "SELECT COUNT(*) FROM order_items") == 1000

    def test_stores_one_row_per_distinct_product_and_customer(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM products") == 15
        assert scalar(connection, "SELECT COUNT(*) FROM customers") == 20

    def test_barcode_count_drops_after_splitting(self):
        # 139 distinct raw strings collapse to 127 distinct barcodes
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM product_barcodes") == 127
        assert scalar(
            connection, "SELECT COUNT(DISTINCT barcode) FROM product_barcodes"
        ) == 127

    def test_known_barcode_maps_to_known_product(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        row = connection.execute(
            "SELECT p.name AS name FROM product_barcodes b"
            " JOIN products p ON p.id = b.product_id"
            " WHERE b.barcode = '8850250001234'"
        ).fetchone()
        assert row["name"] == "น้ำดื่มสิงห์ 600 มล. x 12"

    def test_pack_size_parsed_and_null_when_absent(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        named = connection.execute(
            "SELECT pack_size FROM products WHERE name = ?",
            ("น้ำดื่มสิงห์ 600 มล. x 12",),
        ).fetchone()
        assert named["pack_size"] == 12
        absent = connection.execute(
            "SELECT pack_size, unit FROM products WHERE name = ?",
            ("ทิชชู่ม้วน 24 ม้วน",),
        ).fetchone()
        assert absent["pack_size"] is None

    def test_unit_is_never_guessed(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM products WHERE unit IS NOT NULL") == 0

    def test_normalized_columns_are_populated(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        row = connection.execute(
            "SELECT name_norm, name_fold_light, name_fold_heavy FROM products"
            " WHERE name = ?",
            ("น้ำดื่มสิงห์ 600 มล. x 12",),
        ).fetchone()
        assert row["name_norm"] == "น้ำดื่มสิงห์600มลx12"
        assert row["name_fold_light"] == "นำดืมสิงห600มลx12"
        assert row["name_fold_heavy"] == "นาดมสงห600มลx12"
        # The three levels must be genuinely different views, not copies. An
        # earlier draft of this plan had light and heavy identical here, which
        # would have made the second level pointless.
        assert row["name_fold_light"] != row["name_fold_heavy"]

    def test_vip_tier_stays_on_the_order_line(self):
        # สุรชัย carries all four tiers across their own orders
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        tiers = connection.execute(
            "SELECT DISTINCT vip_group AS v FROM orders o JOIN customers c"
            " ON c.id = o.customer_id WHERE c.name = ? AND o.vip_group <> ''",
            ("สุรชัย",),
        ).fetchall()
        assert sorted(row["v"] for row in tiers) == [
            "Gold",
            "Platinum",
            "VIP",
            "Wholesale VIP",
        ]

    def test_customers_table_has_no_vip_columns(self):
        # guards against someone 'fixing' the data by lifting VIP to customer level
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(customers)")
        }
        assert "vip_group" not in columns
        assert "vip_remark" not in columns

    def test_fts_index_is_searchable(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        found = connection.execute(
            "SELECT product_id FROM products_fts WHERE products_fts MATCH ?",
            ('"น้ำดื่ม"',),
        ).fetchall()
        assert len(found) == 1

    def test_is_idempotent(self):
        rows = read_order_rows(DATA_FILE)
        first = fresh_connection()
        second = fresh_connection()
        report_a = build_database(rows, first)
        report_b = build_database(rows, second)
        assert report_a.summary() == report_b.summary()
        assert scalar(first, "SELECT COUNT(*) FROM orders") == scalar(
            second, "SELECT COUNT(*) FROM orders"
        )
        assert scalar(first, "SELECT COUNT(*) FROM orders") == 1000

    def test_rerunning_on_the_same_connection_replaces_data(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM orders") == 1000
        assert scalar(connection, "SELECT COUNT(*) FROM products") == 15

    def test_skips_incomplete_rows_and_reports_them(self):
        rows = read_order_rows(DATA_FILE)[:5]
        rows[2]["Product Name"] = ""
        connection = fresh_connection()
        report = build_database(rows, connection)
        assert report.rows_read == 5
        assert report.rows_imported == 4
        assert report.rows_skipped == 1
        assert report.warnings

    def test_records_provenance_in_meta(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        stored = dict(
            connection.execute("SELECT key, value FROM meta").fetchall()
        )
        assert stored["rows_imported"] == "1000"
        assert stored["rows_skipped"] == "0"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_build.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.ingest.excel_reader'`

- [ ] **Step 3: Write `src/order_search/ingest/excel_reader.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .fields import parse_date_range, split_barcodes, to_int

SHEET_NAME = "Order Data"
INT_COLUMNS = ("Dept", "Class", "Subclass", "NO.")
DATE_COLUMN = "Original Expected Date"
BARCODE_COLUMN = "Bar_Code"


class SourceFormatError(RuntimeError):
    """Raised when the workbook does not look like the expected export."""


def _dedupe_headers(values: list[Any]) -> list[str]:
    """Excel allows duplicate and blank header cells; give each a usable name."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for index, raw in enumerate(values):
        name = "" if raw is None else str(raw).strip()
        if not name:
            name = f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def read_order_rows(path: str | Path) -> list[dict[str, Any]]:
    """Reads the 'Order Data' worksheet into a list of dicts keyed by header.

    'Bar_Code' becomes a list of barcodes, 'Original Expected Date' becomes
    'date_from' and 'date_to', and the numeric columns become ints.
    """
    workbook = load_workbook(Path(path), read_only=True, data_only=True)
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise SourceFormatError(
                f"worksheet {SHEET_NAME!r} not found;"
                f" found {sorted(workbook.sheetnames)}"
            )
        sheet = workbook[SHEET_NAME]
        stream = sheet.iter_rows(values_only=True)
        try:
            header = next(stream)
        except StopIteration:
            raise SourceFormatError(
                f"worksheet {SHEET_NAME!r} is empty"
            ) from None

        headers = _dedupe_headers(list(header))
        rows: list[dict[str, Any]] = []
        for values in stream:
            if all(v is None or str(v).strip() == "" for v in values):
                continue
            record: dict[str, Any] = dict(zip(headers, values))
            record[BARCODE_COLUMN] = split_barcodes(record.get(BARCODE_COLUMN))
            start, end = parse_date_range(record.get(DATE_COLUMN))
            record["date_from"] = start
            record["date_to"] = end
            for column in INT_COLUMNS:
                if column in record:
                    record[column] = to_int(record[column])
            rows.append(record)
        return rows
    finally:
        workbook.close()
```

- [ ] **Step 4: Run the reader tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_build.py::TestExcelReader`
Expected: PASS, 6 passed

- [ ] **Step 5: Add `build_database` to `build.py`**

Replace the whole of `src/order_search/ingest/build.py` with:

```python
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..textnorm import fold_heavy, fold_light, norm, parse_pack_size
from .schema_path import SCHEMA_PATH
from .validate import ImportReport, validate_rows


def apply_schema(connection: sqlite3.Connection) -> None:
    """Drops and recreates every table. The connection must be autocommit
    (isolation_level=None)."""
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_database(
    rows: list[dict[str, Any]],
    connection: sqlite3.Connection,
) -> ImportReport:
    """Writes rows into a freshly created schema and returns the import report.

    The connection must be autocommit (isolation_level=None) because this
    function manages its own transaction. The whole insert set is one
    transaction: either every row lands or none does.
    """
    usable, _skipped, report = validate_rows(rows)
    apply_schema(connection)

    product_ids: dict[str, int] = {}
    customer_ids: dict[str, int] = {}
    barcode_pairs: set[tuple[int, str]] = set()

    product_rows: list[tuple] = []
    for row in usable:
        name = str(row["Product Name"]).strip()
        if name in product_ids:
            continue
        product_ids[name] = len(product_ids) + 1
        product_rows.append(
            (
                product_ids[name],
                name,
                norm(name),
                fold_light(name),
                fold_heavy(name),
                row.get("Dept"),
                row.get("Class"),
                row.get("Subclass"),
                parse_pack_size(name),
                None,  # unit is absent from the source file, so never guessed
            )
        )

    customer_rows: list[tuple] = []
    for row in usable:
        name = str(row["Customer Name"]).strip()
        if name in customer_ids:
            continue
        customer_ids[name] = len(customer_ids) + 1
        customer_rows.append(
            (
                customer_ids[name],
                name,
                norm(name),
                fold_light(name),
                fold_heavy(name),
            )
        )

    order_rows: list[tuple] = []
    item_rows: list[tuple] = []
    for order_id, row in enumerate(usable, start=1):
        product_id = product_ids[str(row["Product Name"]).strip()]
        customer_id = customer_ids[str(row["Customer Name"]).strip()]
        order_rows.append(
            (
                order_id,
                _text(row.get("NO.")),
                _text(row.get("Store Code")),
                customer_id,
                _text(row.get("Order Type")),
                _iso(row.get("date_from")),
                _iso(row.get("date_to")),
                _text(row.get("Item Remark")),
                _text(row.get("VIP Customer Remarks")),
                _text(row.get("VIP Customer Groups")),
            )
        )
        item_rows.append(
            (order_id, product_id, row.get("qty"), row.get("price"))
        )
        for barcode in row.get("Bar_Code") or []:
            barcode_pairs.add((product_id, barcode))

    connection.execute("BEGIN")
    try:
        connection.executemany(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy, dept, class_code, subclass_code, pack_size, unit)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            product_rows,
        )
        connection.executemany(
            "INSERT INTO customers (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (?,?,?,?,?)",
            customer_rows,
        )
        connection.executemany(
            "INSERT INTO orders (id, order_no, store_code, customer_id,"
            " order_type, date_from, date_to, item_remark, vip_remark, vip_group)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            order_rows,
        )
        connection.executemany(
            "INSERT INTO order_items (order_id, product_id, qty, price)"
            " VALUES (?,?,?,?)",
            item_rows,
        )
        connection.executemany(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (?,?)",
            sorted(barcode_pairs),
        )
        connection.executemany(
            "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
            " VALUES (?,?,?)",
            [(r[2], r[3], r[0]) for r in product_rows],
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    report.products = len(product_ids)
    report.customers = len(customer_ids)
    report.orders = len(order_rows)
    report.barcodes = len(barcode_pairs)
    report.missing_pack_size_products = sum(
        1 for row in product_rows if row[8] is None
    )
    connection.executemany(
        "INSERT INTO meta (key, value) VALUES (?,?)",
        [
            ("rows_read", str(report.rows_read)),
            ("rows_imported", str(report.rows_imported)),
            ("rows_skipped", str(report.rows_skipped)),
            ("products", str(report.products)),
            ("customers", str(report.customers)),
            ("barcodes", str(report.barcodes)),
        ],
    )
    return report
```

- [ ] **Step 6: Run the build tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_build.py`
Expected: PASS, 20 passed

If `test_barcode_count_drops_after_splitting` fails with a count other than 127, re-run the probe rather than changing the expected value: 127 is the measured post-split count.

- [ ] **Step 7: Commit**

```powershell
git add src/order_search/ingest/build.py src/order_search/ingest/excel_reader.py tests/test_build.py
git commit -m "feat(ingest): build normalized SQLite snapshot from Excel"
```

---

## Task 7: Filters

Spec 4.1.1 defines filter semantics that several parts of the engine depend on. Put them in one module so there is a single source of truth.

**Files:**
- Create: `tests/test_filters.py`
- Create: `src/order_search/search/filters.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filters.py`:

```python
from order_search.search.filters import Filters, order_filter_sql


def params_for(filters: Filters):
    sql, params = order_filter_sql(filters)
    return sql, list(params)


class TestEmptyFilters:
    def test_produces_no_predicate(self):
        sql, params = params_for(Filters())
        assert sql == ""
        assert params == []


class TestEqualityFilters:
    def test_single_store(self):
        sql, params = params_for(Filters(store_code=("135",)))
        assert "o.store_code IN (?,?)" in sql
        assert params == ["135"]

    def test_multiple_stores_are_or_within_the_group(self):
        sql, params = params_for(Filters(store_code=("135", "140")))
        assert sql.count("?") == 2
        assert params == ["135", "140"]

    def test_order_type(self):
        sql, params = params_for(Filters(order_type=("Pickup",)))
        assert "o.order_type IN (?,?)" in sql
        assert params == ["Pickup"]

    def test_dept_class_subclass(self):
        sql, params = params_for(Filters(dept=(1, 4), class_code=(101,), subclass_code=(5,)))
        assert "o.dept" not in sql  # dept lives on the product, see below
        assert "p.dept" in sql
        assert "p.class_code" in sql
        assert "p.subclass_code" in sql
        assert params == [1, 4, 101, 5]

    def test_vip_group_filters_on_the_order_line(self):
        sql, params = params_for(Filters(vip_group=("Gold",)))
        assert "o.vip_group" in sql
        assert params == ["Gold"]

    def test_groups_are_anded_together(self):
        sql, _params = params_for(
            Filters(store_code=("135",), order_type=("Pickup",))
        )
        assert sql.count("AND") >= 1
        assert "o.store_code" in sql
        assert "o.order_type" in sql

    def test_blank_values_are_dropped(self):
        sql, params = params_for(Filters(store_code=("", "  ", "135")))
        assert params == ["135"]


class TestDateFilter:
    def test_overlap_semantics(self):
        # an order passes when its own range overlaps the requested range
        sql, params = params_for(
            Filters(date_from="2026-09-01", date_to="2026-09-30")
        )
        assert "o.date_from <= ?" in sql
        assert "o.date_to >= ?" in sql
        assert params == ["2026-09-30", "2026-09-01"]

    def test_orders_without_a_date_are_excluded_when_filtering(self):
        sql, _params = params_for(Filters(date_from="2026-09-01"))
        assert "o.date_from IS NOT NULL" in sql

    def test_no_null_clause_when_not_filtering_by_date(self):
        sql, _params = params_for(Filters(store_code=("135",)))
        assert "IS NOT NULL" not in sql

    def test_only_one_bound_is_allowed(self):
        sql, params = order_filter_sql(Filters(date_from="2026-09-01"))
        assert "o.date_from <= ?" not in sql
        assert "o.date_to >= ?" in sql
        assert list(params) == ["2026-09-01"]

        sql, params = order_filter_sql(Filters(date_to="2026-09-30"))
        assert "o.date_from <= ?" in sql
        assert "o.date_to >= ?" not in sql
        assert list(params) == ["2026-09-30"]

    def test_values_are_iso_comparable_strings(self):
        # ISO YYYY-MM-DD sorts chronologically as text, so plain comparison works
        sql, params = order_filter_sql(
            Filters(date_from="2026-01-05", date_to="2026-11-30")
        )
        assert list(params) == ["2026-11-30", "2026-01-05"]


class TestFiltersValueObject:
    def test_defaults_are_empty(self):
        filters = Filters()
        assert filters.store_code == ()
        assert filters.dept == ()
        assert filters.date_from is None

    def test_is_immutable(self):
        filters = Filters()
        try:
            filters.store_code = ("135",)  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("Filters should be frozen")

    def test_accepts_any_iterable(self):
        filters = Filters(store_code=["135", "140"])
        assert filters.store_code == ("135", "140")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_filters.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.search.filters'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/search/filters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_SCALAR_GROUPS = (
    ("store_code", "o.store_code"),
    ("order_type", "o.order_type"),
    ("vip_group", "o.vip_group"),
)
_PRODUCT_GROUPS = (
    ("dept", "p.dept"),
    ("class_code", "p.class_code"),
    ("subclass_code", "p.subclass_code"),
)


@dataclass(frozen=True)
class Filters:
    """Advanced filter state. Empty tuples mean 'do not filter'.

    dept / class_code / subclass_code live on the product, so the SQL fragment
    references the `p` alias; the caller must join `order_items oi -> products p`.
    """

    store_code: tuple[str, ...] = ()
    order_type: tuple[str, ...] = ()
    vip_group: tuple[str, ...] = ()
    dept: tuple[int, ...] = ()
    class_code: tuple[int, ...] = ()
    subclass_code: tuple[int, ...] = ()
    date_from: str | None = None
    date_to: str | None = None

    def __post_init__(self) -> None:
        for name, _column in _SCALAR_GROUPS + _PRODUCT_GROUPS:
            object.__setattr__(self, name, _clean(getattr(self, name)))


def _clean(values: Any) -> tuple:
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    cleaned = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return tuple(cleaned)


def _in_clause(column: str, values: tuple) -> tuple[str, list]:
    placeholders = ",".join("?" for _ in values)
    return f"{column} IN ({placeholders})", list(values)


def order_filter_sql(filters: Filters) -> tuple[str, list]:
    """Builds the WHERE fragment for order-line filters.

    Semantics come straight from the spec:
      - values inside one group are OR-ed, groups are AND-ed
      - the date range is an OVERLAP test, not a containment test
      - when a date filter is present, orders with no date are excluded
      - when no date filter is present, orders with no date are kept
    """
    if filters is None:
        return "", []

    clauses: list[str] = []
    params: list = []

    for name, column in _SCALAR_GROUPS:
        values = getattr(filters, name)
        if values:
            clause, values_params = _in_clause(column, values)
            clauses.append(clause)
            params.extend(values_params)

    for name, column in _PRODUCT_GROUPS:
        values = getattr(filters, name)
        if values:
            clause, values_params = _in_clause(column, values)
            clauses.append(clause)
            params.extend(values_params)

    date_clauses: list[str] = []
    if filters.date_to:
        date_clauses.append("o.date_from <= ?")
        params.append(filters.date_to)
    if filters.date_from:
        date_clauses.append("o.date_to >= ?")
        params.append(filters.date_from)
    if date_clauses:
        date_clauses.append("o.date_from IS NOT NULL")
        clauses.append("(" + " AND ".join(date_clauses) + ")")

    if not clauses:
        return "", []
    return " AND ".join(clauses), params
```

`field` is imported but unused in the dataclass — remove it from the import line so lint stays clean:

```python
from dataclasses import dataclass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_filters.py`
Expected: PASS, 19 passed

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/search/filters.py tests/test_filters.py
git commit -m "feat(search): filter value object with overlap date semantics"
```

---

## Task 8: Intention detection

**Files:**
- Create: `tests/test_detect.py`
- Create: `src/order_search/search/detect.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_detect.py`:

```python
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.detect import (
    BARCODE,
    BOTH,
    CUSTOMER,
    NONE,
    PRODUCT,
    detect,
)
from conftest import DATA_FILE


def make_engine():
    import sqlite3

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return connection


def test_blank_query():
    connection = make_engine()
    assert detect("   ", connection).kind == NONE
    assert detect("", connection).kind == NONE


def test_barcode_is_recognised():
    connection = make_engine()
    result = detect("8850250001234", connection)
    assert result.kind == BARCODE
    assert result.normalized_query == "8850250001234"


def test_barcode_with_dashes():
    connection = make_engine()
    assert detect("8850-250001-234", connection).kind == BARCODE


def test_exact_customer_name():
    connection = make_engine()
    result = detect("สุรชัย", connection)
    assert result.kind == CUSTOMER
    assert result.customer_id is not None


def test_customer_name_with_spaces_is_still_a_customer():
    connection = make_engine()
    assert detect("  สุรชัย  ", connection).kind == CUSTOMER


def test_exact_product_name():
    connection = make_engine()
    result = detect("น้ำดื่มสิงห์ 600 มล. x 12", connection)
    assert result.kind == PRODUCT
    assert result.product_ids


def test_partial_product_text_is_a_product_query():
    connection = make_engine()
    result = detect("น้ำดื่มสิงห์", connection)
    assert result.kind == PRODUCT
    assert not result.too_short


def test_short_query_is_flagged_too_short():
    connection = make_engine()
    result = detect("น้", connection)
    assert result.too_short is True
    assert result.kind == PRODUCT


def test_query_matching_both_a_customer_and_a_product():
    connection = make_engine()
    connection.execute(
        "INSERT INTO customers (id, name, name_norm, name_fold_light, name_fold_heavy)"
        " VALUES (999, 'น้ำดื่มสิงห์', 'น้ำดื่มสิงห์', 'นาดมสงห', 'นาดมสงห')"
    )
    result = detect("น้ำดื่มสิงห์", connection)
    assert result.kind == BOTH
    assert result.customer_id == 999
    assert result.product_ids


def test_unknown_text_is_still_a_product_query():
    connection = make_engine()
    assert detect("ซไบเตอร์", connection).kind == PRODUCT


def test_normalized_query_is_exposed():
    connection = make_engine()
    result = detect("น้ำดื่มสิงห์ 600 มล. x 12", connection)
    assert result.normalized_query == "น้ำดื่มสิงห์600มลx12"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_detect.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.search.detect'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/search/detect.py`:

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..textnorm import is_barcode_like, norm

BARCODE = "barcode"
CUSTOMER = "customer"
PRODUCT = "product"
BOTH = "both"
NONE = "none"

# FTS5's trigram tokenizer cannot match anything shorter than this.
MIN_TRIGRAM = 3


@dataclass(frozen=True)
class Detection:
    kind: str
    normalized_query: str
    customer_id: int | None = None
    product_ids: tuple[int, ...] = ()
    too_short: bool = False


def detect(query: str, connection: sqlite3.Connection) -> Detection:
    """Decides what the user is looking for.

    Order of tests matters: digits go to the barcode path first, an exact
    customer name wins over a product match, and a query that is neither is
    treated as product text because the product catalogue is the larger set.
    """
    text = (query or "").strip()
    normalized = norm(text)

    if not normalized:
        return Detection(NONE, "")

    if is_barcode_like(text):
        return Detection(BARCODE, normalized)

    exact_customer = connection.execute(
        "SELECT id FROM customers WHERE name_norm = ? ORDER BY id LIMIT 1",
        (normalized,),
    ).fetchone()
    if exact_customer is not None:
        exact_products = connection.execute(
            "SELECT product_id FROM products_fts WHERE name_norm = ?"
            " ORDER BY product_id",
            (normalized,),
        ).fetchall()
        product_ids = tuple(row["product_id"] for row in exact_products)
        kind = BOTH if product_ids else CUSTOMER
        return Detection(kind, normalized, exact_customer["id"], product_ids)

    if len(normalized) < MIN_TRIGRAM:
        return Detection(PRODUCT, normalized, too_short=True)

    return Detection(PRODUCT, normalized)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_detect.py`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/search/detect.py tests/test_detect.py
git commit -m "feat(search): detect whether a query is barcode, customer or product"
```

---

## Task 9: Fuzzy matching

Isolated so the scorer choice is testable on its own. The two rules that matter: use `WRatio` (never `ratio`), and pass a list of strings (never a list of tuples).

**Files:**
- Create: `tests/test_fuzzy.py`
- Create: `src/order_search/search/fuzzy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fuzzy.py`:

```python
import pytest

from order_search.search.fuzzy import (
    best_customers,
    best_products,
)

WATER = "น้ำดื่มสิงห์ 600 มล. x 12"
SUGAR = "น้ำตาลทรายขาว 1 กก. x 10"
OIL = "น้ำมันปาล์ม 1 ลิตร x 12"
DISH = "น้ำยาล้างจาน 500 มล. x 12"
COFFEE = "กาแฟสำเร็จรูป 3 in 1 17 ก. x 27"
TISSUE = "ทิชชู่ม้วน 24 ม้วน"
COLA = "โค้ก 500 มล. x 12"

CUSTOMERS = [
    "สุรชัย",
    "ศิริพร",
    "วราภรณ์",
    "สมชาย",
    "อนุชา",
]


class FakeConnection:
    """Minimal stand-in exposing only what fuzzy.py is allowed to use."""

    def __init__(self, products, customers):
        self.products = products
        self.customers = customers

    def execute(self, sql, params=()):
        joined = " ".join(sql.split())
        if "FROM products" in joined:
            return _rows(
                [
                    {
                        "id": pid,
                        "name": name,
                        "name_norm": _norm(name),
                        "name_fold_heavy": _heavy(name),
                    }
                    for pid, name in self.products
                ]
            )
        if "FROM customers" in joined:
            return _rows(
                [
                    {
                        "id": cid,
                        "name": name,
                        "name_norm": _norm(name),
                        "name_fold_light": _light(name),
                    }
                    for cid, name in self.customers
                ]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class _Row(dict):
    pass


def _rows(items):
    return [_Row(item) for item in items]


def _nfd(text):
    import unicodedata

    return unicodedata.normalize("NFD", text)


def _norm(text):
    import unicodedata

    return "".join(
        ch
        for ch in _nfd(text)
        if unicodedata.category(ch)[0] in ("L", "N", "M")
    ).lower()


def _light(text):
    drop = set("\u0E48\u0E49\u0E4A\u0E4B\u0E4C\u0E4D")
    return "".join(ch for ch in _nfd(text) if ch not in drop).lower()


def _heavy(text):
    import unicodedata

    return "".join(
        ch for ch in _nfd(text) if unicodedata.category(ch) != "Mn"
    ).lower()


@pytest.fixture
def connection():
    return FakeConnection(
        products=[
            (1, WATER),
            (2, SUGAR),
            (3, OIL),
            (4, DISH),
            (5, COFFEE),
            (6, TISSUE),
            (7, COLA),
        ],
        customers=[(index, name) for index, name in enumerate(CUSTOMERS, start=1)],
    )


class TestBestProducts:
    def test_exact_prefix(self, connection):
        assert 1 in _ids(best_products("น้ำดื่มสิงห์", connection))

    def test_middle_substring(self, connection):
        assert 1 in _ids(best_products("สิงห์", connection))

    def test_missing_thanthakhat(self, connection):
        assert 1 in _ids(best_products("สิงห", connection))

    def test_wrong_vowel_and_tone(self, connection):
        # only the heavy fold can catch this, and the confirm pass must agree
        assert 1 in _ids(best_products("สึงห์", connection))

    def test_missing_tone_mark_on_vowel(self, connection):
        assert 1 in _ids(best_products("น้ำดืม", connection))

    def test_short_query_matches_several(self, connection):
        found = _ids(best_products("น้ำ", connection))
        assert {1, 2, 3, 4} <= set(found)

    def test_finds_product_without_pack_size(self, connection):
        assert 6 in _ids(best_products("ทิชชู่", connection))

    def test_thai_digits_are_honoured(self, connection):
        assert 7 in _ids(best_products("โค้ก", connection))

    def test_known_limitation_dropped_vowel(self, connection):
        # a vowel omitted from a three character query cannot reach a score of
        # 70, so this is documented as unreachable rather than asserted to work
        assert best_products("กแฟ", connection) == []

    def test_nonsense_query_returns_nothing(self, connection):
        assert best_products("ซไบเตอร์", connection) == []
        assert best_products("zzz", connection) == []
        assert best_products("๑๒๓", connection) == []

    def test_empty_query_returns_nothing(self, connection):
        assert best_products("", connection) == []
        assert best_products("   ", connection) == []

    def test_results_are_sorted_by_score_then_id(self, connection):
        results = best_products("น้ำ", connection)
        scores = [score for _pid, _norm_text, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_respects_the_limit(self, connection):
        assert len(best_products("น้ำ", connection, limit=2)) == 2


class TestBestCustomers:
    def test_exact_name(self, connection):
        assert _ids(best_customers("สุรชัย", connection)) == [1]

    def test_prefix_of_name(self, connection):
        assert _ids(best_customers("สุรช", connection)) == [1]

    def test_another_exact_name(self, connection):
        assert _ids(best_customers("ศิริพร", connection)) == [2]

    def test_unknown_name_returns_nothing(self, connection):
        assert best_customers("ไม่มีในระบบ", connection) == []

    def test_empty_query_returns_nothing(self, connection):
        assert best_customers("", connection) == []

    def test_respects_the_limit(self, connection):
        assert len(best_customers("ส", connection, limit=2)) <= 2


def _ids(results):
    return [item[0] for item in results]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fuzzy.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.search.fuzzy'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/search/fuzzy.py`:

```python
from __future__ import annotations

import sqlite3

from rapidfuzz import fuzz, process

# Stage 1 widens the pool cheaply; stage 2 confirms on the untouched base form.
# A stage-1-only answer would be wrong because the heavy fold merges distinct
# Thai words such as มา and ม่า.
STAGE1_CUTOFF = 45
STAGE1_POOL = 50
FINAL_CUTOFF = 70

# WRatio is required, not a preference. A user types a substring of a name that
# is 20 to 48 characters long, and fuzz.ratio compares full lengths, so
# 'สิงห์' against 'น้ำดื่มสิงห์600มลx12' never reaches the cutoff while WRatio does.
SCORER = fuzz.WRatio


def best_customers(
    query: str,
    connection: sqlite3.Connection,
    limit: int = 5,
    score_cutoff: int = FINAL_CUTOFF,
) -> list[tuple[int, str, float]]:
    """Returns (customer_id, name_norm, score) best first.

    Names are passed to rapidfuzz as a plain list of strings: passing a list of
    tuples makes every score come out as 0.0.
    """
    rows = connection.execute(
        "SELECT id, name_norm, name_fold_light FROM customers ORDER BY id"
    ).fetchall()
    if not rows:
        return []

    keys = [row["name_fold_light"] for row in rows]
    key_to_id = {row["name_fold_light"]: row["id"] for row in rows}
    id_to_norm = {row["id"]: row["name_norm"] for row in rows}

    matches = process.extract(
        query,
        keys,
        scorer=SCORER,
        score_cutoff=score_cutoff,
        limit=limit,
    )
    out: list[tuple[int, str, float]] = []
    for value, score, _index in matches:
        customer_id = key_to_id.get(value)
        if customer_id is not None:
            out.append((customer_id, id_to_norm[customer_id], float(score)))
    return out


def best_products(
    query: str,
    connection: sqlite3.Connection,
    limit: int = 5,
    stage1_cutoff: int = STAGE1_CUTOFF,
    final_cutoff: int = FINAL_CUTOFF,
) -> list[tuple[int, str, float]]:
    """Returns (product_id, name_norm, score) best first."""
    rows = connection.execute(
        "SELECT id, name_norm, name_fold_heavy FROM products ORDER BY id"
    ).fetchall()
    if not rows or not query:
        return []

    heavy_keys = [row["name_fold_heavy"] for row in rows]
    index_to_id = {index: row["id"] for index, row in enumerate(rows)}
    id_to_norm = {row["id"]: row["name_norm"] for row in rows}

    widened = process.extract(
        query,
        heavy_keys,
        scorer=SCORER,
        score_cutoff=stage1_cutoff,
        limit=STAGE1_POOL,
    )

    confirmed: list[tuple[int, str, float]] = []
    for _value, _score, index in widened:
        product_id = index_to_id.get(index)
        if product_id is None:
            continue
        name_norm = id_to_norm[product_id]
        confirm = SCORER(query, name_norm)
        if confirm >= final_cutoff:
            confirmed.append((product_id, name_norm, float(confirm)))

    confirmed.sort(key=lambda item: (-item[2], item[0]))
    return confirmed[:limit]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fuzzy.py`
Expected: PASS, 21 passed

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/search/fuzzy.py tests/test_fuzzy.py
git commit -m "feat(search): two-stage WRatio fuzzy matching for Thai names"
```

---

## Task 10: The search engine

Composes the four layers. This is the file the whole product rests on, so the tests assert against the verified ground truth rather than against whatever the code happens to produce.

**Files:**
- Create: `tests/test_engine_customer.py`
- Create: `tests/test_engine_product.py`
- Create: `tests/test_engine_barcode.py`
- Create: `src/order_search/search/engine.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine_customer.py`:

```python
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE


def make_engine():
    import sqlite3

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return SearchEngine(connection)


class TestCustomerMode:
    def test_exact_customer_name_returns_that_customer(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert result["mode"] == "customer"
        assert [c["name"] for c in result["customers"]] == ["สุรชัย"]

    def test_customer_order_line_count(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert result["customers"][0]["order_count"] == 65

    def test_customer_bought_fifteen_distinct_products(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert len(result["customers"][0]["products"]) == 15

    def test_customer_product_counts_are_aggregated(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        products = {
            p["name"]: p["order_count"]
            for p in result["customers"][0]["products"]
        }
        assert products["น้ำดื่มสิงห์ 600 มล. x 12"] == 6

    def test_customer_came_from_fourteen_stores(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        stores = result["customers"][0]["products"][0]["stores"]
        assert len(set(stores)) == 14

    def test_customer_order_types_are_reported(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        types = set()
        for product in result["customers"][0]["products"]:
            types.update(product["order_types"])
        assert types == {
            "Express delivery",
            "Pickup",
            "Scheduled delivery",
            "Standard delivery",
        }

    def test_vip_tiers_are_reported_per_product(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        tiers = set()
        for product in result["customers"][0]["products"]:
            tiers.update(product["vip_groups"])
        assert tiers == {"Gold", "Platinum", "VIP", "Wholesale VIP"}

    def test_customer_name_with_surrounding_spaces(self):
        engine = make_engine()
        assert engine.search("  สุรชัย  ")["customers"][0]["name"] == "สุรชัย"

    def test_unknown_customer_returns_no_customers(self):
        engine = make_engine()
        result = engine.search("ไม่มีในระบบ")
        assert result["customers"] == []

    def test_customer_result_exposes_an_id(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert isinstance(result["customers"][0]["customer_id"], int)


class TestFuzzyCustomerLookup:
    """Layer 2 of the search: a customer name typed with a mistake still finds
    the customer. The cutoff of 70 was measured against all 20 real names: it
    recognises every genuine typo tested and matched none of the non-name
    queries (น้ำ, น้ำดื่ม, โค้ก, ทิชชู่, ซไบเตอร์, zzz)."""

    def test_prefix_of_a_name_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("สุรช")
        assert result["mode"] == "customer"
        assert [c["name"] for c in result["customers"]] == ["สุรชัย"]

    def test_omitted_final_vowel_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("อนุช")
        assert [c["name"] for c in result["customers"]] == ["อนุชา"]

    def test_transposed_vowel_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("อนูชา")
        assert [c["name"] for c in result["customers"]] == ["อนุชา"]

    def test_dropped_tone_mark_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("พงษ์ศักติ์")
        assert [c["name"] for c in result["customers"]] == ["พงษ์ศักดิ์"]

    def test_fuzzy_customer_returns_the_full_purchase_history(self):
        engine = make_engine()
        result = engine.search("สุรช")
        assert result["customers"][0]["order_count"] == 65
        assert len(result["customers"][0]["products"]) == 15

    def test_product_text_does_not_invent_a_customer(self):
        engine = make_engine()
        result = engine.search("น้ำ")
        assert result["customers"] == []
        assert result["products"]

    def test_nonsense_does_not_invent_a_customer(self):
        engine = make_engine()
        assert engine.search("ซไบเตอร์")["customers"] == []
        assert engine.search("zzz")["customers"] == []

    def test_barcode_never_triggers_customer_fuzzy(self):
        engine = make_engine()
        assert engine.search("8850250001234")["customers"] == []

    def test_explicit_product_mode_suppresses_customer_results(self):
        engine = make_engine()
        result = engine.search("สุรช", mode="product")
        assert result["customers"] == []

    def test_explicit_customer_mode_still_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("สุรช", mode="customer")
        assert [c["name"] for c in result["customers"]] == ["สุรชัย"]
```

Create `tests/test_engine_product.py`:

```python
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE


def make_engine():
    import sqlite3

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return SearchEngine(connection)


class TestProductMode:
    def test_full_product_name(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["mode"] == "product"
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_every_customer_bought_water(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["customer_count"] == 20

    def test_order_line_count_for_water(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["order_count"] == 86

    def test_customer_breakdown_is_sorted_by_order_count(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        counts = [
            c["order_count"] for c in result["products"][0]["customers"]
        ]
        assert counts == sorted(counts, reverse=True)
        assert result["products"][0]["customers"][0]["name"] == "เอกชัย"

    def test_short_query_matches_four_products(self):
        engine = make_engine()
        result = engine.search("น้ำ")
        assert result["products"]
        assert len(result["products"]) == 4

    def test_middle_substring_finds_the_product(self):
        engine = make_engine()
        result = engine.search("สิงห์")
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_missing_thanthakhat_still_finds_it(self):
        engine = make_engine()
        result = engine.search("สิงห")
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_wrong_vowel_and_tone_still_finds_it(self):
        engine = make_engine()
        result = engine.search("สึงห์")
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_product_without_pack_size_is_findable(self):
        engine = make_engine()
        result = engine.search("ทิชชู่")
        product = result["products"][0]
        assert product["name"] == "ทิชชู่ม้วน 24 ม้วน"
        assert product["pack_size"] is None

    def test_product_carries_its_hierarchy(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        product = result["products"][0]
        assert product["dept"] == 1
        assert product["class_code"] == 101
        assert product["subclass_code"] == 5
        assert product["pack_size"] == 12

    def test_nonsense_query_returns_nothing(self):
        engine = make_engine()
        result = engine.search("ซไบเตอร์")
        assert result["products"] == []
        assert result["customers"] == []


class TestFoldLayerPairing:
    """Layers 3 and 3b match a query against a specific pre-computed column.
    The query must be transformed by the same function that built that column.
    Getting this wrong returns zero rows silently rather than raising, so these
    tests exist to make a mismatched pairing fail loudly.

    Measured: norm('สิงห์') against name_fold_light yields 0 rows, while
    fold_light('สิงห์') yields 1.
    """

    def test_light_fold_column_is_reachable_by_a_tone_stripped_query(self):
        engine = make_engine()
        # every one of these loses tone marks or thanthakhat relative to the
        # stored name, so layer 3 misses and layer 3b must catch them
        for query in ["สิงห", "สิงห์", "ขาวหอมมะลิ", "นำดืมสิงห", "นำดื่มสิงห"]:
            result = engine.search(query)
            assert result["products"], f"layer 3b failed to rescue {query!r}"

    def test_base_column_still_served_by_the_base_form(self):
        engine = make_engine()
        # a fully marked query must match through the base column, untouched
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["name"] == "น้ำดื่มสิงห์ 600 มล. x 12"

    def test_three_character_query_that_shrinks_when_light_folded(self):
        engine = make_engine()
        # norm('น้ำ') is 3 characters, so the base column can serve it, but
        # fold_light('น้ำ') is 'นำ', only 2, which the trigram index cannot
        # match. The base column must therefore still carry this query.
        result = engine.search("น้ำ")
        assert len(result["products"]) == 4

    def test_scoped_match_does_not_cross_columns(self):
        engine = make_engine()
        # 'สงห' exists only in the heavy fold, never in the light fold column.
        # Searching the light column with a heavy form must not silently match
        # via the base column instead.
        rows = engine.connection.execute(
            "SELECT COUNT(*) AS n FROM products_fts"
            " WHERE name_fold_light MATCH ?",
            ('"สงห"',),
        ).fetchone()
        assert rows["n"] == 0
        rows = engine.connection.execute(
            "SELECT COUNT(*) AS n FROM products_fts WHERE name_norm MATCH ?",
            ('"สงห"',),
        ).fetchone()
        assert rows["n"] == 0

    def test_blank_query_is_reported_as_none(self):
        engine = make_engine()
        result = engine.search("   ")
        assert result["detected"] == "none"
        assert result["products"] == []
        assert result["customers"] == []


class TestResponseShape:
    def test_reports_what_it_detected(self):
        engine = make_engine()
        assert engine.search("8850250001234")["detected"] == "barcode"
        assert engine.search("สุรชัย")["detected"] == "customer"
        assert engine.search("โค้ก")["detected"] == "product"

    def test_exposes_the_normalized_query(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["normalized_query"] == "น้ำดื่มสิงห์600มลx12"

    def test_pagination_splits_without_overlap(self):
        engine = make_engine()
        first = engine.search("น้ำ", limit=2)
        assert len(first["products"]) == 2
        assert first["next_cursor"]
        second = engine.search("น้ำ", limit=2, cursor=first["next_cursor"])
        assert second["products"]
        first_ids = {p["product_id"] for p in first["products"]}
        second_ids = {p["product_id"] for p in second["products"]}
        assert not (first_ids & second_ids)

    def test_last_page_has_no_cursor(self):
        engine = make_engine()
        result = engine.search("น้ำ", limit=50)
        assert result["next_cursor"] is None

    def test_bad_cursor_is_ignored_rather_than_raising(self):
        engine = make_engine()
        result = engine.search("น้ำ", cursor="not-a-cursor")
        assert result["products"]

    def test_limit_is_clamped_to_the_maximum(self):
        engine = make_engine()
        result = engine.search("น้ำ", limit=5000)
        assert len(result["products"]) <= 100


class TestFilterIntegration:
    def test_store_filter_narrows_the_customer_list(self):
        engine = make_engine()
        unfiltered = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        filtered = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters={"store_code": ["101"]}
        )
        assert filtered["products"][0]["order_count"] < unfiltered["products"][0]["order_count"]

    def test_order_type_filter(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(order_type=("Pickup",))
        )
        types = set()
        for customer in result["products"][0]["customers"]:
            types.update(customer["order_types"])
        assert types == {"Pickup"}

    def test_vip_filter_is_applied_to_the_order_line(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(vip_group=("Gold",))
        )
        tiers = set()
        for customer in result["products"][0]["customers"]:
            tiers.update(customer["vip_groups"])
        assert tiers == {"Gold"}

    def test_dept_filter(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(dept=(1,))
        )
        assert result["products"]
        everything = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["order_count"] == everything["products"][0]["order_count"]

    def test_impossible_filter_yields_nothing(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(store_code=("101",), order_type=("Pickup",), dept=(9999,))
        )
        assert result["products"] == []
```

Create `tests/test_engine_barcode.py`:

```python
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE


def make_engine():
    import sqlite3

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return SearchEngine(connection)


class TestBarcodeMode:
    def test_known_barcode_finds_its_product(self):
        engine = make_engine()
        result = engine.search("8850250001234")
        assert result["detected"] == "barcode"
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_barcode_result_includes_the_customer_list(self):
        engine = make_engine()
        result = engine.search("8850250001234")
        assert result["products"][0]["customer_count"] == 20

    def test_barcode_with_dashes(self):
        engine = make_engine()
        result = engine.search("8850-250001-234")
        assert result["products"]

    def test_short_barcode_cell_value_is_searchable(self):
        # '21464546' appears as the first half of a multi-barcode cell
        engine = make_engine()
        result = engine.search("21464546")
        assert result["products"]

    def test_unknown_barcode_returns_nothing(self):
        engine = make_engine()
        result = engine.search("0000000000000")
        assert result["products"] == []

    def test_barcode_never_searches_customer_names(self):
        engine = make_engine()
        result = engine.search("8850250001234")
        assert result["customers"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_engine_customer.py tests/test_engine_product.py tests/test_engine_barcode.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'order_search.search.engine'`

- [ ] **Step 3: Write the implementation**

Create `src/order_search/search/engine.py`:

```python
from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from typing import Any

from ..textnorm import digits_only, fold_light
from .detect import BARCODE, BOTH, CUSTOMER, MIN_TRIGRAM, NONE, detect
from .filters import Filters, order_filter_sql
from .fuzzy import best_customers, best_products

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
FUZZY_FALLBACK_THRESHOLD = 5
CUSTOMER_FUZZY_CUTOFF = 70
CUSTOMERS_PER_PRODUCT = 50
PRODUCTS_PER_CUSTOMER = 50


def _phrase(text: str) -> str:
    """Wraps a query so FTS5 reads it as a literal phrase.

    Without the quotes FTS5 parses characters like ':' and '*' as query
    operators, and a Thai name containing them would raise an error.
    """
    return '"' + text.replace('"', '""') + '"'


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return max(0, int(payload["offset"]))
    except (ValueError, KeyError, TypeError, binascii.Error):
        return 0


def _as_filters(filters: Any) -> Filters:
    if filters is None:
        return Filters()
    if isinstance(filters, Filters):
        return filters
    return Filters(**{k: v for k, v in dict(filters).items() if v is not None})


def _clean_list(values: Any) -> list[str]:
    if not values:
        return []
    out = []
    for value in values:
        text = str(value).strip()
        if text:
            out.append(text)
    return sorted(set(out))


class SearchEngine:
    """Answers 'what has this customer bought?' and 'who bought this product?'.

    Layer order, cheapest first:
      1 barcode lookup on an indexed column
      2 exact customer name, then fuzzy over customer names
      3 FTS5 trigram substring match on products
      4 fuzzy WRatio over product names, only when layer 3 found too little
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    # ------------------------------------------------------------------ public

    def search(
        self,
        query: str,
        mode: str = "auto",
        filters: Any = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        active = _as_filters(filters)
        offset = _decode_cursor(cursor)
        detection = detect(query, self.connection)

        payload: dict[str, Any] = {
            "query": query or "",
            "normalized_query": detection.normalized_query,
            "detected": detection.kind,
            "mode": "none",
            "customers": [],
            "products": [],
            "next_cursor": None,
        }
        if detection.kind == NONE:
            return payload

        wants_customer = mode in ("auto", "customer")
        wants_product = mode in ("auto", "product") and detection.kind in (
            BARCODE,
            PRODUCT,
            BOTH,
        )

        customer_id = self._resolve_customer_id(detection) if wants_customer else None
        if customer_id is not None:
            payload["customers"] = self._customer_results([customer_id], active)
            payload["mode"] = "customer"

        if wants_product:
            product_ids = self._product_ids(detection)
            products = self._product_results(product_ids, active, limit, offset)
            payload["products"] = products
            if products:
                payload["mode"] = (
                    "mixed" if payload["mode"] == "customer" else "product"
                )
            total = self._count_products(product_ids, active)
            if offset + len(products) < total:
                payload["next_cursor"] = _encode_cursor(offset + len(products))

        return payload

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Prefix suggestions for the autocomplete box.

        Uses a plain prefix match rather than the fuzzy layers on purpose: a
        dropdown that invents near-misses is worse than one that waits.
        """
        text = (query or "").strip()
        if not text:
            return []
        limit = max(1, min(int(limit), 20))
        normalized = detect(text, self.connection).normalized_query
        if not normalized:
            return []
        pattern = _escape_like(normalized) + "%"
        rows = self.connection.execute(
            "SELECT id, name, name_norm FROM products"
            " WHERE name_norm LIKE ? ESCAPE '\\' ORDER BY name_norm LIMIT ?",
            (pattern, limit),
        ).fetchall()
        return [
            {"type": "product", "id": row["id"], "name": row["name"]}
            for row in rows
        ]

    # ------------------------------------------------------------- layer 2 / 4

    def _product_ids(self, detection) -> list[int]:
        if detection.kind == BARCODE:
            return self._product_ids_by_barcode(digits_only(detection.normalized_query))
        if detection.kind in (PRODUCT, BOTH) and detection.product_ids:
            return list(detection.product_ids)

        if detection.too_short:
            return self._product_ids_by_prefix(detection.normalized_query)

        # Layer 3: the base form against the base column.
        found = self._product_ids_by_fts(detection.normalized_query, "name_norm")
        if len(found) >= FUZZY_FALLBACK_THRESHOLD:
            return found

        # Layer 3b: widen by matching the light-folded query against the
        # light-folded column. The query MUST be transformed by the same
        # function that built the column. Passing the raw or norm()'d query
        # here silently returns nothing, because a mark-carrying query is not
        # a substring of a tone-stripped column. Verified: norm('สิงห์') at
        # name_fold_light gives 0 rows, fold_light('สิงห์') gives 1.
        light_query = fold_light(detection.normalized_query)
        for product_id in self._product_ids_by_fts(light_query, "name_fold_light"):
            if product_id not in found:
                found.append(product_id)
        if len(found) >= FUZZY_FALLBACK_THRESHOLD:
            return found

        # Layer 4: fuzzy, only when both exact paths found too little.
        for product_id, _text, _score in best_products(
            detection.normalized_query, self.connection
        ):
            if product_id not in found:
                found.append(product_id)
        return found

    def _resolve_customer_id(self, detection) -> int | None:
        """Layer 2. An exact name match wins; otherwise fall back to fuzzy
        matching over the customer list.

        The 70 cutoff is measured, not guessed: across all 20 real customer
        names it recognised every genuine typo tried (lowest score 72.7) and
        matched none of the non-name queries. Raising it only loses recall.
        """
        if detection.customer_id is not None:
            return detection.customer_id
        if detection.kind == BARCODE:
            return None
        matches = best_customers(detection.normalized_query, self.connection)
        if not matches:
            return None
        customer_id, _text, score = matches[0]
        return customer_id if score >= CUSTOMER_FUZZY_CUTOFF else None

    # ------------------------------------------------------------- layer 1 / 3

    def _product_ids_by_barcode(self, barcode: str) -> list[int]:
        if not barcode:
            return []
        rows = self.connection.execute(
            "SELECT DISTINCT product_id FROM product_barcodes"
            " WHERE barcode = ? ORDER BY product_id",
            (barcode,),
        ).fetchall()
        return [row["product_id"] for row in rows]

    def _product_ids_by_prefix(self, normalized: str) -> list[int]:
        rows = self.connection.execute(
            "SELECT id FROM products WHERE name_norm LIKE ? ESCAPE '\\'"
            " ORDER BY name_norm",
            (_escape_like(normalized) + "%",),
        ).fetchall()
        return [row["id"] for row in rows]

    def _product_ids_by_fts(self, query: str, column: str) -> list[int]:
        """Matches `query` against one FTS column.

        The MATCH must be scoped to a single column: an unscoped
        `products_fts MATCH ?` searches every indexed column, so a base-form
        query could accidentally match the fold column or the reverse.

        The caller must pass a query transformed by the same function that
        built the column. `name_norm` pairs with `norm()`, `name_fold_light`
        with `fold_light()`.

        The length guard is per call, not shared: light-folding can shorten a
        query, so a base query of exactly 3 characters can become a 2-character
        light query, which the trigram tokenizer cannot match. Only the base
        column falls back to a prefix scan; a too-short fold query simply
        contributes nothing and lets layer 4 do the work.
        """
        if len(query) < MIN_TRIGRAM:
            if column == "name_norm":
                return self._product_ids_by_prefix(query)
            return []
        try:
            rows = self.connection.execute(
                f"SELECT product_id FROM products_fts"
                f" WHERE {column} MATCH ? ORDER BY product_id",
                (_phrase(query),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [row["product_id"] for row in rows]

    # ------------------------------------------------------------- aggregation

    def _count_products(self, product_ids: list[int], filters: Filters) -> int:
        if not product_ids:
            return 0
        where, params = order_filter_sql(filters)
        placeholders = ",".join("?" for _ in product_ids)
        row = self.connection.execute(
            f"SELECT COUNT(DISTINCT oi.product_id) AS total"
            f" FROM order_items oi"
            f" JOIN orders o ON o.id = oi.order_id"
            f" JOIN products p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders})"
            + (f" AND {where}" if where else ""),
            (*product_ids, *params),
        ).fetchone()
        return int(row["total"])

    def _product_results(
        self,
        product_ids: list[int],
        filters: Filters,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        if not product_ids:
            return []
        where, params = order_filter_sql(filters)
        placeholders = ",".join("?" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            f"SELECT oi.product_id AS product_id,"
            f" COUNT(*) AS order_count,"
            f" COUNT(DISTINCT o.customer_id) AS customer_count,"
            f" MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM order_items oi"
            f" JOIN orders o ON o.id = oi.order_id"
            f" JOIN products p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders}){clause}"
            f" GROUP BY oi.product_id"
            f" ORDER BY order_count DESC, oi.product_id ASC"
            f" LIMIT ? OFFSET ?",
            (*product_ids, *params, limit, offset),
        ).fetchall()
        if not rows:
            return []

        page_ids = [row["product_id"] for row in rows]
        details = {
            row["id"]: row
            for row in self.connection.execute(
                f"SELECT id, name, dept, class_code, subclass_code, pack_size, unit"
                f" FROM products WHERE id IN ("
                + ",".join("?" for _ in page_ids)
                + ")",
                tuple(page_ids),
            ).fetchall()
        }
        breakdown = self._customer_breakdown(page_ids, filters)

        out: list[dict[str, Any]] = []
        for row in rows:
            meta = details.get(row["product_id"])
            if meta is None:
                continue
            out.append(
                {
                    "product_id": row["product_id"],
                    "name": meta["name"],
                    "dept": meta["dept"],
                    "class_code": meta["class_code"],
                    "subclass_code": meta["subclass_code"],
                    "pack_size": meta["pack_size"],
                    "unit": meta["unit"],
                    "order_count": row["order_count"],
                    "customer_count": row["customer_count"],
                    "last_date": row["last_date"],
                    "customers": breakdown.get(row["product_id"], []),
                }
            )
        return out

    def _customer_breakdown(
        self, product_ids: list[int], filters: Filters
    ) -> dict[int, list[dict[str, Any]]]:
        if not product_ids:
            return {}
        where, params = order_filter_sql(filters)
        placeholders = ",".join("?" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            f"SELECT oi.product_id AS product_id,"
            f" o.customer_id AS customer_id,"
            f" c.name AS customer_name,"
            f" COUNT(*) AS order_count,"
            f" MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM order_items oi"
            f" JOIN orders o ON o.id = oi.order_id"
            f" JOIN customers c ON c.id = o.customer_id"
            f" WHERE oi.product_id IN ({placeholders}){clause}"
            f" GROUP BY oi.product_id, o.customer_id"
            f" ORDER BY oi.product_id ASC, order_count DESC, o.customer_id ASC",
            (*product_ids, *params),
        ).fetchall()

        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            bucket = grouped.setdefault(row["product_id"], [])
            if len(bucket) >= CUSTOMERS_PER_PRODUCT:
                continue
            bucket.append(
                {
                    "customer_id": row["customer_id"],
                    "name": row["customer_name"],
                    "order_count": row["order_count"],
                    "last_date": row["last_date"],
                }
            )
        return grouped

    def _customer_results(
        self, customer_ids: list[int], filters: Filters
    ) -> list[dict[str, Any]]:
        if not customer_ids:
            return []
        where, params = order_filter_sql(filters)
        placeholders = ",".join("?" for _ in customer_ids)
        clause = f" AND {where}" if where else ""
        heads = self.connection.execute(
            f"SELECT c.id AS customer_id, c.name AS name,"
            f" COUNT(*) AS order_count,"
            f" MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM orders o"
            f" JOIN customers c ON c.id = o.customer_id"
            f" WHERE o.customer_id IN ({placeholders}){clause}"
            f" GROUP BY c.id, c.name"
            f" ORDER BY order_count DESC, c.id ASC",
            (*customer_ids, *params),
        ).fetchall()

        out: list[dict[str, Any]] = []
        for head in heads:
            out.append(
                {
                    "customer_id": head["customer_id"],
                    "name": head["name"],
                    "order_count": head["order_count"],
                    "last_date": head["last_date"],
                    "products": self._products_for_customer(
                        head["customer_id"], filters
                    ),
                }
            )
        return out

    def _products_for_customer(
        self, customer_id: int, filters: Filters
    ) -> list[dict[str, Any]]:
        where, params = order_filter_sql(filters)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            f"SELECT p.id AS product_id, p.name AS name, p.pack_size AS pack_size,"
            f" COUNT(*) AS order_count,"
            f" MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM order_items oi"
            f" JOIN orders o ON o.id = oi.order_id"
            f" JOIN products p ON p.id = oi.product_id"
            f" WHERE o.customer_id = ?{clause}"
            f" GROUP BY p.id, p.name, p.pack_size"
            f" ORDER BY order_count DESC, p.id ASC"
            f" LIMIT ?",
            (customer_id, *params, PRODUCTS_PER_CUSTOMER),
        ).fetchall()
        if not rows:
            return []
        product_ids = [row["product_id"] for row in rows]
        facets = self._order_facets_for_products(product_ids, customer_id, filters)
        return [
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "pack_size": row["pack_size"],
                "order_count": row["order_count"],
                "last_date": row["last_date"],
                "stores": facets.get(row["product_id"], {}).get("stores", []),
                "order_types": facets.get(row["product_id"], {}).get("order_types", []),
                "item_remarks": facets.get(row["product_id"], {}).get("item_remarks", []),
                "vip_groups": facets.get(row["product_id"], {}).get("vip_groups", []),
                "vip_remarks": facets.get(row["product_id"], {}).get("vip_remarks", []),
            }
            for row in rows
        ]

    def _order_facets_for_products(
        self, product_ids: list[int], customer_id: int, filters: Filters
    ) -> dict[int, dict[str, list[str]]]:
        if not product_ids:
            return {}
        where, params = order_filter_sql(filters)
        placeholders = ",".join("?" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            f"SELECT oi.product_id AS product_id, o.store_code AS store_code,"
            f" o.order_type AS order_type, o.item_remark AS item_remark,"
            f" o.vip_group AS vip_group, o.vip_remark AS vip_remark"
            f" FROM order_items oi"
            f" JOIN orders o ON o.id = oi.order_id"
            f" WHERE oi.product_id IN ({placeholders})"
            f" AND o.customer_id = ?{clause}",
            (*product_ids, customer_id, *params),
        ).fetchall()

        names = {
            "stores": "store_code",
            "order_types": "order_type",
            "item_remarks": "item_remark",
            "vip_groups": "vip_group",
            "vip_remarks": "vip_remark",
        }
        out: dict[int, dict[str, list[str]]] = {}
        for row in rows:
            bucket = out.setdefault(
                row["product_id"], {key: [] for key in names}
            )
            for key, column in names.items():
                value = row[column]
                if value and value not in bucket[key]:
                    bucket[key].append(value)
        for bucket in out.values():
            for key in names:
                bucket[key].sort()
        return out


def _escape_like(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
```

- [ ] **Step 4: Run the engine tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_engine_customer.py tests/test_engine_product.py tests/test_engine_barcode.py`
Expected: PASS, 38 passed

Two behaviours in that file are deliberate and must not be "fixed":
- `_products_for_customer` limits to `PRODUCTS_PER_CUSTOMER`; the real data has 15 distinct products per customer so nothing is truncated today.
- `_customer_breakdown` limits to `CUSTOMERS_PER_PRODUCT`; the busiest product has 20 customers so nothing is truncated today.

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/search/engine.py tests/test_engine_customer.py tests/test_engine_product.py tests/test_engine_barcode.py
git commit -m "feat(search): four-layer search engine with aggregation and filters"
```

---

## Task 11: Command line entry points

Makes the engine usable without a server, which is how it gets exercised during development.

**Files:**
- Create: `scripts/import_excel.py`
- Create: `scripts/query_cli.py`
- Create: `scripts/make_fixture.py`
- Create: `tests/test_scripts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scripts.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "sample_order_data_1000_records.xlsx"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def run(args, env_extra=None):
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(PYTHON), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )


class TestImportScript:
    def test_builds_a_database_and_prints_the_report(self, tmp_path):
        target = tmp_path / "snapshot.db"
        result = run(
            [
                "scripts/import_excel.py",
                str(DATA_FILE),
                "--out",
                str(target),
            ]
        )
        assert result.returncode == 0, result.stderr
        for label in [
            "rows read",
            "rows imported",
            "products",
            "customers",
            "barcodes",
        ]:
            assert label in result.stdout
        assert target.is_file()

    def test_reports_127_barcodes(self, tmp_path):
        target = tmp_path / "snapshot.db"
        result = run(
            ["scripts/import_excel.py", str(DATA_FILE), "--out", str(target)]
        )
        assert "barcodes       : 127" in result.stdout

    def test_missing_file_exits_with_a_message(self, tmp_path):
        result = run(
            [
                "scripts/import_excel.py",
                str(tmp_path / "nope.xlsx"),
                "--out",
                str(tmp_path / "x.db"),
            ]
        )
        assert result.returncode != 0
        assert "nope.xlsx" in result.stderr


class TestFixtureScript:
    def test_generates_a_workbook_with_varied_dates(self, tmp_path):
        target = tmp_path / "fixture.xlsx"
        result = run(["scripts/make_fixture.py", "--out", str(target)])
        assert result.returncode == 0, result.stderr
        assert target.is_file()

        from openpyxl import load_workbook

        sheet = load_workbook(target)["Order Data"]
        values = {
            row[12] for row in sheet.iter_rows(min_row=2, values_only=True)
        }
        assert len(values) > 5, "fixture must contain several distinct dates"


class TestQueryScript:
    def test_searches_a_customer(self, tmp_path):
        db = tmp_path / "snapshot.db"
        assert run(
            ["scripts/import_excel.py", str(DATA_FILE), "--out", str(db)]
        ).returncode == 0
        result = run(["scripts/query_cli.py", "--db", str(db), "สุรชัย"])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["mode"] == "customer"
        assert payload["customers"][0]["order_count"] == 65

    def test_searches_a_barcode(self, tmp_path):
        db = tmp_path / "snapshot.db"
        run(["scripts/import_excel.py", str(DATA_FILE), "--out", str(db)])
        result = run(
            ["scripts/query_cli.py", "--db", str(db), "8850250001234"]
        )
        payload = json.loads(result.stdout)
        assert payload["detected"] == "barcode"
        assert payload["products"][0]["name"] == "น้ำดื่มสิงห์ 600 มล. x 12"

    def test_accepts_filters(self, tmp_path):
        db = tmp_path / "snapshot.db"
        run(["scripts/import_excel.py", str(DATA_FILE), "--out", str(db)])
        result = run(
            [
                "scripts/query_cli.py",
                "--db",
                str(db),
                "--store",
                "101",
                "--order-type",
                "Pickup",
                "น้ำดื่มสิงห์ 600 มล. x 12",
            ]
        )
        payload = json.loads(result.stdout)
        assert payload["products"][0]["order_count"] < 86

    def test_suggest_endpoint(self, tmp_path):
        db = tmp_path / "snapshot.db"
        run(["scripts/import_excel.py", str(DATA_FILE), "--out", str(db)])
        result = run(
            ["scripts/query_cli.py", "--db", str(db), "--suggest", "น้ำ"]
        )
        payload = json.loads(result.stdout)
        assert len(payload["suggestions"]) == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts.py`
Expected: FAIL with `returncode` 1 or 2 because the scripts do not exist yet

- [ ] **Step 3: Write `scripts/import_excel.py`**

```python
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import an order workbook into a SQLite snapshot."
    )
    parser.add_argument("source", help="path to the .xlsx file")
    parser.add_argument(
        "--out", required=True, help="path of the SQLite file to create"
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        print(f"source file not found: {source}", file=sys.stderr)
        return 2

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    rows = read_order_rows(source)
    connection = sqlite3.connect(target, isolation_level=None)
    try:
        report = build_database(rows, connection)
    finally:
        connection.close()

    print(report.summary())
    for warning in report.warnings[:20]:
        print(f"  warning: {warning}")
    if len(report.warnings) > 20:
        print(f"  ... and {len(report.warnings) - 20} more warnings")
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write `scripts/query_cli.py`**

```python
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order_search.search.engine import SearchEngine
from order_search.search.filters import Filters


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query an imported snapshot."
    )
    parser.add_argument("query", nargs="?", default="", help="search text")
    parser.add_argument("--db", required=True, help="path to the SQLite file")
    parser.add_argument("--mode", default="auto",
                        choices=["auto", "customer", "product"])
    parser.add_argument("--store", action="append", default=[])
    parser.add_argument("--order-type", action="append", default=[])
    parser.add_argument("--vip", action="append", default=[])
    parser.add_argument("--dept", action="append", default=[])
    parser.add_argument("--class", dest="class_code", action="append", default=[])
    parser.add_argument("--subclass", dest="subclass_code", action="append", default=[])
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--cursor", default=None)
    parser.add_argument(
        "--suggest", default=None, help="return prefix suggestions instead"
    )
    args = parser.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"database not found: {db}", file=sys.stderr)
        print("run scripts/import_excel.py first", file=sys.stderr)
        return 2

    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        engine = SearchEngine(connection)
        if args.suggest is not None:
            payload = {
                "suggestions": engine.suggest(args.suggest, limit=args.limit)
            }
        else:
            filters = Filters(
                store_code=tuple(args.store),
                order_type=tuple(args.order_type),
                vip_group=tuple(args.vip),
                dept=tuple(int(v) for v in args.dept),
                class_code=tuple(int(v) for v in args.class_code),
                subclass_code=tuple(int(v) for v in args.subclass_code),
                date_from=args.date_from,
                date_to=args.date_to,
            )
            payload = engine.search(
                args.query,
                mode=args.mode,
                filters=filters,
                limit=args.limit,
                cursor=args.cursor,
            )
    finally:
        connection.close()

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Write `scripts/make_fixture.py`**

The real file has one single date on every row, so the date filter cannot be tested against it. This writes a workbook with a spread of dates, which is what makes that test possible.

```python
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order_search.ingest.excel_reader import read_order_rows

HEADER = [
    "Store Code",
    "Order Type",
    "Product Name",
    "NO.",
    "Dept",
    "Class",
    "Subclass",
    "Bar_Code",
    "Customer Name",
    "Item Remark",
    "Item Remark",
    "VIP Customer Groups",
    "Original Expected Date",
]
ORDER_TYPES = [
    "Standard delivery",
    "Scheduled delivery",
    "Express delivery",
    "Pickup",
]
REMARKS = ["โทรแจ้งก่อนส่ง", "แพ็คแยก", "ส่งก่อน 12:00", None]
TIERS = ["VIP", "Gold", "Platinum", "Wholesale VIP", None]


def stamp(start: date, days: int) -> str:
    end = start + timedelta(days=days)
    fmt = "%d-%b-%Y"
    if end == start:
        return start.strftime(fmt)
    return f"{start.strftime(fmt)} - {end.strftime(fmt)}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a synthetic workbook with varied dates."
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--source", default=None,
                        help="workbook to take products and customers from")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    source = Path(args.source) if args.source else (
        Path(__file__).resolve().parents[1]
        / "sample_order_data_1000_records.xlsx"
    )
    if not source.is_file():
        print(f"source not found: {source}", file=sys.stderr)
        return 2

    original = read_order_rows(source)
    products = sorted({row["Product Name"] for row in original})
    customers = sorted({row["Customer Name"] for row in original})
    barcodes: dict[str, list[str]] = {}
    for row in original:
        barcodes.setdefault(row["Product Name"], row["Bar_Code"])
    stores = sorted({str(row["Store Code"]) for row in original})
    hierarchy = {
        row["Product Name"]: (row["Dept"], row["Class"], row["Subclass"])
        for row in original
    }

    rng = random.Random(args.seed)
    base = date(2026, 1, 1)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Order Data"
    sheet.append(HEADER)

    for number in range(1, args.rows + 1):
        product = rng.choice(products)
        dept, klass, sub = hierarchy[product]
        codes = barcodes.get(product) or []
        cell = " || ".join(codes) if codes else ""
        start = base + timedelta(days=rng.randint(0, 300))
        sheet.append(
            [
                rng.choice(stores),
                rng.choice(ORDER_TYPES),
                product,
                number,
                dept,
                klass,
                sub,
                cell,
                rng.choice(customers),
                rng.choice(REMARKS),
                rng.choice(REMARKS),
                rng.choice(TIERS),
                stamp(start, rng.choice([0, 0, 1, 2, 5])),
            ]
        )

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    print(f"wrote {target} with {args.rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The `HEADER` list above repeats `"Item Remark"` twice by mistake. Use this corrected version:

```python
HEADER = [
    "Store Code",
    "Order Type",
    "Product Name",
    "NO.",
    "Dept",
    "Class",
    "Subclass",
    "Bar_Code",
    "Customer Name",
    "Item Remark",
    "VIP Customer Remarks",
    "VIP Customer Groups",
    "Original Expected Date",
]
```

- [ ] **Step 6: Run the script tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts.py`
Expected: PASS, 6 passed

- [ ] **Step 7: Commit**

```powershell
git add scripts tests/test_scripts.py
git commit -m "feat(cli): import, query and fixture generation commands"
```

---

## Task 12: Date filter against varied data, and performance

The real workbook has one date for all 1000 rows, so the date overlap filter is untestable against it. This task builds a fixture and proves the filter works.

**Files:**
- Create: `tests/test_date_filter.py`
- Create: `tests/test_perf.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_date_filter.py`:

```python
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
```

Create `tests/test_perf.py`:

```python
import sqlite3
import time

import pytest

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE

P95_BUDGET_SECONDS = 0.2


@pytest.fixture(scope="module")
def engine():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return SearchEngine(connection)


def measure(engine, query, repeats=20, **kwargs):
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        engine.search(query, **kwargs)
        timings.append(time.perf_counter() - started)
    timings.sort()
    index = max(0, int(round(0.95 * len(timings))) - 1)
    return timings[index]


def test_customer_lookup_is_fast(engine):
    assert measure(engine, "สุรชัย") < P95_BUDGET_SECONDS


def test_barcode_lookup_is_fast(engine):
    assert measure(engine, "8850250001234") < P95_BUDGET_SECONDS


def test_exact_product_is_fast(engine):
    assert measure(engine, "น้ำดื่มสิงห์ 600 มล. x 12") < P95_BUDGET_SECONDS


def test_short_query_is_fast(engine):
    assert measure(engine, "น้ำ") < P95_BUDGET_SECONDS


def test_fuzzy_fallback_is_fast(engine):
    assert measure(engine, "สึงห์") < P95_BUDGET_SECONDS


def test_suggest_is_fast(engine):
    started = time.perf_counter()
    for _ in range(20):
        engine.suggest("น้ำ")
    assert (time.perf_counter() - started) / 20 < P95_BUDGET_SECONDS


def test_search_does_not_write_to_the_database(engine):
    connection = engine.connection
    connection.execute("PRAGMA query_only = ON")
    engine.search("สุรชัย")
    engine.search("น้ำ")
```

- [ ] **Step 2: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_date_filter.py tests/test_perf.py`
Expected: PASS, 13 passed

If `test_date_filter_is_an_overlap_not_a_containment` is skipped because the fixture produced no multi-day ranges, raise `--rows` when generating the fixture or lower the seed variance; do not delete the assertion.

- [ ] **Step 3: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS, no failures. Record the total count.

- [ ] **Step 4: Manually verify the CLI end to end**

```powershell
.\.venv\Scripts\python.exe scripts\import_excel.py sample_order_data_1000_records.xlsx --out build\snapshot.db
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db "สุรชัย"
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db "8850250001234"
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db --suggest "น้ำ"
```

Expected: the first prints a report containing `barcodes       : 127`; the second prints JSON with `"order_count": 65`; the third prints the water product; the fourth lists four suggestions.

- [ ] **Step 5: Write the README**

Create `README.md`:

```markdown
# Order Search Core

Imports the order workbook into a normalized SQLite snapshot and answers two
questions fast, in Thai, on a phone or a terminal:

- what has this customer bought before?
- who bought this product?

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Import the data

```powershell
.\.venv\Scripts\python.exe scripts\import_excel.py sample_order_data_1000_records.xlsx --out build\snapshot.db
```

The report must show `products : 15`, `customers : 20`, `barcodes : 127`.

## Query

```powershell
# by customer name
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db "สุรชัย"

# by barcode
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db "8850250001234"

# product text, with filters
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db --store 101 --order-type Pickup "น้ำดื่มสิงห์ 600 มล. x 12"

# autocomplete suggestions
.\.venv\Scripts\python.exe scripts\query_cli.py --db build\snapshot.db --suggest "น้ำ"
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## How the search works

Queries go through four layers, cheapest first:

1. **Barcode** — digits only, index lookup.
2. **Customer name** — exact match, then `WRatio` fuzzy over 20 names.
3. **Product text** — SQLite FTS5 with the `trigram` tokenizer, which is the
   only built-in tokenizer that can match inside Thai text. The default
   `unicode61` tokenizer returns nothing for a query like `สิงห์`.
4. **Fuzzy products** — only when layer 3 found fewer than five results. A cheap
   pass over the tone-mark-stripped form widens the pool, then every candidate is
   confirmed against the untouched form, because stripping marks can merge
   genuinely different words.

Text is normalized into three columns at import time so queries stay cheap:

| column | rule | example |
|--------|------|---------|
| `name_norm` | NFD; keep letters, digits and marks; drop spaces and punctuation | `น้ำดื่มสิงห์600มลx12` |
| `name_fold_light` | as above, then drop tone marks, thanthakhat, nikhahit; **keep vowels** | `นำดืมสิงห600มลx12` |
| `name_fold_heavy` | NFKD; keep letters, digits and spacing vowels; drop every non-spacing mark | `นาดมสงห600มลx12` |

All three drop spaces and punctuation, so they are parallel views of the same
text. A query is transformed by whichever function built the column it is being
matched against: `norm()` for `name_norm`, `fold_light()` for
`name_fold_light`. Pairing them up wrongly returns zero rows rather than
raising, which is why `tests/test_engine_product.py` has a `TestFoldLayerPairing`
class pinning it.

## Known limits

- A query shorter than three characters cannot use the trigram index; those
  queries fall back to a prefix match.
- Omitting a vowel from a very short query (`กแฟ` for `กาแฟ`) does not reach the
  match threshold. The autocomplete box is the mitigation.
- Customer names are the only customer key in the source file, so two people
  sharing a name are treated as one customer.
- `Original Expected Date` is a delivery window, not an order date, and the
  sample file uses a single date for every row.

## Not in this plan

The web service, login, encryption, audit log and PWA are in a separate plan.
This code has no network surface, which is why it can be tested with plain
`pytest`.
```

- [ ] **Step 6: Run the full suite one more time**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS with no failures

- [ ] **Step 7: Commit**

```powershell
git add README.md tests/test_date_filter.py tests/test_perf.py
git commit -m "test: date filter against varied fixtures and performance budgets"
```

---

## Definition of done

- [ ] `.\.venv\Scripts\python.exe -m pytest` exits 0 with every test passing
- [ ] The import report shows 15 products, 20 customers, 1000 orders, 127 barcodes
- [ ] `query_cli.py "สุรชัย"` reports 65 order lines across 15 products
- [ ] `query_cli.py "8850250001234"` returns `น้ำดื่มสิงห์ 600 มล. x 12` with 20 customers
- [ ] `query_cli.py "สิงห"` and `"สึงห์"` both return that same product
- [ ] `query_cli.py --suggest "น้ำ"` returns exactly 4 suggestions
- [ ] p95 under 200 ms for every query shape in `tests/test_perf.py`
- [ ] No module in `src/order_search/search/` imports from `ingest/`, and no
      module in `ingest/` imports from `search/`

---

## Plan 2 preview

The next plan takes this working core and adds the service layer. It will cover,
in order:

1. snapshot encryption with AES-256-GCM and a `DATA_KEY` from the environment
2. user store with argon2id hashes, JWT access and refresh cookies, TOTP
3. the FastAPI app with `POST /api/v1/search` and `POST /api/v1/suggest`,
   both taking PII in the request body rather than the URL
4. RBAC for `staff` and `admin`, the audit log, and rate limiting
5. `Cache-Control: no-store` on every response carrying customer data
6. the mobile-first PWA reading the same engine
7. Dockerfile and deployment notes for a free-tier host

Two things Plan 1 deliberately leaves easy to change, so Plan 2 does not have to
touch the search code: `SearchEngine` takes a plain `sqlite3.Connection`, and the
filter semantics live in exactly one function.
