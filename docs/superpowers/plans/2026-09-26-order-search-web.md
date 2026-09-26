# Order Search Web Service + PWA (Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the tested Plan 1 search core behind a FastAPI service with login, RBAC, audit logging, an encrypted in-memory snapshot, an installable mobile PWA, and a Render deploy.

**Architecture:** One container serves JSON API and static PWA. The AES-256-GCM snapshot is baked into the image at build time, decrypted into memory at boot, deserialized into SQLite, its FTS5 index rebuilt, then locked read-only. Users and audit rows live in a separate writable `app.db`. Every snapshot read goes through one `SnapshotStore` guarded by a single lock.

**Tech Stack:** Python 3.12 (Docker) / 3.14 (dev), FastAPI, uvicorn, pydantic-settings, argon2-cffi, PyJWT, cryptography (AES-GCM), SQLite FTS5 trigram, Vanilla JS PWA, pytest + httpx TestClient.

**Spec:** `docs/superpowers/specs/2026-09-26-order-search-web-design.md`

**Critical validated finding:** `sqlite3.Connection.deserialize()` alone loses the FTS5 index — `MATCH` returns 0 silently. Every loaded snapshot MUST run `INSERT INTO products_fts(products_fts) VALUES('rebuild')` before `PRAGMA query_only=ON`. Task 3 and its tests enforce this.

---

## File Structure

Created in this plan (Plan 1's `src/order_search/**` stays as-is except Task 10's additive engine methods):

- `api/__init__.py` — package marker
- `api/config.py` — `Settings` from env
- `api/crypto.py` — AES-256-GCM seal/open + base64 key loading
- `api/passwords.py` — argon2id hash/verify
- `api/snapshot.py` — `SnapshotStore` (load, rebuild FTS, query surface)
- `api/app_db.py` — writable app database (`AppDB`)
- `api/db_schema.sql` — `users`, `refresh_tokens`, `import_versions`, `audit_log`
- `api/db_helpers.py` — request-state accessors
- `api/users.py` — user CRUD + bootstrap + authenticate
- `api/security.py` — JWT, cookies, refresh rotation, RBAC + CSRF + rate deps
- `api/audit.py` — append-only audit writer/reader
- `api/ratelimit.py` — in-process fixed-window limiter
- `api/imports.py` — xlsx → snapshot bytes helper
- `api/schemas.py` — pydantic request models
- `api/main.py` — app factory, lifespan, middleware, router wiring, static mount
- `api/routers/__init__.py`, `auth.py`, `search.py`, `filters.py`, `admin.py`
- `web/index.html`, `web/app.js`, `web/styles.css`, `web/manifest.webmanifest`, `web/sw.js`, `web/icons/icon.svg`
- `scripts/build_snapshot.py`, `scripts/make_admin.py`
- `Dockerfile`, `.dockerignore`, `render.yaml`
- `tests/test_crypto.py`, `test_snapshot_store.py`, `test_passwords.py`, `test_security.py`, `test_ratelimit.py`, `test_audit.py`, `test_api_boot.py`, `test_api_auth.py`, `test_api_search.py`, `test_api_admin.py`, `test_pwa.py`, `test_config.py`
- Modified: `requirements.txt`, `tests/conftest.py`, `README.md`, and additive methods in `src/order_search/search/engine.py` (Task 9)

---

## Conventions

- All shell commands run from `D:\Project_AI\order-item-details`.
- Python: `.\.venv\Scripts\python.exe`. Tests: `.\.venv\Scripts\python.exe -m pytest`.
- Every commit message follows the existing repo style (`feat(...)`, `test(...)`, `fix(...)`, `docs(...)`).
- Do NOT add comments unless the surrounding file already uses them.

---

### Task 1: Dependencies and Settings

**Files:**
- Create: `api/__init__.py`
- Create: `api/config.py`
- Modify: `requirements.txt`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.7
pydantic-settings>=2.3
argon2-cffi>=23.1
PyJWT>=2.8
httpx>=0.27
python-multipart>=0.0.9
```

- [ ] **Step 2: Install them**

Run: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: ends with `Successfully installed ...` (or "already satisfied").

- [ ] **Step 3: Write the failing test**

`tests/test_config.py`:

```python
from api.config import Settings


def test_defaults_are_dev_safe():
    settings = Settings()
    assert settings.cookie_secure is False
    assert settings.persistent is False
    assert settings.access_ttl_minutes == 15


def test_disk_path_makes_it_persistent(tmp_path):
    settings = Settings(disk_path=str(tmp_path))
    assert settings.persistent is True
    assert settings.data_dir == tmp_path
    assert settings.app_db_path == tmp_path / "app.db"
    assert settings.versions_dir == tmp_path / "versions"


def test_without_disk_path_it_uses_temp_dir():
    settings = Settings(disk_path="")
    assert settings.persistent is False
    assert settings.app_db_path.parent == settings.data_dir


