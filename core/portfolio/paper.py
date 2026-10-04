"""Persistent, forward-only local swing portfolio and tracked daily cycles."""
import hashlib
import json
from datetime import datetime, timedelta, timezone, time, date
from types import SimpleNamespace
from pydantic import Field, model_validator
from typing import Literal
from core.research import store, backtest, upstox
from core.research.config import TradingConfig, Settings
from core.portfolio import manager

IST = timezone(timedelta(hours=5, minutes=30))
KEY = 'portfolios/swing_patterns'


def local_now():
    return datetime.now(IST)


class PaperConfig(TradingConfig):
    name: str = Field('Swing paper portfolio', min_length=1, max_length=80, title='Portfolio name')
    capital: float = Field(..., ge=1000, le=1e10, title='Allocated capital (₹)')
    pattern: Literal['vcp', 'blue_sky', 'multiyear', 'ipo'] = Field('vcp', title='Banana screen')
    entry_mode: Literal['next_open'] = Field('next_open', title='Entry price')
    slippage_bps: float = Field(10, gt=0, le=500, title='Slippage per side (bps)')
    buy_cost_bps: float = Field(10, gt=0, le=500, title='All-in buy charges (bps)')
    sell_cost_bps: float = Field(10, gt=0, le=500, title='All-in sell charges (bps)')
    auto_run: bool = Field(False, title='Run automatically on weekdays')
    run_hour: int = Field(16, ge=16, le=23, title='Daily cycle hour (IST)')
    run_minute: int = Field(15, ge=0, le=59, title='Daily cycle minute')
    acknowledge_limitations: bool = Field(False, title='I understand paper fills and costs are estimates; the edge remains unvalidated')

    @model_validator(mode='after')
    def acknowledge(self):
        if not self.acknowledge_limitations:
            raise ValueError('Acknowledge the paper-trading and data limitations first.')
        return self


def save(config, settings, *, create=False):
    return manager.save('swing_patterns', config, settings, create=create, clock=local_now())


def set_status(status):
    return manager.set_status('swing_patterns', status)


def digest(bars, through):
    rows = [{k: b[k] for k in ('date', 'open', 'high', 'low', 'close', 'volume')}
            for b in bars if b['date'] <= through]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def cycle(log, job_id, *, ingest=True):
    portfolio = store.read(KEY)
    if not portfolio:
        raise ValueError('Create a paper portfolio first.')
    cfg = PaperConfig(**portfolio['config'])
    clock = local_now()
    through = clock.date() if clock.time() >= time(16) else clock.date() - timedelta(days=1)
    instruments = portfolio['universe_snapshot']['instruments']
    if ingest:
        # Freeze membership per portfolio; research universe refreshes cannot remove positions.
        settings = Settings(universe=portfolio['universe'], start=date.fromisoformat(portfolio['history_start']), end=through)
        upstox.ingest(settings, log, universe=portfolio['universe_snapshot'])
    datasets = {}
    ledger = portfolio['ledger']
    last = ledger.get('last_session', '')
    for item in instruments:
        record = store.read('bars/' + item['isin'], {})
        bars = record.get('bars', [])
        if not bars or record.get('requested_end', '') < through.isoformat():
            raise ValueError(f"Incomplete daily coverage for {item['symbol']}. Fetch data and retry; portfolio unchanged.")
        # Reconcile historical inputs before resuming; revisions require investigation.
        if last and digest(bars, last) != portfolio['fingerprints'].get(item['symbol']):
            raise ValueError(f"Processed candles changed for {item['symbol']}. Paper cycle halted; investigate before resuming.")
        datasets[item['symbol']] = [b for b in bars if b['date'] <= through.isoformat()]
    # Process the common observed boundary; do not fabricate holidays or force a stale quote.
    end = min(bars[-1]['date'] for bars in datasets.values() if bars)
    start = max(portfolio['start_session'], (date.fromisoformat(last) + timedelta(days=1)).isoformat() if last else portfolio['start_session'])
    if end < start:
        log(f'No new completed sessions. Portfolio begins {portfolio["start_session"]}; last processed {last or "none"}.')
        return {'portfolio_id': portfolio['id'], 'sessions': 0}
    for symbol, bars in datasets.items():
        if sum(b['date'] < start for b in bars) < backtest.required_warmup(cfg):
            raise ValueError(f'Insufficient indicator warmup for {symbol}. Fetch more history before the paper cycle.')
    simulation_cfg = SimpleNamespace(**cfg.model_dump(), start=start, end=end)
    log(f'Processing {start} through {end}; {portfolio["status"]} paper portfolio, next-open fills with costs.')
    result = backtest.simulate(datasets, simulation_cfg, state=ledger, liquidate=False,
                               allow_entries=portfolio['status'] == 'active')
    new_ledger = result['state']
    new_orders = new_ledger['orders'][len(ledger.get('orders', [])):]
    for order in new_orders:
        order.update(portfolio_id=portfolio['id'], mode='paper', job_id=job_id)
    portfolio.update(ledger=new_ledger, metrics=result['metrics'], updated_at=store.now())
    portfolio['fingerprints'] = {symbol: digest(bars, new_ledger['last_session']) for symbol, bars in datasets.items()}
    sessions = len(new_ledger['curve']) - len(ledger.get('curve', []))
    portfolio['cycles'].append({'job_id': job_id, 'at': store.now(), 'start': start, 'end': end,
                                'sessions': sessions, 'config': cfg.model_dump(mode='json'),
                                'order_count': len(new_orders), 'status': portfolio['status']})
    # Commit cash, positions, orders, trades and checkpoint together; retries are idempotent.
    store.write(KEY, portfolio)
    log(f'Committed {sessions} sessions, {len(new_orders)} simulated fills, {len(new_ledger["positions"])} open positions.')
    return {'portfolio_id': portfolio['id'], 'sessions': sessions, 'orders': len(new_orders)}
