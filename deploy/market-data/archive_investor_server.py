"""Server-side archival into shared PostgreSQL; no local PC or SSH loop required."""
import json
import sys
from pathlib import Path
sys.path.insert(0,'/opt/trader/scripts')
from sync_investor_data import bundle,batches
from import_investor_data import run
source=Path('/srv/trader/data')
state=source/'investor/database_sync.json'
manifest=Path('/srv/trader/private/investor-archive-objects.json')
known=set(json.loads(manifest.read_text())) if manifest.exists() else set()
value=bundle(source,'production');batch=dict(version=1,environment='production',articles=[],documents=[])
identities=set()
for kind in ('articles','documents'):
    for row in value[kind]:
        identity=row.get('kind',kind)+':'+(row.get('id') or row['record']['id'])+':'+row['sha256']
        identities.add(identity)
        if identity not in known:batch[kind].append(row)
result={}
for part in batches(batch):
    result=run(json.dumps(part,sort_keys=True).encode())
    for kind in ('articles','documents'):
        known.update(row.get('kind',kind)+':'+(row.get('id') or row['record']['id'])+':'+row['sha256'] for row in part[kind])
    pending=manifest.with_suffix('.tmp');pending.write_text(json.dumps(sorted(known)));pending.replace(manifest)
if not result:result=json.loads(state.read_text()) if state.exists() else dict(status='complete',environment='production')
from datetime import datetime,timezone
result['synced_at']=datetime.now(timezone.utc).isoformat()
pending=state.with_suffix('.tmp');pending.write_text(json.dumps(result));pending.replace(state)
print(json.dumps(result))