def test_env_overrides_field(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    settings = Settings()
    assert settings.rate_limit_per_minute == 7
    assert settings.cookie_secure is True
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api'`.

- [ ] **Step 5: Write the implementation**

`api/__init__.py`: empty file.

`api/config.py`:

```python
from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-insecure-secret-change-me"
    data_key: str = ""
    data_key_id: str = "v1"
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    snapshot_path: str = "build/snapshot.enc"
    disk_path: str = ""
    cookie_secure: bool = False
    allowed_hosts: str = "*"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 7
    idle_timeout_minutes: int = 30
    rate_limit_per_minute: int = 60
    max_upload_bytes: int = 20 * 1024 * 1024

    @property
    def persistent(self) -> bool:
        return bool(self.disk_path)

    @property
    def data_dir(self) -> Path:
        if self.disk_path:
            return Path(self.disk_path)
        return Path(tempfile.gettempdir()) / "order-search"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def versions_dir(self) -> Path:
        return self.data_dir / "versions"

    @property
    def snapshot_file(self) -> Path:
        return Path(self.snapshot_path)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt api/__init__.py api/config.py tests/test_config.py
git commit -m "feat(api): add web dependencies and env-backed settings"
```

---

### Task 2: AES-256-GCM Snapshot Crypto

**Files:**
- Create: `api/crypto.py`
- Test: `tests/test_crypto.py`

- [ ] **Step 1: Write the failing test**

`tests/test_crypto.py`:

```python
import base64

import pytest

from api.crypto import DecryptionError, load_key, open_sealed, seal

RAW_KEY = bytes(range(32))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def test_roundtrip():
    blob = seal(b"hello snapshot", RAW_KEY, "v1")
    assert open_sealed(blob, {"v1": RAW_KEY}) == b"hello snapshot"


def test_nonce_differs_between_calls():
    first = seal(b"same", RAW_KEY, "v1")
    second = seal(b"same", RAW_KEY, "v1")
    assert first != second


def test_tampered_ciphertext_is_rejected():
    blob = seal(b"hello", RAW_KEY, "v1")
    tampered = blob.replace(b'"ct":"', b'"ct":"A')
    with pytest.raises(DecryptionError):
        open_sealed(tampered, {"v1": RAW_KEY})


def test_wrong_key_is_rejected():
    blob = seal(b"hello", RAW_KEY, "v1")
    with pytest.raises(DecryptionError):
        open_sealed(blob, {"v1": bytes(32)})


def test_unknown_key_id_is_rejected():
    blob = seal(b"hello", RAW_KEY, "v1")
    with pytest.raises(DecryptionError):
        open_sealed(blob, {"other": RAW_KEY})


def test_load_key_requires_32_bytes():
    with pytest.raises(ValueError):
        load_key(b64(b"short"))
    assert load_key(b64(RAW_KEY)) == RAW_KEY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.crypto'`.

- [ ] **Step 3: Write the implementation**

`api/crypto.py`:

```python
from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"OSNC1"
NONCE_BYTES = 12
KEY_BYTES = 32


class DecryptionError(Exception):
    """Raised when a sealed snapshot cannot be opened."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_key(encoded: str) -> bytes:
    key = _b64d(encoded)
    if len(key) != KEY_BYTES:
        raise ValueError(f"data key must be {KEY_BYTES} bytes, got {len(key)}")
    return key


def seal(plaintext: bytes, key: bytes, key_id: str = "v1") -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    aad = MAGIC + key_id.encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return json.dumps(
        {"key_id": key_id, "nonce": _b64e(nonce), "ct": _b64e(ct)}
    ).encode("utf-8")


def open_sealed(blob: bytes, keyring: dict[str, bytes]) -> bytes:
    try:
        envelope = json.loads(blob)
        key_id = envelope["key_id"]
        key = keyring[key_id]
        aad = MAGIC + key_id.encode("utf-8")
        return AESGCM(key).decrypt(
            _b64d(envelope["nonce"]), _b64d(envelope["ct"]), aad
        )
    except (KeyError, ValueError, TypeError, InvalidTag) as exc:
        raise DecryptionError("snapshot could not be decrypted") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_crypto.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add api/crypto.py tests/test_crypto.py
git commit -m "feat(api): aes-256-gcm envelope for the encrypted snapshot"
```

---

### Task 3: App Database, Schema, Passwords and Users

**Files:**
- Create: `api/db_schema.sql`
- Create: `api/app_db.py`
- Create: `api/passwords.py`
- Create: `api/users.py`
- Test: `tests/test_passwords.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_passwords.py`:

```python
import sqlite3

from api.app_db import AppDB
from api.passwords import hash_password, verify_password
from api.users import (
    authenticate,
    bootstrap_admin,
    create_user,
    get_by_username,
    list_users,
    update_user,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "wrong")


def test_create_and_authenticate(tmp_path):
    db = AppDB(tmp_path / "app.db")
    create_user(db, "somchai", "password123", "staff")
    assert authenticate(db, "somchai", "password123")["username"] == "somchai"
    assert authenticate(db, "somchai", "nope") is None
    db.close()


def test_inactive_user_cannot_authenticate(tmp_path):
    db = AppDB(tmp_path / "app.db")
    user_id = create_user(db, "somchai", "password123", "staff")
    update_user(db, user_id, is_active=False)
    assert authenticate(db, "somchai", "password123") is None
    db.close()


def test_username_is_unique(tmp_path):
    db = AppDB(tmp_path / "app.db")
    create_user(db, "somchai", "password123", "staff")
    try:
        create_user(db, "somchai", "password456", "staff")
        assert False, "duplicate username should fail"
    except sqlite3.IntegrityError:
        pass
    db.close()


def test_bootstrap_admin_only_once(tmp_path):
    db = AppDB(tmp_path / "app.db")
    assert bootstrap_admin(db, "admin", "change-me-now") is True
    assert bootstrap_admin(db, "admin2", "change-me-now") is False
    assert get_by_username(db, "admin")["role"] == "admin"
    db.close()


def test_list_and_update_role(tmp_path):
    db = AppDB(tmp_path / "app.db")
    user_id = create_user(db, "ana", "password123", "staff")
    update_user(db, user_id, role="admin")
    row = [u for u in list_users(db) if u["id"] == user_id][0]
    assert row["role"] == "admin"
    assert row["is_active"] == 1
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.app_db'`.

- [ ] **Step 3: Write the schema**

`api/db_schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('staff','admin')),
    totp_secret   TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    issued_at    TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    revoked      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS import_versions (
    id             INTEGER PRIMARY KEY,
    path           TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    row_count      INTEGER,
    product_count  INTEGER,
    customer_count INTEGER,
    is_current     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    created_by     INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER,
    action       TEXT NOT NULL,
    query        TEXT,
    mode         TEXT,
    result_count INTEGER,
    ip           TEXT,
    user_agent   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
```

- [ ] **Step 4: Write the implementation**

`api/passwords.py`:

```python
from __future__ import annotations

from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except Exception:
        return False
```

`api/app_db.py`:

```python
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).with_name("db_schema.sql")


class AppDB:
    """The writable database: users, refresh tokens, versions, audit log."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.lock = threading.Lock()

    def run(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.lock:
            cursor = self.conn.execute(sql, tuple(params))
            return cursor.lastrowid

    def query_one(self, sql: str, params: Iterable[Any] = ()):
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def query_all(self, sql: str, params: Iterable[Any] = ()):
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def close(self) -> None:
        with self.lock:
            self.conn.close()
```

`api/users.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from .app_db import AppDB
from .passwords import hash_password, verify_password

ROLES = ("staff", "admin")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_by_username(db: AppDB, username: str):
    return db.query_one("SELECT * FROM users WHERE username = ?", (username,))


def get_by_id(db: AppDB, user_id: int):
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def create_user(db: AppDB, username: str, password: str, role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    return db.run(
        "INSERT INTO users (username, password_hash, role, is_active, created_at)"
        " VALUES (?,?,?,1,?)",
        (username, hash_password(password), role, _now()),
    )


def authenticate(db: AppDB, username: str, password: str):
    row = get_by_username(db, username)
    if row is None or not row["is_active"]:
        return None
    if not verify_password(row["password_hash"], password):
        return None
    return row


def list_users(db: AppDB):
    return db.query_all(
        "SELECT id, username, role, is_active, created_at FROM users ORDER BY id"
    )


def update_user(
    db: AppDB,
    user_id: int,
    *,
    password: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> bool:
    if get_by_id(db, user_id) is None:
        return False
    if password is not None:
        db.run(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        db.run("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if is_active is not None:
        db.run(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
    return True


def bootstrap_admin(db: AppDB, username: str, password: str) -> bool:
    row = db.query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
    if row["n"]:
        return False
    create_user(db, username, password, "admin")
    return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_passwords.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add api/db_schema.sql api/app_db.py api/passwords.py api/users.py tests/test_passwords.py
git commit -m "feat(api): app database, argon2id passwords and user store"
```

---

### Task 4: SnapshotStore (with mandatory FTS rebuild)

This is the highest-risk component: `deserialize()` alone loses the FTS index, so a golden query is asserted through the store.

**Files:**
- Create: `api/snapshot.py`
- Modify: `src/order_search/search/engine.py` (additive public wrappers only)
- Modify: `tests/conftest.py` (add project root to `sys.path` so `api` imports)
- Test: `tests/test_snapshot_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_snapshot_store.py`:

```python
import sqlite3

import pytest

from api.crypto import DecryptionError, seal
from api.snapshot import SnapshotStore
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine

from conftest import DATA_FILE

RAW_KEY = bytes(range(32))
KEY_ID = "v1"


def make_plaintext_snapshot() -> bytes:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    blob = connection.serialize()
    connection.close()
    return blob


def make_store(tmp_path, plaintext):
    path = tmp_path / "snapshot.enc"
    path.write_bytes(seal(plaintext, RAW_KEY, KEY_ID))
    store = SnapshotStore({KEY_ID: RAW_KEY}, KEY_ID)
    store.load_file(path)
    return store


def test_deserialize_alone_would_lose_fts():
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    bare.deserialize(make_plaintext_snapshot())
    hits = bare.execute(
        "SELECT count(*) AS n FROM products_fts WHERE name_norm MATCH ?",
        ("สิงห์",),
    ).fetchone()["n"]
    bare.close()
    assert hits == 0


def _reference_connection(plaintext):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.deserialize(plaintext)
    connection.execute("INSERT INTO products_fts(products_fts) VALUES('rebuild')")
    connection.execute("PRAGMA query_only=ON")
    return connection


def test_customer_search_matches_direct_engine(tmp_path):
    plaintext = make_plaintext_snapshot()
    store = make_store(tmp_path, plaintext)
    through_store = store.search("สุรชัย")
    reference = SearchEngine(_reference_connection(plaintext)).search("สุรชัย")
    assert through_store["customers"][0]["name"] == "สุรชัย"
    assert (
        through_store["customers"][0]["order_count"]
        == reference["customers"][0]["order_count"]
    )


def test_barcode_search_works_after_load(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    result = store.search("8850250001234")
    assert result["products"]
    assert result["products"][0]["name"].startswith("น้ำดื่มสิงห์")


def test_short_thai_query_works_after_load(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    assert len(store.search("น้ำ")["products"]) == 4


def test_connection_is_read_only(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    with pytest.raises(sqlite3.OperationalError):
        store.connection.execute("DELETE FROM products")


def test_customer_history_and_product_customers(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    history = store.customer_history(1)
    assert history and history[0]["products"]
    buyers = store.product_customers(1)
    assert buyers and buyers[0]["customers"]


def test_facets_and_counts(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    facets = store.facets()
    assert len(facets["store_code"]) == 15
    assert "Standard delivery" in facets["order_type"]
    counts = store.counts()
    assert counts["products"] == 15
    assert counts["customers"] == 20


def test_replace_with_bytes_swaps_data(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    empty = sqlite3.connect(":memory:", isolation_level=None)
    empty.row_factory = sqlite3.Row
    empty.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)")
    empty.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    empty.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
    empty.execute("CREATE TABLE order_items (order_id INTEGER, product_id INTEGER)")
    empty.execute("CREATE TABLE product_barcodes (product_id INTEGER, barcode TEXT)")
    empty.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    empty.execute(
        "CREATE VIRTUAL TABLE products_fts USING fts5("
        "name_norm, name_fold_light, product_id UNINDEXED, tokenize='trigram')"
    )
    empty.execute("INSERT INTO products (id, name) VALUES (1, 'ของใหม่')")
    empty.execute(
        "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
        " VALUES ('ของใหม่', 'ของใหม่', 1)"
    )
    store.replace_with_bytes(empty.serialize())
    empty.close()
    row = store.connection.execute("SELECT name FROM products").fetchone()
    assert row["name"] == "ของใหม่"


def test_wrong_key_fails_to_load(tmp_path):
    path = tmp_path / "snapshot.enc"
    path.write_bytes(seal(make_plaintext_snapshot(), RAW_KEY, KEY_ID))
    store = SnapshotStore({"v1": bytes(32)}, KEY_ID)
    with pytest.raises(DecryptionError):
        store.load_file(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.snapshot'`.

- [ ] **Step 3: Write the implementation**

`api/snapshot.py`:

```python
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from order_search.search.engine import SearchEngine

from . import crypto

FACET_COLUMNS = {
    "store_code": ("orders", "store_code"),
    "order_type": ("orders", "order_type"),
    "vip_group": ("orders", "vip_group"),
    "dept": ("products", "dept"),
    "class_code": ("products", "class_code"),
    "subclass_code": ("products", "subclass_code"),
}


class SnapshotStore:
    """Owns the decrypted snapshot connection and every read against it.

    The connection is built once, held in memory only, and shared behind a
    single lock. Callers never touch it directly.
    """

    def __init__(self, keyring: dict[str, bytes], key_id: str = "v1") -> None:
        self._keyring = keyring
        self._key_id = key_id
        self._connection: sqlite3.Connection | None = None
        self.lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._connection is not None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("snapshot is not loaded")
        return self._connection

    @staticmethod
    def _build(plaintext: bytes) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.deserialize(plaintext)
        connection.execute(
            "INSERT INTO products_fts(products_fts) VALUES('rebuild')"
        )
        connection.execute("PRAGMA query_only=ON")
        return connection

    def replace_with_bytes(self, plaintext: bytes) -> None:
        fresh = self._build(plaintext)
        with self.lock:
            previous, self._connection = self._connection, fresh
        if previous is not None:
            previous.close()

    def load_file(self, path: str | Path) -> None:
        plaintext = crypto.open_sealed(Path(path).read_bytes(), self._keyring)
        self.replace_with_bytes(plaintext)

    def _engine(self) -> SearchEngine:
        return SearchEngine(self.connection)

    def search(self, **kwargs: Any) -> dict[str, Any]:
        with self.lock:
            return self._engine().search(**kwargs)

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        with self.lock:
            return self._engine().suggest(query, limit=limit)

    def customer_history(self, customer_id: int, filters: Any = None):
        with self.lock:
            return self._engine().customer_history(customer_id, filters)

    def product_customers(self, product_id: int, filters: Any = None):
        with self.lock:
            return self._engine().product_customers(product_id, filters)

    def facets(self) -> dict[str, list]:
        out: dict[str, list] = {}
        with self.lock:
            for name, (table, column) in FACET_COLUMNS.items():
                rows = self.connection.execute(
                    f"SELECT DISTINCT {column} AS v FROM {table}"
                    f" WHERE {column} IS NOT NULL ORDER BY {column}"
                ).fetchall()
                out[name] = [row["v"] for row in rows]
        return out

    def counts(self) -> dict[str, int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT key, value FROM meta"
            ).fetchall()
        return {row["key"]: int(row["value"]) for row in rows}

    def close(self) -> None:
        with self.lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
```

- [ ] **Step 4: Add the additive public engine wrappers**

In `src/order_search/search/engine.py`, immediately after the `suggest` method (the method starting at line 157 and ending near line 179) insert:

```python
    def customer_history(
        self, customer_id: int, filters: Any = None
    ) -> list[dict[str, Any]]:
        """Public wrapper for a single customer's purchase history."""
        return self._customer_results([customer_id], _as_filters(filters))

    def product_customers(
        self, product_id: int, filters: Any = None
    ) -> list[dict[str, Any]]:
        """Public wrapper for the customers of a single product."""
        return self._product_results([product_id], _as_filters(filters), 1, 0)
```

- [ ] **Step 5: Update conftest so tests can import `api`**

`tests/conftest.py` becomes:

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (str(ROOT), str(SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

DATA_FILE = ROOT / "sample_order_data_1000_records.xlsx"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_store.py -v`
Expected: PASS (9 passed).

- [ ] **Step 7: Run the full existing suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS (all Plan 1 tests still green plus the new ones).

- [ ] **Step 8: Commit**

```bash
git add api/snapshot.py src/order_search/search/engine.py tests/conftest.py tests/test_snapshot_store.py
git commit -m "feat(api): in-memory snapshot store with mandatory fts rebuild"
```

---

### Task 5: Audit Log and Rate Limiter

**Files:**
- Create: `api/audit.py`
- Create: `api/ratelimit.py`
- Test: `tests/test_audit.py`
- Test: `tests/test_ratelimit.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_audit.py`:

```python
from api.app_db import AppDB
from api.audit import list_entries, record


def test_record_and_list(tmp_path):
    db = AppDB(tmp_path / "app.db")
    record(db, action="search", user_id=None, query="สุรชัย", mode="customer", result_count=1)
    record(db, action="login_failed", query="admin")
    entries = list_entries(db)
    assert len(entries) == 2
    assert entries[0]["action"] == "login_failed"
    assert entries[1]["query"] == "สุรชัย"
    db.close()


def test_filters(tmp_path):
    db = AppDB(tmp_path / "app.db")
    record(db, action="search", user_id=1, query="a")
    record(db, action="import", user_id=1)
    assert len(list_entries(db, action="search")) == 1
    assert len(list_entries(db, user_id=1)) == 2
    assert len(list_entries(db, action="nope")) == 0
    db.close()


def test_before_id_pagination(tmp_path):
    db = AppDB(tmp_path / "app.db")
    for i in range(5):
        record(db, action="search", query=str(i))
    page = list_entries(db, limit=2)
    assert len(page) == 2
    older = list_entries(db, limit=10, before_id=page[-1]["id"])
    assert all(entry["id"] < page[-1]["id"] for entry in older)
    db.close()
```

`tests/test_ratelimit.py`:

```python
from api.ratelimit import RateLimiter


def test_allows_up_to_limit():
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert limiter.allow("u1", now=0)
    assert limiter.allow("u1", now=1)
    assert limiter.allow("u1", now=2)
    assert not limiter.allow("u1", now=3)


def test_window_slides():
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("u1", now=0)
    assert limiter.allow("u1", now=1)
    assert not limiter.allow("u1", now=2)
    assert limiter.allow("u1", now=61)


def test_keys_are_independent():
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("u1", now=0)
    assert not limiter.allow("u1", now=0)
    assert limiter.allow("u2", now=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit.py tests/test_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.audit'`.

- [ ] **Step 3: Write the implementation**

`api/audit.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .app_db import AppDB


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(
    db: AppDB,
    *,
    action: str,
    user_id: int | None = None,
    query: str | None = None,
    mode: str | None = None,
    result_count: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.run(
        "INSERT INTO audit_log (user_id, action, query, mode, result_count, ip,"
        " user_agent, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, action, query, mode, result_count, ip, user_agent, _now()),
    )


def list_entries(
    db: AppDB,
    *,
    limit: int = 100,
    before_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if before_id is not None:
        clauses.append("id < ?")
        params.append(before_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.query_all(
        "SELECT * FROM audit_log" + where + " ORDER BY id DESC LIMIT ?",
        (*params, limit),
    )
    return [dict(row) for row in rows]
```

`api/ratelimit.py`:

```python
from __future__ import annotations

import threading
import time


class RateLimiter:
    """Fixed-window limiter held in process memory (single container)."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_audit.py tests/test_ratelimit.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add api/audit.py api/ratelimit.py tests/test_audit.py tests/test_ratelimit.py
git commit -m "feat(api): append-only audit log and in-process rate limiter"
```

### Task 6: Security (JWT, cookies, RBAC, CSRF, rate deps)

**Files:**
- Create: `api/db_helpers.py`
- Create: `api/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: Write the failing test**

`tests/test_security.py`:

```python
from datetime import timedelta

import pytest

from api import security
from api.app_db import AppDB
from api.users import create_user, get_by_id

SECRET = "test-secret"


def make_db_with_user(tmp_path):
    db = AppDB(tmp_path / "app.db")
    user_id = create_user(db, "somchai", "password123", "admin")
    return db, get_by_id(db, user_id)


def test_issue_and_decode_access(tmp_path):
    db, user = make_db_with_user(tmp_path)
    access, _ = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    payload = security.decode_token(SECRET, access, security.ACCESS)
    assert payload["sub"] == str(user["id"])
    assert payload["role"] == "admin"
    db.close()


def test_expired_access_is_rejected(tmp_path):
    db, user = make_db_with_user(tmp_path)
    access, _ = security.issue_session(
        db, SECRET, user, timedelta(seconds=-1), timedelta(days=7)
    )
    with pytest.raises(security.InvalidToken):
        security.decode_token(SECRET, access, security.ACCESS)
    db.close()


def test_wrong_type_is_rejected(tmp_path):
    db, user = make_db_with_user(tmp_path)
    access, _ = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    with pytest.raises(security.InvalidToken):
        security.decode_token(SECRET, access, security.REFRESH)
    db.close()


def test_refresh_rotation_revokes_old_token(tmp_path):
    db, user = make_db_with_user(tmp_path)
    _, refresh = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    security.rotate_refresh(
        db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
        timedelta(minutes=30),
    )
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
            timedelta(minutes=30),
        )
    db.close()


def test_idle_timeout_revokes(tmp_path):
    db, user = make_db_with_user(tmp_path)
    _, refresh = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    db.run(
        "UPDATE refresh_tokens SET last_used_at = ?",
        ("2000-01-01T00:00:00Z",),
    )
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
            timedelta(minutes=30),
        )
    db.close()


def test_revoke_all_for_user(tmp_path):
    db, user = make_db_with_user(tmp_path)
    _, refresh = security.issue_session(
        db, SECRET, user, timedelta(minutes=15), timedelta(days=7)
    )
    security.revoke_all_for_user(db, user["id"])
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, SECRET, refresh, timedelta(minutes=15), timedelta(days=7),
            timedelta(minutes=30),
        )
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.security'`.

- [ ] **Step 3: Write the request-state helpers**

`api/db_helpers.py`:

```python
from __future__ import annotations

from fastapi import Request

from .app_db import AppDB
from .config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_app_db(request: Request) -> AppDB:
    return request.app.state.app_db


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
```

- [ ] **Step 4: Write the implementation**

`api/security.py`:

```python
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, Response

from . import users
from .db_helpers import get_app_db, get_settings

ACCESS = "access"
REFRESH = "refresh"
ALGORITHM = "HS256"
COOKIE_ACCESS = "access_token"
COOKIE_REFRESH = "refresh_token"
COOKIE_CSRF = "csrf_token"


class InvalidToken(Exception):
    """Raised when a token is missing, expired, malformed or revoked."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


def encode_token(
    secret: str,
    user_id: int,
    role: str,
    token_type: str,
    ttl: timedelta,
    jti: str | None = None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(secret: str, token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidToken("wrong token type")
    return payload


def issue_session(db, secret, user, access_ttl, refresh_ttl) -> tuple[str, str]:
    access = encode_token(secret, user["id"], user["role"], ACCESS, access_ttl)
    jti = uuid.uuid4().hex
    refresh = encode_token(
        secret, user["id"], user["role"], REFRESH, refresh_ttl, jti=jti
    )
    now = _now()
    db.run(
        "INSERT INTO refresh_tokens (id, user_id, issued_at, expires_at,"
        " last_used_at, revoked) VALUES (?,?,?,?,?,0)",
        (jti, user["id"], _iso(now), _iso(now + refresh_ttl), _iso(now)),
    )
    return access, refresh


def rotate_refresh(
    db, secret, token, access_ttl, refresh_ttl, idle_timeout
) -> tuple[str, str]:
    payload = decode_token(secret, token, REFRESH)
    jti = payload.get("jti")
    row = db.query_one("SELECT * FROM refresh_tokens WHERE id = ?", (jti,))
    if row is None or row["revoked"]:
        raise InvalidToken("refresh token revoked")
    if _now() - _parse_iso(row["last_used_at"]) > idle_timeout:
        db.run("UPDATE refresh_tokens SET revoked = 1 WHERE id = ?", (jti,))
        raise InvalidToken("session idle timeout")
    user = users.get_by_id(db, int(payload["sub"]))
    if user is None or not user["is_active"]:
        raise InvalidToken("user inactive")
    db.run("UPDATE refresh_tokens SET revoked = 1 WHERE id = ?", (jti,))
    return issue_session(db, secret, user, access_ttl, refresh_ttl)


def revoke_refresh(db, secret, token: str | None) -> None:
    if not token:
        return
    try:
        payload = decode_token(secret, token, REFRESH)
    except InvalidToken:
        return
    jti = payload.get("jti")
    if jti:
        db.run("UPDATE refresh_tokens SET revoked = 1 WHERE id = ?", (jti,))


def revoke_all_for_user(db, user_id: int) -> None:
    db.run("UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?", (user_id,))


def set_auth_cookies(response: Response, settings, access: str, refresh: str) -> None:
    secure = settings.cookie_secure
    response.set_cookie(
        COOKIE_ACCESS,
        access,
        max_age=settings.access_ttl_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        COOKIE_REFRESH,
        refresh,
        max_age=settings.refresh_ttl_days * 86400,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        COOKIE_CSRF,
        secrets.token_urlsafe(32),
        max_age=settings.refresh_ttl_days * 86400,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    for name in (COOKIE_ACCESS, COOKIE_REFRESH, COOKIE_CSRF):
        response.delete_cookie(name, path="/")


def _user_from_request(request: Request):
    settings = get_settings(request)
    db = get_app_db(request)
    token = request.cookies.get(COOKIE_ACCESS)
    if not token:
        raise HTTPException(401, "not authenticated")
    try:
        payload = decode_token(settings.secret_key, token, ACCESS)
    except InvalidToken:
        raise HTTPException(401, "invalid or expired token") from None
    user = users.get_by_id(db, int(payload["sub"]))
    if user is None or not user["is_active"]:
        raise HTTPException(401, "account disabled")
    return user


def require_staff(request: Request):
    return _user_from_request(request)


def require_admin(request: Request):
    user = _user_from_request(request)
    if user["role"] != "admin":
        raise HTTPException(403, "admin role required")
    return user


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(COOKIE_CSRF)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(403, "csrf token missing or invalid")


def rate_limit(request: Request, user=Depends(require_staff)):
    limiter = request.app.state.rate_limiter
    if not limiter.allow(f"user:{user['id']}"):
        raise HTTPException(429, "rate limit exceeded")
    return user


def login_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    ip = request.client.host if request.client else "anonymous"
    if not limiter.allow(f"ip:{ip}"):
        raise HTTPException(429, "rate limit exceeded")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_security.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add api/db_helpers.py api/security.py tests/test_security.py
git commit -m "feat(api): jwt sessions, refresh rotation, rbac and csrf deps"
```

---

### Task 7: Schemas and App Factory

**Files:**
- Create: `api/schemas.py`
- Create: `api/main.py`
- Create: `api/routers/__init__.py`
- Test: `tests/test_api_boot.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_boot.py`:

```python
import base64
import sqlite3

from fastapi.testclient import TestClient

from api.config import Settings
from api.crypto import seal
from api.main import create_app
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows

from conftest import DATA_FILE

RAW_KEY = bytes(range(32))
KEY_ID = "v1"


def make_settings(tmp_path) -> Settings:
    snapshot = tmp_path / "snapshot.enc"
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    snapshot.write_bytes(seal(connection.serialize(), RAW_KEY, KEY_ID))
    connection.close()
    return Settings(
        secret_key="test-secret",
        data_key=base64.urlsafe_b64encode(RAW_KEY).decode("ascii"),
        data_key_id=KEY_ID,
        snapshot_path=str(snapshot),
        disk_path=str(tmp_path / "data"),
        admin_username="admin",
        admin_password="change-me-now",
    )


def test_healthz_is_ok(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["snapshot"] is True


def test_security_headers_are_present(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_api_responses_are_no_store(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "x", "password": "y"}
        )
    assert response.headers["cache-control"] == "no-store"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_boot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.schemas'`.

- [ ] **Step 3: Write the schemas**

`api/schemas.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FilterModel(BaseModel):
    store_code: list[str] = Field(default_factory=list)
    order_type: list[str] = Field(default_factory=list)
    vip_group: list[str] = Field(default_factory=list)
    dept: list[int] = Field(default_factory=list)
    class_code: list[int] = Field(default_factory=list)
    subclass_code: list[int] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SearchRequest(BaseModel):
    q: str = Field(default="", max_length=200)
    mode: Literal["auto", "customer", "product"] = "auto"
    filters: FilterModel | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class SuggestRequest(BaseModel):
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=8, ge=1, le=20)


class RollbackRequest(BaseModel):
    version_id: int


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["staff", "admin"] = "staff"


class UserPatchRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Literal["staff", "admin"] | None = None
    is_active: bool | None = None
```

- [ ] **Step 4: Write the router skeleton**

`api/routers/__init__.py`: empty file.

`api/routers/auth.py`, `api/routers/search.py`, `api/routers/filters.py`, `api/routers/admin.py` each contain exactly:

```python
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 5: Write the app factory**

`api/main.py`:

```python
from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import crypto
from .app_db import AppDB
from .config import Settings
from .ratelimit import RateLimiter
from .snapshot import SnapshotStore
from .users import bootstrap_admin

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
logger = logging.getLogger("order_search")


def _assert_fts5_supported() -> None:
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        probe.execute("INSERT INTO t VALUES ('ทดสอบ')")
        probe.execute("SELECT rowid FROM t WHERE x MATCH 'ทดสอบ'").fetchall()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "this SQLite build lacks FTS5 trigram support"
        ) from exc
    finally:
        probe.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    _assert_fts5_supported()

    keyring = {settings.data_key_id: crypto.load_key(settings.data_key)}
    snapshot = SnapshotStore(keyring, settings.data_key_id)
    snapshot.load_file(settings.snapshot_file)
    app.state.snapshot = snapshot

    db = AppDB(settings.app_db_path)
    app.state.app_db = db
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    if bootstrap_admin(db, settings.admin_username, settings.admin_password):
        logger.info("bootstrap admin account created")
    try:
        yield
    finally:
        snapshot.close()
        db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Order Search",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.allowed_hosts and settings.allowed_hosts != "*":
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[
                host.strip()
                for host in settings.allowed_hosts.split(",")
                if host.strip()
            ],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.middleware("http")
    async def csrf_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None and request.url.hostname not in origin:
                return JSONResponse(
                    {"detail": "cross-origin request blocked"}, status_code=403
                )
        return await call_next(request)

    @app.get("/healthz")
    def healthz():
        snapshot = getattr(app.state, "snapshot", None)
        return {
            "status": "ok",
            "snapshot": snapshot is not None and snapshot.loaded,
        }

    from .routers import admin, auth, filters, search

    app.include_router(auth.router)
    app.include_router(search.router)
    app.include_router(filters.router)
    app.include_router(admin.router)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_boot.py -v`
Expected: PASS (3 passed). Login returns 404 but still carries `no-store`, so the third test passes.

- [ ] **Step 7: Run the full suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/schemas.py api/main.py api/routers/__init__.py api/routers/auth.py api/routers/search.py api/routers/filters.py api/routers/admin.py tests/test_api_boot.py
git commit -m "feat(api): app factory with lifespan, security headers and router skeleton"
```

