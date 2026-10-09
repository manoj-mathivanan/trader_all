"""Research-only opening-range momentum; completed-bar signals, next-bar fills."""
import hashlib
import json
import math
from bisect import bisect_left
from datetime import date, datetime, timedelta
from statistics import mean, stdev
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.execution.paper import PaperBrokerAdapter
from core.research import backtest, corporate_actions, data_quality, intraday_data, provenance, store
from core.research.config import BacktestConfig
from core.research import momentum_indicators

SOURCES = [
    {'title': 'A Profitable Day Trading Strategy for the U.S. Equity Market', 'url': 'https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf'},
    {'title': 'QuantConnect: Opening Range Breakout for Stocks in Play', 'url': 'https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/p1'},
    {'title': 'AQR: Time Series Momentum (longer-horizon alternative)', 'url': 'https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum'},
    {'title': 'Upstox historical candles V3', 'url': 'https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/'},
    {'title': 'Linda Raschke: momentum pullbacks across timeframes', 'url': 'https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf'},
    {'title': 'Brian Shannon: multiple timeframes and VWAP', 'url': 'https://alphatrends.net/archives/podcast/secrets-from-30-years-of-day-trading-trader-interview-08-06-23/'},
    {'title': 'Ross Cameron: momentum selection and relative volume', 'url': 'https://www.warriortrading.com/momentum-day-trading-strategy/'},
    {'title': 'Kristjan Kullamägi: catalyst-driven episodic pivots', 'url': 'https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/'},
    {'title': 'Baltussen, Da, Lammers, Martens: late-session momentum', 'url': 'https://academicweb.nd.edu/~zda/intramom.pdf'},
    {'title': 'Heston, Korajczyk, Sadka: intraday patterns and reversals', 'url': 'https://arxiv.org/abs/1005.3535'},
    {'title': 'Warrior Trading: EMA and MACD chart indicators', 'url': 'https://support.warriortrading.com/support/solutions/articles/19000141884-4-chart-indicators-wt'},
    {'title': 'SMB: Fashionably Late Scalp rules', 'url': 'https://www.smbtraining.com/blog/wp-content/uploads/2024/04/The-Fashionably-Late-Scalp-Cheat-Sheet.pdf'},
    {'title': 'StockCharts: MACD histogram definition', 'url': 'https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-histogram'},
]


class MomentumConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    strategy_id: Literal['intraday_momentum'] = 'intraday_momentum'
    name: str = Field('Opening-range momentum', min_length=1, max_length=80, title='Run name')
    start: date = Field(..., title='Test from')
    end: date = Field(..., title='Test through')
    capital: float = Field(1000000, ge=1000, le=1e10, title='Starting capital (₹)')
    direction: Literal['both', 'long', 'short'] = Field('both', title='Signal direction (before reversal)')
    execution_mode: Literal['follow', 'reverse'] = Field('follow', title='Signal execution (follow / reverse)')
    exclude_symbols: list[str] = Field(default_factory=list, max_length=50, title='Explicit research exclusions')
    exclude_stock_sessions: list[str] = Field(default_factory=list, max_length=100, title='Excluded stock sessions (SYMBOL:YYYY-MM-DD)')
    opening_minutes: Literal[5, 10, 15, 30] = Field(5, title='Opening range (minutes)')
    confirmation_minutes: Literal[5, 10, 15, 30, 60] = Field(5, title='Completed breakout candle (minutes)')
    volume_lookback: int = Field(14, ge=5, le=50, title='Opening-volume history (sessions)')
    min_relative_volume: float = Field(1.5, ge=0, le=20, title='Minimum opening relative volume')
    liquidity_days: int = Field(20, ge=5, le=50, title='Prior turnover average (sessions)')
    min_turnover: float = Field(50000000, ge=0, le=1e12, title='Minimum prior average turnover (₹)')
    liquid_universe_size: int = Field(50, ge=1, le=500, title='Most liquid stocks to scan each day')
    atr_days: int = Field(14, ge=5, le=50, title='ATR history (sessions; arithmetic mean TR)')
    min_atr_pct: float = Field(1, ge=0, le=20, title='Minimum prior ATR / close (%)')
    stop_atr: float = Field(0.5, gt=0, le=5, title='Initial stop distance (ATR multiple)')
    target_r: float = Field(0, ge=0, le=20, title='Profit target (R; 0 holds until stop/cutoff)')
    risk_pct: float = Field(0.25, gt=0, le=5, title='Risk budget per trade (%)')
    max_positions: int = Field(5, ge=1, le=50, title='Maximum selected stocks per session')
    last_entry_time: str = Field('11:30', pattern=r'^\d{2}:\d{2}$', title='Last entry bar open (IST)')
    square_off_time: str = Field('15:00', pattern=r'^\d{2}:\d{2}$', title='Mandatory exit bar open (IST)')
    require_vwap: bool = Field(False, title='Require breakout close on the trend side of VWAP')
    breakout_buffer_atr: float = Field(0, ge=0, le=2, title='Breakout buffer (prior ATR multiple)')
    min_close_strength: float = Field(0, ge=0, le=1, title='Minimum trend-side close position (0 disables)')
    min_confirmation_body_atr: float = Field(0, ge=0, le=2, title='Minimum directional confirmation body / prior ATR (0 disables)')
    breakeven_after_r: float = Field(0, ge=0, le=10, title='Move stop to cost breakeven after R (0 disables)')
    indicator_filter: Literal['none', 'ema', 'macd', 'ema_macd'] = Field('none', title='Completed-candle momentum filter')
    indicator_minutes: Literal[10, 60] = Field(10, title='EMA / MACD candle interval (minutes)')
    entry_pattern: Literal['breakout', 'flag'] = Field('breakout', title='Entry pattern')
    stop_reference: Literal['atr', 'pullback'] = Field('atr', title='Initial stop reference')
    require_fundamentals: bool = Field(False, title='Require historical fundamentals before entry')
    fundamental_min_score: float = Field(60, ge=0, le=100, title='Minimum fundamental score')
    fundamental_min_coverage_pct: float = Field(80, ge=0, le=100, title='Minimum fundamental evidence coverage (%)')
    fundamental_max_age_days: int = Field(180, ge=1, le=730, title='Maximum financial period age (days)')
    comparison_run_id: str | None = Field(None, pattern=r'^[0-9a-f]{12}$', title='Frozen input reference')
    slippage_bps: float = Field(10, ge=0, le=500, title='Slippage per side (bps)')
    buy_cost_bps: float = Field(10, ge=0, le=500, title='All-in buy charges (bps)')
    sell_cost_bps: float = Field(10, ge=0, le=500, title='All-in sell charges (bps)')
    acknowledge_limitations: bool = Field(False, title='I understand this is an exploratory backtest')

    @model_validator(mode='after')
    def rules(self):
        for item in self.exclude_stock_sessions:
            try:
                symbol, day = item.rsplit(':', 1)
                if not symbol or date.fromisoformat(day).isoformat() != day:
                    raise ValueError()
            except ValueError:
                raise ValueError('Excluded stock sessions must use SYMBOL:YYYY-MM-DD.') from None
        if self.start >= self.end or self.start < date(2022, 4, 1):
            raise ValueError('Choose increasing dates from April 2022 onward (Upstox minute history plus warmup).')
        today = datetime.now(intraday_data.IST).date()
        if self.end >= today:
            raise ValueError('Momentum backtests use completed sessions before today in IST.')
        def minutes(value):
            h, m = map(int, value.split(':'))
            if h > 23 or m > 59 or m % 5:
                raise ValueError('Times must be valid five-minute boundaries in IST.')
            return h * 60 + m
        last, cutoff = minutes(self.last_entry_time), minutes(self.square_off_time)
        if not 555 + self.opening_minutes + 5 <= last < cutoff <= 920:
            raise ValueError('Last entry must follow a completed breakout bar; exit must follow entry and be no later than 15:20 IST.')
        earliest = 555 + math.ceil((self.opening_minutes+5)/self.confirmation_minutes)*self.confirmation_minutes
        if last < earliest:
            raise ValueError('Last entry precedes the first completed confirmation candle after the opening range.')
        if self.max_positions > self.liquid_universe_size:
            raise ValueError('Selected stocks cannot exceed the liquid universe size.')
        if self.indicator_minutes == 60 and self.indicator_filter in ('macd', 'ema_macd') and self.volume_lookback < 20:
            raise ValueError('Hourly MACD needs at least 20 prior sessions for its 100-candle warmup.')
        if self.stop_reference == 'pullback' and self.entry_pattern != 'flag':
            raise ValueError('A pullback stop requires the flag entry pattern.')
        if not self.acknowledge_limitations:
            raise ValueError('Acknowledge research limitations before running.')
        return self


