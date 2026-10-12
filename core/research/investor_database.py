"""Explicit shared history access; never hydrate another environment's trading state."""
import json
import os
from pathlib import Path
import subprocess
import importlib.util
from core.research import store

def helper(name):
    spec=importlib.util.spec_from_file_location(name,store.ROOT/'deploy/market-data'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def connection():
    target=os.environ.get('TRADER_INVESTOR_DB_SSH_TARGET','root@143.244.142.226')
    key=Path(os.environ.get('TRADER_INVESTOR_DB_SSH_KEY',str(Path.home()/'.ssh/manoj_projects_ed25519')))
    if not key.is_file():raise ValueError('Shared database SSH connection is not configured on this environment.')
    return target,key

def read(query):
    if os.environ.get('TRADER_INVESTOR_DB_DSN'):
        try:return helper('export_investor_data').run(query,os.environ['TRADER_INVESTOR_DB_DSN'])
        except Exception:raise ValueError('Shared database read failed; working analysis is unchanged.') from None
    target,key=connection()
    command=['ssh','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10',target,
             '/opt/market-data/venv/bin/python /opt/market-data/export_investor_data.py']
    try:
        result=subprocess.run(command,input=json.dumps(query).encode(),capture_output=True,timeout=40)
        if result.returncode:raise ValueError('Shared database read failed; working analysis is unchanged.')
        return json.loads(result.stdout)
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError):
        raise ValueError('Shared database unavailable; working analysis is unchanged.') from None

def sync(log=lambda message:None):
    if os.environ.get('TRADER_INVESTOR_DB_DSN'):
        from scripts.sync_investor_data import bundle,batches
        import hashlib
        from datetime import datetime,timezone
        try:
            full=bundle(store.DATA,os.environ.get('TRADER_ENV','local'))
            importer=helper('import_investor_data');value={}
            for part in batches(full):
                raw=json.dumps(part,sort_keys=True).encode()
                value=importer.run(raw,os.environ['TRADER_INVESTOR_DB_DSN'])
                if value.get('status')!='complete' or value.get('sha256')!=hashlib.sha256(raw).hexdigest():raise ValueError('Invalid receipt')
            value.update(synced_at=datetime.now(timezone.utc).isoformat(),status='complete')
            store.write('investor/database_sync',value)
            return value
        except Exception:raise ValueError('Shared database sync failed; records retained for retry.') from None
    target,key=connection()
    from scripts.sync_investor_data import run
    log('Saving all local investor records to shared PostgreSQL.')
    try:return run(store.DATA,target,key)
    except Exception:
        raise ValueError('Shared database sync failed; local records retained for retry.') from None

def after_job():
    """Archive final job status as well as evidence; production has its archive timer."""
    if os.environ.get('TRADER_ENV','local')=='production' and not os.environ.get('TRADER_INVESTOR_DB_DSN'):return
    try:sync()
    except ValueError as exc:
        store.write('investor/database_sync',dict(status='retry_pending',reason=str(exc)))
        raise
