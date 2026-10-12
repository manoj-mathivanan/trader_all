CREATE SCHEMA IF NOT EXISTS investor;
CREATE TABLE IF NOT EXISTS investor.article_versions (
    environment text NOT NULL,
    article_id text NOT NULL,
    sha256 text NOT NULL,
    source_id text NOT NULL,
    published_at timestamptz NOT NULL,
    first_seen_at timestamptz NOT NULL,
    record jsonb NOT NULL,
    archived_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(environment, article_id, sha256)
);
CREATE INDEX IF NOT EXISTS investor_articles_by_date ON investor.article_versions(published_at);
CREATE TABLE IF NOT EXISTS investor.documents (
    environment text NOT NULL,
    kind text NOT NULL,
    document_id text NOT NULL,
    sha256 text NOT NULL,
    record jsonb NOT NULL,
    archived_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(environment, kind, document_id, sha256)
);
CREATE TABLE IF NOT EXISTS investor.sync_receipts (
    sha256 text PRIMARY KEY,
    environment text NOT NULL,
    result jsonb NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now()
);
GRANT USAGE ON SCHEMA investor TO market_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA investor TO market_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA investor GRANT SELECT ON TABLES TO market_reader;