---

### Task 8: Auth Router

**Files:**
- Modify: `api/routers/auth.py`
- Test: `tests/test_api_auth.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_auth.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


def login(client, username="admin", password="change-me-now"):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_login_sets_cookies_and_returns_user(client):
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies
    assert "csrf_token" in response.cookies


def test_login_rejects_bad_password(client):
    assert login(client, password="wrong").status_code == 401


def test_me_requires_login(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_current_user(client):
    login(client)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_clears_session(client):
    login(client)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_refresh_keeps_session_alive(client):
    login(client)
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_refresh_without_cookie_is_401(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as fresh:
        assert fresh.post("/api/v1/auth/refresh").status_code == 401


def test_login_is_rate_limited(tmp_path):
    settings = make_settings(tmp_path)
    limited = Settings(**{**settings.model_dump(), "rate_limit_per_minute": 2})
    with TestClient(create_app(limited)) as app_client:
        assert login(app_client, password="wrong").status_code == 401
        assert login(app_client, password="wrong").status_code == 401
        assert login(app_client, password="wrong").status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_auth.py -v`
Expected: FAIL — login returns 404.

- [ ] **Step 3: Write the implementation**

`api/routers/auth.py`:

```python
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import audit, security
from ..db_helpers import client_ip, get_app_db, get_settings, user_agent
from ..schemas import LoginRequest
from ..users import authenticate

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    _limit=Depends(security.login_rate_limit),
):
    settings = get_settings(request)
    db = get_app_db(request)
    user = authenticate(db, payload.username, payload.password)
    if user is None:
        audit.record(
            db,
            action="login_failed",
            query=payload.username,
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
        raise HTTPException(401, "invalid credentials")
    access, refresh = security.issue_session(
        db,
        settings.secret_key,
        user,
        timedelta(minutes=settings.access_ttl_minutes),
        timedelta(days=settings.refresh_ttl_days),
    )
    security.set_auth_cookies(response, settings, access, refresh)
    audit.record(
        db,
        action="login",
        user_id=user["id"],
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    settings = get_settings(request)
    db = get_app_db(request)
    security.revoke_refresh(
        db, settings.secret_key, request.cookies.get(security.COOKIE_REFRESH)
    )
    security.clear_auth_cookies(response)
    return {"ok": True}


@router.post("/refresh")
def refresh(request: Request, response: Response):
    settings = get_settings(request)
    db = get_app_db(request)
    token = request.cookies.get(security.COOKIE_REFRESH)
    if not token:
        raise HTTPException(401, "no refresh token")
    try:
        access, renewed = security.rotate_refresh(
            db,
            settings.secret_key,
            token,
            timedelta(minutes=settings.access_ttl_minutes),
            timedelta(days=settings.refresh_ttl_days),
            timedelta(minutes=settings.idle_timeout_minutes),
        )
    except security.InvalidToken:
        security.clear_auth_cookies(response)
        raise HTTPException(401, "session expired") from None
    security.set_auth_cookies(response, settings, access, renewed)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(security.require_staff)):
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_auth.py tests/test_api_boot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/auth.py tests/test_api_auth.py
git commit -m "feat(api): login, logout, refresh and me endpoints"
```

