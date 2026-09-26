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
