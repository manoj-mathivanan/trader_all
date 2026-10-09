"""Independently check refresh timestamps, fundamental provenance and receipts."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from import_market_data import connect

with connect(Path('/srv/market-data/private/admin_password')) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    states = dict(conn.execute('SELECT status,count(*) FROM market.imports GROUP BY status'))
    assert set(states) == {'complete'}, states
    refreshes = []
    for environment, job, started, completed, synced, result, verification in conn.execute(
            'SELECT r.environment,r.job_id,r.started_at,r.completed_at,r.synced_at,r.result,i.verification '
            'FROM market.refreshes r JOIN market.imports i ON i.id=r.import_id ORDER BY synced_at'):
        assert started == datetime.fromisoformat(result['started_at'])
        assert completed == datetime.fromisoformat(result['completed_at'])
        assert verification['refresh_job_id'] == job
        assert verification['unmatched_candles'] == 0
        refreshes.append(dict(environment=environment, job_id=job, started_at=started.isoformat(),
                              completed_at=completed.isoformat(), synced_at=synced.isoformat(),
                              source_candles=verification['source_candles']))
    validated = 0
    with conn.cursor(name='fundamental_provenance') as cursor:
        cursor.itersize = 1
        cursor.execute('SELECT f.record,f.last_checked_at,f.last_pulled_at,f.sha256,b.gzip_data '
                       'FROM market.fundamentals f JOIN market.blobs b ON b.sha256=f.sha256')
        for record, checked, pulled, sha, compressed in cursor:
            raw = gzip.decompress(compressed)
            assert hashlib.sha256(raw).hexdigest() == sha
            assert json.loads(raw) == record
            assert datetime.fromisoformat(record['last_checked_at']) == checked
            assert (datetime.fromisoformat(record['last_pulled_at']) if record.get('last_pulled_at') else None) == pulled
            validated += 1
    result = dict(verified_at=datetime.now(timezone.utc).isoformat(), import_states=states,
                  refreshes=refreshes, fundamentals_verified=validated,
                  refresh_timestamps_match_source=True, fundamentals_match_source=True)
    Path('/srv/market-data/sync/verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
