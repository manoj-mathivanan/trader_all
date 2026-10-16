"""Activate the verified database release on the existing production server."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
from urllib.request import urlopen
from urllib.error import HTTPError,URLError

ROOT=Path('/opt/trader')
STAGE=Path('/mnt/trader_data/deploy-stage/database-code')
BACKUP=Path('/mnt/trader_data/migration-backups')
DATA=Path('/srv/trader/data')
ORIGINAL=Path('/srv/trader/data.before-database-20261016')


def command(*args,**kwargs):
    return subprocess.run(list(args),check=True,**kwargs)


def database_probe():
    code="from core.research import store; store.ensure_ready(); print('Verified production database connection and encrypted token.')"
    command('docker','run','--rm','--network','host',
            '--mount','type=bind,src=/srv/trader/private,dst=/state/private,readonly',
            '-e','TRADER_STORAGE=postgres','-e','TRADER_ENV=production','-e','TRADER_DB_NAMESPACE=production',
            '-e','TRADER_DB_DSN_FILE=/state/private/database.dsn','-e','TRADER_KEY_FILE=/state/private/database-token.key',
            'trader-trader:database-ready','python','-c',code)


def restore_original():
    subprocess.run(['docker','stop','-t','60','trader-trader-1'],check=False)
    if (BACKUP/'production-code-before-database.tar').exists():
        with tarfile.open(BACKUP/'production-code-before-database.tar') as package:
            for item in package.getmembers():
                target=ROOT/item.name
                if not item.isfile() or not target.resolve().is_relative_to(ROOT):
                    raise ValueError('Invalid rollback code path.')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(package.extractfile(item).read())
    shutil.copy2(BACKUP/'trader-compose.before-database.yaml',ROOT/'compose.yaml')
    if ORIGINAL.is_dir():
        if DATA.exists():
            if any(DATA.iterdir()):
                raise ValueError('Unexpected files in the new data directory; preserving both directories for review.')
            DATA.rmdir()
        ORIGINAL.rename(DATA)
    command('docker','tag','trader-trader:before-database-20261016','trader-trader:latest')
    command('docker','compose','up','-d','--no-build','--force-recreate','trader',cwd=ROOT)
    command('systemctl','start','market-data-refresh.timer','investor-archive.timer')


def main():
    if os.geteuid()!=0 or not Path('/mnt/trader_data').is_mount():
        raise ValueError('Run as root with the database volume mounted.')
    if subprocess.check_output(['docker','inspect','trader-trader-1','--format','{{.State.Running}}'],text=True).strip()!='false':
        raise ValueError('Stop the idle production application before activation.')
    database_probe()
    manifest=json.loads((STAGE/'database-release.json').read_text())
    for name,digest in manifest.items():
        path=(STAGE/name).resolve()
        if not path.is_relative_to(STAGE) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Release integrity check failed: '+name)
    if ORIGINAL.exists() or not DATA.is_dir():
        raise ValueError('Unexpected source/rollback data directory; refusing to replace it.')
    with tarfile.open(BACKUP/'production-code-before-database.tar','x') as archive:
        for name in manifest:
            path=ROOT/name
            if path.is_file():archive.add(path,arcname=name)
    try:
        for name in manifest:
            if name=='compose.yaml':continue
            target=ROOT/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(STAGE/name,target)
        text=(ROOT/'compose.yaml').read_text()
        anchor='      TRADER_ENV: production'
        if text.count(anchor)!=1 or 'TRADER_STORAGE:' in text:
            raise ValueError('Unexpected production Compose environment.')
        text=text.replace(anchor,anchor+'\n      TRADER_STORAGE: postgres\n      TRADER_DB_NAMESPACE: production\n      TRADER_DB_DSN_FILE: /state/private/database.dsn\n      TRADER_KEY_FILE: /state/private/database-token.key')
        (ROOT/'compose.yaml').write_text(text)
        DATA.rename(ORIGINAL)
        DATA.mkdir();os.chown(DATA,10001,10001)
        command('docker','compose','config','--quiet',cwd=ROOT)
        command('docker','tag','trader-trader:database-ready','trader-trader:latest')
        command('docker','compose','up','-d','--no-build','--force-recreate','trader',cwd=ROOT)
        for _ in range(40):
            try:
                with urlopen('http://127.0.0.1:8765/',timeout=2) as response:
                    if response.status==200:break
            except HTTPError as error:
                if error.code==401:break
            except (URLError,TimeoutError):pass
            time.sleep(.5)
        else:raise ValueError('Production application did not become ready.')
        probe="""from dashboard.api.main import bootstrap
import json
v=bootstrap()
assert v['storage']=={'backend':'postgres','namespace':'production'}
assert len(v['runs'])==1 and len(v['screens'])==4
assert not v['paper_scenarios'] and not any(v['paper_portfolios'].values())
print(json.dumps({'storage':v['storage'],'backtests':len(v['runs']),'strategies':[s['name'] for s in v['screens']],'paper_portfolios':0}))
"""
        command('docker','exec','-i','trader-trader-1','python','-',input=probe,text=True)
        if any(DATA.rglob('*.json')):
            raise ValueError('Unexpected filesystem business-data writes after database cutover.')
        command('systemctl','disable','market-data-refresh.timer','investor-archive.timer')
        print('PRODUCTION_DATABASE_CUTOVER_VERIFIED',flush=True)
    except BaseException:
        restore_original()
        raise


if __name__=='__main__':main()
