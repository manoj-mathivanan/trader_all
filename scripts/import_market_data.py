"""Import and verify a market bundle into PostgreSQL without changing source files.

Run in the dedicated server venv. Credentials come from a private password file,
never command-line arguments. Re-running a completed bundle is idempotent.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import re

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

COLUMNS = ('isin', 'interval_minutes', 'timestamp_ms', 'session_date',
           'open', 'high', 'low', 'close', 'volume', 'sha256', 'fetched_at')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_report(path, result):
    if path:
        pending = path.with_suffix('.tmp')
        pending.write_text(json.dumps(result, indent=2))
        pending.replace(path)


def blob_check(compressed, sha, expected_bytes):
    found = hashlib.sha256()
    count = 0
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
        while block := stream.read(1024 * 1024):
            found.update(block)
            count += len(block)
    if count != expected_bytes or found.hexdigest() != sha:
        raise ValueError('Archived source checksum/size mismatch: ' + sha)


def connect(password_file, database='market_data'):
    return psycopg.connect(host='127.0.0.1', port=5432, dbname=database,
                           user='market_admin', password=password_file.read_text().strip(),
                           connect_timeout=10, application_name='market-data-import')


def save_fundamental(conn, path, sha, import_id, raw):
    if not re.fullmatch(r'company/fundamentals/IN[A-Z0-9]{10}\.json', path):
        return
    record = json.loads(raw)
    checked = record.get('last_checked_at')
    if not checked:
        return
    clock = datetime.fromisoformat(checked)
    if clock.tzinfo is None:
        raise ValueError('Fundamental check timestamp requires a timezone')
    conn.execute('INSERT INTO market.fundamentals VALUES (%s,%s,%s,%s,%s,%s) '
                 'ON CONFLICT (isin) DO UPDATE SET record=EXCLUDED.record,last_checked_at=EXCLUDED.last_checked_at,'
                 'last_pulled_at=EXCLUDED.last_pulled_at,sha256=EXCLUDED.sha256,import_id=EXCLUDED.import_id '
                 'WHERE EXCLUDED.last_checked_at > market.fundamentals.last_checked_at',
                 (Path(path).stem, Jsonb(record), checked, record.get('last_pulled_at'), sha, import_id))


def run(bundle, password_file, schema, report, database='market_data'):
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('version') != 1 or manifest.get('environment') not in ('local', 'production'):
        raise ValueError('Unsupported bundle')
    import_id = digest(manifest_path)
    for name, expected in manifest['payload_sha256'].items():
        if name not in ('daily.csv.gz', 'five_minute.csv.gz', 'instruments.json', 'blobs.sqlite') or digest(bundle / name) != expected:
            raise ValueError('Bundle payload checksum mismatch')
    for item in manifest['files']:
        name = Path(item['path'])
        if name.is_absolute() or '..' in name.parts or name.suffix != '.json' or 'private' in name.parts:
            raise ValueError('Unsafe source file path')
        sha = item['sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Unsafe blob identifier')
    with connect(password_file, database) as conn:
        conn.execute(schema.read_text())
        # One importer at a time, including during archive upload commits.
        if not conn.execute('SELECT pg_try_advisory_lock(72061009)').fetchone()[0]:
            raise RuntimeError('Another market importer is active')
        existing = conn.execute('SELECT status, verification FROM market.imports WHERE id = %s', (import_id,)).fetchone()
        if existing and existing[0] == 'complete':
            if report:
                write_report(report, existing[1])
            print(json.dumps(existing[1]), flush=True)
            return existing[1]
        conn.execute('INSERT INTO market.imports(id, environment, manifest, status) VALUES (%s,%s,%s,\'running\') '
                     'ON CONFLICT (id) DO UPDATE SET status = \'running\'',
                     (import_id, manifest['environment'], Jsonb(manifest)))
        conn.commit()
        blob_sizes = {f['sha256']: f['raw_bytes'] for f in manifest['files']}
        present = {row[0] for row in conn.execute('SELECT sha256 FROM market.blobs')}
        packed = sqlite3.connect('file:' + (bundle / 'blobs.sqlite').as_posix() + '?mode=ro', uri=True) if manifest.get('blob_store') == 'sqlite' else None
        blob_rows = []
        for index, (sha, size) in enumerate(blob_sizes.items(), 1):
            if packed:
                row = packed.execute('SELECT raw_bytes,gzip_data FROM blobs WHERE sha256=?', (sha,)).fetchone()
                if not row or row[0] != size:
                    raise ValueError('Missing or mismatched packed blob: ' + sha)
                compressed = row[1]
            else:
                compressed = (bundle / 'blobs' / (sha + '.json.gz')).read_bytes()
            # Check all uploaded source bytes, even when the content already exists.
            blob_check(compressed, sha, size)
            if sha not in present:
                blob_rows.append((sha, size, compressed))
            # Bound both byte buffering and rows. Large frozen files stand alone.
            if len(blob_rows) >= 100 or sum(len(r[2]) for r in blob_rows) >= 4 * 2**20:
                with conn.cursor() as cur:
                    cur.executemany('INSERT INTO market.blobs(sha256,raw_bytes,gzip_data) VALUES (%s,%s,%s) '
                                    'ON CONFLICT DO NOTHING', blob_rows)
                conn.commit()
                blob_rows = []
            if index % 2000 == 0:
                print(f'Validated/archived {index}/{len(blob_sizes)} unique sources', flush=True)
        if blob_rows:
            with conn.cursor() as cur:
                cur.executemany('INSERT INTO market.blobs(sha256,raw_bytes,gzip_data) VALUES (%s,%s,%s) '
                                'ON CONFLICT DO NOTHING', blob_rows)
            conn.commit()
        if packed:
            packed.close()
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO market.source_files(import_id,relative_path,category,sha256) VALUES (%s,%s,%s,%s) '
                            'ON CONFLICT DO NOTHING',
                            [(import_id, f['path'], f['category'], f['sha256']) for f in manifest['files']])
        conn.commit()
        instruments = json.loads((bundle / 'instruments.json').read_text())
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO market.instruments(isin,symbol,provider_key,metadata,fetched_at) '
                            'VALUES (%s,%s,%s,%s,%s) ON CONFLICT (isin) DO UPDATE SET symbol=EXCLUDED.symbol, '
                            'provider_key=EXCLUDED.provider_key, metadata=EXCLUDED.metadata, fetched_at=EXCLUDED.fetched_at '
                            'WHERE EXCLUDED.fetched_at > market.instruments.fetched_at',
                            [(isin, r['instrument']['symbol'], r['instrument']['key'], Jsonb(r['instrument']), r['fetched_at'])
                             for isin, r in instruments.items()])
        # Candle updates and final completion commit together. A interrupted COPY
        # rolls back all canonical changes, while verified immutable blobs can resume.
        conn.execute('CREATE TEMP TABLE stage (LIKE market.candles INCLUDING DEFAULTS INCLUDING CONSTRAINTS) ON COMMIT DROP')
        conn.execute('ALTER TABLE stage ADD PRIMARY KEY (isin, interval_minutes, timestamp_ms)')
        conn.execute(sql.SQL('ALTER TABLE stage ALTER COLUMN import_id SET DEFAULT {}').format(sql.Literal(import_id)))
        for name in ('daily', 'five_minute'):
            print('Loading ' + name + ' candles', flush=True)
            with conn.cursor().copy('COPY stage (' + ','.join(COLUMNS) + ') FROM STDIN WITH (FORMAT CSV)') as copy:
                with gzip.open(bundle / (name + '.csv.gz'), 'rb') as stream:
                    while block := stream.read(1024 * 1024):
                        copy.write(block)
        observed = dict(conn.execute('SELECT interval_minutes,count(*) FROM stage GROUP BY interval_minutes').fetchall())
        expected = {1440: manifest['counts']['daily'], 5: manifest['counts']['five_minute']}
        if any(observed.get(k, 0) != v for k, v in expected.items()):
            raise ValueError('Candle counts do not match the source manifest')
        coverage = {isin + ':' + str(interval): {'count': n, 'first': str(first), 'last': str(last)}
                    for isin, interval, n, first, last in conn.execute(
                        'SELECT isin,interval_minutes,count(*),min(session_date),max(session_date) FROM stage GROUP BY isin,interval_minutes')}
        if coverage != manifest['coverage']:
            raise ValueError('Instrument/session coverage does not match the source manifest')
        conflicts = conn.execute('SELECT count(*) FROM stage s JOIN market.candles c '
                                 'USING (isin,interval_minutes,timestamp_ms) WHERE s.sha256 <> c.sha256').fetchone()[0]
        print(f'Coverage verified; retaining {conflicts} overlapping candle differences', flush=True)
        conn.execute('INSERT INTO market.candle_revisions SELECT c.* FROM market.candles c JOIN stage s '
                     'USING (isin,interval_minutes,timestamp_ms) WHERE s.sha256 <> c.sha256 ON CONFLICT DO NOTHING')
        conn.execute('INSERT INTO market.candle_revisions SELECT s.* FROM stage s JOIN market.candles c '
                     'USING (isin,interval_minutes,timestamp_ms) WHERE s.sha256 <> c.sha256 ON CONFLICT DO NOTHING')
        conn.execute('INSERT INTO market.candles SELECT * FROM stage '
                     'ON CONFLICT (isin,interval_minutes,timestamp_ms) DO UPDATE SET '
                     'session_date=EXCLUDED.session_date,open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,'
                     'close=EXCLUDED.close,volume=EXCLUDED.volume,sha256=EXCLUDED.sha256,'
                     'fetched_at=EXCLUDED.fetched_at,import_id=EXCLUDED.import_id '
                     'WHERE EXCLUDED.fetched_at > market.candles.fetched_at')
        matching = ('s.session_date = t.session_date AND s.open = t.open AND s.high = t.high AND '
                    's.low = t.low AND s.close = t.close AND s.volume = t.volume AND s.sha256 = t.sha256')
        unmatched = conn.execute(
            'SELECT count(*) FROM stage s WHERE NOT EXISTS (SELECT 1 FROM market.candles t '
            'WHERE t.isin=s.isin AND t.interval_minutes=s.interval_minutes AND t.timestamp_ms=s.timestamp_ms AND ' + matching + ') '
            'AND NOT EXISTS (SELECT 1 FROM market.candle_revisions t WHERE t.isin=s.isin AND '
            't.interval_minutes=s.interval_minutes AND t.timestamp_ms=s.timestamp_ms AND ' + matching + ')').fetchone()[0]
        if unmatched:
            raise ValueError(f'Full candle value verification failed for {unmatched} rows')
        file_count = conn.execute('SELECT count(*) FROM market.source_files WHERE import_id=%s', (import_id,)).fetchone()[0]
        if file_count != len(manifest['files']):
            raise ValueError('Archived source file count mismatch')
        for item in manifest['files']:
            if re.fullmatch(r'company/fundamentals/IN[A-Z0-9]{10}\.json', item['path']):
                compressed = conn.execute('SELECT gzip_data FROM market.blobs WHERE sha256=%s',
                                          (item['sha256'],)).fetchone()[0]
                save_fundamental(conn, item['path'], item['sha256'], import_id, gzip.decompress(compressed))
        refresh = manifest.get('refresh')
        if refresh:
            conn.execute('INSERT INTO market.refreshes(import_id,environment,job_id,started_at,completed_at,partial,result) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (import_id, manifest['environment'], refresh.get('job_id'), refresh['started_at'],
                          refresh['completed_at'], bool(refresh.get('partial')), Jsonb(refresh)))
        result = {'import_id': import_id, 'environment': manifest['environment'], 'status': 'complete',
                  'source_files': file_count, 'unique_blobs': len(blob_sizes), 'source_candles': manifest['counts'],
                  'instruments': len(instruments), 'conflicting_candles_preserved': conflicts,
                  'unmatched_candles': unmatched, 'source_checksums_verified': True,
                  'instrument_coverage_verified': True, 'completed_at': datetime.now(timezone.utc).isoformat()}
        if refresh:
            result['refresh_job_id'] = refresh.get('job_id')
        conn.execute('UPDATE market.imports SET status=\'complete\',completed_at=clock_timestamp(),verification=%s WHERE id=%s',
                     (Jsonb(result), import_id))
        conn.commit()
        conn.execute('ANALYZE market.candles')
        conn.execute('ANALYZE market.candle_revisions')
        conn.commit()
        if report:
            write_report(report, result)
        print(json.dumps(result), flush=True)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--password-file', type=Path, default=Path('/srv/market-data/private/admin_password'))
    parser.add_argument('--schema', type=Path, default=Path('/opt/market-data/schema.sql'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    run(args.bundle, args.password_file, args.schema, args.report)
