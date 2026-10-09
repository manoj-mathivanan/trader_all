"""Independently verify stored archive bytes and report database coverage."""
import argparse
import gzip
import hashlib
import gc
import tempfile
import json
from pathlib import Path
from datetime import datetime, timezone

import psycopg


def verify(report):
    password = Path('/srv/market-data/private/admin_password').read_text().strip()
    with psycopg.connect(host='127.0.0.1', dbname='market_data', user='market_admin', password=password) as conn:
        imports = []
        for import_id, environment, status, manifest, result in conn.execute(
                'SELECT id,environment,status,manifest,verification FROM market.imports ORDER BY started_at'):
            if status != 'complete':
                raise ValueError('An import is not complete: ' + import_id)
            actual = {p: sha for p, sha in conn.execute(
                'SELECT relative_path,sha256 FROM market.source_files WHERE import_id=%s', (import_id,))}
            expected = {f['path']: f['sha256'] for f in manifest['files']}
            if actual != expected:
                raise ValueError('Source file mapping differs from manifest')
            imports.append(result)
        if not imports:
            raise ValueError('No completed imports')
        # The final manifest can contain tens of thousands of paths. Release it
        # before scanning archives on the 1 GB host.
        del actual, expected, manifest
        gc.collect()
        validated = 0
        raw_bytes = compressed_bytes = 0
        with conn.cursor(name='archive_verification') as cursor:
            cursor.itersize = 1
            cursor.execute('SELECT sha256,raw_bytes,octet_length(gzip_data), '
                           'CASE WHEN octet_length(gzip_data) <= 4194304 THEN gzip_data END '
                           'FROM market.blobs ORDER BY sha256')
            for sha, size, compressed_size, compressed in cursor:
                digest = hashlib.sha256()
                count = 0
                # BYTEA decoding can allocate several copies of a large value.
                # Fetch large values in bounded slices and spool them to disk.
                with tempfile.SpooledTemporaryFile(max_size=4194304) as archive:
                    if compressed is not None:
                        archive.write(compressed)
                    else:
                        for offset in range(0, compressed_size, 1024 * 1024):
                            block = conn.execute(
                                'SELECT substring(gzip_data FROM %s FOR %s) FROM market.blobs WHERE sha256=%s',
                                (offset + 1, 1024 * 1024, sha)).fetchone()[0]
                            archive.write(block)
                    archive.seek(0)
                    with gzip.GzipFile(fileobj=archive, mode='rb') as stream:
                        while block := stream.read(1024 * 1024):
                            count += len(block)
                            digest.update(block)
                if count != size or digest.hexdigest() != sha:
                    raise ValueError('Stored blob verification failed: ' + sha)
                validated += 1
                raw_bytes += size
                compressed_bytes += compressed_size
                if validated % 10000 == 0:
                    print(f'Independently verified {validated} database archive blobs', flush=True)
        candles = []
        for interval, n, instruments, first, last in conn.execute(
                'SELECT interval_minutes,count(*),count(DISTINCT isin),min(session_date),max(session_date) '
                'FROM market.candles GROUP BY interval_minutes ORDER BY interval_minutes'):
            candles.append({'interval_minutes': interval, 'count': n, 'instruments': instruments,
                            'first_session': str(first), 'last_session': str(last)})
        result = {'verified_at': datetime.now(timezone.utc).isoformat(), 'imports': imports,
                  'candles': candles, 'instruments': conn.execute('SELECT count(*) FROM market.instruments').fetchone()[0],
                  'source_files': conn.execute('SELECT count(*) FROM market.source_files').fetchone()[0],
                  'verified_archive_blobs': validated, 'unique_archive_raw_bytes': raw_bytes,
                  'unique_archive_compressed_bytes': compressed_bytes,
                  'candle_revisions': conn.execute('SELECT count(*) FROM market.candle_revisions').fetchone()[0],
                  'database_bytes': conn.execute('SELECT pg_database_size(current_database())').fetchone()[0]}
    report.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('/srv/market-data/imports/database-verification.json'))
    verify(parser.parse_args().report)
