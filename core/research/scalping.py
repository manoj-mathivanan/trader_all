"""One-minute pullback research. Completed signals, chronological cash accounting."""
import hashlib
import json
import math
from bisect import bisect_left
from datetime import date, datetime
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.execution.paper import PaperBrokerAdapter
from core.research import corporate_actions, data_quality, intraday_data, momentum, provenance, store


class ScalpingParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    strategy_id: Literal['scalping'] = 'scalping'
    name: str = Field('EMA pullback scalping', min_length=1, max_length=80, title='Run name')
    capital: float = Field(1000000, ge=1000, le=1e10, title='Starting capital (₹)')
    direction: Literal['both', 'long', 'short'] = 'both'
    entry_filter: Literal['candles', 'ema', 'ema_vwap'] = Field('ema', title='Entry confirmation')
    trend_fast: int = Field(9, ge=2, le=50, title='Five-minute fast EMA')
    trend_slow: int = Field(20, ge=3, le=100, title='Five-minute slow EMA')
    pullback_ema: int = Field(9, ge=2, le=50, title='One-minute pullback EMA')
    pullback_bars: int = Field(2, ge=1, le=5, title='Consecutive adverse pullback candles')
    ema_touch_bps: float = Field(5, ge=0, le=100, title='Pullback EMA touch tolerance (bps)')
    entry_buffer_bps: float = Field(1, ge=0, le=100, title='Breakout and stop buffer (bps)')
    min_stop_pct: float = Field(0.05, gt=0, le=5, title='Minimum stop distance (%)')
    max_stop_pct: float = Field(0.5, gt=0, le=10, title='Maximum stop distance (%)')
    liquidity_days: int = Field(20, ge=5, le=50, title='Prior turnover history (sessions)')
    min_turnover: float = Field(50000000, ge=0, le=1e12, title='Minimum prior average turnover (₹)')
    liquid_universe_size: int = Field(20, ge=1, le=100, title='Most liquid stocks to scan')
    risk_pct: float = Field(0.1, gt=0, le=5, title='Risk per trade (%)')
    max_positions: int = Field(3, ge=1, le=20, title='Maximum concurrent positions')
    target_r: float = Field(1.5, gt=0, le=10, title='Profit target (R)')
    max_holding_minutes: int = Field(15, ge=1, le=120, title='Maximum holding minutes')
    cooldown_minutes: int = Field(5, ge=1, le=120, title='Cooldown after exit (minutes)')
    max_trades_per_symbol: int = Field(3, ge=1, le=20, title='Maximum trades per stock per day')
    daily_loss_pct: float = Field(1, gt=0, le=20, title='Daily loss limit: pause entries (%)')
    participation_pct: float = Field(1, gt=0, le=10, title='Maximum share of signal-minute volume (%)')
    first_entry_time: str = Field('09:45', pattern=r'^\d{2}:\d{2}$', title='First entry open (IST)')
    last_entry_time: str = Field('14:30', pattern=r'^\d{2}:\d{2}$', title='Last entry open (IST)')
    square_off_time: str = Field('15:15', pattern=r'^\d{2}:\d{2}$', title='Mandatory exit open (IST)')
    slippage_bps: float = Field(10, ge=0, le=500, title='Slippage per side (bps)')
    buy_cost_bps: float = Field(10, ge=0, le=500, title='All-in buy charges (bps)')
    sell_cost_bps: float = Field(10, ge=0, le=500, title='All-in sell charges (bps)')
    acknowledge_limitations: bool = Field(False, title='I understand this is exploratory candle-based research')

    @model_validator(mode='after')
    def rules(self):
        if self.trend_fast >= self.trend_slow or self.min_stop_pct > self.max_stop_pct:
            raise ValueError('Fast EMA must be shorter than slow EMA; minimum stop must not exceed maximum.')
        if self.max_positions > self.liquid_universe_size:
            raise ValueError('Position limit cannot exceed scan size.')
        values = []
        for value in (self.first_entry_time, self.last_entry_time, self.square_off_time):
            h, m = map(int, value.split(':'))
            if h > 23 or m > 59:
                raise ValueError('Invalid IST time.')
            values.append(h*60+m)
        if not 560 <= values[0] <= values[1] < values[2] <= 920:
            raise ValueError('Entry times must follow 09:20 and precede square-off, no later than 15:20 IST.')
        if not self.acknowledge_limitations:
            raise ValueError('Acknowledge research limitations before running.')
        return self