def prepare(settings, cfg):
    if cfg.comparison_run_id:
        reference = store.read('runs/'+cfg.comparison_run_id)
        datasets = store.read('run_data/'+cfg.comparison_run_id)
        if not reference or reference.get('strategy_id') != 'intraday_momentum' or not datasets:
            raise ValueError('Choose a saved momentum run with its frozen input snapshot.')
        if settings.universe != reference['universe']:
            raise ValueError('Select the reference momentum universe before comparing.')
        if str(cfg.start)<reference['config']['start'] or str(cfg.end)>reference['config']['end']:
            raise ValueError('Comparison dates must stay within the frozen reference window.')
        needed = max(cfg.volume_lookback,cfg.liquidity_days,cfg.atr_days+1)
        if any(sum(b['date']<str(cfg.start) for b in rows)<needed for rows in datasets.values()):
            raise ValueError('Frozen daily inputs lack the requested warmup. Start a new data-fetch experiment or shorten the lookback.')
        for item in reference['manifest']:
            rows = datasets.get(item['symbol'])
            if rows is None or hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()!=item['sha256']:
                raise ValueError('Frozen daily input hash changed; comparison halted.')
        return exclude_inputs(reference['universe_snapshot'], datasets, reference['manifest'], reference.get('excluded', []), cfg)
    # Reuse daily coverage, listing evidence and universe validation, without swing signals.
    proxy = BacktestConfig(start=cfg.start, end=cfg.end, acknowledge_limitations=True)
    universe, datasets, manifest, excluded = backtest.prepare(settings, proxy)
    context = max(cfg.volume_lookback, cfg.liquidity_days, cfg.atr_days) + 2
    trimmed = {}
    for symbol, rows in datasets.items():
        days = [b['date'] for b in rows]
        first = bisect_left(days, str(cfg.start))
        trimmed[symbol] = rows[max(0, first-context):bisect_left(days, str(cfg.end))+1]
        trimmed[symbol] = [b for b in trimmed[symbol] if b['date'] <= str(cfg.end)]
        if trimmed[symbol] and corporate_actions.actions(rows):
            trimmed[symbol][0] = dict(trimmed[symbol][0], corporate_actions=corporate_actions.actions(rows))
    manifest = [{**m, 'source_sha256':m['sha256'], 'bars':len(trimmed[m['symbol']]),
                 'first':trimmed[m['symbol']][0]['date'], 'last':trimmed[m['symbol']][-1]['date'],
                 'sha256':hashlib.sha256(json.dumps(trimmed[m['symbol']],sort_keys=True).encode()).hexdigest()}
                for m in manifest if trimmed[m['symbol']]]
    return exclude_inputs(universe, trimmed, manifest, excluded, cfg)


def exclude_inputs(universe, datasets, manifest, excluded, cfg):
    """Explicit per-experiment exclusions; never modify the universe/cache."""
    omit = set(cfg.exclude_symbols)
    known = {item['symbol'] for item in universe['instruments']}
    session_symbols = {item.rsplit(':', 1)[0] for item in cfg.exclude_stock_sessions}
    if (omit | session_symbols) - known:
        raise ValueError('Unknown research exclusions: ' + ', '.join(sorted((omit | session_symbols)-known)))
    datasets = {symbol: rows for symbol, rows in datasets.items() if symbol not in omit}
    if not datasets:
        raise ValueError('Research exclusions leave no eligible daily inputs.')
    return universe, datasets, [m for m in manifest if m['symbol'] not in omit], sorted(set(excluded) | omit)


