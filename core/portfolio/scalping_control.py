"""Dashboard controls for the independent scalping process; no process-kill commands."""
import os
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

from core.portfolio.locking import mutex
from core.research import store

CONTROL = 'scalping_stream/control'
STATE = 'scalping_stream/runner'


def running():
    try:
        with mutex('scalping_runner', timeout=0):
            return False
    except ValueError:
        return True


def status():
    saved = store.read(STATE, {})
    control = store.read(CONTROL, {})
    alive = running()
    if not alive:
        if saved.get('status') not in ('stopped', 'failed'):
            saved = {**saved, 'status':'stopped', 'message':'Runner is not running. Positions and fills remain saved.'}
        if control.get('run_requested') and control.get('requested_at'):
            if (datetime.now(timezone.utc)-datetime.fromisoformat(control['requested_at'])).total_seconds() < 10:
                saved = {**saved, 'status':'starting', 'message':'Starting the standalone quote runner.'}
    return {**saved, 'running':alive, 'stop_requested':not control.get('run_requested',False)}


def start():
    if not store.read('portfolios/scalping'):
        raise ValueError('Create a scalping paper portfolio with allocated capital first.')
    store.token()  # Validate presence without returning or logging the token.
    with mutex('scalping_control'):
        current = status()
        if current.get('running') or current.get('status')=='starting':
            return current
        store.write(CONTROL,dict(run_requested=True,request_id=uuid4().hex[:12],requested_at=store.now()))
        env = dict(os.environ, TRADER_DATA_DIR=str(store.DATA.resolve()), TRADER_PRIVATE_DIR=str(store.private_dir().resolve()))
        try:
            subprocess.Popen([sys.executable,'-m','core.portfolio.scalping_runner'],cwd=store.ROOT,env=env,
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except OSError:
            store.write(CONTROL,dict(run_requested=False))
            raise ValueError('Could not start the scalping process. The paper ledger is unchanged.') from None
    return status()


def stop():
    with mutex('scalping_control'):
        store.write(CONTROL,dict(run_requested=False,requested_at=store.now()))
    return status()


def autostart():
    portfolio = store.read('portfolios/scalping')
    if portfolio and portfolio['config'].get('auto_run'):
        try:
            start()
        except ValueError:
            store.write(STATE,dict(status='failed',message='Automatic runner startup failed. Check token and portfolio settings.',heartbeat_at=store.now()))