class ScalpingConfig(ScalpingParameters):
    start: date = Field(..., title='Test from')
    end: date = Field(..., title='Test through')
    comparison_run_id: str | None = Field(None, pattern=r'^[0-9a-f]{12}$', title='Frozen input reference')

    @model_validator(mode='after')
    def research_dates(self):
        if not date(2022, 4, 1) <= self.start < self.end < datetime.now(intraday_data.IST).date():
            raise ValueError('Choose increasing completed-session dates from April 2022 onward.')
        return self


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(settings, cfg):
    if cfg.comparison_run_id:
        report = store.read('runs/'+cfg.comparison_run_id)
        daily = store.read('run_data/'+cfg.comparison_run_id)
        if not report or report.get('strategy_id') != 'scalping' or not daily:
            raise ValueError('Saved scalping reference with frozen inputs is required.')
        if settings.universe != report['universe'] or str(cfg.start) < report['config']['start'] or str(cfg.end) > report['config']['end']:
            raise ValueError('Replay must use the reference universe and stay inside its date window.')
        for item in report['manifest']:
            if digest(daily.get(item['symbol'])) != item['sha256']:
                raise ValueError('Frozen daily input hash changed; replay halted.')
        return report['universe_snapshot'], daily, report['manifest'], report['excluded']
    proxy = momentum.MomentumConfig(start=cfg.start, end=cfg.end, liquidity_days=cfg.liquidity_days,
                                   volume_lookback=50, acknowledge_limitations=True)
    return momentum.prepare(settings, proxy)


def entry_plan(datasets, cfg, *, days=None, require_day_bar=True):
    plan, requests = {}, {}
    warmup_days = max(2, math.ceil(cfg.trend_slow*5/75)+1)
    days = days if days is not None else {b['date'] for rows in datasets.values() for b in rows if str(cfg.start) <= b['date'] <= str(cfg.end)}
    for day in sorted(days):
        if day in intraday_data.SPECIAL_SESSIONS:
            continue
        candidates = []
        for symbol, rows in datasets.items():
            i = bisect_left([b['date'] for b in rows], day)
            if i < max(cfg.liquidity_days, warmup_days) or (require_day_bar and (i == len(rows) or rows[i]['date'] != day)):
                continue
            prior = corporate_actions.adjusted_bars(rows[:i], day)
            turnover = mean(b['close']*b['volume'] for b in prior[-cfg.liquidity_days:])
            history = [b['date'] for b in prior[-warmup_days:]]
            if turnover < cfg.min_turnover or any(d in intraday_data.SPECIAL_SESSIONS for d in history):
                continue
            if any(history[0] < a['ex_date'] <= day for a in corporate_actions.actions(rows)):
                raise ValueError(f'Corporate action crosses minute EMA warmup for {symbol} on {day}; minute price basis requires verification.')
            candidates.append(dict(symbol=symbol, turnover=turnover, history=history,
                                   daily_open=rows[i]['open'] if i < len(rows) and rows[i]['date'] == day else None))
        plan[day] = sorted(candidates, key=lambda c: (-c['turnover'], c['symbol']))[:cfg.liquid_universe_size]
        for c in plan[day]:
            for d in [day, *c['history']]:
                requests.setdefault(d, []).append({'symbol': c['symbol']})
    return plan, requests


def ema(values, period):
    """SMA seed; no indicator value before the declared warmup."""
    output, current = [], None
    for i, value in enumerate(values):
        if i == period-1:
            current = mean(values[:period])
        elif i >= period:
            current += 2/(period+1)*(value-current)
        output.append(current)
    return output