---

### Task 9: Search, Suggest and Filter Routes

**Files:**
- Modify: `api/routers/search.py`
- Modify: `api/routers/filters.py`
- Test: `tests/test_api_search.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_search.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        test_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        yield test_client


def test_search_by_customer(client):
    response = client.post("/api/v1/search", json={"q": "สุรชัย"})
    assert response.status_code == 200
    body = response.json()
    assert body["detected"] == "customer"
    assert body["customers"][0]["name"] == "สุรชัย"


def test_search_by_barcode(client):
    response = client.post("/api/v1/search", json={"q": "8850250001234"})
    products = response.json()["products"]
    assert products and products[0]["name"].startswith("น้ำดื่มสิงห์")


def test_search_with_typo(client):
    response = client.post("/api/v1/search", json={"q": "สิงห"})
    assert response.json()["products"]


def test_short_thai_query_returns_four_products(client):
    response = client.post("/api/v1/search", json={"q": "น้ำ"})
    assert len(response.json()["products"]) == 4


def test_pii_never_appears_in_the_url(client):
    response = client.post("/api/v1/search", json={"q": "สุรชัย"})
    assert "สุรชัย" not in str(response.request.url)


def test_search_requires_login(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as anonymous:
        assert anonymous.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 401


def test_suggest_returns_products(client):
    response = client.post("/api/v1/suggest", json={"q": "น้ำ", "limit": 10})
    assert len(response.json()["suggestions"]) == 4


def test_query_length_is_capped(client):
    response = client.post("/api/v1/search", json={"q": "ก" * 201})
    assert response.status_code == 422


def test_filters_endpoint(client):
    response = client.get("/api/v1/filters")
    body = response.json()
    assert len(body["store_code"]) == 15
    assert "Standard delivery" in body["order_type"]


def test_search_with_store_filter(client):
    response = client.post(
        "/api/v1/search",
        json={"q": "น้ำ", "filters": {"store_code": ["101"]}},
    )
    assert response.json()["products"]


def test_search_is_rate_limited(tmp_path):
    from api.config import Settings

    settings = make_settings(tmp_path)
    limited = Settings(**{**settings.model_dump(), "rate_limit_per_minute": 2})
    with TestClient(create_app(limited)) as app_client:
        app_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        assert app_client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 200
        assert app_client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 200
        assert app_client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_search.py -v`
