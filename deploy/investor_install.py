"""Apply a checked investor overlay on the existing production checkout."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tarfile
from datetime import datetime,timezone
root=Path('/opt/trader');stage=Path('/srv/trader/deploy-stage');stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
backup=Path('/srv/trader/deploy-backups')/('investor-'+stamp);backup.mkdir(parents=True)
with tarfile.open(stage/'investor-code.tar.gz') as package:
    manifest=json.load(package.extractfile('investor-deploy-manifest.json'))
    for name,digest in manifest.items():
        if hashlib.sha256((root/name).read_text(encoding='utf-8').encode()).hexdigest()!=digest:raise ValueError('Production baseline changed: '+name)
    for member in package.getmembers():
        name=member.name
        if not member.isfile() or Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Invalid deployment member')
        target=root/name
        if target.exists():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(package.extractfile(member).read())
compose=root/'compose.yaml';shutil.copy2(compose,backup/'compose.yaml')
text=compose.read_text()
if '/srv/trader/private/investor-openai.env' not in text:
    if text.count('    environment:')!=1:raise ValueError('Unexpected compose environment')
    text=text.replace('    environment:','    env_file:\n      - /srv/trader/private/investor-openai.env\n    environment:')
    compose.write_text(text)
data=Path('/srv/trader/data')
with tarfile.open(stage/'investor-data.tar.gz') as package:
    for member in package.getmembers():
        if not member.isfile() or not member.name.startswith('investor/') or '..' in Path(member.name).parts:raise ValueError('Invalid investor artifact')
        target=data/member.name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.name not in ('settings.json','rules.json'):continue
        target.write_bytes(package.extractfile(member).read());os.chown(target,10001,10001)
for folder in (data/'investor').rglob('*'):
    if folder.is_dir():os.chown(folder,10001,10001)
os.chown(data/'investor',10001,10001)
for name in ('import_investor_data.py','investor_schema.sql','archive_investor_server.py'):
    shutil.copy2(root/'deploy/market-data'/name,Path('/opt/market-data')/name)
for name in ('investor-archive.service','investor-archive.timer'):
    shutil.copy2(root/'deploy/market-data'/name,Path('/etc/systemd/system')/name)
subprocess.run(['docker','tag','trader-trader','trader-trader:investor-before-'+stamp],check=True)
print('Investor overlay prepared; rollback snapshot '+str(backup),flush=True)
subprocess.run(['docker','compose','build','trader'],cwd=root,check=True)
probe='from core.research import store; import json; print(json.dumps([j["id"] for j in store.read("jobs",[]) if j["status"] in ("queued","running")]))'
result=subprocess.run(['docker','exec','-i','trader-trader-1','python','-'],input=probe,text=True,capture_output=True,check=True)
if json.loads(result.stdout):raise ValueError('Active production jobs; image built but restart deferred')
subprocess.run(['docker','compose','up','-d','--no-build','trader'],cwd=root,check=True)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','investor-archive.timer'],check=True)
print('Production investor service and archive timer started.',flush=True)
