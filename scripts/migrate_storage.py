"""Verified, resumable JSON -> PostgreSQL migration without deleting originals.

Export prepares compressed, deduplicated content on the source machine. Import
can run beside PostgreSQL, avoiding a round trip for every historical candle.
Large frozen snapshots are verified as streams, without decoding them on the VM.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import time

from psycopg.types.json import Jsonb
from core.research import postgres_store as pg, store

VERSION = 1


def source_records(source, files):
    """Overlap small-file I/O with bounded memory; large snapshots stay serial."""
    with ThreadPoolExecutor(max_workers=8) as workers:
        pending, size = [], 0
        def flush():
            return zip(pending,workers.map(lambda name:(source/name).read_bytes(),pending))
        for name, (length, _) in files.items():
            if pending and (len(pending)>=64 or size+length>32*1024*1024):
                yield from flush()
                pending, size = [], 0
            if length>8*1024*1024:
                yield name,(source/name).read_bytes()
            else:
                pending.append(name)
                size+=length
        if pending:
            yield from flush()


def inventory(source):
    result = {}
    for path in sorted(source.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(source).as_posix()
        if name.split('/')[0] in ('private','locks') or any(p.startswith('.') for p in path.relative_to(source).parts):
            continue
        if path.suffix in ('.lock','.tmp','.log','.pid'):
            continue
        stat = path.stat()
        result[name] = (stat.st_size, stat.st_mtime_ns)
    return result


def projection(name):
    return name == 'jobs' or name.startswith(('bars/','intraday/','runs/','portfolios/','portfolio_scenarios/'))


def export(source, destination, *, stopped=False, log=print):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not stopped:
        raise ValueError('Stop the source application and runners, then pass --stopped to export.')
    if not source.is_dir() or destination.is_relative_to(source):
        raise ValueError('Choose an existing source directory and an archive destination outside it.')
    before = inventory(source)
    if not before:
        raise ValueError('The source contains no application data.')
    manifest = dict(version=VERSION, source_environment=os.environ.get('TRADER_ENV','local'),
                    created_at=store.now(), records=[], credentials=[], source_bytes=0)
    seen, started = set(), time.monotonic()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name+'.partial')

    def add(archive, name, raw):
        info = tarfile.TarInfo(name)
        info.size, info.mode = len(raw), 0o600
        archive.addfile(info, io.BytesIO(raw))

    def document(archive, name, value, source_hash):
        raw = pg.pack(value)
        record = dict(kind='document', name=store.validate_name(name),
                      source_sha256=source_hash, sha256=hashlib.sha256(raw).hexdigest(),
                      raw_bytes=len(raw), metadata=pg.metadata(name,value), projection=projection(name))
        content(archive, record, raw)

    def content(archive, record, raw):
        if record['sha256'] not in seen:
            add(archive, 'contents/'+record['sha256']+'.gz', gzip.compress(raw,compresslevel=6,mtime=0))
            seen.add(record['sha256'])
        manifest['records'].append(record)

    try:
        with tarfile.open(temporary,'w') as archive:
            for index, (filename, raw) in enumerate(source_records(source,before),1):
                source_hash = hashlib.sha256(raw).hexdigest()
                manifest['source_bytes'] += len(raw)
                if filename.endswith('.json'):
                    value = json.loads(raw.decode('utf-8-sig'))
                    del raw
                    document(archive,filename[:-5],value,source_hash)
                    del value
                else:
                    content(archive,dict(kind='artifact',name=store.validate_name(filename),
                                         source_sha256=source_hash,sha256=source_hash,raw_bytes=len(raw)),raw)
                    del raw
                if index % 1000 == 0:
                    log(f'Prepared {index}/{len(before)} files ({int(time.monotonic()-started)}s).',flush=True)
            # Reference data and initial bundled strategy definitions become DB
            # documents; runtime never needs to scan those source directories.
            from core.research.strategy_presets import bundled_presets
            seeds = {'strategy_catalog':bundled_presets()}
            for path in (store.ROOT/'reference_data').glob('*.json'):
                seeds['reference/'+path.stem] = json.loads(path.read_text(encoding='utf-8'))
            for name, value in seeds.items():
                if name+'.json' not in before:
                    document(archive,name,value,hashlib.sha256(pg.pack(value)).hexdigest())
            private = Path(os.environ.get('TRADER_PRIVATE_DIR',source/'private'))
            token_path = private/'upstox.json'
            if token_path.is_file():
                record = json.loads(token_path.read_text(encoding='utf-8-sig'))
                token = record.get('access_token')
                if not token and record.get('encrypted_token'):
                    token = store.cipher().decrypt(record['encrypted_token'].encode()).decode()
                if token:
                    encrypted = store.cipher().encrypt(token.encode())
                    manifest['credentials'].append(dict(owner=os.environ.get('TRADER_USER_ID','owner'),
                                                         encrypted=base64.b64encode(encrypted).decode()))
            if before != inventory(source):
                raise ValueError('Source data changed during export. Stop its writers and retry.')
            manifest['unique_contents'] = len(seen)
            encoded = pg.pack(manifest)
            add(archive,'manifest.json',encoded)
            add(archive,'manifest.sha256',hashlib.sha256(encoded).hexdigest().encode())
        os.replace(temporary,destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    log(f'Prepared {len(manifest["records"])} records and {len(seen)} unique contents.',flush=True)
    return manifest


def checked_content(archive, record):
    digest = record['sha256']
    if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid archive content digest.')
    raw = archive.extractfile('contents/'+digest+'.gz').read()
    checksum, length = hashlib.sha256(), 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as decoded:
        while chunk := decoded.read(1024*1024):
            checksum.update(chunk)
            length += len(chunk)
    if checksum.hexdigest()!=digest or length!=record['raw_bytes']:
        raise ValueError('Migration content checksum or length mismatch.')
    return raw


def load_manifest(archive):
    raw = archive.extractfile('manifest.json').read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != archive.extractfile('manifest.sha256').read().decode():
        raise ValueError('Migration manifest checksum mismatch.')
    value = json.loads(raw)
    if value.get('version') != VERSION:
        raise ValueError('Unsupported migration format.')
    identities = set()
    for record in value['records']:
        store.validate_name(record['name'])
        identity = (record['kind'],record['name'])
        if record['kind'] not in ('document','artifact') or identity in identities:
            raise ValueError('Invalid or duplicate migration key.')
        identities.add(identity)
    return value, digest


def verify(archive, manifest, *, log=print):
    """Read every stored content back and verify bytes, not just record counts."""
    conn, ns = pg.connection(), pg.namespace()
    checked = set()
    for index, record in enumerate(manifest['records'],1):
        table = 'documents' if record['kind']=='document' else 'artifacts'
        row = conn.execute(f'SELECT sha256 FROM trader.{table} WHERE namespace=%s AND name=%s',
                           (ns,record['name'])).fetchone()
        if not row or row[0] != record['sha256']:
            raise ValueError('Database record differs from migration: '+record['name'])
        if row[0] not in checked:
            content = conn.execute('SELECT content,raw_bytes FROM trader.contents WHERE sha256=%s',(row[0],)).fetchone()
            checksum, length = hashlib.sha256(), 0
            with gzip.GzipFile(fileobj=io.BytesIO(bytes(content[0]))) as decoded:
                while chunk := decoded.read(1024*1024):
                    checksum.update(chunk)
                    length += len(chunk)
            if checksum.hexdigest()!=row[0] or length!=record['raw_bytes'] or length!=content[1]:
                raise ValueError('Database content failed verification: '+record['name'])
            checked.add(row[0])
        if index % 2000 == 0:
            log(f'Verified {index}/{len(manifest["records"])} records.',flush=True)
    return len(checked)


def restore(source, *, verify_only=False, log=print):
    if not store.database_enabled():
        raise ValueError('Set TRADER_STORAGE=postgres and the target database connection first.')
    pg.initialize()
    with pg.mutex('application-instance',timeout=0), pg.mutex('storage-migration',timeout=0), tarfile.open(source,'r') as archive:
        manifest, fingerprint = load_manifest(archive)
        with pg.transaction():
            ready = pg.read('storage/migration_ready')
            if ready and ready.get('manifest_sha256') != fingerprint:
                raise ValueError('The target namespace already contains a different completed migration.')
            if not verify_only:
                pg.write('storage/migration_status',dict(status='importing',manifest_sha256=fingerprint))
        conn, ns = pg.connection(), pg.namespace()
        if not verify_only:
            known = {row[0] for row in conn.execute('SELECT sha256 FROM trader.contents')}
            existing={(table,name):digest for table in ('documents','artifacts')
                      for name,digest in conn.execute(f'SELECT name,sha256 FROM trader.{table} WHERE namespace=%s',(ns,))}
            # Bound each atomic checkpoint while amortizing WAL fsync. Resume
            # skips committed records and retries the last incomplete batch.
            for start in range(0,len(manifest['records']),64):
                with pg.transaction():
                    for index,record in enumerate(manifest['records'][start:start+64],start+1):
                        table='documents' if record['kind']=='document' else 'artifacts'
                        digest,name=record['sha256'],record['name']
                        previous=existing.get((table,name))
                        if previous and previous!=digest:
                            raise ValueError('Refusing to overwrite conflicting target data: '+name)
                        if not previous:
                            content=checked_content(archive,record)
                            if digest not in known:
                                conn.execute('INSERT INTO trader.contents(sha256,content,raw_bytes) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                                             (digest,content,record['raw_bytes']))
                            if table=='documents':
                                value=json.loads(gzip.decompress(content)) if projection(name) else None
                                conn.execute('INSERT INTO trader.documents(namespace,name,sha256,metadata) VALUES (%s,%s,%s,%s)',
                                             (ns,name,digest,Jsonb(pg.metadata(name,value) if value is not None else record.get('metadata',{}))))
                                if projection(name):pg.project(name,value,digest)
                            else:
                                conn.execute('INSERT INTO trader.artifacts(namespace,name,sha256) VALUES (%s,%s,%s)',(ns,name,digest))
                            conn.execute('INSERT INTO trader.migrations(namespace,name,source_sha256,destination_sha256) VALUES (%s,%s,%s,%s) ON CONFLICT(namespace,name) DO UPDATE SET source_sha256=EXCLUDED.source_sha256,destination_sha256=EXCLUDED.destination_sha256,verified_at=now()',
                                         (ns,record['kind']+':'+name,record['source_sha256'],digest))
                            existing[(table,name)]=digest
                        known.add(digest)
                        if index % 1000 == 0:
                            log(f'Imported {index}/{len(manifest["records"])} records.',flush=True)
            with pg.transaction():
                for credential in manifest.get('credentials',[]):
                    encrypted = base64.b64decode(credential['encrypted'])
                    store.cipher().decrypt(encrypted)  # Require the intended runtime key.
                    pg.save_token(credential['owner'],encrypted)
        verified = verify(archive,manifest,log=log)
        receipt = dict(status='verified',manifest_sha256=fingerprint,namespace=ns,
                       records=len(manifest['records']),unique_contents=verified,
                       source_bytes=manifest['source_bytes'],verified_at=store.now())
        if not verify_only:
            with pg.transaction():
                pg.write('storage/migration_ready',receipt)
                pg.write('storage/migration_status',receipt)
        log(json.dumps(receipt),flush=True)
        return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('export')
    prepare.add_argument('--source',type=Path,required=True)
    prepare.add_argument('--destination',type=Path,required=True)
    prepare.add_argument('--stopped',action='store_true')
    apply=commands.add_parser('import')
    apply.add_argument('--source',type=Path,required=True)
    apply.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='export':export(args.source,args.destination,stopped=args.stopped)
        else:restore(args.source,verify_only=args.verify_only)
    finally:
        pg.close()


if __name__=='__main__':
    main()
