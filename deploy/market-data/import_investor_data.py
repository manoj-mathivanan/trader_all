"""Import personal investor evidence over authenticated SSH stdin; no HTTP service."""
import hashlib
import json
from pathlib import Path
import sys

import psycopg
from psycopg.types.json import Jsonb


def run(raw, dsn=None):
    if len(raw) > 100_000_000:
        raise ValueError('Investor archive exceeds import limit')
    bundle = json.loads(raw)
    if bundle.get('version') != 1 or bundle.get('environment') not in ('local', 'production'):
        raise ValueError('Unsupported investor archive')
    environment = bundle['environment']
    digest = hashlib.sha256(raw).hexdigest()
    connection=dict(connect_timeout=10,application_name='investor-archive')
    if not dsn:connection.update(host='127.0.0.1',dbname='market_data',user='market_admin',password=Path('/srv/market-data/private/admin_password').read_text().strip())
    with psycopg.connect(dsn or '',**connection) as conn:
        if not dsn:conn.execute(Path(__file__).with_name('investor_schema.sql').read_text())
        if not conn.execute('SELECT pg_try_advisory_xact_lock(72061011)').fetchone()[0]:
            raise RuntimeError('Another investor archive importer is active')
        previous = conn.execute('SELECT result FROM investor.sync_receipts WHERE sha256=%s', (digest,)).fetchone()
        if previous:
            return previous[0]
        articles_inserted = documents_inserted = 0
        for row in bundle['articles']:
            value = row['record']
            expected = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            if expected != row['sha256']:
                raise ValueError('Article checksum mismatch')
            articles_inserted += conn.execute(
                'INSERT INTO investor.article_versions(environment,article_id,sha256,source_id,published_at,first_seen_at,record) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                (environment, value['id'], row['sha256'], value['source_id'], value['published_at'],
                 value.get('first_seen_at', value['retrieved_at']), Jsonb(value))).rowcount
        for row in bundle['documents']:
            if row['kind'] not in ('refreshes','reviews','llm_responses','feed_responses','news','article_documents',
                                   'article_summaries','scans','monitor_runs','alerts','article_coverage',
                                   'watchlist','settings','rules','portfolio_snapshot','scan','monitor','discovery','execution','stock_details','assessments',
                                   'latest','full_articles','analysis_jobs','validation_reports'):
                raise ValueError('Unsupported investor document')
            expected = hashlib.sha256(json.dumps(row['record'], sort_keys=True).encode()).hexdigest()
            if expected != row['sha256']:
                raise ValueError('Document checksum mismatch')
            documents_inserted += conn.execute(
                'INSERT INTO investor.documents(environment,kind,document_id,sha256,record) '
                'VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                (environment, row['kind'], row['id'], row['sha256'], Jsonb(row['record']))).rowcount
        counts = dict(conn.execute("SELECT 'article_versions',count(*) FROM investor.article_versions WHERE environment=%s "
                                   "UNION ALL SELECT kind,count(*) FROM investor.documents WHERE environment=%s GROUP BY kind",
                                   (environment, environment)).fetchall())
        result = dict(status='complete', environment=environment, sha256=digest,
                      articles_inserted=articles_inserted, documents_inserted=documents_inserted, counts=counts)
        conn.execute('INSERT INTO investor.sync_receipts(sha256,environment,result) VALUES(%s,%s,%s)',
                     (digest, environment, Jsonb(result)))
        return result


if __name__ == '__main__':
    print(json.dumps(run(sys.stdin.buffer.read(100_000_001))))
