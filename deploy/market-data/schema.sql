BEGIN;
CREATE SCHEMA IF NOT EXISTS market;
CREATE TABLE IF NOT EXISTS market.schema_version (
    version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO market.schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS market.imports (
    id text PRIMARY KEY,
    environment text NOT NULL,
    manifest jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'complete')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    verification jsonb
);
CREATE TABLE IF NOT EXISTS market.blobs (
    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    raw_bytes bigint NOT NULL CHECK (raw_bytes >= 0),
    gzip_data bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market.source_files (
    import_id text NOT NULL REFERENCES market.imports(id),
    relative_path text NOT NULL,
    category text NOT NULL,
    sha256 text NOT NULL REFERENCES market.blobs(sha256),
    PRIMARY KEY (import_id, relative_path)
);
CREATE INDEX IF NOT EXISTS source_files_sha256 ON market.source_files(sha256);
CREATE TABLE IF NOT EXISTS market.instruments (
    isin text PRIMARY KEY,
    symbol text NOT NULL,
    provider_key text NOT NULL,
    metadata jsonb NOT NULL,
    fetched_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS market.candles (
    isin text NOT NULL REFERENCES market.instruments(isin),
    interval_minutes smallint NOT NULL CHECK (interval_minutes IN (5, 1440)),
    timestamp_ms bigint NOT NULL,
    session_date date NOT NULL,
    open numeric NOT NULL CHECK (open > 0),
    high numeric NOT NULL CHECK (high > 0),
    low numeric NOT NULL CHECK (low > 0),
    close numeric NOT NULL CHECK (close > 0),
    volume numeric NOT NULL CHECK (volume >= 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    fetched_at timestamptz NOT NULL,
    import_id text NOT NULL REFERENCES market.imports(id),
    PRIMARY KEY (isin, interval_minutes, timestamp_ms),
    CHECK (low <= least(open, close) AND high >= greatest(open, close) AND low <= high)
);
-- Only conflicting candle versions are repeated here. All exact original source
-- files, including frozen/derived experiment inputs, are preserved in blobs.
CREATE TABLE IF NOT EXISTS market.candle_revisions (
    LIKE market.candles INCLUDING DEFAULTS INCLUDING CONSTRAINTS,
    PRIMARY KEY (isin, interval_minutes, timestamp_ms, sha256)
);
CREATE INDEX IF NOT EXISTS candles_by_session ON market.candles(interval_minutes, session_date);
CREATE TABLE IF NOT EXISTS market.refreshes (
    import_id text PRIMARY KEY REFERENCES market.imports(id),
    environment text NOT NULL,
    job_id text,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    partial boolean NOT NULL,
    result jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS market.fundamentals (
    isin text PRIMARY KEY,
    record jsonb NOT NULL,
    last_checked_at timestamptz NOT NULL,
    last_pulled_at timestamptz,
    sha256 text NOT NULL REFERENCES market.blobs(sha256),
    import_id text NOT NULL REFERENCES market.imports(id)
);
CREATE OR REPLACE VIEW market.daily_bars AS
    SELECT * FROM market.candles WHERE interval_minutes = 1440;
CREATE OR REPLACE VIEW market.five_minute_bars AS
    SELECT * FROM market.candles WHERE interval_minutes = 5;
CREATE OR REPLACE VIEW market.coverage AS
    SELECT isin, interval_minutes, count(*) AS candle_count,
           min(session_date) AS first_session, max(session_date) AS last_session,
           max(fetched_at) AS fetched_at
    FROM market.candles GROUP BY isin, interval_minutes;
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'market_reader') THEN
        CREATE ROLE market_reader NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA market TO market_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA market TO market_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT SELECT ON TABLES TO market_reader;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
COMMIT;
