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

## Web service

The API and PWA put the same search core behind HTTP.

### Build the encrypted snapshot

```powershell
$env:DATA_KEY = .\.venv\Scripts\python.exe -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
New-Item -ItemType Directory -Force build | Out-Null
Set-Content -Path build\data_key.txt -Value $env:DATA_KEY -NoNewline
.\.venv\Scripts\python.exe scripts\build_snapshot.py sample_order_data_1000_records.xlsx --out snapshot.enc
```

Keep `DATA_KEY` secret. `snapshot.enc` is ciphertext and may be committed.

### Run locally

```powershell
$env:PYTHONPATH = "src"
$env:DATA_KEY = Get-Content build\data_key.txt
$env:SECRET_KEY = "dev-secret-change-me-please-32-bytes"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change-me-now"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000`, log in, search. The API lives under `/api/v1`
and `GET /healthz` reports whether the snapshot loaded.

### Provision another admin

```powershell
.\.venv\Scripts\python.exe scripts\make_admin.py --db "$env:TEMP\order-search\app.db" --username boss --password password123
```

### Deploy to Render

Push the repository, create the service from `render.yaml`, then set `DATA_KEY`
(the value used to build `snapshot.enc`), `ADMIN_PASSWORD` and `SECRET_KEY` in
the dashboard. Free instances have no persistent disk, so `users` and
`audit_log` reset on redeploy; attach a disk and set `DISK_PATH` to keep them.

### Security notes

- Search and suggest are `POST` so customer text never lands in a URL.
- `snapshot.enc` is decrypted into memory only. The FTS index is rebuilt after
  deserialization so a damaged index still answers queries.
- Sessions use httpOnly access/refresh cookies with rotation; the CSRF token is
  read by the app and echoed in the `X-CSRF-Token` header.
- The service worker caches the app shell only, never `/api/`.

## Testing the web service

```powershell
.\.venv\Scripts\python.exe -m pytest
```
