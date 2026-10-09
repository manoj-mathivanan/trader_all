"""Sync completed refreshes without putting database credentials in Trader.

Run once a minute: production imports directly; local stages a verified bundle
over SSH and waits for the server import receipt. Failed operations are retried.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import re

try:
    from market_data_bundle import export
except ImportError:
    from scripts.market_data_bundle import export

REMOTE = '/srv/market-data/sync'
PAYLOADS = {'manifest.json', 'blobs.sqlite', 'daily.csv.gz', 'five_minute.csv.gz', 'instruments.json'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)


def cleanup(state, token):
    if not re.fullmatch(r'(local|production)-[a-f0-9]{32}', token):
        raise ValueError('Unsafe refresh identity')
    for name in PAYLOADS - {'manifest.json'}:
        (state / 'bundles' / token / name).unlink(missing_ok=True)
    (state / 'bundles' / (token + '.tar')).unlink(missing_ok=True)
    (state / 'inbox' / (token + '.tar')).unlink(missing_ok=True)


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
                handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def ready_refresh(source):
    refresh = read(source / 'market_fetch.json')
    if not refresh.get('completed_at'):
        return None
    for key in ('started_at', 'completed_at'):
        if datetime.fromisoformat(refresh[key]).tzinfo is None:
            raise ValueError('Refresh timestamps require a timezone')
    return refresh


def identity(refresh, environment):
    return environment + '-' + hashlib.sha256(
        (str(refresh.get('job_id')) + ':' + refresh['completed_at']).encode()).hexdigest()[:32]


def bundle_for(source, state, environment, refresh):
    token = identity(refresh, environment)
    bundle = state / 'bundles' / token
    if not (bundle / 'manifest.json').exists():
        # A failed export has no manifest and must not be reused as complete.
        if bundle.exists():
            import shutil
            if not bundle.resolve().is_relative_to((state / 'bundles').resolve()):
                raise ValueError('Unsafe bundle directory')
            shutil.rmtree(bundle)
        export(source, bundle, environment, refresh=refresh)
    return token, bundle


def ssh(args, command, *, allow_missing=False):
    result = subprocess.run(['ssh', '-i', str(args.ssh_key), '-o', 'IdentitiesOnly=yes',
                             '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                             '-o', 'ServerAliveInterval=15', args.ssh_target, command],
                            capture_output=True, text=True, timeout=3600)
    if result.returncode and not allow_missing:
        raise RuntimeError('Database sync SSH failed; will retry')
    return result


def local(args):
    progress = args.state / 'progress.json'
    current = read(progress)
    if current.get('status') == 'queued':
        receipt = ssh(args, f'cat {REMOTE}/reports/{current["token"]}.json', allow_missing=True)
        if receipt.returncode == 255:
            raise RuntimeError('Database receipt connection failed; will retry')
        if receipt.returncode == 0:
            verification = json.loads(receipt.stdout)
            if verification.get('status') != 'complete' or verification.get('environment') != 'local':
                raise ValueError('Invalid database import receipt')
            current.update(status='complete', verification=verification)
            write(progress, current)
            cleanup(args.state, current['token'])
        return
    refresh = ready_refresh(args.source)
    if not refresh or current.get('token') == identity(refresh, 'local'):
        return
    token, bundle = bundle_for(args.source, args.state, 'local', refresh)
    archive = bundle.with_suffix('.tar')
    if not archive.exists():
        with tarfile.open(archive.with_suffix('.tmp'), 'w') as tar:
            for name in sorted(PAYLOADS):
                tar.add(bundle / name, arcname=token + '/' + name)
        archive.with_suffix('.tmp').replace(archive)
    ssh(args, f'mkdir -p {REMOTE}/inbox {REMOTE}/reports')
    subprocess.run(['scp', '-i', str(args.ssh_key), '-o', 'IdentitiesOnly=yes',
                    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', str(archive),
                    f'{args.ssh_target}:{REMOTE}/inbox/{token}.uploading'], check=True, timeout=3600)
    ssh(args, f'mv {REMOTE}/inbox/{token}.uploading {REMOTE}/inbox/{token}.tar')
    write(progress, {'token': token, 'status': 'queued', 'refresh_completed_at': refresh['completed_at']})


def unpack(archive, directory):
    token = archive.stem
    if not re.fullmatch(r'local-[a-f0-9]{32}', token):
        raise ValueError('Unsafe uploaded refresh identity')
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if {m.name for m in members} != {token + '/' + p for p in PAYLOADS} or len(members) != len(PAYLOADS):
            raise ValueError('Unexpected refresh archive members')
        if any(not m.isfile() for m in members):
            raise ValueError('Refresh archive contains a non-file member')
        tar.extractall(directory, filter='data')
    return directory / token


def server(args):
    from import_market_data import run
    args.state.mkdir(parents=True, exist_ok=True)
    reports = args.state / 'reports'
    reports.mkdir(exist_ok=True)
    failures = []
    for archive in sorted((args.state / 'inbox').glob('*.tar')):
        report = reports / (archive.stem + '.json')
        if report.exists() and read(report).get('status') == 'complete':
            cleanup(args.state, archive.stem)
            continue
        try:
            bundle = unpack(archive, args.state / 'bundles')
            if read(bundle / 'manifest.json').get('environment') != 'local':
                raise ValueError('Uploaded refresh must be local')
            run(bundle, args.password_file, args.schema, report)
            cleanup(args.state, archive.stem)
        except Exception as exc:
            failures.append(type(exc).__name__)
    progress = args.state / 'progress.json'
    current = read(progress)
    refresh = ready_refresh(args.source)
    if refresh and current.get('token') != identity(refresh, 'production'):
        try:
            token, bundle = bundle_for(args.source, args.state, 'production', refresh)
            report = reports / (token + '.json')
            verification = run(bundle, args.password_file, args.schema, report)
            write(progress, {'token': token, 'status': 'complete', 'verification': verification,
                             'refresh_completed_at': refresh['completed_at']})
            cleanup(args.state, token)
        except Exception as exc:
            failures.append(type(exc).__name__)
    if failures:
        raise RuntimeError('Refresh sync failed; will retry: ' + ', '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', action='store_true')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--ssh-target')
    parser.add_argument('--ssh-key', type=Path)
    parser.add_argument('--password-file', type=Path, default=Path('/srv/market-data/private/admin_password'))
    parser.add_argument('--schema', type=Path, default=Path('/opt/market-data/schema.sql'))
    args = parser.parse_args()
    if not args.server and (not args.ssh_target or not args.ssh_key):
        parser.error('Local sync requires an SSH target and key')
    with lock(args.state / 'worker.lock'):
        try:
            (server if args.server else local)(args)
            (args.state / 'last-error.json').unlink(missing_ok=True)
        except Exception as exc:
            write(args.state / 'last-error.json', {'at': datetime.now(timezone.utc).isoformat(),
                                                  'error_type': type(exc).__name__, 'retry': True})
            raise


if __name__ == '__main__':
    main()