def features(sessions, candidate, day, cfg, completed_bars=None):
    history = []
    for d in candidate['history']:
        history.extend(intraday_data.trading_bars(sessions[d], '15:29', 1))
    bars = intraday_data.trading_bars(sessions[day], cfg.square_off_time, 1) if completed_bars is None else completed_bars
    if not bars:
        return [], []
    if completed_bars is not None:
        intraday_data.trading_bars(bars, bars[-1]['time'], 1)
    if len(history)//5 < 5*cfg.trend_slow:
        raise ValueError('Insufficient frozen minute warmup for trend EMAs.')
    all_bars = history+bars
    one = ema([b['close'] for b in all_bars], cfg.pullback_ema)[len(history):]
    # Every historical regular session contains exactly 375 minutes (75 complete bins).
    closes = [all_bars[i]['close'] for i in range(4, len(all_bars), 5)]
    fast, slow = ema(closes, cfg.trend_fast), ema(closes, cfg.trend_slow)
    vwap = momentum.session_vwap(bars)
    result = []
    for j, b in enumerate(bars):
        k = (len(history)+j+1)//5-1
        # k refers only to the last completed five-minute candle at this signal close.
        previous_close = closes[k-1]
        result.append(dict(ema=one[j], fast=fast[k], slow=slow[k], previous_fast=fast[k-1],
                           trend_close=closes[k], previous_trend_close=previous_close, vwap=vwap[j]))
    return bars, result


def signal(bars, values, j, cfg):
    n = cfg.pullback_bars
    if j < n+1:
        return None
    f, b = values[j], bars[j]
    pullback = bars[j-n:j]
    impulse = bars[j-n-1]
    for side, sign in [('long', 1), ('short', -1)]:
        if cfg.direction not in ('both', side):
            continue
        if not (sign*(f['trend_close']-f['previous_trend_close']) > 0 if cfg.entry_filter == 'candles' else
                sign*(f['fast']-f['slow']) > 0 and sign*(f['fast']-f['previous_fast']) > 0 and sign*(f['trend_close']-f['fast']) > 0):
            continue
        if sign*(impulse['close']-impulse['open']) <= 0 or any(sign*(p['close']-p['open']) >= 0 for p in pullback):
            continue
        trigger = max(p['high'] for p in pullback) if sign == 1 else min(p['low'] for p in pullback)
        trigger *= 1+sign*cfg.entry_buffer_bps/10000
        if sign*(b['close']-trigger) <= 0 or sign*(b['close']-b['open']) <= 0:
            continue
        if cfg.entry_filter != 'candles':
            tolerance = cfg.ema_touch_bps/10000
            touched = any(p['low'] <= values[j-n+i]['ema']*(1+tolerance) and
                          p['high'] >= values[j-n+i]['ema']*(1-tolerance) for i, p in enumerate(pullback))
            if not touched or sign*(b['close']-f['ema']) <= 0:
                continue
        if cfg.entry_filter == 'ema_vwap' and (f['vwap'] is None or sign*(b['close']-f['vwap']) <= 0):
            continue
        stop = (min(p['low'] for p in pullback) if sign == 1 else max(p['high'] for p in pullback))*(1-sign*cfg.entry_buffer_bps/10000)
        return dict(direction=side, sign=sign, trigger=trigger, stop=stop, indicators=f)
    return None


