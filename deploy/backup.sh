#!/bin/bash
set -euo pipefail
exec 9>/run/trader-backup.lock
flock -n 9 || exit 0
cd /opt/trader
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/srv/trader/data/jobs.json')
if p.exists() and any(j['status'] in ('queued', 'running') for j in json.loads(p.read_text())):
    raise SystemExit('Backup deferred: a job is active. Run manually after completion.')
PY
docker compose stop trader
trap 'cd /opt/trader; docker compose start trader' EXIT
mkdir -p /srv/trader/backup-state /srv/trader/backups
python3 deploy/data_snapshot.py snapshot /srv/trader/data /srv/trader/backup-state
tar -czf /srv/trader/backups/data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz -C /srv/trader/backup-state .
find /srv/trader/backups -name 'data-*.tar.gz' -mtime +7 -delete
