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
matched against.

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
