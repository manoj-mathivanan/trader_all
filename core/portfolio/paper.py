"""Persistent, forward-only local swing portfolio and tracked daily cycles."""
import hashlib
import json
from datetime import datetime, timedelta, timezone, time, date
from types import SimpleNamespace
from pydantic import Field, model_validator
from typing import Literal
from core.research import store, backtest, upstox, data_quality, market_history, provenance, candle_repairs, sector
from core.research.config import TradingConfig, Settings
from core.portfolio import manager

IST = timezone(timedelta(hours=5, minutes=30))
KEY = 'portfolios/swing_patterns'


def local_now():
    return datetime.now(IST)


class PaperIngestionRange(Settings):
    """A portfolio's fixed history grows beyond the research form's ten-year cap."""

    @model_validator(mode='after')
    def dates(self):
        if self.start >= self.end:
            raise ValueError('Paper history start must precede the completed-session cutoff.')
        return self


class PaperConfig(TradingConfig):
    sector_observe_only: bool = Field(True, title='Observe sector decisions without blocking entries')
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


def repair_context_start(portfolio, bars, cfg):
    """Conservative earliest input used by any saved cycle, including exit context."""
    cycles = portfolio.get('cycles', [])
    if not cycles or any(not c.get('config') or not c.get('start') for c in cycles):
        return None  # Legacy ledgers without context evidence require full reconciliation.
    configs = [cfg.model_dump(), *[c['config'] for c in cycles]]
    lookback = 0
    for values in configs:
        historic = SimpleNamespace(**{**cfg.model_dump(), **values})
        length = backtest.required_warmup(historic)
        if historic.pattern == 'blue_sky':
            length = max(length, historic.blue_sky_lookback_days)
        if historic.skip_weak_markets:
            length = max(length, 200)
        if historic.winner_exit == 'trail_30w':
            length = max(length, 150)
        lookback = max(lookback, length)
    first = min(portfolio['start_session'], *[c['start'] for c in cycles])
    index = next((i for i, b in enumerate(bars) if b['date'] >= first), 0)
    return bars[max(0, index - lookback - 1)]['date'] if bars else None


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
        settings = PaperIngestionRange(universe=portfolio['universe'], start=date.fromisoformat(portfolio['history_start']), end=through)
        upstox.ingest(settings, log, universe=portfolio['universe_snapshot'], extend_history=False)
        if cfg.sector_filter != 'off':
            try:
                sector.fetch(settings, log, job_id, universe=portfolio['universe_snapshot'],
                             start=date.fromisoformat(portfolio['history_start']), end=through)
            except ValueError as exc:
                log(f'Sector refresh unavailable: {exc}; missing/stale evidence blocks entries while exits continue.')
    datasets = {}
    reference = market_history.evidence(snapshot=True)
    reconciliation = store.read('metadata/paper_repair_reconciliations', {}).get(portfolio['id'], {})
    repair_reconciled = candle_repairs.reconciliation_matches(reconciliation, portfolio, reference)
    histories = {}
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
        derived, history = market_history.prepare(item, record, reference=reference)
        if last and not repair_reconciled:
            prior = (portfolio.get('cycles') or [{}])[-1].get('history_evidence', {}).get(item['symbol'], {})
            candle_repairs.reconcile(prior, history, last,
                                     relevant_from=repair_context_start(portfolio, bars, cfg))
        if not derived:
            if item['symbol'] in ledger.get('positions', {}):
                raise ValueError(f"Held instrument {item['symbol']} is quarantined. Paper cycle halted; ledger unchanged.")
            log(f"Excluded {item['symbol']}: quarantined or no valid listed history.")
            continue
        datasets[item['symbol']] = [b for b in derived if b['date'] <= through.isoformat()]
        histories[item['symbol']] = history
    # Process the common observed boundary; do not fabricate holidays or force a stale quote.
    if not datasets:
        raise ValueError('No eligible paper inputs after history checks; ledger unchanged.')
    end = min(bars[-1]['date'] for bars in datasets.values() if bars)
    start = max(portfolio['start_session'], (date.fromisoformat(last) + timedelta(days=1)).isoformat() if last else portfolio['start_session'])
    if end < start:
        log(f'No new completed sessions. Portfolio begins {portfolio["start_session"]}; last processed {last or "none"}.')
        return {'portfolio_id': portfolio['id'], 'sessions': 0}
    for symbol, bars in datasets.items():
        if sum(b['date'] < start for b in bars) < backtest.required_warmup(cfg):
            if symbol in ledger.get('positions', {}):
                raise ValueError(f'Insufficient indicator warmup for held {symbol}. Paper cycle halted; ledger unchanged.')
            log(f'{symbol}: entries wait for sufficient listed-history warmup; no candles invented.')
    simulation_cfg = SimpleNamespace(**cfg.model_dump(), start=start, end=end)
    sector_snapshot = None
    sector_gate = None
    if cfg.sector_filter != 'off':
        sector_snapshot = sector.capture(portfolio['universe_snapshot'])
        if portfolio.get('sector_mapping') is not None:
            sector_snapshot['mappings'] = portfolio['sector_mapping']
            sector_snapshot['mapping_captured_at'] = portfolio['sector_mapping_captured_at']
            for identifier in {v['index'] for v in sector_snapshot['mappings'].values() if v.get('index')}:
                sector_snapshot['prices'][identifier] = store.read('sector/prices/'+identifier, {})
            sector_snapshot['sha256'] = market_history.digest({k:v for k,v in sector_snapshot.items() if k != 'sha256'})
        # Revisions to processed sector inputs require investigation, like stock revisions.
        prior_cycle = next((c for c in reversed(portfolio.get('cycles', [])) if c.get('sector_reference')), None)
        if prior_cycle:
            prior = store.read('paper_sector/'+prior_cycle['job_id'], {})
            sector.verify(prior, prior_cycle['sector_reference']['sha256'])
            for identifier, record in prior['prices'].items():
                processed = [b for b in record.get('bars', []) if b['date'] <= prior_cycle['end']]
                current = [b for b in sector_snapshot['prices'].get(identifier, {}).get('bars', []) if b['date'] <= prior_cycle['end']]
                if processed and processed != current:
                    raise ValueError('Processed sector index history changed; investigate before resuming paper.')
        sector_gate = sector.Gate(sector_snapshot, cfg.sector_filter)
    if cfg.pattern == 'ipo':
        verified = sum(bars[0].get('listing_metadata', {}).get('ipo_verified') is True for bars in datasets.values())
        log(f'IPO listing evidence: {verified}/{len(datasets)} symbols; missing evidence blocks new IPO entries.')
    quality = data_quality.audit(datasets, start=start, end=end, after=last)
    data_quality.require_no_anomalies(quality)
    log(f'Processing {start} through {end}; {portfolio["status"]} paper portfolio, next-open fills with costs.')
    from core.research import fundamentals
    symbol_isins={item['symbol']:item['isin'] for item in instruments}
    fundamental_screen=fundamentals.buy_screen('swing_patterns')
    fundamental_checks=[]
    fundamental_cache={}
    def financial_check(symbol,day):
        if (symbol,day) not in fundamental_cache:
            fundamental_cache[symbol,day]=fundamentals.buy_check(symbol_isins[symbol],'swing_patterns',
                at=datetime.fromisoformat(day+'T09:15:00+05:30'),screen=fundamental_screen)
        return fundamental_cache[symbol,day]
    def entry_check(symbol,day):
        check=financial_check(symbol,day)
        fundamental_checks.append(dict(symbol=symbol,day=day,buy_allowed=check['buy_allowed'],score=check['score'],
                                      coverage_pct=check['coverage_pct'],reasons=check['block_reasons'],
                                      snapshot_id=(check['snapshot'] or {}).get('id'),screen=check['screen']))
        return check['buy_allowed']
    def ranking_score(symbol,day):
        check=financial_check(symbol,day)
        return {k:check[k] for k in ('score','coverage_pct','flags','period_end') if k in check}
    result = backtest.simulate(datasets, simulation_cfg, state=ledger, liquidate=False,
                               allow_entries=portfolio['status'] == 'active', entry_warmup=backtest.required_warmup(cfg),
                               entry_check=entry_check,
                               sector_gate=sector_gate,
                               sector_observe_only=cfg.sector_observe_only,
                               fundamental_scores=ranking_score if cfg.candidate_rank == 'fundamental_score' else None)
    new_ledger = result['state']
    new_orders = new_ledger['orders'][len(ledger.get('orders', [])):]
    for order in new_orders:
        order.update(portfolio_id=portfolio['id'], mode='paper', job_id=job_id)
    portfolio.update(ledger=new_ledger, metrics=result['metrics'], updated_at=store.now(), data_quality=quality)
    # Fingerprints remain on source history, not the derived listing-filtered view.
    portfolio['fingerprints'] = {item['symbol']: digest(store.read('bars/' + item['isin'])['bars'], new_ledger['last_session'])
                                 for item in instruments}
    sessions = len(new_ledger['curve']) - len(ledger.get('curve', []))
    portfolio['cycles'].append({'job_id': job_id, 'at': store.now(), 'start': start, 'end': end,
                                'sessions': sessions, 'config': cfg.model_dump(mode='json'),
                                'order_count': len(new_orders), 'status': portfolio['status']})
    portfolio['cycles'][-1].update(history_evidence=histories, provenance=provenance.capture())
    portfolio['cycles'][-1]['fundamental_checks']=fundamental_checks
    portfolio['cycles'][-1]['sector_checks'] = result['sector_checks']
    if sector_snapshot is not None:
        # Do not freeze an empty mapping after a failed first refresh.
        if sector_snapshot['mappings'] and portfolio.get('sector_mapping') is None:
            portfolio['sector_mapping'] = sector_snapshot['mappings']
            portfolio['sector_mapping_captured_at'] = sector_snapshot['mapping_captured_at']
        store.write('paper_sector/'+job_id, sector_snapshot)
        portfolio['cycles'][-1]['sector_reference'] = dict(sha256=sector_snapshot['sha256'], notice=sector.NOTICE)
    # Commit cash, positions, orders, trades and checkpoint together; retries are idempotent.
    store.write(KEY, portfolio)
    log(f'Committed {sessions} sessions, {len(new_orders)} simulated fills, {len(new_ledger["positions"])} open positions.')
    return {'portfolio_id': portfolio['id'], 'sessions': sessions, 'orders': len(new_orders)}