def entry_plan(datasets, cfg):
    """Only prior daily bars decide liquidity/ATR; request OR-volume context too."""
    plan, requests = {}, {}
    omitted_sessions = set(cfg.exclude_stock_sessions)
    for day in sorted({b['date'] for rows in datasets.values() for b in rows if str(cfg.start) <= b['date'] <= str(cfg.end)}):
        if day in intraday_data.SPECIAL_SESSIONS:
            continue
        eligible = []
        for symbol, rows in datasets.items():
            i = bisect_left([b['date'] for b in rows], day)
            n = max(cfg.atr_days+1, cfg.liquidity_days, cfg.volume_lookback)
            if i < n or i >= len(rows) or rows[i]['date'] != day:
                continue
            prior = corporate_actions.adjusted_bars(rows[:i], day)
            turnover = mean(b['close']*b['volume'] for b in prior[-cfg.liquidity_days:])
            ranges = [max(prior[j]['high']-prior[j]['low'], abs(prior[j]['high']-prior[j-1]['close']), abs(prior[j]['low']-prior[j-1]['close'])) for j in range(len(prior)-cfg.atr_days, len(prior))]
            atr = mean(ranges)
            if turnover < cfg.min_turnover or atr <= 0 or atr/prior[-1]['close']*100 < cfg.min_atr_pct:
                continue
            history = [b['date'] for b in prior[-cfg.volume_lookback:]]
            if any(f'{symbol}:{d}' in omitted_sessions for d in [day, *history]):
                continue  # Explicit missing-open input; no substitute or invented volume.
            if any(d in intraday_data.SPECIAL_SESSIONS for d in history):
                continue  # Same-clock relative volume requires comparable regular openings.
            eligible.append(dict(symbol=symbol, atr=atr, turnover=turnover, history=history,
                                 daily_open=rows[i]['open'], actions=corporate_actions.actions(rows)))
        plan[day] = sorted(eligible, key=lambda x: (-x['turnover'], x['symbol']))[:cfg.liquid_universe_size]
        for candidate in plan[day]:
            for d in [day, *candidate['history']]:
                requests.setdefault(d, []).append({'symbol': candidate['symbol']})
    return plan, requests


def opening(bars, cfg):
    count = cfg.opening_minutes//5
    regular = intraday_data.trading_bars(bars, f'{(555+cfg.opening_minutes-5)//60:02d}:{(555+cfg.opening_minutes-5)%60:02d}')
    return dict(high=max(b['high'] for b in regular[:count]), low=min(b['low'] for b in regular[:count]),
                open=regular[0]['open'], close=regular[count-1]['close'], volume=sum(b['volume'] for b in regular[:count]))


def session_vwap(bars):
    """Completed-bar typical-price VWAP; never include later candles."""
    notional = volume = 0
    result = []
    for b in bars:
        notional += (b['high']+b['low']+b['close'])/3*b['volume']
        volume += b['volume']
        result.append(notional/volume if volume else None)
    return result


def confirmation_quality(bars, last, minutes, sign, atr):
    """Only the completed session-aligned candle's constituents describe strength."""
    count = minutes//5
    rows = bars[last-count+1:last+1]
    if len(rows) != count or (last+1) % count:
        raise ValueError('Confirmation quality requires a complete aligned candle.')
    high, low, close = max(b['high'] for b in rows), min(b['low'] for b in rows), rows[-1]['close']
    strength = ((close-low) if sign==1 else (high-close))/(high-low) if high>low else 0
    return dict(open=rows[0]['open'],high=high,low=low,close=close,
                close_strength=strength,body_atr=sign*(close-rows[0]['open'])/atr)