def simulate(datasets, cfg, sessions, plan):
    broker = PaperBrokerAdapter(cfg)
    cash, peak, max_dd = cfg.capital, cfg.capital, 0
    trades, curve = [], []
    fees_total = slip_total = skipped = ambiguous = 0
    loss_halt_days = 0
    for day, candidates in sorted(plan.items()):
        prepared = {}
        for c in candidates:
            symbol = c['symbol']
            try:
                bars, values = features(sessions[symbol], c, day, cfg)
            except (KeyError, ValueError) as exc:
                raise ValueError(f'Incomplete scalping inputs for {symbol} on {day}: {exc}') from None
            if abs(bars[0]['open']/c['daily_open']-1) >= .35:
                raise ValueError(f'Intraday/daily price units disagree for {symbol} on {day}.')
            prepared[symbol] = (bars, values)
        active, cooldown, counts = {}, {}, {}
        day_start, halt = cash, False
        length = next((len(b) for b, _ in prepared.values()), 0)

        def mark(index, field):
            return cash+sum(p['reserved']+p['sign']*p['quantity']*(prepared[s][0][index][field]-p['entry'])-p['entry_fee']
                            for s, p in active.items())

        def close(symbol, index, raw, reason, precision):
            nonlocal cash, fees_total, slip_total
            p = active.pop(symbol)
            b = prepared[symbol][0][index]
            fill = broker.fill(raw, p['quantity'], 'sell' if p['sign'] == 1 else 'buy')
            fees = p['entry_fee']+fill['fees']
            pnl = p['sign']*p['quantity']*(fill['price']-p['entry'])-fees
            cash += p['reserved']+pnl
            fees_total += fees
            slip_total += p['entry_slippage']+fill['slippage']
            cooldown[symbol] = index+cfg.cooldown_minutes
            trades.append(dict(symbol=symbol, direction=p['direction'], execution_horizon='intraday',
                               signal_date=day, signal_time=p['signal']['time'], signal_timestamp=p['signal']['timestamp'],
                               entry_date=day, exit_date=day, entry_time=p['bar']['time'], exit_time=b['time'],
                               entry_timestamp=p['bar']['timestamp'], exit_timestamp=b['timestamp'],
                               entry=p['entry'], exit=fill['price'], quantity=p['quantity'], exit_quantity=p['quantity'],
                               pnl=pnl, r=pnl/(p['quantity']*p['distance']), reason=reason, fees=fees, borrow_cost=0,
                               trigger=p['trigger'], initial_stop=p['stop'], target=p['target'],
                               signal_close=p['signal']['close'], signal_indicators=p['indicators'],
                               holding_minutes=index-p['index'], stop_trace=p['trace'], exit_time_precision=precision))

        for i in range(length):
            # Open-price exits occur before open-price entries. Intrabar exits cannot fund earlier entries.
            for symbol in list(active):
                b, p = prepared[symbol][0][i], active[symbol]
                p['trace'].append(dict(timestamp=b['timestamp'], stop=p['stop']))
                reason = None
                if b['time'] == cfg.square_off_time:
                    reason = 'Mandatory intraday square-off'
                elif i-p['index'] >= cfg.max_holding_minutes:
                    reason = 'Maximum holding time'
                elif p['sign']*(b['open']-p['stop']) <= 0:
                    reason = 'Gap through pullback stop'
                elif p['sign']*(b['open']-p['target']) >= 0:
                    reason = 'Gap beyond profit target'
                if reason:
                    close(symbol, i, b['open'], reason, 'one-minute bar open')
            opening_equity = mark(i, 'open')
            if opening_equity <= day_start*(1-cfg.daily_loss_pct/100):
                halt = True
            for c in candidates:
                symbol = c['symbol']
                bars, values = prepared[symbol]
                b = bars[i]
                if i == 0 or not cfg.first_entry_time <= b['time'] <= cfg.last_entry_time or symbol in active or i < cooldown.get(symbol, 0) or counts.get(symbol, 0) >= cfg.max_trades_per_symbol:
                    continue
                s = signal(bars, values, i-1, cfg)
                if not s:
                    continue
                if halt or len(active) >= cfg.max_positions:
                    skipped += 1
                    continue
                side = 'buy' if s['sign'] == 1 else 'sell'
                fill = broker.fill(b['open'], 1, side)['price']
                distance = s['sign']*(fill-s['stop'])
                if s['stop'] <= 0 or not cfg.min_stop_pct <= distance/fill*100 <= cfg.max_stop_pct:
                    skipped += 1
                    continue
                target = fill+s['sign']*distance*cfg.target_r
                if target <= 0:
                    skipped += 1
                    continue
                fee_rate = (cfg.buy_cost_bps if s['sign'] == 1 else cfg.sell_cost_bps)/10000
                stop_fill = broker.fill(s['stop'], 1, 'sell' if s['sign'] == 1 else 'buy')
                unit_risk = s['sign']*(fill-stop_fill['price'])+fill*fee_rate+stop_fill['fees']
                qty = max(0, min(math.floor(max(0, opening_equity)*cfg.risk_pct/100/unit_risk),
                                 math.floor(min(cash, max(0, opening_equity)/cfg.max_positions)/(fill*(1+fee_rate))),
                                 math.floor(bars[i-1]['volume']*cfg.participation_pct/100)))
                if not qty:
                    skipped += 1
                    continue
                entry = broker.fill(b['open'], qty, side)
                reserved = fill*qty+entry['fees']
                cash -= reserved
                active[symbol] = dict(**s, entry=fill, quantity=qty, reserved=reserved, distance=distance,
                                      entry_fee=entry['fees'], entry_slippage=entry['slippage'], target=target,
                                      index=i, bar=b, signal=bars[i-1], trace=[dict(timestamp=b['timestamp'], stop=s['stop'])])
                counts[symbol] = counts.get(symbol, 0)+1
            for symbol in list(active):
                b, p = prepared[symbol][0][i], active[symbol]
                stop_hit = b['low'] <= p['stop'] if p['sign'] == 1 else b['high'] >= p['stop']
                target_hit = b['high'] >= p['target'] if p['sign'] == 1 else b['low'] <= p['target']
                if stop_hit or target_hit:
                    ambiguous += int(stop_hit and target_hit)
                    close(symbol, i, p['stop'] if stop_hit else p['target'], 'Pullback stop loss' if stop_hit else 'Profit target', 'one-minute candle')
            equity = mark(i, 'close')
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak-equity)/peak*100)
            if equity <= day_start*(1-cfg.daily_loss_pct/100):
                halt = True
        if active:
            raise ValueError('Scalping session ended without mandatory liquidation.')
        loss_halt_days += int(halt)
        curve.append(dict(date=day, equity=round(cash, 2), drawdown_pct=(peak-cash)/peak*100))
    if not curve:
        raise ValueError('No regular sessions in the scalping test window.')
    wins, losses = [t for t in trades if t['pnl'] > 0], [t for t in trades if t['pnl'] < 0]
    return dict(trades=trades, curve=curve, metrics=dict(initial_capital=cfg.capital, final_equity=cash,
                return_pct=(cash/cfg.capital-1)*100, max_drawdown_pct=max_dd, trade_count=len(trades),
                win_rate=len(wins)/len(trades)*100 if trades else None,
                expectancy_r=mean(t['r'] for t in trades) if trades else None,
                profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
                modeled_fees=fees_total, modeled_slippage=slip_total, skipped_entries=skipped,
                ambiguous_stop_target_bars=ambiguous, overnight_positions=0, drawdown_basis='minute-close marked equity'),
                diagnostics=dict(long=momentum.trade_summary([t for t in trades if t['direction'] == 'long']),
                                 short=momentum.trade_summary([t for t in trades if t['direction'] == 'short']),
                                 daily_loss_halt_sessions=loss_halt_days, cost_impact=fees_total+slip_total,
                                 average_holding_minutes=mean(t['holding_minutes'] for t in trades) if trades else None,
                                 turnover=sum((t['entry']+t['exit'])*t['quantity'] for t in trades),
                                 time_of_day=[dict(name=name, **momentum.trade_summary([t for t in trades if start <= t['entry_time'] < end]))
                                              for name, start, end in [('Morning', '09:15', '11:00'), ('Midday', '11:00', '13:00'), ('Afternoon', '13:00', '15:30')]]))


