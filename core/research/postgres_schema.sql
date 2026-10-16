CREATE SCHEMA IF NOT EXISTS trader;
CREATE TABLE IF NOT EXISTS trader.schema_version (version integer PRIMARY KEY);
INSERT INTO trader.schema_version VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO trader.schema_version VALUES (2) ON CONFLICT DO NOTHING;
-- Immutable, compressed content is shared by identical snapshots. Names and
-- accounting state stay isolated by environment namespace.
CREATE TABLE IF NOT EXISTS trader.contents (
    sha256 text PRIMARY KEY, content bytea NOT NULL, raw_bytes bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS trader.documents (
    namespace text NOT NULL, name text NOT NULL, sha256 text NOT NULL REFERENCES trader.contents,
    revision bigint NOT NULL DEFAULT 1, metadata jsonb NOT NULL DEFAULT '{}',
    updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(namespace,name)
);
CREATE INDEX IF NOT EXISTS documents_prefix ON trader.documents(namespace,name text_pattern_ops);
CREATE INDEX IF NOT EXISTS documents_content ON trader.documents(sha256);
CREATE TABLE IF NOT EXISTS trader.artifacts (
    namespace text NOT NULL, name text NOT NULL, sha256 text NOT NULL REFERENCES trader.contents,
    PRIMARY KEY(namespace,name)
);
CREATE TABLE IF NOT EXISTS trader.credentials (
    namespace text NOT NULL, owner_id text NOT NULL, provider text NOT NULL,
    encrypted_value bytea NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(namespace,owner_id,provider)
);
CREATE INDEX IF NOT EXISTS artifacts_content ON trader.artifacts(sha256);
CREATE TABLE IF NOT EXISTS trader.candles (
    namespace text NOT NULL, document_name text NOT NULL, ordinal integer NOT NULL,
    isin text NOT NULL, interval_minutes integer NOT NULL, session text NOT NULL,
    open numeric NOT NULL, high numeric NOT NULL, low numeric NOT NULL,
    close numeric NOT NULL, volume numeric NOT NULL, bar jsonb NOT NULL,
    PRIMARY KEY(namespace,document_name,ordinal),
    FOREIGN KEY(namespace,document_name) REFERENCES trader.documents ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS candles_lookup ON trader.candles(namespace,isin,interval_minutes,session);
-- Intraday readers work on one instrument/session at a time. Native JSONB
-- keeps every candle queryable without millions of duplicate per-bar indexes.
CREATE TABLE IF NOT EXISTS trader.intraday_sessions (
    namespace text NOT NULL, document_name text NOT NULL, isin text NOT NULL,
    interval_minutes integer NOT NULL, session text NOT NULL, bars jsonb NOT NULL,
    candle_count integer GENERATED ALWAYS AS (jsonb_array_length(bars)) STORED,
    source_sha256 text NOT NULL REFERENCES trader.contents,
    PRIMARY KEY(namespace,document_name),
    FOREIGN KEY(namespace,document_name) REFERENCES trader.documents ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK (jsonb_typeof(bars)='array')
);
CREATE INDEX IF NOT EXISTS intraday_sessions_lookup ON trader.intraday_sessions(namespace,isin,interval_minutes,session);
CREATE INDEX IF NOT EXISTS intraday_sessions_content ON trader.intraday_sessions(source_sha256);
CREATE TABLE IF NOT EXISTS trader.runs (
    namespace text NOT NULL, id text NOT NULL, strategy_id text,
    config jsonb NOT NULL, metrics jsonb NOT NULL, source_sha256 text NOT NULL REFERENCES trader.contents,
    PRIMARY KEY(namespace,id)
);
CREATE TABLE IF NOT EXISTS trader.portfolios (
    namespace text NOT NULL, id text NOT NULL, strategy_id text NOT NULL,
    config jsonb NOT NULL, status text NOT NULL, cash numeric, last_session text,
    source_sha256 text NOT NULL REFERENCES trader.contents, PRIMARY KEY(namespace,id)
);
CREATE TABLE IF NOT EXISTS trader.trade_records (
    namespace text NOT NULL, owner_kind text NOT NULL, owner_id text NOT NULL,
    ordinal integer NOT NULL, symbol text, pnl numeric, record jsonb NOT NULL,
    PRIMARY KEY(namespace,owner_kind,owner_id,ordinal)
);
CREATE INDEX IF NOT EXISTS runs_content ON trader.runs(source_sha256);
CREATE INDEX IF NOT EXISTS portfolios_content ON trader.portfolios(source_sha256);
CREATE TABLE IF NOT EXISTS trader.jobs (
    namespace text NOT NULL, id text NOT NULL, status text NOT NULL, record jsonb NOT NULL,
    PRIMARY KEY(namespace,id)
);
CREATE TABLE IF NOT EXISTS trader.migrations (
    namespace text NOT NULL, name text NOT NULL, source_sha256 text NOT NULL,
    destination_sha256 text NOT NULL, verified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(namespace,name)
);
CREATE OR REPLACE VIEW trader.fundamentals AS
 SELECT namespace,name,metadata FROM trader.documents WHERE name LIKE 'company/fundamentals/%';
CREATE OR REPLACE VIEW trader.news AS
 SELECT namespace,name,metadata FROM trader.documents WHERE name LIKE 'investor/articles/%';
