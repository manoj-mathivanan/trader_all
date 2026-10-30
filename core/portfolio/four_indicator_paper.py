"""Daily reconstructed paper ledgers for the equity indicator variants."""
from datetime import date, timedelta
from types import SimpleNamespace
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from core.research import store, market_data, market_history, corporate_actions, current_session
from core.research import four_indicator_swing as fs
from core.research.config import Settings
from core.portfolio import manager, paper

class PaperConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field('Four-indicator paper', min_length=1, max_length=80)
    rule_set: Literal['rsi','bollinger'] = Field('bollinger', title='Entry variant')
    start_session: date = Field(..., title='Replay begins')
    capital: float = Field(1000000, ge=1000, le=1e10)
    max_positions: int = Field(10, ge=1, le=100)
    rsi_threshold: float = Field(65, ge=0, le=100, title='RSI (14) must be above')
    bollinger_multiplier: float = Field(2.5, gt=0, le=10, title='Bollinger (20) standard deviations')
    slippage_bps: float = Field(10, ge=0, le=500)
    buy_cost_bps: float = Field(10, ge=0, le=500)
    sell_cost_bps: float = Field(10, ge=0, le=500)
    auto_run: bool = True
    run_hour: int = Field(16, ge=16, le=23)
    run_minute: int = Field(15, ge=0, le=59)

    @model_validator(mode='before')
    @classmethod
    def variant_defaults(cls, value):
        if isinstance(value, dict) and value.get('rule_set', 'bollinger') == 'rsi':
            return {**fs.LEGACY_PARAMETERS, 'max_positions':5, **value}
        return value

    @model_validator(mode='after')
    def completed_start(self):
        if self.start_session > paper.local_now().date():
            raise ValueError('Replay start must be today or earlier.')
        return self

def save(config, settings, *, create=False, portfolio_id=None):
    key = manager.key(fs.STRATEGY, portfolio_id)
    with store.LOCK:
        manager.ensure_idle()
        existing = store.read(key)
        if create and existing:
            raise ValueError('This paper portfolio already exists.')
        if not create:
            if not existing:
                raise ValueError('Create the paper portfolio first.')
            editable = {'name','auto_run','run_hour','run_minute'}
            previous = {**existing['config'], **fs.stored_parameters(existing['config'])}
            if any(previous.get(k) != v for k,v in config.model_dump(mode='json').items() if k not in editable):
                raise ValueError('Rules, start date, capital and costs freeze per paper portfolio. Create a separate scenario to change them.')
            existing['config'] = config.model_dump(mode='json')
        else:
            clock = paper.local_now()
            existing = dict(id=portfolio_id or fs.STRATEGY,strategy_name=fs.STRATEGY,mode='paper',
                            status='active',created_at=store.now(),start_session=str(config.start_session),
                            universe=settings.universe,config=config.model_dump(mode='json'),
                            ledger={},cycles=[],metrics={'final_equity':config.capital},
                            replay_through=str(clock.date()-timedelta(days=1)),
                            reconstruction_notice='Historical sessions through creation are replayed simulated fills; later sessions use completed daily bars. No broker orders.')
        existing['updated_at'] = store.now()
        store.write(key,existing)
        return existing


def adopt_all_four_defaults(portfolio_id):
    """Explicit owner-requested entry-rule change; retain all processed accounting."""
    key = manager.key(fs.STRATEGY, portfolio_id)
    with store.LOCK:
        manager.ensure_idle()
        portfolio = store.read(key)
        if not portfolio or portfolio['config']['rule_set'] != 'bollinger':
            raise ValueError('Select an existing all-four paper portfolio.')
        previous = portfolio['config']
        config = PaperConfig(**{**previous, **fs.ALL_FOUR_DEFAULTS}).model_dump(mode='json')
        if config == previous:
            return portfolio
        at = store.now()
        portfolio.setdefault('config_history', []).append(dict(
            at=at, reason='Owner requested balanced all-four defaults',
            effective_after_session=portfolio.get('ledger', {}).get('last_session'),
            previous_config=previous, config=config))
        portfolio.update(config=config, updated_at=at)
        store.write(key, portfolio)
        return portfolio

