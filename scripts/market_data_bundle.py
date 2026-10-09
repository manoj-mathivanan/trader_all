"""Export only market inputs; credentials and paper/account state are excluded.

Standard-library only. Source JSON files are retained byte-for-byte as gzip blobs;
large frozen experiment files are streamed, never parsed on the small server.
"""
import argparse
import csv
from datetime import date, datetime, time, timezone, timedelta
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3

IST = timezone(timedelta(hours=5, minutes=30))
FOLDERS = ('bars', 'intraday/5m', 'run_data', 'run_intraday', 'run_fundamentals',
           'universes', 'metadata', 'provider_overrides', 'company')
SECRET_KEYS = re.compile(rb'"(?:access_token|encrypted_token|api_key|api_secret|password|private_key|authorization)"\s*:', re.I)
JWT = re.compile(rb'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
COLUMNS = ('isin', 'interval_minutes', 'timestamp_ms', 'session_date',
           'open', 'high', 'low', 'close', 'volume', 'sha256', 'fetched_at')


def candle_row(instrument, bar, interval, fetched_at):
    day = date.fromisoformat(bar['date'])
    stamp = bar.get('timestamp')
    if stamp is None and interval == 1440:
        stamp = int(datetime.combine(day, time(), IST).timestamp() * 1000)
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        raise ValueError('Candle timestamp must be an integer in milliseconds')
    instant = datetime.fromtimestamp(stamp / 1000, IST)
    if instant.date() != day:
        raise ValueError('Candle timestamp and session date disagree')
    if interval == 5 and (instant.minute % 5 or instant.second or instant.microsecond):
        raise ValueError('Candle is outside a five-minute boundary')
    values = [float(bar[key]) for key in ('open', 'high', 'low', 'close', 'volume')]
    o, h, l, c, v = values
    if not all(math.isfinite(x) for x in values) or min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c) or l > h:
        raise ValueError('Invalid OHLCV candle')
    # repr(float) is an exact round-trip representation of the source JSON number.
    fields = [instrument['isin'], str(interval), str(stamp), str(day), *map(repr, values)]
    digest = hashlib.sha256(json.dumps(fields, separators=(',', ':')).encode()).hexdigest()
    return [*fields, digest, fetched_at]