Expected: FAIL — search returns 404.

- [ ] **Step 3: Write the implementation**

`api/routers/search.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from order_search.search.filters import Filters

from .. import audit, security
from ..db_helpers import client_ip, get_app_db, user_agent
from ..schemas import SearchRequest, SuggestRequest

router = APIRouter(prefix="/api/v1", tags=["search"])


def _filters(payload):
    if payload.filters is None:
        return None
    return Filters(**payload.filters.model_dump())


@router.post("/search")
def search(
    payload: SearchRequest,
    request: Request,
    user=Depends(security.rate_limit),
):
    result = request.app.state.snapshot.search(
        query=payload.q,
        mode=payload.mode,
        filters=_filters(payload),
        limit=payload.limit,
        cursor=payload.cursor,
    )
    audit.record(
        get_app_db(request),
        action="search",
        user_id=user["id"],
        query=payload.q,
        mode=result["mode"],
        result_count=len(result["products"]) + len(result["customers"]),
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return result


@router.post("/suggest")
def suggest(
    payload: SuggestRequest,
    request: Request,
    user=Depends(security.rate_limit),
):
    suggestions = request.app.state.snapshot.suggest(
        payload.q, limit=payload.limit
    )
    return {"suggestions": suggestions}
```

`api/routers/filters.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import security

router = APIRouter(prefix="/api/v1", tags=["filters"])


@router.get("/filters")
def filters(request: Request, user=Depends(security.rate_limit)):
    return request.app.state.snapshot.facets()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_search.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add api/routers/search.py api/routers/filters.py tests/test_api_search.py
git commit -m "feat(api): search, suggest and filter facet endpoints"
```

### Task 10: Customer and Product Detail Routes

**Files:**
- Modify: `api/routers/search.py`
- Test: `tests/test_api_search.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_search.py`:

```python
def test_customer_history_endpoint(client):
    response = client.get("/api/v1/customers/1/history")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == 1
    assert body["products"]


def test_customer_history_bad_date_is_422(client):
    response = client.get(
        "/api/v1/customers/1/history", params={"date_from": "26-Sep-2026"}
    )
    assert response.status_code == 422


def test_customer_history_unknown_id_is_404(client):
    assert client.get("/api/v1/customers/99999/history").status_code == 404


def test_product_customers_endpoint(client):
    response = client.get("/api/v1/products/1/customers")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == 1
    assert body["customers"]


def test_product_customers_unknown_id_is_404(client):
    assert client.get("/api/v1/products/99999/customers").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_search.py -v`
Expected: FAIL — 404 for the new routes (they return FastAPI's own 404, and the bad-date/unknown-id cases do not yet behave).

- [ ] **Step 3: Write the implementation**

Append to `api/routers/search.py`:

```python
@router.get("/customers/{customer_id}/history")
def customer_history(
    customer_id: int,
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    user=Depends(security.rate_limit),
):
    try:
        filters = Filters(date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    history = request.app.state.snapshot.customer_history(customer_id, filters)
    if not history:
        raise HTTPException(404, "customer not found")
    return history[0]


@router.get("/products/{product_id}/customers")
def product_customers(
    product_id: int,
    request: Request,
    user=Depends(security.rate_limit),
):
    results = request.app.state.snapshot.product_customers(product_id)
    if not results:
        raise HTTPException(404, "product not found")
    return results[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_search.py -v`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
git add api/routers/search.py tests/test_api_search.py
git commit -m "feat(api): customer history and product customers detail endpoints"
```

---

### Task 11: Admin Users Routes

**Files:**
- Modify: `api/routers/admin.py`
- Test: `tests/test_api_admin.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_admin.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        test_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        yield test_client


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def test_list_users(client):
    response = client.get("/api/v1/admin/users")
    assert response.status_code == 200
    assert any(user["username"] == "admin" for user in response.json()["users"])


def test_create_and_update_user(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "somchai", "password": "password123", "role": "staff"},
        headers=csrf(client),
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    patched = client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"role": "admin"},
        headers=csrf(client),
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "admin"


def test_mutation_requires_csrf_header(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "somchai", "password": "password123", "role": "staff"},
    )
    assert response.status_code == 403


def test_staff_cannot_reach_admin(client):
    client.post(
        "/api/v1/admin/users",
        json={"username": "staffy", "password": "password123", "role": "staff"},
        headers=csrf(client),
    )
    staff = TestClient(client.app)
    staff.post(
        "/api/v1/auth/login",
        json={"username": "staffy", "password": "password123"},
    )
    assert staff.get("/api/v1/admin/users").status_code == 403
    assert staff.get("/api/v1/admin/audit").status_code == 403
    staff.close()


def test_short_password_is_rejected(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "weak", "password": "short", "role": "staff"},
        headers=csrf(client),
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_admin.py -v`
Expected: FAIL — admin routes return 404.

- [ ] **Step 3: Write the implementation**

Replace `api/routers/admin.py` with:

```python
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit, security, users
from ..db_helpers import get_app_db
from ..schemas import UserCreateRequest, UserPatchRequest

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users")
def list_users(request: Request, _admin=Depends(security.require_admin)):
    rows = users.list_users(get_app_db(request))
    return {"users": [dict(row) for row in rows]}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    _admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_app_db(request)
    try:
        user_id = users.create_user(
            db, payload.username, payload.password, payload.role
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "username already exists") from None
    audit.record(
        db,
        action="user_create",
        user_id=_admin["id"],
        query=payload.username,
        mode=payload.role,
    )
    row = users.get_by_id(db, user_id)
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_active": row["is_active"],
    }


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    payload: UserPatchRequest,
    request: Request,
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_app_db(request)
    updated = users.update_user(
        db,
        user_id,
        password=payload.password,
        role=payload.role,
        is_active=payload.is_active,
    )
    if not updated:
        raise HTTPException(404, "user not found")
    if payload.password is not None:
        security.revoke_all_for_user(db, user_id)
    audit.record(
        db,
        action="user_update",
        user_id=admin["id"],
        query=str(user_id),
        mode=payload.role,
    )
    row = users.get_by_id(db, user_id)
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_active": row["is_active"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_admin.py -v`
Expected: PASS (5 passed). The `test_staff_cannot_reach_admin` test reuses the same app instance, so the newly created staff user exists in the same `app.db`.

- [ ] **Step 5: Commit**

```bash
git add api/routers/admin.py tests/test_api_admin.py
git commit -m "feat(api): admin user management endpoints"
```

---

### Task 12: Admin Import, Versions and Rollback