def frozen_sessions(cfg, reference=None):
    sessions = store.read('run_intraday/'+cfg.comparison_run_id)
    reference = reference or store.read('runs/'+cfg.comparison_run_id)
    if not sessions or digest(sessions) != reference['intraday_source']['sha256']:
        raise ValueError('Frozen one-minute inputs are missing or changed; replay halted.')
    return sessions


def coverage(settings, cfg):
    universe, daily, _, excluded = prepare(settings, cfg)
    _, requests = entry_plan(daily, cfg)
    required = {(c['symbol'], d) for d, rows in requests.items() for c in rows}
    instruments = {c['symbol']: c for c in universe['instruments']}
    if cfg.comparison_run_id:
        sessions = frozen_sessions(cfg)
        ready = sum(bool(sessions.get(s, {}).get(d)) for s, d in required)
    else:
        ready = sum(bool(store.read(intraday_data.cache_key(instruments[s]['isin'], d, 1), {}).get('bars')) for s, d in required)
    return dict(stock_sessions=len(required), cached=ready, missing=len(required)-ready, excluded=excluded,
                estimated_candles=len(required)*375, source='frozen reference' if cfg.comparison_run_id else 'one-minute cache')


def run(settings, cfg, log, job_id):
    universe, daily, manifest, excluded = prepare(settings, cfg)
    quality = data_quality.audit(daily, end=cfg.end)
    daily = data_quality.exclude_anomalies(daily, quality, log)
    if not daily:
        raise ValueError('No eligible stocks remain after excluding unresolved price gaps.')
    manifest = [row for row in manifest if row['symbol'] in daily]
    excluded = list(dict.fromkeys([*excluded, *quality['excluded_symbols']]))
    plan, requests = entry_plan(daily, cfg)
    sessions = frozen_sessions(cfg) if cfg.comparison_run_id else intraday_data.load_ranges(requests, universe, log, 1)
    result = simulate(daily, cfg, sessions, plan)
    result.update(id=job_id, strategy_id='scalping', created_at=store.now(), config=cfg.model_dump(mode='json'),
                  universe=settings.universe, universe_snapshot=universe, manifest=manifest, excluded=excluded,
                  selection_plan=plan,
                  provenance=provenance.capture(), data_quality=quality,
                  intraday_source=dict(provider='Upstox historical V3', interval_minutes=1, timezone='Asia/Kolkata', sha256=digest(sessions)),
                  warnings=[
                      'Research hypothesis, not a proven scalping edge. Reserve untouched dates; stress costs and slippage.',
                      'Current constituent universe is survivorship biased; corporate-action minute adjustments are unverified. Warmup crossings halt.',
                      'Prior turnover ranks stocks. Five-minute EMAs use SMA seeds and at least five slow-EMA periods of prior-session warmup.',
                      'Impulse, adverse pullback candles and completed close beyond their extreme trigger next-minute-open entry.',
                      'EMA mode requires trend alignment, rising/falling fast EMA and a pullback EMA touch. EMA + VWAP adds completed-bar typical-price VWAP.',
                      'Candle-only mode uses consecutive completed five-minute closes for direction and the same pullback pattern, without EMA or VWAP gates.',
                      'Full notional plus entry fees reserved for longs and shorts; no leverage. Open exits fund open entries; intrabar proceeds only fund later bars.',
                      'Participation cap uses the previous completed signal-minute volume; it is a liquidity proxy, not an actual next-open fill guarantee.',
                      'Stop and target in the same minute assume stop first. Candle data cannot establish seconds-level ordering, spread or queue priority.',
                      'Daily loss limit latches a pause on new entries using open/close marked equity; existing stops and exits continue. Loss can exceed the threshold.',
                      'Fees and slippage are editable assumptions; short eligibility, circuits, tick sizes, borrow and actual execution are unverified.',
                      'Drawdown uses minute-close marked equity with entry fees, without estimated liquidation fees or intraminute extrema.',
                  ])
    result['warnings'].extend(quality['warnings'])
    result['evaluation'] = momentum.chronological_evaluation(result)
    store.write('run_data/'+job_id, daily)
    store.write('run_intraday/'+job_id, sessions)
    store.write('runs/'+job_id, result)
    with store.LOCK:
        index = store.read('runs_index', [])
        index.insert(0, {k: result[k] for k in ('id', 'created_at', 'strategy_id', 'config', 'universe', 'metrics')})
        store.write('runs_index', index)
    log(f"Recorded {len(result['trades'])} scalping trades; net return {result['metrics']['return_pct']:.2f}%.")
    return {'run_id': job_id, 'partial': bool(quality['excluded_symbols']),
            'price_gap_exclusions': quality['excluded_symbols']}


