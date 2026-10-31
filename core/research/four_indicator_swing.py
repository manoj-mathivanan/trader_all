"""Daily equity adaptation of the video's four indicators; normal saved backtests."""
from core.execution.upstox import equity_charges, size_order
from bisect import bisect_left, bisect_right
from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.research import store, market_history, corporate_actions, data_quality, intraday_data
from core.strategies.four_indicator import indicators, decision
from core.strategies.four_indicator_allocation import AllocationConfig, AllocationContext, allocation_notice

STRATEGY = 'four_indicator_swing'
LEGACY_PARAMETERS = dict(rsi_threshold=70, bollinger_multiplier=2)
ALL_FOUR_DEFAULTS = dict(max_positions=10, rsi_threshold=65, bollinger_multiplier=2.5)
RULES = (
    ('supertrend', 'Supertrend only', (0,), False),
    ('rsi', '+ RSI > 70', (0, 1), False),
    ('r1', '+ Close > R1', (0, 1, 2), False),
    ('bollinger', 'All four indicators', (0, 1, 2, 3), False),
    ('below_r1', 'Below-R1 counter-test', (0, 1, 3), True),
)


class SwingConfig(AllocationConfig):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    strategy_id: Literal['four_indicator_swing'] = STRATEGY
    name: str = Field('Four-indicator daily swing', min_length=1, max_length=80, title='Run name')
    start: date = Field(..., title='Test from')
    end: date = Field(..., title='Test through')
    coverage_mode: Literal['full_window', 'available_history'] = Field('full_window', title='Stock history coverage')
    rule_set: Literal['main', 'all', 'supertrend', 'rsi', 'r1', 'bollinger', 'below_r1'] = Field('bollinger', title='Rule variant (main runs four; all adds counter-test)')
    capital: float = Field(1000000, ge=1000, le=1e10, title='Starting capital (₹)')
    max_positions: int = Field(10, ge=1, le=100, title='Maximum simultaneous positions')
    rsi_threshold: float = Field(65, ge=0, le=100, title='RSI (14) must be above')
    bollinger_multiplier: float = Field(2.5, gt=0, le=10, title='Bollinger (20) standard deviations')
    slippage_bps: float = Field(10, ge=0, le=500, title='Slippage per side (bps)')
    buy_cost_bps: float = Field(10, ge=0, le=500, title='Legacy buy bps (ignored; Upstox Plus applies)')
    sell_cost_bps: float = Field(10, ge=0, le=500, title='Legacy sell bps (ignored; Upstox Plus applies)')
    comparison_run_id: str | None = Field(None, pattern=r'^[a-f0-9]{12}$', title='Frozen input reference')

    @model_validator(mode='before')
    @classmethod
    def entry_defaults(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        reference = value.get('comparison_run_id')
        if isinstance(reference, str) and re.fullmatch(r'[a-f0-9]{12}', reference):
            config = (store.read('runs/'+reference) or {}).get('config', {})
            for key, fallback in LEGACY_PARAMETERS.items():
                value.setdefault(key, config.get(key, fallback))
        elif value.get('rule_set', 'bollinger') != 'bollinger':
            value = {**LEGACY_PARAMETERS, 'max_positions':5, **value}
        return value

    @model_validator(mode='after')
    def dates(self):
        if self.start >= self.end or self.end >= datetime.now(intraday_data.IST).date():
            raise ValueError('Choose increasing completed-session dates before today in IST.')
        return self


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def stored_parameters(config):
    """Old saved runs and portfolios predate configurable entry thresholds."""
    return {key: config.get(key, fallback) for key, fallback in LEGACY_PARAMETERS.items()}


def read_many(names):
    if store.database_enabled():
        from core.research import postgres_store
        return postgres_store.read_many(names)
    return {name: store.read(name) for name in names}


def prepare(settings, cfg, log):
    if cfg.comparison_run_id:
        ref = store.read('runs/'+cfg.comparison_run_id)
        frozen = store.read('run_data/'+cfg.comparison_run_id)
        if not ref or ref.get('strategy_id') != STRATEGY or not frozen or digest(frozen) != ref['input_sha256']:
            raise ValueError('Four-indicator frozen inputs are unavailable or changed.')
        if str(cfg.start) != ref['config']['start'] or str(cfg.end) != ref['config']['end']:
            raise ValueError('Frozen reruns must keep the original date window.')
        if cfg.coverage_mode != ref['config'].get('coverage_mode','full_window'):
            raise ValueError('Frozen reruns must keep the original history coverage mode.')
        log('Using verified frozen daily stock inputs; no market downloads.')
        return frozen
    universe = store.read('universes/'+settings.universe)
    if not universe:
        raise ValueError('Refresh the stock universe and daily data first.')
    evidence = market_history.evidence(snapshot=True)
    calendar = store.read('bars/NIFTY50',{}).get('bars',[])
    expected = {b['date'] for b in calendar if str(cfg.start) <= b['date'] <= str(cfg.end)}
    if not expected:
        raise ValueError('Cached exchange sessions are unavailable for these dates. Refresh daily market data first.')
    datasets, excluded, reasons, history = {}, [], {}, {}
    items = universe['instruments']
    for start in range(0, len(items), 128):
        batch = items[start:start+128]
        records = read_many(['bars/'+x['isin'] for x in batch])
        for item in batch:
            symbol = item['symbol']
            record = records.get('bars/'+item['isin'])
            reason = None
            if not record or not record.get('bars'):
                reason = 'No cached daily candles.'
            else:
                rows, details = market_history.prepare(item, record, reference=evidence, fingerprint=False)
                dates = [b['date'] for b in rows]
                first, last = bisect_left(dates, str(cfg.start)), bisect_right(dates, str(cfg.end))
                if first == last or last <= max(first,100) or not dates or dates[-1] < str(cfg.end) or (cfg.coverage_mode == 'full_window' and first < 100):
                    reason = 'Insufficient date coverage or 100 pre-window warmup candles.'
                elif cfg.coverage_mode == 'full_window' and expected-set(dates[first:last]):
                    reason = 'Missing stock candles on observed exchange sessions inside the test window.'
                elif any(str(cfg.start) < a['ex_date'] <= str(cfg.end) for a in corporate_actions.actions(rows)):
                    reason = 'Split/bonus inside the test window requires share-rebasing support.'
                else:
                    rows = corporate_actions.adjusted_bars(rows, str(cfg.start))
                    # Prices have now been rebased once; do not apply raw action factors again.
                    selected = [{k:v for k,v in b.items() if k != 'corporate_actions'} for b in rows[max(0, first-150):last]]
                    findings = data_quality.audit({symbol:selected})['findings']
                    if findings:
                        reason = 'Unresolved price discontinuity in the input window.'
                    else:
                        datasets[symbol] = selected
                        history[symbol] = details
            if reason:
                excluded.append(symbol)
                reasons[symbol] = reason
        log(f'Daily stock inputs checked: {min(start+128,len(items))}/{len(items)}; {len(datasets)} eligible.')
    if not datasets:
        raise ValueError('No cached stocks cover these dates with 100 warmup candles. Choose a window inside downloaded daily history.')
    fragments = {}
    if cfg.coverage_mode == 'available_history':
        # An observed valid stock candle is evidence of a market session, including
        # older dates absent from the cached index calendar. New listings join only
        # after their own indicator warmup; no prelisting bars are fabricated.
        observed = expected | {b['date'] for rows in datasets.values() for b in rows
                               if str(cfg.start) <= b['date'] <= str(cfg.end)}
        for symbol,rows in list(datasets.items()):
            missing = {day for day in observed if rows[0]['date'] <= day <= str(cfg.end)}-{b['date'] for b in rows}
            if missing:
                # Keep the latest continuous segment ending at the test cutoff.
                # Earlier isolated fragments cannot safely carry a position across
                # an unknown-price interval, and missing prices are never invented.
                cutoff = max(missing)
                continuous = [b for b in rows if b['date'] > cutoff]
                if len(continuous) <= 100:
                    excluded.append(symbol)
                    reasons[symbol] = 'Fewer than 100 contiguous warmup candles after the last data gap.'
                    del datasets[symbol]
                    del history[symbol]
                else:
                    datasets[symbol] = continuous
                    fragments[symbol] = dict(original_first=rows[0]['date'],last_gap=cutoff,
                                             ignored_candles=len(rows)-len(continuous))
        if not datasets:
            raise ValueError('No stock has contiguous observed-session coverage after its own warmup.')
    coverage = {s:dict(first_available=rows[0]['date'],last_available=rows[-1]['date'],
                       eligible_from=max(str(cfg.start),rows[100]['date'])) for s,rows in datasets.items()}
    return dict(datasets=datasets, universe=universe, benchmark=[b for b in calendar if b['date'] <= str(cfg.end)], excluded=excluded, exclusion_reasons=reasons,
                history=history, coverage=coverage, history_fragments=fragments,
                coverage_policy='latest-contiguous-segment-v1' if cfg.coverage_mode == 'available_history' else 'full-window-v1',
                captured_at=store.now(), source='Cached daily equity candles')


def features(datasets, log=None, *, rsi_threshold=70, bollinger_multiplier=2):
    result = {}
    for symbol, rows in datasets.items():
        values = indicators(rows, bollinger_multiplier=bollinger_multiplier)
        result[symbol] = [decision(dict(b,time='close'), f, rows[i-1], rsi_threshold=rsi_threshold,
                                   bollinger_multiplier=bollinger_multiplier) if i >= 20 else None
                          for i,(b,f) in enumerate(zip(rows,values))]
        if log and (len(result)%100 == 0 or len(result) == len(datasets)):
            log(f'Daily indicators calculated: {len(result)}/{len(datasets)} stocks.')
    return result


def simulate(datasets, signals, cfg, rule, *, state=None, liquidate=True, entry_start=None, entries_allowed=True, instruments=(), benchmark=(), entry_filter=None):
    _, label, checks, below = rule
    events = {}
    for symbol, rows in datasets.items():
        for i,b in enumerate(rows):
            if str(cfg.start) <= b['date'] <= str(cfg.end):
                events.setdefault(b['date'], {})[symbol] = i
    from copy import deepcopy
    state = deepcopy(state or {})
    cash = state.get('cash', cfg.capital)
    positions, marks = state.get('positions', {}), state.get('marks', {})
    trades, curve, orders = state.get('trades', []), state.get('curve', []), state.get('orders', [])
    fees, slippage, skipped = state.get('total_fees',0), state.get('total_slippage',0), state.get('skipped_entries',0)
    peak = max([cfg.capital]+[c['equity'] for c in curve])
    drawdown = state.get('max_drawdown_pct',0)
    slip = cfg.slippage_bps/10000
    days = sorted(events)
    allocation_context = AllocationContext(datasets, cfg, instruments, benchmark)
    allocation_cfg = allocation_context.config
    filter_decisions = []

    def close(symbol, bar, raw, reason):
        nonlocal cash, fees, slippage
        p = positions.pop(symbol)
        price = raw*(1-slip)
        charge = equity_charges(price, p['quantity'], 'sell', bar['date'])['total']
        cash += price*p['quantity']-charge
        fees += charge
        slippage += (raw-price)*p['quantity']
        pnl = (price-p['entry'])*p['quantity']-p['entry_fee']-charge
        trades.append(dict(p, symbol=symbol, exit=price, exit_date=bar['date'], reason=reason,
                           pnl=pnl, fees=p['entry_fee']+charge,
                           return_pct=pnl/(p['entry']*p['quantity']+p['entry_fee'])*100))
        orders.append(dict(symbol=symbol,side='SELL',date=bar['date'],price=price,quantity=p['quantity'],fees=charge,reason=reason))

    for day in days:
        available = events[day]
        exited = set()
        # Prior completed-session signals fill at today's real open.
        for symbol in sorted(positions):
            if symbol not in available:
                continue
            i = available[symbol]
            signal = signals[symbol][i-1] if i else None
            if signal and signal['exit']:
                close(symbol, datasets[symbol][i], datasets[symbol][i]['open'], 'Supertrend reversal · next open')
                exited.add(symbol)
        candidates = []
        for symbol,i in available.items():
            if not entries_allowed or symbol in positions or symbol in exited or i < 100:
                continue
            rows = datasets[symbol]
            # Signals preceding the experiment start are context, not historical entries.
            if rows[i-1]['date'] < str(entry_start or cfg.start):
                continue
            signal = signals[symbol][i-1]
            if signal and all(signal['checks'][j]['passed'] for j in checks) and (not below or signal['close'] < signal['checks'][2]['value']):
                candidates.append((allocation_context.rank(symbol, i-1, rows[i-1]), symbol, i))
        equity_open = cash+sum(p['quantity']*(datasets[s][available[s]]['open'] if s in available else marks[s]) for s,p in positions.items())
        for _,symbol,i in sorted(candidates):
            if len(positions) >= cfg.max_positions:
                skipped += 1
                continue
            bar = datasets[symbol][i]
            filter_evidence = None
            if entry_filter is not None:
                allowed, filter_evidence = entry_filter(symbol, datasets[symbol][i-1]['date'], day)
                filter_decisions.append(dict(symbol=symbol, date=day, allowed=allowed, evidence=filter_evidence))
                if not allowed:
                    skipped += 1
                    continue
            price = bar['open']*(1+slip)
            allocation = allocation_context.allocation(symbol, i-1, datasets[symbol][i-1]['date'], equity_open, cfg.max_positions)
            if filter_evidence is not None:
                allocation['analyst_filter'] = filter_evidence
            sector = allocation_context.sectors.get(symbol, '')
            sector_exposure = sum(p['quantity']*(datasets[s][available[s]]['open'] if s in available else marks[s])
                                  for s,p in positions.items() if allocation_context.sectors.get(s, '') == sector)
            budget = allocation['requested_budget']
            if allocation_cfg.max_sector_pct < 100:
                budget = min(budget, max(0, equity_open*allocation_cfg.max_sector_pct/100-sector_exposure))
            allocation.update(sector_exposure_before=sector_exposure, cash_budget=max(0, min(budget, cash)))
            quantity = size_order(equity_open, min(budget,cash), price, price, 100, day)
            if quantity <= 0:
                skipped += 1
                continue
            charge = equity_charges(price, quantity, 'buy', day)['total']
            cash -= price*quantity+charge
            fees += charge
            slippage += (price-bar['open'])*quantity
            positions[symbol] = dict(entry=price, entry_date=day, quantity=quantity, entry_fee=charge,
                                     entry_cost=price*quantity+charge,
                                     signal_date=datasets[symbol][i-1]['date'], signal=signals[symbol][i-1], allocation=allocation)
            orders.append(dict(symbol=symbol,side='BUY',date=day,price=price,quantity=quantity,fees=charge,signal_date=datasets[symbol][i-1]['date'], allocation=allocation))
        for symbol,i in available.items():
            marks[symbol] = datasets[symbol][i]['close']
        # Liquidate at each symbol's final observed close, rather than inventing a missing fill.
        for symbol in list(positions):
            i = available.get(symbol)
            if liquidate and i is not None and (day == days[-1] or i+1 == len(datasets[symbol])):
                close(symbol,datasets[symbol][i],datasets[symbol][i]['close'],'End of backtest · final observed close')
        equity = cash+sum(p['quantity']*marks[s] for s,p in positions.items())
        peak = max(peak,equity)
        drawdown = max(drawdown,(peak-equity)/peak*100)
        curve.append(dict(date=day,equity=equity,cash=cash,positions=len(positions)))
        if cash < -.001:
            raise ValueError('Cash accounting became negative; simulation halted.')
    if positions and liquidate:
        raise ValueError('Missing terminal prices prevent closing all positions.')
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [t['pnl'] for t in trades if t['pnl'] < 0]
    equity = cash+sum(p['quantity']*marks[s] for s,p in positions.items())
    ledger = dict(cash=cash,positions=positions,marks=marks,trades=trades,curve=curve,orders=orders,
                  total_fees=fees,total_slippage=slippage,skipped_entries=skipped,max_drawdown_pct=drawdown,
                  last_session=days[-1] if days else state.get('last_session'))
    result = dict(trades=trades, curve=curve, metrics=dict(final_equity=equity,return_pct=(equity/cfg.capital-1)*100,
                max_drawdown_pct=drawdown,trade_count=len(trades),win_rate=100*len(wins)/len(trades) if trades else None,
                profit_factor=sum(wins)/-sum(losses) if losses else None,modeled_fees=fees,modeled_slippage=slippage,
                skipped_entries=skipped,drawdown_basis='Marked at daily closes',net_pnl=equity-cfg.capital,
                average_exposure_pct=sum(c.get('exposure_pct',(c['equity']-c['cash'])/c['equity']*100 if c['equity'] > 0 else 0) for c in curve)/len(curve) if curve else 0,
                traded_notional=sum(o['price']*o['quantity'] for o in orders),
                top_five_pnl=sum(sorted((t['pnl'] for t in trades if t['pnl'] > 0),reverse=True)[:5])),
                rule_label=label)
    if not liquidate:
        result['ledger'] = ledger
    if entry_filter is not None:
        result['entry_filter_decisions'] = filter_decisions
    return result


def run(settings, cfg, log, job_id):
    frozen = prepare(settings,cfg,log)
    datasets = frozen['datasets']
    signal_values = features(datasets,log,**stored_parameters(cfg.model_dump()))
    input_sha256 = digest(frozen)
    manifest = [dict(symbol=s,sha256=digest(rows),bars=len(rows)) for s,rows in datasets.items()]
    selected = [r for r in RULES if cfg.rule_set in ('all',r[0]) or (cfg.rule_set == 'main' and r[0] != 'below_r1')]
    ids, summaries = [], []
    for rule in selected:
        if rule[0] == 'rsi':
            rule = (rule[0], f'+ RSI > {cfg.rsi_threshold:g}', *rule[2:])
        run_id = job_id if not ids else uuid4().hex[:12]
        result = simulate(datasets,signal_values,cfg,rule,instruments=frozen['universe']['instruments'],benchmark=frozen.get('benchmark',()))
        config = cfg.model_copy(update=dict(rule_set=rule[0],name=(cfg.name+' · '+rule[1])[:80])).model_dump(mode='json')
        result.update(id=run_id,strategy_id=STRATEGY,created_at=store.now(),config=config,
                      universe=settings.universe,universe_snapshot=frozen['universe'],input_sha256=input_sha256,
                      excluded=frozen['excluded'],exclusion_reasons=frozen['exclusion_reasons'],
                      stock_coverage=frozen.get('coverage',{}),
                      history_fragments=frozen.get('history_fragments',{}),coverage_policy=frozen.get('coverage_policy','full-window-v1'),
                      manifest=manifest,
                      warnings=['Daily equity swing adaptation of an intraday option-buying video; no options are traded or priced.',
                                f'Supertrend 10/3; RSI(14) >{cfg.rsi_threshold:g}; traditional prior-day R1; Bollinger(20,{cfg.bollinger_multiplier:g}). Each variant uses only its declared entry conditions.',
                                'Entries and Supertrend reversal exits fill at the next observed session open. No profit target, extra fundamental gate or maximum holding period.',
                                allocation_notice(cfg),
                                'No leverage. Prices mark at daily closes; final holdings liquidate at the final observed close. Cash and sector limits include entry fees conservatively; exposure can exceed an entry cap after price moves.',
                                'Current universe membership causes survivorship bias. Known in-window splits/bonuses and unresolved data gaps are excluded and listed. Dividends and historical taxes are not reconstructed.',
                                'Fees and slippage are explicit assumptions. This is exploratory research, not evidence of a deployable edge.'])
        if any(h.get('provisional_daily') for h in frozen.get('history', {}).values()):
            result['warnings'].append('Inputs include provisional daily aggregates from complete current-session minute candles. Final minute-bar closes can differ from published daily closes; inspect frozen history provenance.')
        if cfg.coverage_mode == 'available_history':
            result['warnings'].append('Full available history: each stock becomes eligible after 100 observed warmup candles in its latest continuous cached history ending at the test cutoff. Earlier isolated fragments are listed and ignored; index and valid stock candles define observed exchange sessions. Stocks without enough continuous warmup are excluded. No prelisting or missing prices are invented.')
        log(f'{rule[1]}: calculation finished; saving frozen inputs and trade report.')
        store.write('run_data/'+run_id,frozen)
        store.write('runs/'+run_id,result)
        summaries.append({k:result[k] for k in ('id','strategy_id','created_at','config','universe','metrics')})
        ids.append(run_id)
        log(f'{rule[1]}: {result["metrics"]["trade_count"]} trades; net return {result["metrics"]["return_pct"]:.2f}%.')
    with store.LOCK:
        store.write('runs_index',list(reversed(summaries))+store.read('runs_index',[]))
    return dict(run_id=ids[0],run_ids=ids,eligible_symbols=len(datasets),excluded_symbols=len(frozen['excluded']))
