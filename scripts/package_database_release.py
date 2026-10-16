"""Package runtime source with byte-level integrity checks, excluding state/secrets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def package(destination):
    root=Path(__file__).resolve().parents[1]
    files=[]
    for folder in ('core','strategies','reference_data','dashboard','scripts'):
        files.extend(p for p in sorted((root/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts)
    for name in ('Dockerfile','requirements-lock.txt','requirements.txt','package.json','package-lock.json','.dockerignore','compose.yaml',
                 'deploy/market-data/import_investor_data.py','deploy/market-data/export_investor_data.py','deploy/market-data/investor_schema.sql',
                 'deploy/activate_database.py','deploy/database_backup.py'):
        files.append(root/name)
    with tarfile.open(destination,'w:gz') as archive:
        for path in files:archive.add(path,arcname=path.relative_to(root).as_posix())
        raw=json.dumps({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},sort_keys=True).encode()
        item=tarfile.TarInfo('database-release.json');item.size=len(raw);archive.addfile(item,io.BytesIO(raw))
    print(f'Packaged {len(files)} runtime files.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--destination',type=Path,required=True)
    package(parser.parse_args().destination)