def compare(settings, reference_id, log, job_id):
    """All three declared confirmation variants on identical frozen inputs/costs."""
    from uuid import uuid4
    reference = store.read('runs/'+reference_id)
    if not reference or reference.get('strategy_id') != 'scalping':
        raise ValueError('Saved scalping reference unavailable.')
    trials = []
    for label, mode in [('Candles only', 'candles'), ('EMA confirmation', 'ema'), ('EMA + VWAP', 'ema_vwap')]:
        cfg = ScalpingConfig(**{**reference['config'], 'name':label, 'entry_filter':mode, 'comparison_run_id':reference_id})
        run_id = uuid4().hex[:12]
        log(f'Confirmation comparison: {label}.')
        try:
            run(settings, cfg, log, run_id)
            report = store.read('runs/'+run_id)
            trials.append(dict(label=label, run_id=run_id, status='success', metrics=report['metrics'], evaluation=report['evaluation']))
        except Exception as exc:
            from core.research.jobs import failure_detail
            trials.append(dict(label=label, status='failed', error=str(exc) if isinstance(exc, ValueError) else failure_detail(exc),
                               metrics=dict(return_pct=None, max_drawdown_pct=None, trade_count=None), evaluation={'segments':[]}))
        store.write('scalping_comparisons/'+job_id, dict(id=job_id, reference_id=reference_id, trials=trials))
    baseline = trials[0]['metrics']['return_pct']
    for t in trials:
        value = t['metrics']['return_pct']
        t['delta_return_pct'] = value-baseline if value is not None and baseline is not None else None
    result = dict(id=job_id, reference_id=reference_id, start=reference['config']['start'], end=reference['config']['end'],
                  trials=trials, notice='All three declared variants retained on identical frozen data and costs. Exploratory comparison; no automatic promotion.')
    store.write('scalping_comparisons/'+job_id, result)
    with store.LOCK:
        index = store.read('scalping_comparisons_index', [])
        index.insert(0, result)
        store.write('scalping_comparisons_index', index)
    return {'comparison_id':job_id, 'run_id':next((t['run_id'] for t in trials if t['status']=='success'), None),
            'partial':any(t['status']=='failed' for t in trials)}


