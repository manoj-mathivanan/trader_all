"""Wait for a known-size SSH upload and import it in a durable server job."""
import argparse
from pathlib import Path
import re
import tarfile
import tempfile
import time

from import_market_data import run


def main(name, expected_bytes):
    if not re.fullmatch('[a-z0-9-]{1,80}', name) or expected_bytes <= 0:
        raise ValueError('Invalid uploaded bundle name/size')
    root = Path('/srv/market-data/imports')
    archive = root / (name + '.tar')
    deadline = time.monotonic() + 1200
    print('Waiting for uploaded bundle: ' + name, flush=True)
    while not archive.exists() or archive.stat().st_size != expected_bytes:
        if archive.exists() and archive.stat().st_size > expected_bytes:
            raise ValueError('Upload exceeds expected size')
        if time.monotonic() > deadline:
            raise TimeoutError('Upload did not finish within 20 minutes')
        time.sleep(5)
    destination = root / name
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix='unpack-', dir=root) as temporary:
            staging = Path(temporary)
            allowed = {name, name + '/', *(name + '/' + file for file in
                       ('blobs.sqlite', 'daily.csv.gz', 'five_minute.csv.gz', 'instruments.json', 'manifest.json'))}
            with tarfile.open(archive, 'r:') as bundle:
                if any(member.name not in allowed or not (member.isfile() or member.isdir()) for member in bundle.getmembers()):
                    raise ValueError('Unexpected file/link in uploaded bundle')
                bundle.extractall(staging, filter='data')
            (staging / name).rename(destination)
    print('Upload unpacked; starting verified import', flush=True)
    run(destination, Path('/srv/market-data/private/admin_password'),
        Path('/opt/market-data/schema.sql'), root / 'local-verification.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('expected_bytes', type=int)
    args = parser.parse_args()
    main(args.name, args.expected_bytes)
