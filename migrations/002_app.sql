CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.schema_migrations (
    name       text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role          text NOT NULL CHECK (role IN ('staff','admin')),
    totp_secret   text,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.refresh_tokens (
    id           text PRIMARY KEY,
    user_id      bigint NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    issued_at    timestamptz NOT NULL,
    expires_at   timestamptz NOT NULL,
    last_used_at timestamptz NOT NULL,
    revoked      boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON app.refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS app.data_versions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version        integer NOT NULL,
    source_filename text,
    row_count      integer,
    product_count  integer,
    customer_count integer,
    order_count    integer,
    barcode_count  integer,
    is_current     boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by     bigint REFERENCES app.users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_current
    ON app.data_versions(is_current) WHERE is_current;

CREATE TABLE IF NOT EXISTS app.audit_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      bigint,
    action       text NOT NULL,
    query        text,
    mode         text,
    result_count integer,
    ip           text,
    user_agent   text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON app.audit_log(created_at);

CREATE TABLE IF NOT EXISTS app.rate_buckets (
    key          text NOT NULL,
    window_start timestamptz NOT NULL,
    hits         integer NOT NULL DEFAULT 0,
    PRIMARY KEY (key, window_start)
);