def trade_chart(result, trade, sessions):
    cfg = ScalpingConfig(**result['config'])
    daily = store.read('run_data/'+result['id'])
    if not daily or any(digest(daily.get(m['symbol'])) != m['sha256'] for m in result['manifest']):
        raise ValueError('Frozen daily chart inputs are missing or changed.')
    plan = result['selection_plan']
    candidate = next(c for c in plan[trade['entry_date']] if c['symbol'] == trade['symbol'])
    bars, values = features(sessions[trade['symbol']], candidate, trade['entry_date'], cfg)
    series = [dict(id=k, label=label, color=color) for k, label, color in
              [('trigger', 'Pullback breakout', '#c49b44'), ('protective_stop', 'Pullback stop', '#c77565'),
               ('target', 'Profit target', '#2c8c62')]]
    if cfg.entry_filter != 'candles':
        series.extend(dict(id=k, label=label, color=color) for k, label, color in
                      [('ema', 'One-minute pullback EMA', '#5879c6'), ('fast', 'Completed five-minute fast EMA', '#8b65b5'),
                       ('slow', 'Completed five-minute slow EMA', '#7b8b65')])
    if cfg.entry_filter == 'ema_vwap':
        series.append(dict(id='vwap', label='Completed-bar VWAP', color='#4898a8'))
    enriched = []
    for b, f in zip(bars, values):
        context = {k: f[k] for k in ('ema', 'fast', 'slow', 'vwap')}
        # A candle's timestamp is its open: display indicators known at that open.
        previous = enriched[-1]['completed_values'] if enriched else {}
        chart_values = {s['id']: previous.get(s['id']) for s in series if s['id'] in context}
        if trade['signal_timestamp'] <= b['timestamp'] <= trade['exit_timestamp']:
            chart_values['trigger'] = trade['trigger']
        if trade['entry_timestamp'] <= b['timestamp'] <= trade['exit_timestamp']:
            chart_values.update(protective_stop=trade['initial_stop'], target=trade['target'])
        enriched.append(dict(b, chart_values=chart_values, completed_values=context))
    feature = trade['signal_indicators']
    checks = [dict(label='Entry confirmation', actual=cfg.entry_filter, required='Configured candle / EMA / VWAP gates', passed=True),
              dict(label='Signal close / trigger', actual=f"{trade['signal_close']:.2f} / {trade['trigger']:.2f}", required='Directional breakout', passed=True)]
    if cfg.entry_filter != 'candles':
        checks.extend([
            dict(label='Completed five-minute trend EMAs', actual=f"Fast {feature['fast']:.2f}; slow {feature['slow']:.2f}; previous fast {feature['previous_fast']:.2f}",
                 required='Fast above slow and rising for longs; reverse for shorts', passed=True),
            dict(label='One-minute pullback EMA', actual=feature['ema'], required='Pullback touch; signal close returns to trend side', passed=True),
        ])
    if cfg.entry_filter == 'ema_vwap':
        checks.append(dict(label='Completed signal VWAP', actual=feature['vwap'], required='Signal above for longs; below for shorts', passed=True))
    return dict(bars=enriched, explanation=dict(pattern='Scalping pullback continuation',
                entry_mode='Completed one-minute close → next one-minute open', winner_exit='Target / stop / time limit / cutoff',
                candidate_rank='prior_turnover', series=series, signal=dict(date=trade['signal_date'], timestamp=trade['signal_timestamp']),
                checks=checks,
                notices=['Frozen one-minute data. Indicator lines show values known at each bar open; signal values are recorded at its completed close.',
                         'Stop/target fills identify a minute interval; stop first if both are touched.']))