def flag_quality(bars, last, minutes, sign, atr, rejection_reasons=None):
    """Fixed two-candle pullback after an impulse, then completed resumption."""
    def reject(reason):
        if rejection_reasons is not None:
            rejection_reasons[reason] = rejection_reasons.get(reason,0)+1
        return None
    if (last+1) % (minutes//5):
        return reject('unfinished_candle')
    candles = momentum_indicators.aggregate(bars[:last+1], minutes)
    if len(candles) < 4:
        return reject('insufficient_current_session_candles')
    impulse, first, second, resume = candles[-4:]
    body = sign*(impulse['close']-impulse['open'])
    if body < .25*atr:
        return reject('impulse_below_quarter_atr')
    if any(sign*(b['close']-b['open']) >= 0 for b in (first,second)):
        return reject('not_two_adverse_candles')
    if sign*(second['close']-first['close']) >= 0:
        return reject('pullback_closes_not_declining')
    extreme = min(first['low'],second['low']) if sign==1 else max(first['high'],second['high'])
    retracement = sign*(impulse['close']-extreme)
    if not 0 < retracement <= .5*body:
        return reject('retracement_outside_zero_to_half_impulse_body')
    level = max(first['high'],second['high']) if sign==1 else min(first['low'],second['low'])
    if sign*(resume['close']-resume['open']) <= 0 or sign*(resume['close']-level) <= 0:
        return reject('no_directional_resumption_beyond_pullback')
    return dict(impulse_body_atr=body/atr,retracement_fraction=retracement/body,
                pullback_extreme=extreme,resumption_level=level,pullback_candles=2)


def fundamental_gate(value, cfg):
    reasons = []
    if not value or value.get('score') is None:
        reasons.append('Missing historical fundamentals')
    else:
        if value['score'] < cfg.fundamental_min_score:
            reasons.append('Score below threshold')
        if value.get('coverage_pct',0) < cfg.fundamental_min_coverage_pct:
            reasons.append('Evidence coverage below threshold')
        if value.get('period_age_days') is None or value['period_age_days'] > cfg.fundamental_max_age_days:
            reasons.append('Financial period stale or unknown')
        # Freshness is enforced by this experiment's explicit age threshold.
        # Preserve risk flags, but do not let the scorer's default 180-day
        # warning silently override a user-requested longer maximum age.
        reasons.extend(flag for flag in value.get('flags',[])
                       if flag != 'Financial period is more than 180 days old')
    return dict(**(value or {}),allowed=not reasons,block_reasons=reasons)


def simulate(datasets, cfg, sessions, plan=None, *, entry_check=None, fundamental_scores=None):
    if cfg.require_fundamentals and fundamental_scores is None:
        raise ValueError('Historical fundamental evidence is required; current scores cannot substitute.')
    plan = entry_plan(datasets, cfg)[0] if plan is None else plan
    broker = PaperBrokerAdapter(cfg)
    cash = peak = cfg.capital
    max_dd = fees_total = slip_total = skipped = ambiguous = 0
    trades, curve, selections = [], [], []
    no_breakout = no_quantity = vwap_rejections = quality_rejections = indicator_rejections = pattern_rejections = 0
    pattern_rejection_reasons = {}
    fundamental_checks = []
    for day in sorted({b['date'] for rows in datasets.values() for b in rows if str(cfg.start) <= b['date'] <= str(cfg.end)}):
        candidates = []
        for c in plan.get(day, []):
            symbol = c['symbol']
            try:
                bars = intraday_data.trading_bars(sessions[symbol][day], cfg.square_off_time)
                op = opening(bars, cfg)
                volumes = []
                for h in c['history']:
                    v = opening(sessions[symbol][h], cfg)['volume']
                    for action in c['actions']:
                        if h < action['ex_date'] <= day and action['volume_basis'] == 'raw':
                            v *= action['share_factor']
                    volumes.append(v)
            except (KeyError, ValueError) as exc:
                raise ValueError(f'Incomplete momentum inputs for {symbol} on {day}: {exc}') from None
            if abs(op['open']/c['daily_open']-1) >= .35:
                raise ValueError(f'Intraday/daily price units disagree for {symbol} on {day}.')
            rv = op['volume']/mean(volumes) if mean(volumes)>0 else 0
            side = 'long' if op['close']>op['open'] else 'short' if op['close']<op['open'] else None
            if side and rv >= cfg.min_relative_volume and cfg.direction in ('both', side):
                candidates.append({**c, 'bars': bars, 'opening': op, 'relative_volume': rv, 'direction': side})
        candidates.sort(key=lambda c: (-c['relative_volume'], c['symbol']))
        skipped += max(0, len(candidates)-cfg.max_positions)
        selected = candidates[:cfg.max_positions]
        selections.append(dict(date=day, liquid_candidates=len(plan.get(day, [])), volume_qualified=len(candidates),
                               selected=[dict(symbol=c['symbol'], relative_volume=c['relative_volume'], direction=c['direction']) for c in selected]))
        # Reserve equal notional budgets at range completion. No same-day capital recycling.
        equity = cash
        day_pnl = 0
        for c in selected:
            bars, op, direction = c['bars'], c['opening'], c['direction']
            signal_direction = direction
            sign = 1 if direction=='long' else -1
            trigger = (op['high'] if sign==1 else op['low'])+sign*cfg.breakout_buffer_atr*c['atr']
            vwap = session_vwap(bars)
            indicators = momentum_indicators.features(sessions[c['symbol']], c, day, bars,
                cfg.indicator_minutes, cfg.indicator_filter) if cfg.indicator_filter != 'none' else {}
            idx = None
            pattern = None
            for j in range(cfg.opening_minutes//5, len(bars)-1):
                if bars[j+1]['time']>cfg.last_entry_time:
                    break
                # Session-aligned larger candle closes. Its final five-minute close
                # is the aggregate close; no unfinished higher-timeframe candle.
                if (j+1) % (cfg.confirmation_minutes//5):
                    continue
                if sign*(bars[j]['close']-trigger)>0:
                    if cfg.entry_pattern == 'flag':
                        pattern = flag_quality(bars,j,cfg.confirmation_minutes,sign,c['atr'],pattern_rejection_reasons)
                        if pattern is None:
                            pattern_rejections += 1
                            continue
                    if cfg.indicator_filter != 'none' and not momentum_indicators.accepts(indicators[j], sign, cfg.indicator_filter):
                        indicator_rejections += 1
                        continue
                    if cfg.require_vwap and (vwap[j] is None or sign*(bars[j]['close']-vwap[j])<=0):
                        vwap_rejections += 1
                        continue
                    quality = confirmation_quality(bars,j,cfg.confirmation_minutes,sign,c['atr'])
                    if ((cfg.min_close_strength and quality['close_strength']<cfg.min_close_strength) or
                        (cfg.min_confirmation_body_atr and quality['body_atr']<cfg.min_confirmation_body_atr)):
                        quality_rejections += 1
                        continue
                    idx = j+1
                    break
            if idx is None:
                no_breakout += 1
                continue
            signal_sign = sign
            if cfg.execution_mode == 'reverse':
                sign = -sign
                direction = 'long' if sign == 1 else 'short'
            fundamental_check = None
            if cfg.require_fundamentals:
                fundamental_check = fundamental_gate(fundamental_scores(c['symbol'],day,bars[idx]['time']),cfg)
                fundamental_checks.append(dict(symbol=c['symbol'],date=day,time=bars[idx]['time'],direction=direction,**fundamental_check))
                if not fundamental_check['allowed']:
                    skipped += 1
                    continue
            if sign == 1 and entry_check is not None and not entry_check(c['symbol'],day,bars[idx]['time']):
                skipped += 1
                continue
            raw_entry = bars[idx]['open']
            fill = broker.fill(raw_entry, 1, 'buy' if sign==1 else 'sell')['price']
            # Reverse execution preserves signal detection, then mirrors the
            # protective distance onto the adverse side of the actual position.
            stop = (fill-sign*signal_sign*(fill-pattern['pullback_extreme'])
                    if cfg.stop_reference == 'pullback' else fill-sign*cfg.stop_atr*c['atr'])
            distance = sign*(fill-stop)
            if stop <= 0 or distance <= 0:
                skipped += 1
                continue
            fee_rate = (cfg.buy_cost_bps if sign==1 else cfg.sell_cost_bps)/10000
            exit_rate = (cfg.sell_cost_bps if sign==1 else cfg.buy_cost_bps)/10000
            unit_risk = distance+fill*fee_rate+stop*(exit_rate+cfg.slippage_bps/10000)
            qty = max(0, min(math.floor(max(0,equity)*cfg.risk_pct/100/unit_risk),
                             math.floor(max(0,equity)/cfg.max_positions/(fill*(1+fee_rate)))))
            if not qty:
                skipped += 1
                no_quantity += 1
                continue
            entry = broker.fill(raw_entry, qty, 'buy' if sign==1 else 'sell')
            target = fill+sign*distance*cfg.target_r if cfg.target_r else None
            if target is not None and target <= 0:
                raise ValueError('Profit target has a non-positive price; reduce the R target.')
            initial_stop = stop
            trace, exit_bar, raw_exit, reason = [], bars[-1], bars[-1]['open'], 'Mandatory intraday square-off'
            for b in bars[idx:]:
                trace.append(dict(timestamp=b['timestamp'], date=day, time=b['time'], stop=stop))
                if b['time']==cfg.square_off_time:
                    break
                if sign*(b['open']-stop)<=0:
                    exit_bar, raw_exit, reason = b, b['open'], 'Gap through pullback stop' if cfg.stop_reference=='pullback' else 'Gap through ATR stop'
                    break
                if target is not None and sign*(b['open']-target)>=0:
                    exit_bar, raw_exit, reason = b, b['open'], 'Profit target'
                    break
                stop_hit = b['low']<=stop if sign==1 else b['high']>=stop
                target_hit = target is not None and (b['high']>=target if sign==1 else b['low']<=target)
                if stop_hit:
                    ambiguous += bool(target_hit)
                    exit_bar, raw_exit, reason = b, stop, 'Pullback stop loss' if cfg.stop_reference=='pullback' else 'ATR stop loss'
                    break
                if target_hit:
                    exit_bar, raw_exit, reason = b, target, 'Profit target'
                    break
                if cfg.breakeven_after_r and sign*(b['close']-fill)>=distance*cfg.breakeven_after_r:
                    slip = cfg.slippage_bps/10000
                    breakeven = fill*(1+fee_rate)/(1-exit_rate)/(1-slip) if sign==1 else fill*(1-fee_rate)/(1+exit_rate)/(1+slip)
                    stop = max(stop, breakeven) if sign==1 else min(stop, breakeven)
            exit_fill = broker.fill(raw_exit, qty, 'sell' if sign==1 else 'buy')
            fees = entry['fees']+exit_fill['fees']
            pnl = sign*qty*(exit_fill['price']-fill)-fees
            day_pnl += pnl
            fees_total += fees
            slip_total += entry['slippage']+exit_fill['slippage']
            trades.append(dict(symbol=c['symbol'], direction=direction, signal_direction=signal_direction,
                               execution_mode=cfg.execution_mode, execution_horizon='intraday',
                               signal_date=day, signal_time=bars[idx-1]['time'], signal_timestamp=bars[idx-1]['timestamp'],
                               entry_date=day, exit_date=day, entry_time=bars[idx]['time'], exit_time=exit_bar['time'],
                               entry_timestamp=bars[idx]['timestamp'], exit_timestamp=exit_bar['timestamp'],
                               entry=fill, exit=exit_fill['price'], quantity=qty, exit_quantity=qty,
                               pnl=pnl, r=pnl/(qty*distance), reason=reason, fees=fees, borrow_cost=0,
                               trigger=trigger, initial_stop=initial_stop, target=target, atr=c['atr'],
                               signal_vwap=vwap[idx-1], signal_close=bars[idx-1]['close'],
                               signal_indicators=indicators.get(idx-1),
                               signal_pattern=pattern,
                               fundamentals=fundamental_check,
                               confirmation_quality=confirmation_quality(bars,idx-1,cfg.confirmation_minutes,signal_sign,c['atr']),
                               relative_volume=c['relative_volume'], opening_high=op['high'], opening_low=op['low'],
                               stop_trace=trace, exit_time_precision='cutoff bar open' if reason=='Mandatory intraday square-off' else 'five-minute candle'))
        cash += day_pnl
        peak = max(peak, cash)
        dd = (peak-cash)/peak*100
        max_dd = max(max_dd, dd)
        curve.append(dict(date=day, equity=round(cash,2), drawdown_pct=dd))
    if not curve:
        raise ValueError('No sessions in the momentum test window.')
    wins, losses = [t for t in trades if t['pnl']>0], [t for t in trades if t['pnl']<0]
    equities = [cfg.capital, *[c['equity'] for c in curve]]
    returns = [b/a-1 for a,b in zip(equities,equities[1:]) if a>0]
    diagnostics = dict(session_count=len(curve), no_breakout=no_breakout, no_quantity=no_quantity,
                       vwap_rejected_signals=vwap_rejections,
                       quality_rejected_signals=quality_rejections,
                       indicator_rejected_signals=indicator_rejections,
                       pattern_rejected_signals=pattern_rejections,
                       pattern_rejection_reasons=pattern_rejection_reasons,
                       fundamental_checks=fundamental_checks,
                       fundamental_rejected_entries=sum(not c['allowed'] for c in fundamental_checks),
                       fundamental_missing_entries=sum(c.get('score') is None for c in fundamental_checks),
                       long=trade_summary([t for t in trades if t['direction']=='long']),
                       short=trade_summary([t for t in trades if t['direction']=='short']),
                       cost_impact=fees_total+slip_total,
                       pnl_before_modeled_cost_impact=sum(t['pnl'] for t in trades)+fees_total+slip_total)
    return dict(trades=trades, curve=curve, selections=selections, diagnostics=diagnostics,
                metrics=dict(initial_capital=cfg.capital, final_equity=cash, return_pct=(cash/cfg.capital-1)*100,
                             max_drawdown_pct=max_dd, trade_count=len(trades),
                             win_rate=len(wins)/len(trades)*100 if trades else None,
                             expectancy_r=mean(t['r'] for t in trades) if trades else None,
                             profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
                             sharpe=mean(returns)/stdev(returns)*math.sqrt(252) if len(returns)>1 and stdev(returns)>0 else None,
                             modeled_fees=fees_total, modeled_slippage=slip_total, modeled_borrow_costs=0,
                             skipped_entries=skipped, ambiguous_stop_target_bars=ambiguous, overnight_positions=0,
                             long_trades=sum(t['direction']=='long' for t in trades), short_trades=sum(t['direction']=='short' for t in trades),
                             drawdown_basis='session-end equity'))


def run(settings, cfg, log, job_id, *, fundamental_evidence=None):
    universe, datasets, manifest, excluded = prepare(settings, cfg)
    quality = data_quality.audit(datasets, end=cfg.end)
    data_quality.require_no_anomalies(quality)
    plan, requests = entry_plan(datasets, cfg)
    log(f'Momentum: {len(datasets)} daily symbols; scan up to {cfg.liquid_universe_size} per day ranked by prior turnover.')
    if cfg.comparison_run_id:
        sessions = store.read('run_intraday/'+cfg.comparison_run_id, {})
        if not sessions:
            raise ValueError('Frozen minute inputs are unavailable; comparison will not download substitutes.')
        reference = store.read('runs/'+cfg.comparison_run_id)
        expected = reference.get('intraday_source',{}).get('sha256')
        if expected and hashlib.sha256(json.dumps(sessions,sort_keys=True).encode()).hexdigest()!=expected:
            raise ValueError('Frozen minute input hash changed; comparison halted.')
        log('Using frozen daily, minute and universe snapshots; no current-data substitute or download.')
    else:
        sessions = intraday_data.load_ranges(requests, universe, log)
    fundamental_scores = None
    if cfg.require_fundamentals or fundamental_evidence is not None:
        from core.research import fundamental_history
        if fundamental_evidence is None and cfg.comparison_run_id:
            frozen = store.read('runs/'+cfg.comparison_run_id,{}).get('fundamental_reference')
            if frozen:
                fundamental_evidence = store.read('run_fundamentals/'+cfg.comparison_run_id)
                if not fundamental_evidence or fundamental_evidence.get('sha256') != frozen['sha256']:
                    raise ValueError('Frozen fundamental evidence is missing or changed.')
        if fundamental_evidence is None:
            fundamental_evidence = fundamental_history.capture(universe,log)
        scores = fundamental_history.Scores(fundamental_evidence)
        def fundamental_scores(symbol,day,time):
            return scores(symbol,day,at=datetime.fromisoformat(day+'T'+time+':00+05:30'))
    result = simulate(datasets, cfg, sessions, plan, fundamental_scores=fundamental_scores)
    result.update(id=job_id, strategy_id='intraday_momentum', created_at=store.now(), config=cfg.model_dump(mode='json'),
                  universe=settings.universe, universe_snapshot=universe, manifest=manifest, excluded=excluded,
                  provenance=provenance.capture(), data_quality=quality, research_sources=SOURCES,
                  intraday_source=dict(provider='Upstox historical V3', interval_minutes=5, timezone='Asia/Kolkata',
                                       stock_sessions=sum(len(s) for s in sessions.values()),
                                       sha256=hashlib.sha256(json.dumps(sessions, sort_keys=True).encode()).hexdigest()),
                  warnings=[
                      'India adaptation, not a reproduction of published US returns or a proven best strategy.',
                      'Current constituents only; survivorship bias and unverified corporate-action adjustments remain.',
                      'Liquidity/ATR use prior sessions. Relative volume uses the same opening interval from prior sessions only.',
                      f'Entry requires a completed {cfg.confirmation_minutes}-minute session-aligned close beyond the range, filled at the next five-minute open; differs from the paper stop-entry rule.',
                      'ATR is an arithmetic mean of prior true ranges. Parameters and rupee liquidity thresholds are research choices, not optimized results.',
                      'Equal capital budgets reserved at range completion, no leverage or same-day capital recycling; shorts reserve full notional and fees.',
                      'One trade per selected stock per session. Stops and targets in the same bar assume stop first.',
                      'Stops use candle intervals, not exact tick times. Cutoff fills use its open without future prices.',
                      'Costs are user assumptions. Short eligibility, circuits, participation, stock borrow and actual fills are not verified.',
                      'Sharpe assumes 252 sessions and zero risk-free return. Drawdown uses session-end equity; intraday drawdown can be larger.',
                      'Exploratory sample: reserve untouched dates and test costs/parameter sensitivity before judging an edge.',
                  ])
    if cfg.comparison_run_id:
        result['comparison'] = dict(run_id=cfg.comparison_run_id, source='frozen_momentum_snapshot')
    if cfg.execution_mode == 'reverse':
        result['warnings'].append('Reverse experiment: original selection, breakout and filters determine signals; execution takes the opposite side at the same next-bar open. Stops/targets and costs use the actual position side. Direction selection refers to the original signal side; pullback stop distances are mirrored around the fill.')
    if cfg.exclude_symbols:
        result['warnings'].append('Explicit research exclusions applied before daily liquidity selection: ' + ', '.join(cfg.exclude_symbols) + '. Exclusions chosen after data inspection can bias results; this is a reduced-universe experiment.')
    if cfg.exclude_stock_sessions:
        result['warnings'].append('Explicit stock-session exclusions: ' + ', '.join(cfg.exclude_stock_sessions) + '. Candidates also skip dates whose opening-volume lookback uses an excluded session. This data-availability policy can bias results.')
    result['warnings'].extend([
        'VWAP uses cumulative typical-price × volume from completed five-minute candles, not tick-level VWAP.',
        'Optional breakeven stops update only after a completed close and become active next bar. Gaps can still lose money.',
        'Before-cost P&L is an attribution on the actual filled trades, not a separate zero-cost simulation; costs also affect sizing.',
        'Optional close-position and directional-body filters use complete confirmation candles and prior daily ATR; they do not guarantee continuation.',
        'Optional EMA9/20 and MACD12/26/9 use completed session-aligned 10/60-minute candles with prior-session SMA-seeded warmup. Warmup regular bars end at 15:00; partial terminal bins are discarded. Corporate-action crossings halt indicator tests pending independent intraday basis verification.',
        'Optional flag entries require a directional impulse >=0.25 prior ATR, exactly two adverse candles retracing at most half its body, then a completed close beyond the pullback extremes and opening trigger. This is a mechanical adaptation, not a reproduction of discretionary practitioner trades.',
    ])
    result['evaluation'] = chronological_evaluation(result)
    if fundamental_evidence is not None:
        store.write('run_fundamentals/'+job_id,fundamental_evidence)
        result['fundamental_reference'] = {k:fundamental_evidence[k] for k in ('sha256','captured_at','method','notice')}
        result['warnings'].append('Historical fundamentals reconstructed from verified archived filings published by the exact entry time. Missing, insufficient-coverage, stale or flagged evidence blocks both long and short entries. The same quality screen on shorts is an experimental universe filter, not a bearish valuation thesis. Selection is unchanged and blocked slots are not backfilled.')
        result['warnings'].append(fundamental_evidence['notice'])
    store.write('run_data/'+job_id, datasets)
    store.write('run_intraday/'+job_id, sessions)
    store.write('runs/'+job_id, result)
    with store.LOCK:
        runs = store.read('runs_index', [])
        runs.insert(0, {k:result[k] for k in ('id','created_at','strategy_id','config','universe','metrics')})
        store.write('runs_index', runs)
    log(f"Recorded {len(result['trades'])} momentum trades; net return {result['metrics']['return_pct']:.2f}%.")
    return {'run_id':job_id}


def trade_summary(trades):
    return dict(trade_count=len(trades), pnl=sum(t['pnl'] for t in trades), fees=sum(t['fees'] for t in trades),
                win_rate=sum(t['pnl']>0 for t in trades)/len(trades)*100 if trades else None,
                expectancy_r=mean(t['r'] for t in trades) if trades else None)


def chronological_evaluation(result):
    curve = result['curve']
    split = max(1, min(len(curve)-1, len(curve)*2//3))
    segments = []
    equity = result['metrics']['initial_capital']
    for name, rows in [('Earlier sample',curve[:split]), ('Later sample',curve[split:])]:
        if not rows:
            continue
        peak = equity
        dd = 0
        for row in rows:
            peak = max(peak,row['equity'])
            dd = max(dd,(peak-row['equity'])/peak*100)
        trades = [t for t in result['trades'] if rows[0]['date']<=t['entry_date']<=rows[-1]['date']]
        segments.append(dict(name=name,start=rows[0]['date'],end=rows[-1]['date'],sessions=len(rows),
                             return_pct=(rows[-1]['equity']/equity-1)*100 if equity>0 else None,
                             max_drawdown_pct=dd, **trade_summary(trades)))
        equity = rows[-1]['equity']
    return dict(segments=segments, notice='Chronological 2/3–1/3 diagnostic only. Both segments of this short known window are exploratory, not an untouched holdout or proof of an edge.')


REFINEMENTS = [
    ('Baseline replay', {}),
    ('VWAP confirmation', {'require_vwap':True}),
    ('VWAP + 0.1 ATR buffer', {'require_vwap':True,'breakout_buffer_atr':0.1}),
    ('VWAP + breakeven at 1R', {'require_vwap':True,'breakeven_after_r':1}),
    ('VWAP + 0.75 ATR stop', {'require_vwap':True,'stop_atr':0.75}),
    ('VWAP + 2R target', {'require_vwap':True,'target_r':2}),
]

# Declared before reviewing these results. One-factor tests, not a parameter grid.
RESEARCH_IDEAS = [
    ('Baseline replay', {}),
    ('10-minute confirmation', {'confirmation_minutes':10}),
    ('Hourly confirmation', {'confirmation_minutes':60}),
    ('10-minute opening range', {'opening_minutes':10}),
    ('15-minute opening range', {'opening_minutes':15}),
    ('30-minute opening range', {'opening_minutes':30}),
    ('Opening relative volume >= 2', {'min_relative_volume':2}),
    ('Opening relative volume >= 3', {'min_relative_volume':3}),
    ('Entries through 10:00', {'last_entry_time':'10:00'}),
    ('Long only', {'direction':'long'}),
    ('Short only', {'direction':'short'}),
    ('0.1 ATR breakout buffer', {'breakout_buffer_atr':0.1}),
]

STRONGER_IDEAS = [
    ('Baseline replay', {}),
    ('Hourly control', {'confirmation_minutes':60}),
    ('Hourly + VWAP', {'confirmation_minutes':60,'require_vwap':True}),
    ('Hourly + 0.1 ATR buffer', {'confirmation_minutes':60,'breakout_buffer_atr':0.1}),
    ('Hourly + close in trend-side 30%', {'confirmation_minutes':60,'min_close_strength':0.7}),
    ('Hourly + directional body >= 0.1 ATR', {'confirmation_minutes':60,'min_confirmation_body_atr':0.1}),
    ('Stronger hourly confirmation', {'confirmation_minutes':60,'require_vwap':True,'breakout_buffer_atr':0.1,
                                      'min_close_strength':0.7,'min_confirmation_body_atr':0.1}),
]

INDICATOR_IDEAS = [
    ('Baseline replay', {}),
    ('10-minute buffered control', {'confirmation_minutes':10, 'breakout_buffer_atr':0.1, 'indicator_filter':'none'}),
    ('10-minute EMA9/20 trend', {'confirmation_minutes':10, 'breakout_buffer_atr':0.1, 'indicator_filter':'ema', 'indicator_minutes':10}),
    ('10-minute MACD momentum', {'confirmation_minutes':10, 'breakout_buffer_atr':0.1, 'indicator_filter':'macd', 'indicator_minutes':10}),
    ('10-minute EMA and MACD', {'confirmation_minutes':10, 'breakout_buffer_atr':0.1, 'indicator_filter':'ema_macd', 'indicator_minutes':10}),
    ('Hourly buffered control', {'confirmation_minutes':60, 'breakout_buffer_atr':0.1, 'indicator_filter':'none'}),
    ('Hourly EMA9/20 trend', {'confirmation_minutes':60, 'breakout_buffer_atr':0.1, 'indicator_filter':'ema', 'indicator_minutes':60}),
]


PULLBACK_IDEAS = [
    ('Baseline replay', {}),
    ('10-minute buffered control', {'confirmation_minutes':10,'breakout_buffer_atr':0.1}),
    ('Flag resumption with ATR stop', {'confirmation_minutes':10,'breakout_buffer_atr':0.1,'entry_pattern':'flag'}),
    ('Flag resumption with pullback stop', {'confirmation_minutes':10,'breakout_buffer_atr':0.1,'entry_pattern':'flag','stop_reference':'pullback'}),
    ('Flag with pullback stop and 2R target', {'confirmation_minutes':10,'breakout_buffer_atr':0.1,'entry_pattern':'flag','stop_reference':'pullback','target_r':2}),
    ('Flag + EMA with 2R target', {'confirmation_minutes':10,'breakout_buffer_atr':0.1,'entry_pattern':'flag','stop_reference':'pullback','target_r':2,'indicator_filter':'ema','indicator_minutes':10}),
    ('Flag + relative volume 2 with 2R target', {'confirmation_minutes':10,'breakout_buffer_atr':0.1,'entry_pattern':'flag','stop_reference':'pullback','target_r':2,'min_relative_volume':2}),
]


FUNDAMENTAL_IDEAS = [
    ('Matched control without fundamentals', {'require_fundamentals':False}),
    ('Historical fundamental quality before entry', {'require_fundamentals':True}),
]


def compare(settings, reference_id, log, job_id, suite='refinements'):
    """Predeclared refinements on identical frozen inputs and cost assumptions."""
    from uuid import uuid4
    reference = store.read('runs/'+reference_id)
    if not reference or reference.get('strategy_id')!='intraday_momentum':
        raise ValueError('Saved momentum reference unavailable.')
    suites = {'refinements':REFINEMENTS, 'research':RESEARCH_IDEAS, 'stronger':STRONGER_IDEAS, 'indicators':INDICATOR_IDEAS, 'pullbacks':PULLBACK_IDEAS, 'fundamentals':FUNDAMENTAL_IDEAS}
    if suite not in suites:
        raise ValueError('Unknown momentum comparison suite.')
    variants = suites[suite]
    fundamental_evidence = None
    if suite == 'fundamentals':
        from core.research import fundamental_history
        if reference.get('fundamental_reference'):
            fundamental_evidence = store.read('run_fundamentals/'+reference_id)
            if not fundamental_evidence or fundamental_evidence.get('sha256') != reference['fundamental_reference']['sha256']:
                raise ValueError('Frozen fundamental evidence is missing or changed.')
        else:
            fundamental_evidence = fundamental_history.capture(reference['universe_snapshot'],log)
    trials = []
    result = dict(id=job_id,reference_id=reference_id,reference_name=reference['config']['name'],
                  created_at=store.now(),start=reference['config']['start'],end=reference['config']['end'],
                  suite=suite,trials=trials, planned_trials=[dict(label=label,changes=changes) for label,changes in variants],
                  notice='Comparison running. Each completed or failed trial is retained; no automatic promotion.')
    store.write('momentum_comparisons/'+job_id,result)
    for label, changes in variants:
        cfg = MomentumConfig(**{**reference['config'], 'name':label, 'comparison_run_id':reference_id, **changes})
        run_id = uuid4().hex[:12]
        log(f'Comparison {len(trials)+1}/{len(variants)}: {label}.')
        try:
            if fundamental_evidence is not None:
                run(settings,cfg,log,run_id,fundamental_evidence=fundamental_evidence)
            else:
                run(settings,cfg,log,run_id)
            report = store.read('runs/'+run_id)
            trials.append(dict(label=label,run_id=run_id,changes=changes,status='success',metrics=report['metrics'],
                               evaluation=report['evaluation'],diagnostics=report['diagnostics']))
        except Exception as exc:
            from core.research.jobs import failure_detail
            error = str(exc) if isinstance(exc,ValueError) else failure_detail(exc)
            trials.append(dict(label=label,run_id=run_id,changes=changes,status='failed',error=error,
                               config=cfg.model_dump(mode='json'),metrics=dict(return_pct=None,max_drawdown_pct=None,trade_count=None),
                               evaluation={'segments':[]},diagnostics={}))
            log(f'Trial failed and retained: {label}. {error}')
        store.write('momentum_comparisons/'+job_id,result)
    baseline = trials[0]['metrics']['return_pct']
    for trial in trials:
        value = trial['metrics']['return_pct']
        trial['delta_return_pct'] = value-baseline if value is not None and baseline is not None else None
    failed = sum(t['status']=='failed' for t in trials)
    result['failed_trials'] = failed
    result['notice'] = f'All {len(variants)} declared trials retained, including {failed} failures. Identical frozen data and modeled costs; exploratory comparison, no default changes or automatic winner selection.'
    store.write('momentum_comparisons/'+job_id,result)
    with store.LOCK:
        comparisons = store.read('momentum_comparisons_index',[])
        comparisons.insert(0,result)
        store.write('momentum_comparisons_index',comparisons)
    log('Comparison complete: all trials retained; strategy defaults unchanged.')
    return {'comparison_id':job_id,'run_id':next((t['run_id'] for t in trials if t['status']=='success'),None), 'partial':bool(failed)}


def trade_chart(result, trade, minutes):
    series = [dict(id='trigger',label='Opening-range breakout',color='#c49b44'),
              dict(id='protective_stop',label='Pullback stop' if result['config'].get('stop_reference')=='pullback' else 'ATR stop',color='#c77565')]
    if result['config'].get('require_vwap'):
        series.append(dict(id='vwap',label='Completed-bar VWAP',color='#5879c6'))
    if trade['target'] is not None:
        series.append(dict(id='target',label='Profit target',color='#2c8c62'))
    end_opening = 555+result['config']['opening_minutes']
    bars = []
    vwap = session_vwap(minutes)
    stops = {x['timestamp']:x['stop'] for x in trade.get('stop_trace', [])}
    for i, b in enumerate(minutes):
        h,m = map(int,b['time'].split(':'))
        values = {'trigger':trade['trigger']} if h*60+m >= end_opening else {}
        if trade['entry_timestamp']<=b['timestamp']<=trade['exit_timestamp']:
            values['protective_stop'] = stops.get(b['timestamp'],trade['initial_stop'])
            if trade['target'] is not None:
                values['target'] = trade['target']
        if result['config'].get('require_vwap') and vwap[i] is not None:
            values['vwap'] = vwap[i]
        bars.append(dict(b,chart_values=values))
    checks = [dict(label='Opening relative volume',actual=trade['relative_volume'], required=f">= {result['config']['min_relative_volume']}",passed=True),
              dict(label='Prior-session ATR',actual=trade['atr'],required='Stop distance uses prior ATR',passed=None),
              dict(label='Breakout direction',actual=trade.get('signal_direction', trade['direction']),required=result['config']['direction'],passed=True)]
    if trade.get('execution_mode') == 'reverse':
        checks.append(dict(label='Reversed execution', actual=trade['direction'], required='Opposite to the original breakout signal', passed=True))
    if trade.get('signal_indicators'):
        feature = trade['signal_indicators']
        checks.append(dict(label=f"Completed {feature['minutes']}-minute {result['config']['indicator_filter']} filter",
                           actual=f"EMA9 {feature['ema9']:.2f}; EMA20 {feature['ema20']:.2f}; MACD {feature['macd']:.3f}; histogram {feature['histogram']:.3f} (previous {feature['previous_histogram']:.3f})",
                           required='Directional alignment / rising momentum; prior-session warmup', passed=True))
    if trade.get('signal_pattern'):
        pattern = trade['signal_pattern']
        checks.append(dict(label='Two-candle flag resumption',
                           actual=f"Impulse {pattern['impulse_body_atr']:.2f} ATR; retracement {pattern['retracement_fraction']:.1%}; pullback extreme {pattern['pullback_extreme']:.2f}",
                           required='Impulse >=0.25 ATR; retracement <=50%; completed close beyond pullback',passed=True))
    if trade.get('fundamentals'):
        fundamental=trade['fundamentals']
        checks.append(dict(label='Historical fundamentals before entry',
                           actual=f"Score {fundamental['score']}; coverage {fundamental['coverage_pct']}%; period {fundamental['period_end']}; available {fundamental['available_at']}",
                           required=f"Score >= {result['config']['fundamental_min_score']}; coverage >= {result['config']['fundamental_min_coverage_pct']}%; age <= {result['config']['fundamental_max_age_days']} days; no flags",passed=True))
    quality = trade.get('confirmation_quality',{})
    for field, actual, label in [('min_close_strength','close_strength','Confirmation close position'),
                                 ('min_confirmation_body_atr','body_atr','Directional confirmation body / ATR')]:
        if result['config'].get(field):
            checks.append(dict(label=label,actual=quality.get(actual),required=f">= {result['config'][field]}",
                               passed=True if actual in quality else None))
    if result['config'].get('require_vwap'):
        checks.append(dict(label='Signal close / VWAP',actual=f"{trade['signal_close']:.2f} / {trade['signal_vwap']:.2f}",
                           required='Above VWAP for long; below for short',passed=True))
    return dict(bars=bars, explanation=dict(pattern='Opening-range momentum', entry_mode=f"Completed {result['config'].get('confirmation_minutes',5)}-minute breakout close → next five-minute open",
                winner_exit='ATR stop / cutoff',candidate_rank='opening_relative_volume', series=series,
                signal=dict(date=trade['signal_date'], timestamp=trade['signal_timestamp']),
                checks=checks,
                notices=['Opening range and relative-volume ranks are known only after the opening interval completes.',
                         'Signal timestamp identifies the final five-minute constituent of the completed confirmation candle. Entry uses the next five-minute open. Larger candles align to 09:15 IST.',
                         'Frozen five-minute inputs. Stop/target fills identify intervals; mandatory square-off uses the cutoff bar open.']))
