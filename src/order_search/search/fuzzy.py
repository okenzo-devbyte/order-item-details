from __future__ import annotations

from rapidfuzz import fuzz, process

from ..db import Reader, Tables
from ..textnorm import norm

# Stage 1 widens the pool cheaply; stage 2 confirms on the untouched base form.
# A stage-1-only answer would be wrong because the heavy fold merges distinct
# Thai words such as มา and ม่า.
#
# STAGE1_CUTOFF is 40, not 45: with the corrected space-free folds a legitimate
# full-prefix query scores 44.4, so 45 would silently drop it. Measured across
# the real catalogue, 40 admits every genuine typo tried while nonsense
# queries still score far below it.
STAGE1_CUTOFF = 40
STAGE1_POOL = 50
FINAL_CUTOFF = 70

# WRatio is required, not a preference. A user types a substring of a name that
# is 20 to 48 characters long, and fuzz.ratio compares full lengths, so
# 'สิงห์' against 'น้ำดื่มสิงห์600มลx12' never reaches the cutoff while WRatio
# does. Verified: ratio gives nothing at 70, partial_ratio 100, WRatio 90.
SCORER = fuzz.WRatio


def best_customers(
    query: str,
    reader: Reader,
    tables: Tables,
    limit: int = 5,
    score_cutoff: int = FINAL_CUTOFF,
) -> list[tuple[int, str, float]]:
    """Returns (customer_id, name_norm, score) best first.

    Names are passed to rapidfuzz as a plain list of strings: passing a list of
    tuples makes every score come out as 0.0, and the return is a 3-tuple
    (value, score, index) that must be destructured accordingly.
    """
    normalized = norm(query)
    if not normalized:
        return []
    rows = reader.all(
        f"SELECT id, name_norm, name_fold_light FROM {tables.customers}"
        " ORDER BY id"
    )
    if not rows:
        return []

    keys = [row["name_fold_light"] for row in rows]
    key_to_id = {row["name_fold_light"]: row["id"] for row in rows}
    id_to_norm = {row["id"]: row["name_norm"] for row in rows}

    matches = process.extract(
        normalized,
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
    reader: Reader,
    tables: Tables,
    limit: int = 5,
    stage1_cutoff: int = STAGE1_CUTOFF,
    final_cutoff: int = FINAL_CUTOFF,
) -> list[tuple[int, str, float]]:
    """Returns (product_id, name_norm, score) best first.

    Two stages: a cheap WRatio pass over the heavy folds widens the pool, then
    every candidate is confirmed with WRatio against the untouched base form.
    The heavy fold is never allowed to decide alone.
    """
    normalized = norm(query)
    if not normalized:
        return []
    rows = reader.all(
        f"SELECT id, name_norm, name_fold_heavy FROM {tables.products}"
        " ORDER BY id"
    )
    if not rows:
        return []

    heavy_keys = [row["name_fold_heavy"] for row in rows]
    index_to_id = {index: row["id"] for index, row in enumerate(rows)}
    id_to_norm = {row["id"]: row["name_norm"] for row in rows}

    widened = process.extract(
        normalized,
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
        confirm = SCORER(normalized, name_norm)
        if confirm >= final_cutoff:
            confirmed.append((product_id, name_norm, float(confirm)))

    confirmed.sort(key=lambda item: (-item[2], item[0]))
    return confirmed[:limit]
