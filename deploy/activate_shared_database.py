"""Use the existing authoritative trader_local dataset for the production backend."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import urlopen

ROOT = Path('/opt/trader')
PRIVATE = Path('/srv/trader/private')


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


PROBE = '''
import hashlib,json
from core.research import store,postgres_store as pg
with store.application_lock():
 store.ensure_ready()
 c=pg.connection()
 c.execute('BEGIN READ ONLY')
 assert c.execute('SELECT current_database()').fetchone()[0]=='trader_local'
 assert pg.namespace()=='local'
 assert pg.read('auth/users/manoj'), 'The existing local admin must be preserved.'
 assert not c.execute("SELECT count(*) FROM trader.jobs WHERE status IN ('queued','running')").fetchone()[0], 'Wait for active jobs.'
 rows=c.execute("SELECT name,sha256 FROM trader.documents WHERE name LIKE 'runs/%%' OR name LIKE 'portfolio%%' OR name IN ('settings','strategy_catalog','bar_catalog') ORDER BY name").fetchall()
 print(json.dumps(dict(database='trader_local',namespace=pg.namespace(),documents=c.execute('SELECT count(*) FROM trader.documents').fetchone()[0],runs=c.execute('SELECT count(*) FROM trader.runs').fetchone()[0],research_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())))
 c.rollback()
'''


def main():
    if os.geteuid() != 0 or not Path('/mnt/trader_data').is_mount():
        raise ValueError('Run as root with the database volume mounted.')
    os.umask(0o077)
    compose = ROOT / 'compose.yaml'
    previous = compose.read_text()
    replacements = {
        'TRADER_DB_DSN_FILE: /state/private/database.dsn': 'TRADER_DB_DSN_FILE: /state/private/database-shared.dsn',
        'TRADER_DB_NAMESPACE: production': 'TRADER_DB_NAMESPACE: local',
        'TRADER_KEY_FILE: /state/private/database-token.key': 'TRADER_KEY_FILE: /state/private/database-shared-token.key',
    }
    if all(value in previous for value in replacements.values()):
        raise ValueError('Shared cutover is already configured; inspect rather than repeating it.')
    updated = previous
    for old, new in replacements.items():
        if updated.count(old) != 1:
            raise ValueError('Unexpected deployment configuration: '+old)
        updated = updated.replace(old, new)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path('/mnt/trader_data/migration-backups') / ('shared-database-'+stamp)
    backup.mkdir(mode=0o700)
    shutil.copy2(compose, backup / 'compose.before.yaml')
    image = subprocess.check_output(['docker', 'inspect', 'trader-trader-1', '--format', '{{.Image}}'], text=True).strip()
    (backup / 'image.txt').write_text(image+'\n')
    for source, target in [('database-local.dsn', 'database-shared.dsn'),
                           ('database-local-token.key', 'database-shared-token.key')]:
        destination = PRIVATE / target
        if destination.exists() and destination.read_bytes() != (PRIVATE / source).read_bytes():
            raise ValueError('Preserving unexpected existing shared credentials.')
        shutil.copy2(PRIVATE / source, destination)
        destination.chmod(0o600)
        os.chown(destination, 10001, 10001)
    # The local backend must be stopped first: the advisory lock prevents two workers.
    probe = command('docker', 'run', '--rm', '-i', '--network', 'host',
                    '--mount', 'type=bind,src=/srv/trader/private,dst=/state/private,readonly',
                    '-e', 'TRADER_STORAGE=postgres', '-e', 'TRADER_ENV=production',
                    '-e', 'TRADER_DB_NAMESPACE=local',
                    '-e', 'TRADER_DB_DSN_FILE=/state/private/database-shared.dsn',
                    '-e', 'TRADER_KEY_FILE=/state/private/database-shared-token.key',
                    image, 'python', '-', input=PROBE, text=True, capture_output=True)
    baseline = json.loads(probe.stdout)
    (backup / 'baseline.json').write_text(json.dumps(baseline, indent=2))
    try:
        compose.write_text(updated)
        command('docker', 'compose', 'config', '--quiet', cwd=ROOT)
        command('docker', 'compose', 'stop', '-t', '60', 'trader', cwd=ROOT)
        command('docker', 'compose', 'up', '-d', '--no-build', '--force-recreate', 'trader', cwd=ROOT)
        for attempt in range(60):
            try:
                with urlopen('http://127.0.0.1:8765/api/auth/session', timeout=2) as response:
                    state = json.load(response)
                    if response.status == 200 and state['enabled'] and not state['setup_required']:
                        break
            except (OSError, ValueError):
                pass
            time.sleep(.5)
        else:
            raise ValueError('Shared backend did not become ready.')
        verification = PROBE.replace('with store.application_lock():', 'if True:')
        result = command('docker', 'exec', '-i', 'trader-trader-1', 'python', '-',
                         input=verification, text=True, capture_output=True)
        current = json.loads(result.stdout)
        if current['research_sha256'] != baseline['research_sha256'] or current['runs'] != baseline['runs']:
            raise ValueError('Research inventory changed unexpectedly during cutover.')
        (backup / 'verified.json').write_text(json.dumps(current, indent=2))
        print(json.dumps(dict(status='verified', baseline=baseline, current=current, rollback_directory=str(backup))))
    except BaseException:
        compose.write_text(previous)
        command('docker', 'compose', 'up', '-d', '--no-build', '--force-recreate', 'trader', cwd=ROOT)
        raise


if __name__ == '__main__':
    main()
