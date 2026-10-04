"""Content-addressed, compressed snapshots of non-secret Trader JSON state."""
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


def snapshot(source, target):
    blobs = target / 'blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for path in sorted(source.rglob('*')):
        if not path.is_file() or 'private' in path.relative_to(source).parts or path.suffix == '.tmp':
            continue
        if path.suffix != '.json':
            raise ValueError(f'Unexpected file: {path}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        blob = blobs / (digest + '.json.gz')
        if not blob.exists():
            raw = path.read_text(encoding='utf-8')
            json.loads(raw)
            if re.search(r'"(?:access_token|encrypted_token|api_key|api_secret|password|private_key)"\s*:', raw, re.I) or re.search(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', raw):
                raise ValueError(f'Credential found: {path}')
            del raw
            pending = blob.with_suffix('.tmp')
            with path.open('rb') as src, pending.open('wb') as dst:
                with gzip.GzipFile(filename='', mode='wb', fileobj=dst, mtime=0) as compressed:
                    shutil.copyfileobj(src, compressed)
            pending.replace(blob)
        manifest[path.relative_to(source).as_posix()] = digest
    target.mkdir(parents=True, exist_ok=True)
    pending = target / 'manifest.tmp'
    pending.write_text(json.dumps({'version': 1, 'files': manifest}, indent=2) + '\n', encoding='utf-8')
    pending.replace(target / 'manifest.json')
    used = set(manifest.values())
    for blob in blobs.glob('*.json.gz'):
        if blob.name.removesuffix('.json.gz') not in used:
            blob.unlink()
    print(f'Snapshot: {len(manifest)} files, {len(used)} unique blobs.')


def restore(source, target):
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest['version'] != 1:
        raise ValueError('Unsupported snapshot version')
    if target.exists() and any(target.iterdir()):
        raise ValueError('Restore destination must be empty')
    target.mkdir(parents=True, exist_ok=True)
    for name, digest in manifest['files'].items():
        path = (target / name).resolve()
        if not path.is_relative_to(target.resolve()) or 'private' in Path(name).parts or path.suffix != '.json' or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Unsafe snapshot manifest')
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(source / 'blobs' / (digest + '.json.gz'), 'rb') as src, path.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError(f'Corrupt snapshot: {name}')
    print(f'Restored {len(manifest["files"])} verified files.')


if __name__ == '__main__':
    {'snapshot': snapshot, 'restore': restore}[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
