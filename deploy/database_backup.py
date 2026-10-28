"""Dump both isolated application databases onto the existing attached volume."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    import fcntl
    os.umask(0o077)
    if not Path('/mnt/trader_data').is_mount():raise ValueError('Database volume is not mounted.')
    lock=Path('/run/trader-database-backup.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    directory=Path('/mnt/trader_data/backups/trader')
    directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o700)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    receipts=[]
    for environment in ('production','local'):
        path=directory/('trader-'+environment+'-'+stamp+'.dump')
        temporary=path.with_suffix('.partial')
        command=['docker','run','--rm','--log-driver','none','--network','host','--memory','256m','--memory-swap','512m','--cpus','0.5',
                 '--mount','type=bind,src=/srv/market-data/private/admin_password,dst=/run/secrets/admin_password,readonly',
                 '-e','PGDATABASE=trader_'+environment,'postgres:17-alpine','sh','-c',
                 'export PGPASSWORD="$(cat /run/secrets/admin_password)"; exec pg_dump -h 127.0.0.1 -U market_admin -d "$PGDATABASE" -Fc -Z 1']
        try:
            with temporary.open('xb') as output:subprocess.run(command,stdout=output,check=True)
            with temporary.open('rb') as source:
                subprocess.run(['docker','run','--rm','--log-driver','none','-i','--memory','128m','postgres:17-alpine','pg_restore','--list'],stdin=source,stdout=subprocess.DEVNULL,check=True)
            checksum=hashlib.sha256()
            with temporary.open('rb') as source:
                while chunk:=source.read(1024*1024):checksum.update(chunk)
            temporary.rename(path)
            path.with_suffix('.sha256').write_text(checksum.hexdigest()+'  '+path.name+'\n')
            key=Path('/srv/trader/private')/('database-token.key' if environment=='production' else 'database-local-token.key')
            key_directory=directory/'keys';key_directory.mkdir(exist_ok=True);key_directory.chmod(0o700)
            key_name=environment+'-'+hashlib.sha256(key.read_bytes()).hexdigest()+'.key'
            key_backup=key_directory/key_name
            if not key_backup.exists():shutil.copy2(key,key_backup);key_backup.chmod(0o600)
            receipts.append(dict(environment=environment,file=path.name,bytes=path.stat().st_size,sha256=checksum.hexdigest(),token_key='keys/'+key_name))
            # Preserve the existing seven-daily-backup policy, after a new dump
            # has passed validation. Only this script's own named dumps qualify.
            for old in sorted(directory.glob('trader-'+environment+'-*.dump'),reverse=True)[7:]:
                old.unlink();old.with_suffix('.sha256').unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
    (directory/'latest.json').write_text(json.dumps(dict(completed_at=datetime.now(timezone.utc).isoformat(),databases=receipts),indent=2))
    print(json.dumps(receipts))


if __name__=='__main__':main()
