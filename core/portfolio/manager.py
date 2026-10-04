"""One durable portfolio per registered strategy; never pool strategy capital."""
from datetime import timedelta
from core.research import store
from core.strategies.registry import get_strategy


def key(strategy_id):
    if not get_strategy(strategy_id):
        raise ValueError('Unknown strategy.')
    return 'portfolios/' + strategy_id


def get(strategy_id):
    return store.read(key(strategy_id))


def schedule_key(strategy_id):
    key(strategy_id)  # Registry validation also prevents path traversal.
    # Preserve the existing Swing checkpoint and portfolio paths.
    return 'paper_schedule' if strategy_id == 'swing_patterns' else 'paper_schedules/' + strategy_id


def ensure_idle():
    if any(j['status'] in ('queued', 'running') for j in store.read('jobs', [])):
        raise ValueError('Wait for the active job before changing the paper portfolio.')


def save(strategy_id, config, settings, *, create=False, clock):
    portfolio_key = key(strategy_id)
    with store.LOCK:
        ensure_idle()
        existing = get(strategy_id)
        if create:
            if existing:
                raise ValueError(f'{get_strategy(strategy_id).name} already has a portfolio. Edit its configuration instead.')
            universe = store.read('universes/' + settings.universe)
            if not universe or not universe.get('instruments'):
                raise ValueError('Refresh the universe and load daily history first.')
            if any(not store.read('bars/' + i['isin'], {}).get('bars') for i in universe['instruments']):
                raise ValueError('Fetch daily history for every universe symbol first.')
            existing = {'id': strategy_id, 'strategy_name': strategy_id, 'mode': 'paper',
                        'broker_account_id': None, 'sizer_type': 'percent_risk', 'status': 'active',
                        'created_at': store.now(), 'start_session': (clock.date() + timedelta(days=1)).isoformat(),
                        'universe': settings.universe, 'universe_snapshot': universe,
                        'history_start': str(settings.start), 'ledger': {}, 'fingerprints': {},
                        'cycles': [], 'config_history': []}
        elif not existing:
            raise ValueError('Create a paper portfolio first.')
        elif config.capital != existing['config']['capital']:
            raise ValueError('Allocated capital is fixed after creation to preserve portfolio accounting.')
        if existing['strategy_name'] != strategy_id or existing['id'] != strategy_id:
            raise ValueError('Portfolio strategy identity mismatch; trading halted.')
        existing['config'] = config.model_dump(mode='json')
        existing['config_history'].append({'at': store.now(), 'config': existing['config']})
        existing['updated_at'] = store.now()
        store.write(portfolio_key, existing)
        return existing


def set_status(strategy_id, status):
    if status not in ('active', 'paused'):
        raise ValueError('Choose active or paused.')
    with store.LOCK:
        ensure_idle()
        portfolio = get(strategy_id)
        if not portfolio:
            raise ValueError('Create a paper portfolio first.')
        portfolio['status'] = status
        portfolio['updated_at'] = store.now()
        store.write(key(strategy_id), portfolio)
        return portfolio
