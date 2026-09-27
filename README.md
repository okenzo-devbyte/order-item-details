# Order Search

Imports the order workbook into a normalized Postgres dataset and answers two
questions fast, in Thai, on a phone or a terminal:

- what has this customer bought before?
- who bought this product?

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "<your Supabase transaction pooler url>"
```

`DATABASE_URL` must be the Supabase transaction pooler on port **6543**
(`aws-1-ap-southeast-1.pooler.supabase.com`), not the direct connection, which
is IPv6-only. Append `?sslmode=require` to the URL.

## Load the data

```powershell
.\.venv\Scripts\python.exe scripts\load_postgres.py sample_order_data_1000_records.xlsx
```

The report must show `products : 15`, `customers : 20`, `barcodes : 127`.
Each run writes a new `{table}_v{n}` set and repoints the views, so the
previous version stays available.

## Run locally

```powershell
$env:PYTHONPATH = "src"
$env:SECRET_KEY = "dev-secret-change-me-please-32-bytes"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change-me-now"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000`, log in, search. The API lives under `/api/v1`
and `GET /healthz` reports the product/customer/order counts the service is
serving.

### Provision another admin

```powershell
.\.venv\Scripts\python.exe scripts\make_admin.py --username boss --password password123
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## How the search works

Queries go through four layers, cheapest first:

1. **Barcode** — digits only, index lookup.
2. **Customer name** — exact match, then `WRatio` fuzzy over the customer list.
3. **Product text** — a `pg_trgm` substring match over the normalised product
   columns. `LIKE '%query%'` is indexed by a GIN trigram index and works inside
   Thai text without a tokenizer.
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

## Security notes

- Search and suggest are `POST` so customer text never lands in a URL.
- Sessions use httpOnly access/refresh cookies with rotation; the CSRF token is
  read by the app and echoed in the `X-CSRF-Token` header.
- The service worker caches the app shell only, never `/api/`.