def cycle(log, job_id, *, ingest=True, portfolio_id=None):
    key = manager.key(fs.STRATEGY,portfolio_id)
    portfolio = store.read(key)
    if not portfolio:
        raise ValueError('Create a four-indicator paper portfolio first.')
    cfg = PaperConfig(**{**portfolio['config'], **fs.stored_parameters(portfolio['config'])})
    previous = store.read(portfolio['input_reference']) if portfolio.get('input_reference') else None
    if portfolio.get('input_reference') and (not previous or fs.digest(previous) != portfolio['cycles'][-1]['input_sha256']):
        raise ValueError('Saved paper inputs are missing or changed; ledger unchanged.')
    universe = previous['universe'] if previous else store.read('universes/'+portfolio['universe'])
    with httpx.Client(timeout=40) as client:
        if ingest:
            token = store.token()
            end = market_data.last_traded_day(client,token)
            market_data.save_daily(client,market_data.BENCHMARK,token,cfg.start_session-timedelta(days=400),end)
            if previous:
                symbols = set(previous['datasets'])
            else:
                cached = fs.read_many(['bars/'+i['isin'] for i in universe['instruments']])
                symbols = {i['symbol'] for i in universe['instruments'] if (cached.get('bars/'+i['isin']) or {}).get('bars')}
            for n,item in enumerate(universe['instruments'],1):
                if item['symbol'] not in symbols:
                    continue
                market_data.save_daily(client,item,token,cfg.start_session-timedelta(days=400),end)
                if n%50 == 0:
                    log(f'Refreshed {n}/{len(universe["instruments"])} daily instruments.')
        else:
            cutoff = paper.local_now().date()
            if current_session.completed_day(paper.local_now()) != cutoff:
                cutoff -= timedelta(days=1)
            dates = [b['date'] for b in store.read('bars/NIFTY50',{}).get('bars',[])
                     if b['date'] <= str(cutoff)]
            if not dates:
                raise ValueError('No completed benchmark sessions are cached.')
            end = date.fromisoformat(max(dates))
    last = portfolio['ledger'].get('last_session')
    if last and str(end) <= last:
        log('No new completed sessions; ledger unchanged.')
        return dict(portfolio_id=portfolio['id'],sessions=0)
    if end < cfg.start_session:
        log('No completed session on or after the replay start; ledger unchanged.')
        return dict(portfolio_id=portfolio['id'],sessions=0)
    # The observed completed session can be today; backtest form date restrictions
    # do not apply to the paper engine's internal input preparation.
    research = SimpleNamespace(start=min(cfg.start_session,end-timedelta(days=1)),end=end,
                               coverage_mode='available_history',rule_set=cfg.rule_set,comparison_run_id=None)
    if not previous:
        frozen = fs.prepare(Settings(universe=portfolio['universe']),research,log)
    else:
        from copy import deepcopy
        frozen = deepcopy(previous)
        evidence = market_history.evidence(snapshot=True)
        items = {i['symbol']:i for i in universe['instruments']}
        records = fs.read_many(['bars/'+items[s]['isin'] for s in previous['datasets']])
        sessions = {b['date'] for b in store.read('bars/NIFTY50',{})['bars'] if last < b['date'] <= str(end)}
        for symbol,old in previous['datasets'].items():
            record = records.get('bars/'+items[symbol]['isin']) or {}
            rows,_ = market_history.prepare(items[symbol],record,reference=evidence,fingerprint=False)
            if any(str(cfg.start_session) < a['ex_date'] <= str(end) for a in corporate_actions.actions(rows)):
                raise ValueError(f'{symbol}: corporate action requires reconciliation; ledger unchanged.')
            rows = corporate_actions.adjusted_bars(rows,str(cfg.start_session))
            rows = [{k:v for k,v in b.items() if k != 'corporate_actions'} for b in rows if old[0]['date'] <= b['date'] <= str(end)]
            if fs.digest([b for b in rows if b['date'] <= old[-1]['date']]) != fs.digest(old):
                raise ValueError(f'{symbol}: previously processed inputs changed; ledger unchanged.')
            missing = sessions-{b['date'] for b in rows}
            if missing:
                # Only suspend an unheld stock with no prices in the entire new
                # interval. A partially covered interval could contain an entry
                # before the gap, so it still requires reconciliation.
                if symbol in portfolio['ledger'].get('positions', {}) or missing != sessions:
                    raise ValueError(f'{symbol}: missing completed-session prices; ledger unchanged.')
                reason = f'No completed-session prices for {min(missing)} through {max(missing)}; unheld stock suspended from new entries.'
                frozen['datasets'].pop(symbol)
                frozen['excluded'] = sorted(set(frozen.get('excluded', [])) | {symbol})
                frozen.setdefault('exclusion_reasons', {})[symbol] = reason
                frozen.setdefault('suspended_inputs', {})[symbol] = dict(
                    suspended_through=str(end), missing_sessions=sorted(missing),
                    last_observed=old[-1]['date'], reason=reason)
                for field in ('coverage', 'history_fragments'):
                    frozen.get(field, {}).pop(symbol, None)
                log(f'{symbol}: {reason}')
                continue
            from core.research import data_quality
            if data_quality.audit({symbol:rows})['findings']:
                raise ValueError(f'{symbol}: unresolved price discontinuity; ledger unchanged.')
            frozen['datasets'][symbol] = rows
        frozen['captured_at'] = store.now()
        if not frozen['datasets']:
            raise ValueError('No eligible stock prices remain for this cycle; ledger unchanged.')
    start = date.fromisoformat(last)+timedelta(days=1) if last else cfg.start_session
    simcfg = SimpleNamespace(**{**cfg.model_dump(),'start':start,'end':end})
    rule = next(r for r in fs.RULES if r[0] == cfg.rule_set)
    result = fs.simulate(frozen['datasets'],fs.features(frozen['datasets'],log,**fs.stored_parameters(portfolio['config'])),simcfg,rule,
                         state=portfolio['ledger'],liquidate=False,entry_start=cfg.start_session,
                         entries_allowed=portfolio['status']=='active')
    ledger = result['ledger']
    for order in ledger['orders']:
        order['mode'] = 'historical_replay' if order['date'] <= portfolio['replay_through'] else 'daily_reconstruction'
        order.setdefault('job_id',job_id)
        order.setdefault('status','Simulated · '+order['mode'].replace('_',' '))
    reference = 'paper_inputs/'+portfolio['id']+'/'+job_id
    cycle_record = dict(job_id=job_id,at=store.now(),start=str(start),end=str(end),config=portfolio['config'],
                        input_reference=reference,input_sha256=fs.digest(frozen),status=portfolio['status'])
    with store.LOCK:
        if store.read(key) != portfolio:
            raise ValueError('Portfolio changed during cycle; retry without modifying the ledger.')
        if store.read(reference) is not None:
            raise ValueError('Paper input snapshot already exists; retry with a new cycle ID.')
        store.write(reference,frozen)
        portfolio.update(ledger=ledger,metrics=result['metrics'],input_reference=reference,
                         universe_snapshot=frozen['universe'],excluded=frozen['exclusion_reasons'],
                         updated_at=store.now())
        portfolio['cycles'].append(cycle_record)
        store.write(key,portfolio)
    count = sum(str(start)<=c['date']<=str(end) for c in ledger['curve'])
    log(f'{portfolio["config"]["name"]}: {count} sessions; {len(ledger["positions"])} open positions; equity ₹{result["metrics"]["final_equity"]:,.2f}.')
    return dict(portfolio_id=portfolio['id'],sessions=count,open_positions=len(ledger['positions']),metrics=result['metrics'])