**Files:**
- Create: `api/imports.py`
- Modify: `api/snapshot.py` (add `seal_bytes` and `load_version_bytes`)
- Modify: `api/routers/admin.py`
- Test: `tests/test_api_admin_import.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_admin_import.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from conftest import DATA_FILE
from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        test_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        yield test_client


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def upload(client):
    with open(DATA_FILE, "rb") as handle:
        return client.post(
            "/api/v1/admin/import",
            files={
                "file": (
                    "orders.xlsx",
                    handle,
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                )
            },
            headers=csrf(client),
        )


def test_import_creates_a_version(client):
    response = upload(client)
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["products"] == 15
    assert body["report"]["customers"] == 20
    assert body["persistent"] is True


def test_search_still_works_after_import(client):
    upload(client)
    response = client.post("/api/v1/search", json={"q": "สุรชัย"})
    assert response.json()["customers"][0]["name"] == "สุรชัย"


def test_versions_endpoint_lists_versions(client):
    upload(client)
    response = client.get("/api/v1/admin/import/versions")
    assert response.status_code == 200
    body = response.json()
    assert body["persistent"] is True
    assert len(body["versions"]) >= 1


def test_rollback_restores_previous_snapshot(client):
    upload(client)
    versions = client.get("/api/v1/admin/import/versions").json()["versions"]
    target = versions[0]["id"]
    response = client.post(
        "/api/v1/admin/import/rollback",
        json={"version_id": target},
        headers=csrf(client),
    )
    assert response.status_code == 200
    assert client.post("/api/v1/search", json={"q": "น้ำ"}).status_code == 200


def test_rejects_non_xlsx(client):
    response = client.post(
        "/api/v1/admin/import",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=csrf(client),
    )
    assert response.status_code == 422


def test_rollback_unknown_version_is_404(client):
    response = client.post(
        "/api/v1/admin/import/rollback",
        json={"version_id": 99999},
        headers=csrf(client),
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_admin_import.py -v`
Expected: FAIL — import route returns 404.

- [ ] **Step 3: Add the snapshot seal/load helpers**

In `api/snapshot.py`, add these two methods to `SnapshotStore` (after `load_file`):

```python
    def seal_bytes(self, plaintext: bytes) -> bytes:
        return crypto.seal(plaintext, self._keyring[self._key_id], self._key_id)

    def load_version_bytes(self, path: str | Path) -> bytes:
        return crypto.open_sealed(Path(path).read_bytes(), self._keyring)
```

- [ ] **Step 4: Write the import helper**

`api/imports.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows


def build_snapshot_bytes(xlsx_path: Path):
    """Returns (serialized_sqlite_bytes, ImportReport) for an uploaded workbook."""
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        report = build_database(read_order_rows(xlsx_path), connection)
        return connection.serialize(), report
    finally:
        connection.close()
```

- [ ] **Step 5: Write the admin import routes**

Append to `api/routers/admin.py`:

```python
import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import File, UploadFile

from ..db_helpers import client_ip, get_settings, user_agent
from ..imports import build_snapshot_bytes
from ..schemas import RollbackRequest


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


@router.post("/import")
async def import_workbook(
    request: Request,
    file: UploadFile = File(...),
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    settings = get_settings(request)
    db = get_app_db(request)
    snapshot = request.app.state.snapshot

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "only .xlsx workbooks are accepted")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "uploaded workbook is too large")

    versions_dir: Path = settings.versions_dir
    versions_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".xlsx", dir=versions_dir, delete=False
    ) as handle:
        handle.write(data)
        temp_xlsx = Path(handle.name)

    try:
        plaintext, report = build_snapshot_bytes(temp_xlsx)
    finally:
        temp_xlsx.unlink(missing_ok=True)

    sealed = snapshot.seal_bytes(plaintext)
    digest = hashlib.sha256(sealed).hexdigest()
    version_path = versions_dir / f"{_timestamp()}_{digest[:8]}.enc"
    version_path.write_bytes(sealed)

    db.run("UPDATE import_versions SET is_current = 0")
    version_id = db.run(
        "INSERT INTO import_versions (path, sha256, row_count, product_count,"
        " customer_count, is_current, created_at, created_by)"
        " VALUES (?,?,?,?,?,1,?,?)",
        (
            str(version_path),
            digest,
            report.rows_imported,
            report.products,
            report.customers,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            admin["id"],
        ),
    )
    snapshot.replace_with_bytes(plaintext)
    audit.record(
        db,
        action="import",
        user_id=admin["id"],
        query=str(version_id),
        result_count=report.rows_imported,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return {
        "version_id": version_id,
        "persistent": settings.persistent,
        "report": {
            "rows_read": report.rows_read,
            "rows_imported": report.rows_imported,
            "rows_skipped": report.rows_skipped,
            "products": report.products,
            "customers": report.customers,
            "barcodes": report.barcodes,
        },
    }


@router.get("/import/versions")
def list_versions(request: Request, _admin=Depends(security.require_admin)):
    settings = get_settings(request)
    rows = get_app_db(request).query_all(
        "SELECT id, path, sha256, row_count, product_count, customer_count,"
        " is_current, created_at, created_by FROM import_versions"
        " ORDER BY id DESC"
    )
    return {
        "persistent": settings.persistent,
        "versions": [dict(row) for row in rows],
    }


@router.post("/import/rollback")
def rollback(
    payload: RollbackRequest,
    request: Request,
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_app_db(request)
    snapshot = request.app.state.snapshot
    row = db.query_one(
        "SELECT * FROM import_versions WHERE id = ?", (payload.version_id,)
    )
    if row is None:
        raise HTTPException(404, "version not found")
    try:
        plaintext = snapshot.load_version_bytes(row["path"])
    except Exception:
        raise HTTPException(422, "version file missing or corrupt") from None
    snapshot.replace_with_bytes(plaintext)
    db.run("UPDATE import_versions SET is_current = 0")
    db.run("UPDATE import_versions SET is_current = 1 WHERE id = ?", (row["id"],))
    audit.record(
        db,
        action="rollback",
        user_id=admin["id"],
        query=str(row["id"]),
    )
    return {"ok": True, "version_id": row["id"]}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_admin_import.py tests/test_api_admin.py -v`
Expected: PASS (11 passed).

- [ ] **Step 7: Commit**

```bash
git add api/imports.py api/snapshot.py api/routers/admin.py tests/test_api_admin_import.py
git commit -m "feat(api): admin workbook import with versioned rollback"
```

---

### Task 13: Admin Audit Route

**Files:**
- Modify: `api/routers/admin.py`
- Test: `tests/test_api_admin_audit.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_admin_audit.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        test_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        yield test_client


def test_audit_records_searches(client):
    client.post("/api/v1/search", json={"q": "สุรชัย"})
    response = client.get("/api/v1/admin/audit")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert any(entry["action"] == "search" for entry in entries)


def test_audit_filter_by_action(client):
    client.post("/api/v1/search", json={"q": "น้ำ"})
    response = client.get("/api/v1/admin/audit", params={"action": "search"})
    assert all(entry["action"] == "search" for entry in response.json()["entries"])


def test_audit_pagination(client):
    for query in ("น้ำ", "สุรชัย", "กาแฟ"):
        client.post("/api/v1/search", json={"q": query})
    first = client.get("/api/v1/admin/audit", params={"limit": 1}).json()
    assert len(first["entries"]) == 1
    older = client.get(
        "/api/v1/admin/audit",
        params={"limit": 10, "before_id": first["entries"][0]["id"]},
    ).json()
    assert all(
        entry["id"] < first["entries"][0]["id"] for entry in older["entries"]
    )


def test_login_failure_is_audited(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as anonymous:
        anonymous.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        anonymous.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me-now"},
        )
        entries = anonymous.get("/api/v1/admin/audit").json()["entries"]
    assert any(entry["action"] == "login_failed" for entry in entries)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_admin_audit.py -v`
Expected: FAIL — `/api/v1/admin/audit` returns 404.

- [ ] **Step 3: Write the implementation**

Append to `api/routers/admin.py`:

```python
from ..audit import list_entries


@router.get("/audit")
def get_audit(
    request: Request,
    limit: int = 100,
    before_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
    _admin=Depends(security.require_admin),
):
    limit = max(1, min(limit, 500))
    entries = list_entries(
        get_app_db(request),
        limit=limit,
        before_id=before_id,
        user_id=user_id,
        action=action,
    )
    return {"entries": entries}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_admin_audit.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the full suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add api/routers/admin.py tests/test_api_admin_audit.py
git commit -m "feat(api): admin audit log endpoint"
```

### Task 14: PWA Static App Shell

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/app.js`
- Create: `web/manifest.webmanifest`
- Create: `web/sw.js`
- Create: `web/icons/icon.svg`
- Test: `tests/test_pwa.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pwa.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

from test_api_boot import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Order Search" in response.text