def archive(path, blobs):
    """Hash, scan for secrets and gzip the same stream; source changes halt export."""
    before = path.stat()
    pending = blobs / 'pending.gz'
    digest = hashlib.sha256()
    tail = b''
    with path.open('rb') as src, pending.open('wb') as dst:
        with gzip.GzipFile(filename='', mode='wb', fileobj=dst, mtime=0, compresslevel=1) as zipped:
            while block := src.read(1024 * 1024):
                scan = tail + block
                if SECRET_KEYS.search(scan) or JWT.search(scan):
                    raise ValueError(f'Credential-like content in market input {path.name}')
                tail = scan[-8192:]
                digest.update(block)
                zipped.write(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Source changed during export: {path.name}; retry when downloads are idle')
    sha = digest.hexdigest()
    target = blobs / (sha + '.json.gz')
    if target.exists():
        pending.unlink()
    else:
        pending.replace(target)
    return sha, before.st_size


def archive_sqlite(path, connection):
    """Pack small blobs into one file instead of creating 50,000 tiny files."""
    before = path.stat()
    digest = hashlib.sha256()
    raw = path.read_bytes() if before.st_size <= 4 * 2**20 else None
    if raw is not None:
        if SECRET_KEYS.search(raw) or JWT.search(raw):
            raise ValueError(f'Credential-like content in market input {path.name}')
        digest.update(raw)
    else:
        tail = b''
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                scan = tail + block
                if SECRET_KEYS.search(scan) or JWT.search(scan):
                    raise ValueError(f'Credential-like content in market input {path.name}')
                tail = scan[-8192:]
                digest.update(block)
    sha = digest.hexdigest()
    if not connection.execute('SELECT 1 FROM blobs WHERE sha256=?', (sha,)).fetchone():
        if raw is not None:
            compressed = gzip.compress(raw, compresslevel=1, mtime=0)
        else:
            output = io.BytesIO()
            check = hashlib.sha256()
            with path.open('rb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0, compresslevel=1) as zipped:
                while block := stream.read(1024 * 1024):
                    check.update(block)
                    zipped.write(block)
            if check.hexdigest() != sha:
                raise ValueError(f'Source changed during export: {path.name}')
            compressed = output.getvalue()
        connection.execute('INSERT INTO blobs VALUES (?,?,?)', (sha, before.st_size, compressed))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Source changed during export: {path.name}; retry when downloads are idle')
    return sha, before.st_size, raw


def export(source, target, environment, *, refresh=None):
    source, target = source.resolve(), target.resolve()
    if not source.is_dir() or target == source or source.is_relative_to(target):
        raise ValueError('Invalid source/target directories')
    if target.exists() and any(target.iterdir()):
        raise ValueError('Bundle destination must be empty')
    target.mkdir(parents=True, exist_ok=True)
    # SQLite is a portable transfer container, not the shared production database.
    # A manifest is written only after completion, so interrupted exports cannot
    # be mistaken for valid bundles. Avoid per-file writes on Windows.
    blob_path = target / 'blobs.sqlite'
    blob_store = sqlite3.connect(blob_path)
    blob_store.execute('PRAGMA journal_mode=OFF')
    blob_store.execute('PRAGMA synchronous=OFF')
    blob_store.execute('CREATE TABLE blobs (sha256 TEXT PRIMARY KEY, raw_bytes INTEGER NOT NULL, gzip_data BLOB NOT NULL)')
    manifest = {'version': 1, 'environment': environment,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'blob_store': 'sqlite', 'files': [], 'counts': {'daily': 0, 'five_minute': 0}, 'coverage': {},
                'snapshot_policy': 'Frozen/derived inputs are archived exactly, never merged into provider candles.'}
    instruments = {}
    if refresh:
        manifest['refresh'] = refresh
        since = datetime.fromisoformat(refresh['started_at']).timestamp() - 1
        until = datetime.fromisoformat(refresh['completed_at']).timestamp() + 1
    outputs = {name: gzip.open(target / (name + '.csv.gz'), 'wt', encoding='utf-8', newline='', compresslevel=1)
               for name in ('daily', 'five_minute')}
    writers = {name: csv.writer(out, lineterminator='\n') for name, out in outputs.items()}
    try:
        for folder in FOLDERS:
            if refresh and folder.startswith('run_'):
                continue
            paths = sorted((source / folder).rglob('*.json'))
            if refresh:
                paths = [p for p in paths if since <= p.stat().st_mtime <= until]
            for index, path in enumerate(paths, 1):
                relative = path.relative_to(source).as_posix()
                sha, size, raw = archive_sqlite(path, blob_store)
                manifest['files'].append({'path': relative, 'category': folder,
                                          'sha256': sha, 'raw_bytes': size})
                if folder in ('bars', 'intraday/5m'):
                    # Parse the immutable archived bytes, not a second source read.
                    if raw is None:
                        raw = gzip.decompress(blob_store.execute('SELECT gzip_data FROM blobs WHERE sha256=?', (sha,)).fetchone()[0])
                    record = json.loads(raw)
                    instrument = record['instrument']
                    if folder == 'bars' and path.stem != instrument['isin']:
                        raise ValueError(f'Instrument/path mismatch: {relative}')
                    if folder == 'intraday/5m' and path.parent.name != instrument['isin']:
                        raise ValueError(f'Instrument/path mismatch: {relative}')
                    fetched = record.get('fetched_at') or '1970-01-01T00:00:00+00:00'
                    clock = datetime.fromisoformat(fetched)
                    if clock.tzinfo is None:
                        raise ValueError(f'Missing fetched_at timezone: {relative}')
                    prior = instruments.get(instrument['isin'])
                    if prior is None or clock > datetime.fromisoformat(prior['fetched_at']):
                        instruments[instrument['isin']] = {'instrument': instrument, 'fetched_at': fetched}
                    name = 'daily' if folder == 'bars' else 'five_minute'
                    interval = 1440 if name == 'daily' else 5
                    seen = set()
                    for bar in record['bars']:
                        if refresh and bar['date'] < refresh['daily_start' if interval == 1440 else 'minute_start']:
                            continue
                        row = candle_row(instrument, bar, interval, fetched)
                        if row[2] in seen:
                            raise ValueError(f'Duplicate candle in {relative}')
                        if interval == 5 and row[3] != path.stem:
                            raise ValueError(f'Session/path mismatch: {relative}')
                        seen.add(row[2])
                        writers[name].writerow(row)
                        manifest['counts'][name] += 1
                        key = instrument['isin'] + ':' + str(interval)
                        coverage = manifest['coverage'].setdefault(key, {'count': 0, 'first': row[3], 'last': row[3]})
                        coverage['count'] += 1
                        coverage['first'] = min(coverage['first'], row[3])
                        coverage['last'] = max(coverage['last'], row[3])
                if index % 2000 == 0:
                    blob_store.commit()
                    print(f'{environment}: {folder} {index}/{len(paths)} files', flush=True)
            print(f'{environment}: archived {folder}: {len(paths)} files', flush=True)
    finally:
        for out in outputs.values():
            out.close()
        blob_store.commit()
        unique_blobs = blob_store.execute('SELECT count(*) FROM blobs').fetchone()[0]
        blob_store.close()
    (target / 'instruments.json').write_text(json.dumps(instruments, sort_keys=True), encoding='utf-8')
    for name in ('daily.csv.gz', 'five_minute.csv.gz', 'instruments.json', 'blobs.sqlite'):
        with (target / name).open('rb') as stream:
            manifest.setdefault('payload_sha256', {})[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest['unique_blobs'] = unique_blobs
    manifest['compressed_bytes'] = sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    (target / 'manifest.json').write_bytes(raw)
    print(json.dumps({'environment': environment, 'counts': manifest['counts'], 'files': len(manifest['files']),
                      'unique_blobs': manifest['unique_blobs'], 'compressed_MiB': round(manifest['compressed_bytes'] / 2**20, 2),
                      'manifest_sha256': hashlib.sha256(raw).hexdigest()}), flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--environment', required=True, choices=('local', 'production'))
    args = parser.parse_args()
    export(args.source, args.target, args.environment)
