from __future__ import annotations

import re
import unicodedata

_KEEP_PREFIXES = ("L", "N", "M")
_TONE_MARKS = frozenset("\u0E48\u0E49\u0E4A\u0E4B")
_THANTHAKHAT = "\u0E4C"
_NIKHAHIT = "\u0E4D"
_LIGHT_DROP = _TONE_MARKS | {_THANTHAKHAT, _NIKHAHIT}
# A pack size is an 'x' preceded by a non-Latin-letter boundary, so Latin words
# ending in 'x' ('Max12', 'Complex9') are rejected. The digit run is ASCII-only
# because \d is Unicode-aware and would accept fullwidth digits.
_PACK_RE = re.compile(r"(?<![A-Za-z])x\s*([0-9]+)\s*$")
_DIGITS = frozenset("0123456789")
_BARCODE_SEPARATORS = " -"


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", str(text))


def _nfkd(text: str) -> str:
    """Compatibility decomposition. Used by fold_heavy only — never by norm()
    or fold_light(), whose NFD behaviour is load-bearing for trigram matching.

    Thai 'ำ' (U+0E33 sara am) is a *spacing* character (category Lo) whose
    Unicode decomposition is the compatibility mapping '<compat> 0E4D 0E32'.
    NFD therefore leaves it whole, so a customer who types a plain 'า' for
    'ำ' would not match the real product name. NFKD splits it into a
    non-spacing nikhahit plus 'า', and the heavy fold's Mn filter then absorbs
    the mark.
    """
    return unicodedata.normalize("NFKD", str(text))


def _letters_n_marks(text: str) -> str:
    """Keeps only Unicode categories L, N and M.

    All three levels run through this, so norm/fold_light/fold_heavy are
    parallel views of one text: spaces, punctuation and symbols are removed
    everywhere. Without it the folds would keep whitespace while norm removed
    it, and a norm'd query could never equal a stored fold value.
    """
    return "".join(
        ch for ch in text if unicodedata.category(ch)[0] in _KEEP_PREFIXES
    )


def norm(text: str | None) -> str:
    """Base search form: NFD, keep categories L/N/M, drop whitespace and
    punctuation, lowercase.

    Combining marks (category M) are kept on purpose. pg_trgm and the LIKE
    patterns built from these columns work on character counts, so stripping
    marks would shorten 'น้ำ' from three characters to two and the query would
    silently return nothing.
    """
    if not text:
        return ""
    return _letters_n_marks(_nfd(text)).lower()


def fold_light(text: str | None) -> str:
    """Drops Thai tone marks, thanthakhat and nikhahit but keeps vowels.

    This fixes the two most common typing mistakes — omitting thanthakhat and
    omitting a tone mark — without collapsing words that differ only by vowel.
    """
    if not text:
        return ""
    return "".join(
        ch for ch in _letters_n_marks(_nfd(text)) if ch not in _LIGHT_DROP
    ).lower()


def fold_heavy(text: str | None) -> str:
    """Drops every non-spacing mark (category Mn), vowels included.

    Compatibility decomposition (NFKD, not NFD) is intentional: 'ำ' only
    yields 'า' once it has been split, so a plain-vowel substitution by the
    user still matches. See _nfkd().

    Use this only to widen the candidate pool for fuzzy matching, never as the
    final decision: it can merge genuinely different Thai words.
    """
    if not text:
        return ""
    kept = [
        ch for ch in _nfkd(text) if unicodedata.category(ch) != "Mn"
    ]
    return _letters_n_marks("".join(kept)).lower()


def parse_pack_size(name: str | None) -> int | None:
    """Reads the trailing 'x 12' of a product name.

    This is the pack size, not the quantity sold. Returns None when absent.
    """
    if not name:
        return None
    match = _PACK_RE.search(str(name).strip())
    return int(match.group(1)) if match else None


def digits_only(text: str | None) -> str:
    """Returns the ASCII digits 0-9 of `text` and nothing else.

    Returns '' for anything that contains no ASCII digit, including non-ASCII
    digit lookalikes such as fullwidth '８', Arabic-Indic '٨' and superscript
    '²'. This is deliberate: the lookup column holds ASCII barcodes, so a
    non-ASCII key could never match. Only meaningful as the key builder for a
    query that is_barcode_like has already approved — is_barcode_like applies
    the same ASCII restriction so the two never disagree.
    """
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ch in _DIGITS)


def is_barcode_like(query: str | None) -> bool:
    """True when the query is 8 to 14 ASCII digits, ignoring spaces and dashes.

    The isascii() guard is required, not decorative: str.isdigit() is true for
    878 non-ASCII code points, which digits_only discards, so without it a
    non-ASCII query would be accepted as a barcode and then silently build an
    empty lookup key.
    """
    if not query:
        return False
    compact = "".join(
        ch for ch in str(query) if ch not in _BARCODE_SEPARATORS
    )
    return (
        compact.isascii()
        and compact.isdigit()
        and 8 <= len(compact) <= 14
    )
