"""Inspect or atomically complete a partially uploaded market bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main(args):
    if not re.fullmatch('[a-z0-9-]{1,80}', args.name):
        raise ValueError('Invalid bundle name')
    archive = Path('/srv/market-data/imports') / (args.name + '.tar')
    if args.mode == 'inspect':
        print(json.dumps({'bytes': archive.stat().st_size, 'sha256': digest(archive)}), flush=True)
        return
    suffix = archive.with_suffix('.tar.tail')
    if archive.stat().st_size != args.offset or digest(archive) != args.prefix_sha256:
        raise ValueError('Partial upload differs from the verified prefix')
    if suffix.stat().st_size != args.total_bytes - args.offset or digest(suffix) != args.suffix_sha256:
        raise ValueError('Uploaded suffix checksum/size mismatch')
    complete = archive.with_suffix('.tar.complete')
    found = hashlib.sha256()
    with complete.open('xb') as dst:
        for path in (archive, suffix):
            with path.open('rb') as src:
                while block := src.read(1024 * 1024):
                    found.update(block)
                    dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    if found.hexdigest() != args.full_sha256 or complete.stat().st_size != args.total_bytes:
        raise ValueError('Reassembled archive checksum/size mismatch')
    complete.replace(archive)
    print('Complete upload verified byte-for-byte and published atomically.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'finish'))
    parser.add_argument('name')
    parser.add_argument('--offset', type=int)
    parser.add_argument('--total-bytes', type=int)
    parser.add_argument('--prefix-sha256')
    parser.add_argument('--suffix-sha256')
    parser.add_argument('--full-sha256')
    main(parser.parse_args())