def test_manifest_is_valid_json(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    manifest = json.loads(response.text)
    assert manifest["name"]
    assert manifest["start_url"] == "/"


def test_service_worker_is_served(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_service_worker_never_caches_api(client):
    text = client.get("/sw.js").text
    assert "/api/" not in text.split("const SHELL")[0]
    shell_line = [line for line in text.splitlines() if "const SHELL" in line][0]
    assert "api" not in shell_line


def test_styles_and_app_js_are_served(client):
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/icons/icon.svg").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pwa.py -v`
Expected: FAIL — `/` returns 404 (no `web/` directory, so nothing is mounted).

- [ ] **Step 3: Write the files**

`web/index.html`:

```html
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0f766e">
  <title>Order Search</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icons/icon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <main id="login-view" class="view">
    <h1>Order Search</h1>
    <form id="login-form">
      <label for="username">ชื่อผู้ใช้</label>
      <input id="username" name="username" autocomplete="username" required autofocus>
      <label for="password">รหัสผ่าน</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">เข้าสู่ระบบ</button>
    </form>
    <p id="login-error" class="error" role="alert"></p>
  </main>

  <main id="app-view" class="view" hidden>
    <header class="topbar">
      <h1>Order Search</h1>
      <span id="who" class="who"></span>
      <button id="logout" class="link">ออก</button>
    </header>

    <form id="search-form" class="searchbar">
      <input id="search-input" placeholder="ชื่อลูกค้า / สินค้า / บาร์โค้ด" autocomplete="off">
      <button type="button" id="clear-search" class="link">ล้าง</button>
      <button type="submit">ค้นหา</button>
    </form>

    <div class="chips" id="mode-chips">
      <button type="button" data-mode="auto" class="chip active">อัตโนมัติ</button>
      <button type="button" data-mode="customer" class="chip">ลูกค้า</button>
      <button type="button" data-mode="product" class="chip">สินค้า</button>
      <button type="button" id="open-filters" class="chip">ตัวกรอง</button>
    </div>

    <ul id="suggestions" class="suggestions" hidden></ul>
    <p id="result-note" class="note">
      วันที่คือวันคาดส่ง ไม่ใช่วันสั่งซื้อ
    </p>
    <div id="results" class="results"></div>
  </main>

  <section id="filter-sheet" class="sheet" hidden>
    <div class="sheet-body">
      <h2>ตัวกรอง</h2>
      <div id="filter-fields"></div>
      <div class="sheet-actions">
        <button type="button" id="clear-filters" class="link">ล้างตัวกรอง</button>
        <button type="button" id="apply-filters">ใช้ตัวกรอง</button>
      </div>
    </div>
  </section>

  <script src="/app.js"></script>
</body>
</html>
```

`web/styles.css`:

```css
:root {
  --teal: #0f766e;
  --line: #d8dee3;
  --muted: #5b6b78;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #14202b;
  background: #f6f8fa;
}
.view { padding: 16px; max-width: 720px; margin: 0 auto; }
.view[hidden], [hidden] { display: none; }
h1 { font-size: 1.25rem; }
label { display: block; margin: 12px 0 4px; font-size: .85rem; color: var(--muted); }
input {
  width: 100%;
  padding: 14px;
  font-size: 1rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}
button {
  padding: 14px 18px;
  font-size: 1rem;
  border: 0;
  border-radius: 10px;
  background: var(--teal);
  color: #fff;
}
button.link {
  background: none;
  color: var(--muted);
  padding: 8px;
}
.error { color: #b91c1c; min-height: 1.2em; }
.topbar { display: flex; align-items: center; gap: 8px; }
.topbar h1 { flex: 1; }
.who { font-size: .8rem; color: var(--muted); }
.searchbar { display: flex; gap: 8px; align-items: center; }
.searchbar input { flex: 1; }
.chips { display: flex; gap: 8px; margin: 12px 0; flex-wrap: wrap; }
.chip {
  background: #fff;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 8px 14px;
}
.chip.active { background: var(--teal); color: #fff; border-color: var(--teal); }
.suggestions {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}
.suggestions li { padding: 12px; border-bottom: 1px solid #eef1f4; }
.suggestions li:last-child { border-bottom: 0; }
.note { font-size: .78rem; color: var(--muted); }
.results { display: flex; flex-direction: column; }
.row {
  border-bottom: 1px solid var(--line);
  padding: 12px 4px;
  font-size: .92rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.row .title { font-weight: 600; }
.row .meta { color: var(--muted); font-size: .82rem; }
.badge {
  background: #ffd54f;
  border-radius: 4px;
  padding: 0 6px;
  font-size: .72rem;
  font-weight: 600;
}
.sheet {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, .4);
  display: flex;
  align-items: flex-end;
}
.sheet-body {
  width: 100%;
  max-height: 80vh;
  overflow: auto;
  background: #fff;
  border-radius: 16px 16px 0 0;
  padding: 16px;
}
.sheet-actions { display: flex; justify-content: space-between; margin-top: 16px; }
```

`web/app.js`:

```javascript
const state = {
  user: null,
  mode: "auto",
  filters: {},
  cursor: null,
  query: "",
};

function cookie(name) {
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name + "=([^;]*)")
  );
  return match ? decodeURIComponent(match[1]) : null;
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (options.body) headers["Content-Type"] = "application/json";
  const csrf = cookie("csrf_token");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    showLogin();
    throw new Error("unauthenticated");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || "request failed");
  }
  if (response.status === 204) return null;
  return response.json();
}

function showLogin() {
  document.getElementById("login-view").hidden = false;
  document.getElementById("app-view").hidden = true;
}

function showApp(user) {
  state.user = user;
  document.getElementById("login-view").hidden = true;
  document.getElementById("app-view").hidden = false;
  document.getElementById("who").textContent = `${user.username} (${user.role})`;
  loadFilterOptions();
}

function renderResults(payload) {
  const container = document.getElementById("results");
  container.innerHTML = "";
  const customers = payload.customers || [];
  const products = payload.products || [];

  customers.forEach((customer) => {
    const card = document.createElement("div");
    card.className = "row";
    card.innerHTML =
      `<span class="title">${customer.name}</span>` +
      `<span class="meta">${customer.order_count} ออเดอร์ · ${customer.products.length} สินค้า</span>`;
    (customer.products || []).forEach((product) => {
      const line = document.createElement("div");
      line.className = "row";
      line.innerHTML =
        `<span>${product.name}</span>` +
        `<span class="meta">${product.order_count}× · ${product.last_date || "-"} · ` +
        `${(product.stores || []).join(", ") || "-"}</span>`;
      container.appendChild(line);
    });
    container.appendChild(card);
  });

  products.forEach((product) => {
    const line = document.createElement("div");
    line.className = "row";
    line.innerHTML =
      `<span class="title">${product.name}</span>` +
      `<span class="meta">${product.customer_count} คน · ${product.order_count} ออเดอร์ · ` +
      `ล่าสุด ${product.last_date || "-"}</span>`;
    container.appendChild(line);
  });

  if (!customers.length && !products.length) {
    container.innerHTML = '<p class="note">ไม่พบผลลัพธ์</p>';
  }
  state.cursor = payload.next_cursor || null;
}

async function runSearch(query) {
  state.query = query;
  const payload = await api("/api/v1/search", {
    method: "POST",
    body: JSON.stringify({
      q: query,
      mode: state.mode,
      filters: state.filters,
      limit: 20,
    }),
  });
  renderResults(payload);
}

let suggestTimer = null;
function scheduleSuggest(query) {
  clearTimeout(suggestTimer);
  if (query.trim().length < 2) {
    hideSuggestions();
    return;
  }
  suggestTimer = setTimeout(async () => {
    try {
      const payload = await api("/api/v1/suggest", {
        method: "POST",
        body: JSON.stringify({ q: query, limit: 8 }),
      });
      const list = document.getElementById("suggestions");
      list.innerHTML = "";
      (payload.suggestions || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item.name;
        li.addEventListener("click", () => {
          document.getElementById("search-input").value = item.name;
          hideSuggestions();
          runSearch(item.name);
        });
        list.appendChild(li);
      });
      list.hidden = !payload.suggestions.length;
    } catch (error) {
      hideSuggestions();
    }
  }, 250);
}

function hideSuggestions() {
  const list = document.getElementById("suggestions");
  list.hidden = true;
  list.innerHTML = "";
}

async function loadFilterOptions() {
  try {
    const facets = await api("/api/v1/filters");
    const fields = document.getElementById("filter-fields");
    fields.innerHTML = "";
    const groups = {
      store_code: "สาขา",
      order_type: "ประเภทออเดอร์",
      vip_group: "VIP",
      dept: "Dept",
    };
    Object.entries(groups).forEach(([key, label]) => {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = `<label>${label}</label>`;
      const select = document.createElement("select");
      select.multiple = true;
      select.dataset.filterKey = key;
      (facets[key] || []).forEach((value) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = String(value);
        select.appendChild(option);
      });
      wrapper.appendChild(select);
      fields.appendChild(wrapper);
    });
    const dates = document.createElement("div");
    dates.innerHTML =
      '<label>จากวันที่</label><input type="date" id="filter-date-from">' +
      '<label>ถึงวันที่</label><input type="date" id="filter-date-to">';
    fields.appendChild(dates);
  } catch (error) {
    // Filters are a convenience; a failure here must not block search.
  }
}

function collectFilters() {
  const filters = {};
  document.querySelectorAll("[data-filter-key]").forEach((select) => {
    const values = Array.from(select.selectedOptions).map((o) => o.value);
    if (values.length) filters[select.dataset.filterKey] = values;
  });
  const from = document.getElementById("filter-date-from").value;
  const to = document.getElementById("filter-date-to").value;
  if (from) filters.date_from = from;
  if (to) filters.date_to = to;
  return filters;
}

function init() {
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.getElementById("login-error");
    error.textContent = "";
    try {
      const user = await api("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: document.getElementById("username").value,
          password: document.getElementById("password").value,
        }),
      });
      showApp(user);
    } catch (loginError) {
      error.textContent = "เข้าสู่ระบบไม่สำเร็จ";
    }
  });

  document.getElementById("logout").addEventListener("click", async () => {
    await fetch("/api/v1/auth/logout", { method: "POST" });
    showLogin();
  });

  document.getElementById("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    hideSuggestions();
    runSearch(document.getElementById("search-input").value);
  });

  document.getElementById("search-input").addEventListener("input", (event) => {
    scheduleSuggest(event.target.value);
  });

  document.getElementById("clear-search").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("results").innerHTML = "";
    hideSuggestions();
  });

  document.getElementById("mode-chips").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (!button) return;
    state.mode = button.dataset.mode;
    document
      .querySelectorAll("#mode-chips .chip[data-mode]")
      .forEach((chip) => chip.classList.toggle("active", chip === button));
  });

  document.getElementById("open-filters").addEventListener("click", () => {
    document.getElementById("filter-sheet").hidden = false;
  });

  document.getElementById("apply-filters").addEventListener("click", () => {
    state.filters = collectFilters();
    document.getElementById("filter-sheet").hidden = true;
  });

  document.getElementById("clear-filters").addEventListener("click", () => {
    document.querySelectorAll("[data-filter-key]").forEach((select) => {
      select.selectedIndex = -1;
    });
    document.getElementById("filter-date-from").value = "";
    document.getElementById("filter-date-to").value = "";
    state.filters = {};
  });

  api("/api/v1/auth/me")
    .then(showApp)
    .catch(() => showLogin());

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

init();
```

`web/manifest.webmanifest`:

```json
{
  "name": "Order Search",
  "short_name": "Order Search",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#f6f8fa",
  "theme_color": "#0f766e",
  "icons": [
    {
      "src": "/icons/icon.svg",
      "sizes": "any",
      "type": "image/svg+xml",
      "purpose": "any maskable"
    }
  ]
}
```

`web/sw.js`:

```javascript
const CACHE = "order-search-shell-v1";
const SHELL = [
  "/",
  "/app.js",
  "/styles.css",
  "/manifest.webmanifest",
  "/icons/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/") || event.request.method !== "GET") {
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/"))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
```

`web/icons/icon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="192" height="192">
  <rect width="192" height="192" rx="32" fill="#0f766e"/>
  <circle cx="84" cy="84" r="42" fill="none" stroke="#ffffff" stroke-width="14"/>
  <line x1="116" y1="116" x2="156" y2="156" stroke="#ffffff" stroke-width="18" stroke-linecap="round"/>
</svg>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pwa.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add web tests/test_pwa.py
git commit -m "feat(web): installable vanilla-js pwa with app-shell-only caching"
```

---

### Task 15: Build and Admin Scripts

**Files:**
- Create: `scripts/build_snapshot.py`
- Create: `scripts/make_admin.py`
- Test: `tests/test_scripts.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scripts.py`:

```python
import base64
import os
import subprocess
import sys
from pathlib import Path

from api.snapshot import SnapshotStore

from conftest import DATA_FILE

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
RAW_KEY = bytes(range(32))
KEY = base64.urlsafe_b64encode(RAW_KEY).decode("ascii")


def run_script(script, args, env_extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["DATA_KEY"] = KEY
    env["DATA_KEY_ID"] = "v1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(PYTHON), str(ROOT / "scripts" / script)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )


def test_build_snapshot_produces_a_searchable_file(tmp_path):
    out = tmp_path / "snapshot.enc"
    result = run_script(
        "build_snapshot.py", [str(DATA_FILE), "--out", str(out)]
    )
    assert result.returncode == 0, result.stderr
    assert "products" in result.stdout
    store = SnapshotStore({"v1": RAW_KEY}, "v1")
    store.load_file(out)
    assert len(store.search("น้ำ")["products"]) == 4


def test_make_admin_creates_a_login(tmp_path):
    db_path = tmp_path / "app.db"
    result = run_script(
        "make_admin.py",
        ["--db", str(db_path), "--username", "boss", "--password", "password123"],
    )
    assert result.returncode == 0, result.stderr
    from api.app_db import AppDB

    db = AppDB(db_path)
    from api.users import authenticate

    assert authenticate(db, "boss", "password123")["role"] == "admin"
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts.py -v`
Expected: FAIL — script files do not exist.

- [ ] **Step 3: Write the implementation**

`scripts/build_snapshot.py`:

```python
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api import crypto
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an encrypted SQLite snapshot from an order workbook."
    )
    parser.add_argument("source", help="path to the .xlsx file")
    parser.add_argument("--out", required=True, help="path of snapshot.enc")
    parser.add_argument("--key", default=os.environ.get("DATA_KEY", ""))
    parser.add_argument("--key-id", default=os.environ.get("DATA_KEY_ID", "v1"))
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        print(f"source file not found: {source}", file=sys.stderr)
        return 2
    if not args.key:
        print("DATA_KEY is required (env or --key)", file=sys.stderr)
        return 2

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        report = build_database(read_order_rows(source), connection)
        plaintext = connection.serialize()
    finally:
        connection.close()

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(crypto.seal(plaintext, crypto.load_key(args.key), args.key_id))

    print(report.summary())
    print(f"key_id   : {args.key_id}")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/make_admin.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.app_db import AppDB
from api.users import create_user, get_by_username, update_user


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or reset an admin account in app.db."
    )
    parser.add_argument("--db", required=True, help="path to app.db")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin", choices=("staff", "admin"))
    args = parser.parse_args()

    db = AppDB(Path(args.db))
    try:
        existing = get_by_username(db, args.username)
        if existing is None:
            create_user(db, args.username, args.password, args.role)
            print(f"created {args.role} {args.username}")
        else:
            update_user(
                db,
                existing["id"],
                password=args.password,
                role=args.role,
                is_active=True,
            )
            print(f"updated {args.role} {args.username}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Build the real snapshot and commit it**

Run:

```powershell
$env:DATA_KEY = .\.venv\Scripts\python.exe -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
Write-Output "SAVE THIS DATA_KEY in Render env: $env:DATA_KEY"
.\.venv\Scripts\python.exe scripts\build_snapshot.py sample_order_data_1000_records.xlsx --out snapshot.enc
```

Expected: `products : 15`, `customers : 20`, `barcodes : 127`, then `wrote snapshot.enc`.

Commit the ciphertext (never the key, never the xlsx):

```bash
git add scripts/build_snapshot.py scripts/make_admin.py tests/test_scripts.py snapshot.enc
git commit -m "feat(scripts): encrypted snapshot builder and admin provisioning"
```

- [ ] **Step 6: Ensure the source workbook is not committed**

Add to `.gitignore` if missing:

```
*.xlsx
!sample_order_data_1000_records.xlsx
.env
```

Run: `git status --short` — `sample_order_data_1000_records.xlsx` must not be staged. It is already tracked from Plan 1, which is acceptable for this synthetic sample only.

---

### Task 16: Dockerfile, .dockerignore and render.yaml

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `render.yaml`

- [ ] **Step 1: Write the files**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SNAPSHOT_PATH=/app/data/snapshot.enc

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY api/ api/
COPY web/ web/
COPY scripts/ scripts/
COPY snapshot.enc data/snapshot.enc

RUN python -c "import sqlite3; sqlite3.connect(':memory:').execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\")"

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`.dockerignore`:

```
.venv
.git
.pytest_cache
docs
tests
__pycache__
*.pyc
.superpowers
build
render.yaml
```

`render.yaml`:

```yaml
services:
  - type: web
    name: order-search
    runtime: docker
    plan: free
    healthCheckPath: /healthz
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DATA_KEY
        sync: false
      - key: DATA_KEY_ID
        value: v1
      - key: ADMIN_USERNAME
        value: admin
      - key: ADMIN_PASSWORD
        sync: false
      - key: COOKIE_SECURE
        value: "true"
      - key: SNAPSHOT_PATH
        value: /app/data/snapshot.enc
```

- [ ] **Step 2: Verify the Dockerfile build**

Run: `docker build -t order-search .` (only where Docker is available)
Expected: build succeeds and the FTS5 probe RUN step exits 0. If Docker is not installed locally (this machine has none), record that the build is verified on Render and move on.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile .dockerignore render.yaml
git commit -m "build: docker image and render blueprint"
```

---

### Task 17: README and Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the "Not in this plan" section**

Replace the final section of `README.md` with:

````markdown
## Web service

The API and PWA are the second half of the project. Everything below runs the
same search core behind HTTP.

### Build the encrypted snapshot

```powershell
$env:DATA_KEY = .\.venv\Scripts\python.exe -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
.\.venv\Scripts\python.exe scripts\build_snapshot.py sample_order_data_1000_records.xlsx --out snapshot.enc
```

Keep `DATA_KEY` secret. `snapshot.enc` is ciphertext and may be committed.

### Run locally

```powershell
$env:SECRET_KEY = "dev-secret"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change-me-now"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000`, log in, search. The API is under `/api/v1`.

### Provision another admin

```powershell
.\.venv\Scripts\python.exe scripts\make_admin.py --db "$env:TEMP\order-search\app.db" --username boss --password password123
```

### Deploy to Render

Push the repo, create the service from `render.yaml`, then set `DATA_KEY`,
`ADMIN_PASSWORD` and `SECRET_KEY` in the dashboard. Free instances have no
persistent disk, so `users` and `audit_log` reset on redeploy; add a disk and
set `DISK_PATH` to keep them.

### Security notes

- Search and suggest are POST so customer text never lands in a URL.
- `snapshot.enc` is decrypted into memory only; the FTS index is rebuilt after
  deserialization because SQLite does not restore it.
- The service worker caches the app shell only, never `/api/`.
````

- [ ] **Step 2: Run the full suite one more time**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS (Plan 1 + Plan 2 tests).

- [ ] **Step 3: Start the server and smoke-test it**

Run:

```powershell
$env:DATA_KEY = "<the key you saved>"
$env:SECRET_KEY = "dev-secret"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000
```

Then in another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

Expected: `{ status = ok; snapshot = True }`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the web service, build and deploy"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Implementing task |
|--------------|-------------------|
| 0.1 deserialize/FTS rebuild finding | Task 4 |
| 3.3 SnapshotStore | Task 4 |
| 3.4 atomic swap + rollback | Task 12 |
| 4.2 app.db schema | Task 3 |
| 4.3 session model (access/refresh/idle/rotation) | Tasks 6, 8 |
| 5 API surface | Tasks 8, 9, 10, 11, 12, 13 |
| 5.1 error convention | Tasks 7, 8, 9, 10, 11, 12 |
| 6 security (argon2, JWT, RBAC, CSRF, rate, no-store, HSTS, AES-GCM) | Tasks 1, 2, 3, 5, 6, 7 |
| 7 PWA (login, search, chips, layout B, filters, sw) | Task 14 |
| 8 build/deploy (Dockerfile, render.yaml, boot FTS check) | Tasks 15, 16 |
| 9 tests | Tasks 1-16 |
| 10 known limits (ephemeral, cold start) | Task 17 README |

**Placeholder scan:** No `TBD`, `TODO`, "add validation", or "similar to Task N". Every code step shows the full file or the full appended block.

**Type consistency:** `SnapshotStore.search/suggest/customer_history/product_customers/facets/counts`, `AppDB.run/query_one/query_all`, `users.create_user/get_by_id/get_by_username/update_user/authenticate/bootstrap_admin`, `security.issue_session/rotate_refresh/revoke_refresh/revoke_all_for_user/require_staff/require_admin/require_csrf/rate_limit/login_rate_limit`, and `audit.record/list_entries` are used with identical signatures across all tasks.

**Known deferred item:** TOTP 2FA is intentionally out of scope (spec 2.1); `users.totp_secret` exists but is unused.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-26-order-search-web.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?



