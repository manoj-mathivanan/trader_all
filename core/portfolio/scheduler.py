"""Local weekday scheduler. Requires the single dashboard process to stay running."""
from threading import Event, Thread
from datetime import datetime
from functools import partial
from core.research import jobs, store
from core.portfolio import paper, manager, registry


def recover_interrupted():
    """Release only interrupted schedule claims, preserving normal failed attempts."""
    with store.LOCK:
        saved_jobs = store.read('jobs', [])
        targets = [(s, p['id']) for s in registry.PLUGINS for p in manager.list_portfolios(s)]
        targets += [(s, s) for s in registry.PLUGINS if not manager.get(s)]
        for strategy_id, portfolio_id in targets:
            checkpoint_key = manager.schedule_key(strategy_id, portfolio_id)
            claim = store.read(checkpoint_key, {})
            if not claim.get('attempt_day'):
                continue
            job = next((j for j in saved_jobs if j['id'] == claim.get('job_id')), None)
            if not job and not claim.get('job_id'):
                # Backward-compatible recovery of the original Swing claim format.
                job = next((j for j in saved_jobs
                            if j.get('payload', {}).get('portfolio_id') == portfolio_id
                            and j.get('created_at')
                            and datetime.fromisoformat(j['created_at']).astimezone(paper.IST).date().isoformat() == claim['attempt_day']), None)
            interrupted = job and job.get('status') == 'failed' and any(
                row['message'].startswith('Interrupted by server restart') for row in job.get('logs', []))
            if not job or interrupted:
                store.write(checkpoint_key, {**claim, 'attempt_day': None, 'recovered_at': store.now()})


def tick():
    with store.LOCK:
        clock = paper.local_now()
        if clock.weekday() >= 5:
            return
        targets = [(s, p) for s in sorted(registry.PLUGINS) for p in manager.list_portfolios(s)]
        for strategy_id, portfolio in targets:
            plugin = registry.PLUGINS[strategy_id]
            if plugin.trigger_mode != 'batch':
                continue
            if not portfolio or not portfolio['config'].get('auto_run'):
                continue
            config = portfolio['config']
            if (clock.hour, clock.minute) < (config['run_hour'], config['run_minute']):
                continue
            if config.get('execution_time') == 'midday' and (clock.hour, clock.minute) >= (15, 15):
                continue
            day = clock.date().isoformat()
            checkpoint_key = manager.schedule_key(strategy_id, portfolio['id'])
            if store.read(checkpoint_key, {}).get('attempt_day') == day:
                continue
            if any(j['status'] in ('queued', 'running') for j in store.read('jobs', [])):
                return
            runner = partial(plugin.run_cycle, portfolio_id=portfolio['id']) if strategy_id in ('swing_patterns','four_indicator_swing') else plugin.run_cycle
            job = jobs.submit('Paper daily cycle', runner,
                              {'portfolio_id': portfolio['id'], 'strategy_id': strategy_id, 'trigger': 'schedule'})
            store.write(checkpoint_key, {'attempt_day': day, 'at': store.now(), 'job_id': job['id']})


def start():
    stop = Event()

    def run():
        while not stop.wait(30):
            try:
                tick()
            except Exception:
                # A damaged store must not terminate the HTTP process or expose secrets.
                # Manual cycle validation and job logs surface actionable failures.
                continue

    thread = Thread(target=run, name='paper-schedule', daemon=True)
    thread.start()
    return stop, thread
