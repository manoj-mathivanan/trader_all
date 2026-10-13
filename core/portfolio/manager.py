"""One durable portfolio per registered strategy; never pool strategy capital."""
from datetime import timedelta
import re
from core.research import store
from core.strategies.registry import get_strategy


def key(strategy_id, portfolio_id=None):
    if not get_strategy(strategy_id):
        raise ValueError('Unknown strategy.')
    if portfolio_id is not None and portfolio_id != strategy_id:
        if strategy_id != 'swing_patterns' or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', portfolio_id):
            raise ValueError('Invalid swing scenario identity.')
        return 'portfolio_scenarios/' + strategy_id + '/' + portfolio_id
    return 'portfolios/' + strategy_id


def get(strategy_id, portfolio_id=None):
    return store.read(key(strategy_id, portfolio_id))


def list_portfolios(strategy_id):
    result = [get(strategy_id)] if get(strategy_id) else []
    if strategy_id == 'swing_patterns':
        directory = store.DATA / 'portfolio_scenarios' / strategy_id
        result.extend(get(strategy_id, path.stem) for path in sorted(directory.glob('*.json')))
    return [p for p in result if p]


def schedule_key(strategy_id, portfolio_id=None):
    key(strategy_id, portfolio_id)  # Registry validation also prevents path traversal.
    if portfolio_id and portfolio_id != strategy_id:
        return 'paper_scenario_schedules/' + portfolio_id
    # Preserve the existing Swing checkpoint and portfolio paths.
    return 'paper_schedule' if strategy_id == 'swing_patterns' else 'paper_schedules/' + strategy_id


def ensure_idle():
    if any(j['status'] in ('queued', 'running') for j in store.read('jobs', [])):
        raise ValueError('Wait for the active job before changing the paper portfolio.')


def save(strategy_id, config, settings, *, create=False, clock, portfolio_id=None, universe_snapshot=None):
    portfolio_key = key(strategy_id, portfolio_id)
    identity = portfolio_id or strategy_id
    with store.LOCK:
        ensure_idle()
        existing = get(strategy_id, portfolio_id)
        if create:
            if existing:
                raise ValueError(f'{get_strategy(strategy_id).name} already has a portfolio. Edit its configuration instead.')
            universe = universe_snapshot or store.read('universes/' + settings.universe)
            if not universe or not universe.get('instruments'):
                raise ValueError('Refresh the universe and load daily history first.')
            if any(not store.read('bars/' + i['isin'], {}).get('bars') for i in universe['instruments']):
                raise ValueError('Fetch daily history for every universe symbol first.')
            existing = {'id': identity, 'strategy_name': strategy_id, 'mode': 'paper',
                        'broker_account_id': None, 'sizer_type': 'percent_risk', 'status': 'active',
                        'created_at': store.now(), 'start_session': (clock.date() + timedelta(days=1)).isoformat(),
                        'universe': settings.universe, 'universe_snapshot': universe,
                        'history_start': str(settings.start), 'ledger': {}, 'fingerprints': {},
                        'cycles': [], 'config_history': []}
        elif not existing:
            raise ValueError('Create a paper portfolio first.')
        elif config.capital != existing['config']['capital']:
            raise ValueError('Allocated capital is fixed after creation to preserve portfolio accounting.')
        if existing['strategy_name'] != strategy_id or existing['id'] != identity:
            raise ValueError('Portfolio strategy identity mismatch; trading halted.')
        if not create and existing['config'].get('execution_time', 'next_open') != getattr(config, 'execution_time', 'next_open') and existing.get('ledger'):
            raise ValueError('Create a separate scenario to change execution timing after trading starts.')
        if not create and (existing['config'].get('simulation_model','legacy') == 'banana_proxy_v1'
                           or getattr(config,'simulation_model','legacy') == 'banana_proxy_v1'):
            editable = {'name','auto_run','run_hour','run_minute','acknowledge_limitations'}
            previous = type(config)(**existing['config']).model_dump(mode='json')
            current = config.model_dump(mode='json')
            if any(previous[k] != current[k] for k in current if k not in editable):
                raise ValueError('Create a separate reference scenario to change its engine, filters or execution rules.')
        existing['config'] = config.model_dump(mode='json')
        existing['config_history'].append({'at': store.now(), 'config': existing['config']})
        existing['updated_at'] = store.now()
        store.write(portfolio_key, existing)
        return existing


def set_status(strategy_id, status, portfolio_id=None):
    if status not in ('active', 'paused'):
        raise ValueError('Choose active or paused.')
    with store.LOCK:
        ensure_idle()
        portfolio = get(strategy_id, portfolio_id)
        if not portfolio:
            raise ValueError('Create a paper portfolio first.')
        portfolio['status'] = status
        portfolio['updated_at'] = store.now()
        store.write(key(strategy_id, portfolio_id), portfolio)
        return portfolio
