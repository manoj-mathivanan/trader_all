"""Long-only daily breakout research with next-open fills."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from core.execution.paper import PaperBrokerAdapter
from core.risk.position_sizer import percent_risk_size
from core.research import store, data_quality, market_history, provenance, corporate_actions
from strategies.swing_patterns.patterns.signals import matches
from core.research import bearish


def signal(bars, i, cfg):
    return matches(bars, i, cfg)


def required_warmup(cfg):
    if cfg.pattern in dict(bearish.SCREENS):
        return bearish.required_history(cfg) - 1
    extra = 220 if getattr(cfg, 'require_rising_long_trend', False) else 200 if getattr(cfg, 'require_long_trend', False) else 0
    if getattr(cfg, 'min_rs_rating', 0) > 0 or getattr(cfg, 'candidate_rank', 'alphabetical') == 'rs_126':
        extra = max(extra, 126)
    if cfg.pattern == 'vcp':
        return max(cfg.vcp_window_days * 3, cfg.sma_days, 50, extra)
    if cfg.pattern == 'blue_sky':
        return max(cfg.sma_days, 50, extra)
    if cfg.pattern == 'multiyear':
        return max(cfg.multiyear_base_days, cfg.sma_days, 50, extra)
    if cfg.pattern == 'ipo':
        return max(cfg.base_days, cfg.sma_days, 50, extra)
    return max(cfg.base_days, cfg.sma_days, 50, extra)


def simulate(datasets, cfg, *, state=None, liquidate=True, allow_entries=True, entry_warmup=0):
    """One daily engine for research and durable paper sessions.

    State is copied: a failed cycle never mutates the last committed ledger.
    """
    if getattr(cfg, 'execution_horizon', 'swing') == 'intraday':
        raise ValueError('Intraday backtests require five-minute inputs. Use the backtest job workflow.')
    if cfg.pattern in dict(bearish.SCREENS):
        if state is not None or not liquidate or not allow_entries:
            raise ValueError('Bearish backtests support isolated research runs only, not paper portfolios.')
        from core.research.short_backtest import simulate as simulate_short
        if getattr(cfg, 'execution_horizon', 'swing') == 'intraday':
            raise ValueError('Intraday shorts require five-minute inputs. Use the backtest job workflow to fetch and audit them.')
        return simulate_short(datasets, cfg, entry_warmup=entry_warmup)
    state = deepcopy(state or {})
    events = {}
    for symbol, bars in datasets.items():
        for i, bar in enumerate(bars):
            if str(cfg.start) <= bar['date'] <= str(cfg.end) and bar['date'] > state.get('last_session', ''):
                events.setdefault(bar['date'], {})[symbol] = (i, bar)
    if not events:
        raise ValueError('No candles in the chosen test interval.')
    cash = state.get('cash', cfg.capital)
    positions, marks = state.get('positions', {}), state.get('marks', {})
    trades, curve, orders = state.get('trades', []), state.get('curve', []), state.get('orders', [])
    broker = PaperBrokerAdapter(cfg)
    slip, buy_fee, sell_fee = cfg.slippage_bps / 10000, cfg.buy_cost_bps / 10000, cfg.sell_cost_bps / 10000
    peak = state.get('peak', cfg.capital)
    max_dd = state.get('max_dd', 0)
    total_fees, total_slippage, skipped = (state.get(k, 0) for k in ('total_fees', 'total_slippage', 'skipped'))

    market_cache = {}
    context_cache = {}
    action_log = state.get('corporate_actions', [])
    applied = {x['id'] for x in action_log}

    def context(symbol, day):
        key = (symbol, day)
        if key not in context_cache:
            context_cache[key] = corporate_actions.adjusted_bars(datasets[symbol], day)
        return context_cache[key]
    rs_enabled = getattr(cfg, 'min_rs_rating', 0) > 0 or getattr(cfg, 'candidate_rank', 'alphabetical') == 'rs_126'
    date_indices = {s: {b['date']: i for i, b in enumerate(bars)} for s, bars in datasets.items()} if cfg.skip_weak_markets or rs_enabled else {}
    rs_cache = {}

    def relative_strength(day):
        if day not in rs_cache:
            returns = {}
            for symbol, bars in datasets.items():
                bars = context(symbol, day)
                idx = date_indices[symbol].get(day)
                if idx is not None and idx >= 126:
                    returns[symbol] = bars[idx]['close'] / bars[idx - 126]['close'] - 1
            values = sorted(returns.values())
            from bisect import bisect_left, bisect_right
            rs_cache[day] = {s: ((bisect_left(values, value) + bisect_right(values, value) - 1) / 2
                                / max(len(values) - 1, 1) * 100, value) for s, value in returns.items()}
        return rs_cache[day]

    def market_is_strong(day):
        """Banana-style breadth gate: at least 40% above the 200-session average."""
        if day in market_cache:
            return market_cache[day]
        eligible = above = 0
        for symbol, bars in datasets.items():
            bars = context(symbol, day)
            session = date_indices[symbol].get(day)
            if session is None or session < 199:
                continue
            eligible += 1
            average = sum(row['close'] for row in bars[session - 199:session + 1]) / 200
            above += bars[session]['close'] > average
        coverage = eligible / len(datasets) * 100 if datasets else 0
        market_cache[day] = (eligible > 0 and coverage >= getattr(cfg, 'market_min_coverage_pct', 80)
                             and above / eligible >= getattr(cfg, 'market_breadth_pct', 40) / 100)
        return market_cache[day]

    def moving_average(bars, idx, length):
        if idx + 1 < length:
            return None
        return sum(row['close'] for row in bars[idx - length + 1:idx + 1]) / length

    def pivot_for(bars, signal_idx, cfg):
        if cfg.pattern == 'blue_sky':
            lookback = min(cfg.blue_sky_lookback_days, signal_idx)
        elif cfg.pattern == 'multiyear':
            lookback = min(cfg.multiyear_base_days, signal_idx)
        else:
            lookback = min(cfg.base_days, signal_idx)
        if lookback < 1:
            return None
        return max(row['high'] for row in bars[signal_idx - lookback:signal_idx])

    def close(symbol, price, day, reason):
        nonlocal cash, total_fees, total_slippage
        p = positions.pop(symbol)
        execution = broker.fill(price, p['quantity'], 'sell')
        fill, fee = execution['price'], execution['fees']
        cash += fill * p['quantity'] - fee
        total_fees += fee
        total_slippage += execution['slippage']
        orders.append({'id': f"{symbol}:{day}:sell", 'symbol': symbol, 'date': day, 'side': 'sell',
                       'quantity': p['quantity'], 'price': fill, 'fees': fee, 'status': 'FILLED', 'reason': reason})
        pnl = fill * p['quantity'] - fee - p['entry_cost']
        trades.append({'symbol': symbol, 'entry_date': p['entry_date'], 'exit_date': day,
                       'entry': p.get('entry_fill', p['entry']), 'exit': fill,
                       'quantity': p.get('entry_quantity', p['quantity']), 'exit_quantity': p['quantity'],
                       'pnl': pnl, 'r': pnl / p['initial_risk'], 'reason': reason,
                       'fees': p['entry_fee'] + fee})

    for day in sorted(events):
        context_cache.clear()
        session = events[day]
        # Rebase eligible holdings before checking their stop against the ex-date
        # open. Original fills and cash remain untouched. Replay is idempotent.
        for symbol in list(positions):
            for action in corporate_actions.actions(datasets[symbol]):
                action_id = symbol + ':' + action['id']
                if (action_id in applied or action['price_basis'] != 'raw'
                        or not positions[symbol]['entry_date'] < action['ex_date'] <= day):
                    continue
                positions[symbol], marks[symbol] = corporate_actions.rebase_position(positions[symbol], marks[symbol], action)
                action_log.append({'id': action_id, 'symbol': symbol, 'date': action['ex_date'],
                                   'kind': action['kind'], 'share_factor': action['share_factor'], 'source': action['source']})
                applied.add(action_id)
        exited = set()
        entered_today = set()
        # Open-time exits precede entries; intraday proceeds cannot fund open-time buys.
        for symbol in sorted(list(positions)):
            if symbol not in session:
                continue
            _, b = session[symbol]
            p = positions[symbol]
            if b['open'] <= p['stop'] or p['age'] >= p.get('exit_config', {}).get('max_hold_days', cfg.max_hold_days):
                close(symbol, b['open'], day, 'Gap through stop' if b['open'] <= p['stop'] else 'Time exit')
                exited.add(symbol)
        equity_at_open = cash + sum(p['quantity'] * (session[s][1]['open'] if s in session else marks[s]) for s, p in positions.items())
        # Ranking uses only the completed signal session, never the entry-day close.
        def priority(symbol):
            idx, _ = session[symbol]
            signal_idx = idx if cfg.entry_mode == 'close' and cfg.pattern != 'breakout' else idx - 1
            score = relative_strength(datasets[symbol][signal_idx]['date']).get(symbol, (-1, -1)) if signal_idx >= 0 else (-1, -1)
            return (-score[0], -score[1], symbol)

        candidates = sorted(session, key=priority) if getattr(cfg, 'candidate_rank', 'alphabetical') == 'rs_126' else sorted(session)
        for symbol in candidates:
            if not allow_entries:
                break
            i, b = session[symbol]
            signal_idx = i if cfg.entry_mode == 'close' and cfg.pattern != 'breakout' else i - 1
            if symbol in positions or symbol in exited or (cfg.pattern == 'breakout' and i < 1) or signal_idx < entry_warmup or signal_idx < 0 or not signal(context(symbol, datasets[symbol][signal_idx]['date']), signal_idx, cfg):
                continue
            signal_day = datasets[symbol][signal_idx]['date']
            if getattr(cfg, 'min_rs_rating', 0) > 0 and relative_strength(signal_day).get(symbol, (-1, 0))[0] < cfg.min_rs_rating:
                skipped += 1
                continue
            if cfg.skip_weak_markets and not market_is_strong(signal_day):
                skipped += 1
                continue
            if len(positions) >= cfg.max_positions:
                skipped += 1
                continue
            if cfg.pattern != 'breakout' and cfg.entry_mode == 'close':
                raw_fill = b['close']
            elif cfg.pattern != 'breakout' and cfg.entry_mode == 'pivot':
                pivot = pivot_for(context(symbol, day), signal_idx, cfg)
                raw_fill = max(b['open'], pivot or b['open'])
                if b['high'] < raw_fill:
                    skipped += 1
                    continue
            else:
                raw_fill = b['open']
            fill = raw_fill * (1 + slip)
            stop = fill * (1 - cfg.stop_pct / 100)
            qty = percent_risk_size(equity_at_open, cash, fill, stop, cfg)
            if qty < 1:
                skipped += 1
                continue
            execution = broker.fill(raw_fill, qty, 'buy')
            fee = execution['fees']
            cash -= qty * fill + fee
            total_fees += fee
            total_slippage += execution['slippage']
            orders.append({'id': f"{symbol}:{day}:buy", 'symbol': symbol, 'date': day, 'side': 'buy',
                           'quantity': qty, 'price': fill, 'fees': fee, 'status': 'FILLED', 'reason': 'Completed-bar signal'})
            positions[symbol] = {'entry': fill, 'entry_date': day, 'entry_cost': qty * fill + fee,
                                 'entry_fee': fee, 'quantity': qty, 'stop': stop, 'best_close': fill,
                                 'initial_risk': qty * (fill - stop), 'age': 0,
                                 'exit_config': {k: getattr(cfg, k) for k in ('pattern', 'stop_pct', 'breakeven_r', 'winner_exit', 'trail_pct', 'max_hold_days')}}
            marks[symbol] = b['open']
            entered_today.add(symbol)
        for symbol in sorted(list(positions)):
            if symbol not in session:
                continue
            idx, b = session[symbol]
            p = positions[symbol]
            exit_cfg = SimpleNamespace(**p.get('exit_config', {k: getattr(cfg, k) for k in ('pattern', 'stop_pct', 'breakeven_r', 'winner_exit', 'trail_pct', 'max_hold_days')}))
            target_pct = {'take_8': 8, 'take_15': 15, 'take_25': 25}.get(exit_cfg.winner_exit)
            if symbol in entered_today and cfg.pattern != 'breakout' and cfg.entry_mode in ('close', 'pivot'):
                # Daily OHLC cannot locate the low relative to an intraday pivot fill.
                # Activate protection next session instead of retroactively stopping out.
                marks[symbol] = b['close']
                future = datasets[symbol]
                if liquidate and (idx == len(future) - 1 or future[idx + 1]['date'] > str(cfg.end)):
                    close(symbol, b['close'], day, 'End of available test data')
                continue
            if b['low'] <= p['stop']:
                close(symbol, p['stop'], day, 'Stop loss / trailing stop')
                continue
            p['age'] += 1
            p['best_close'] = max(p['best_close'], b['close'])
            # Close-based updates activate next session, never retroactively.
            if b['close'] >= p['entry'] * (1 + exit_cfg.stop_pct / 100 * exit_cfg.breakeven_r):
                breakeven = p['entry_cost'] / p['quantity'] / ((1 - sell_fee) * (1 - slip))
                if exit_cfg.pattern == 'breakout':
                    trailing = None
                elif exit_cfg.winner_exit == 'trail_30w':
                    trailing = moving_average(context(symbol, day), idx, 150)
                elif target_pct is not None:
                    trailing = None
                else:
                    trailing = moving_average(context(symbol, day), idx, 50)
                if trailing is not None:
                    p['stop'] = max(p['stop'], breakeven, trailing)
                elif target_pct is not None and b['close'] >= p['entry'] * (1 + target_pct / 100):
                    close(symbol, b['close'], day, f'Take profit +{target_pct}%')
                    continue
                else:
                    p['stop'] = max(p['stop'], breakeven, p['best_close'] * (1 - exit_cfg.trail_pct / 100))
            marks[symbol] = b['close']
            future = datasets[symbol]
            if liquidate and (idx == len(future) - 1 or future[idx + 1]['date'] > str(cfg.end)):
                close(symbol, b['close'], day, 'End of available test data')
        equity = cash + sum(p['quantity'] * marks[s] for s, p in positions.items())
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
        curve.append({'date': day, 'equity': round(equity, 2), 'drawdown_pct': round((peak - equity) / peak * 100, 4)})
    wins, losses = [t for t in trades if t['pnl'] > 0], [t for t in trades if t['pnl'] < 0]
    return {'trades': trades, 'curve': curve, 'corporate_actions': action_log,
        'state': {'cash': cash, 'positions': positions, 'marks': marks, 'trades': trades, 'curve': curve,
                  'corporate_actions': action_log,
                  'orders': orders, 'last_session': curve[-1]['date'], 'peak': peak, 'max_dd': max_dd,
                  'total_fees': total_fees, 'total_slippage': total_slippage, 'skipped': skipped},
        'metrics': {
        'initial_capital': cfg.capital, 'final_equity': curve[-1]['equity'],
        'return_pct': (curve[-1]['equity'] / cfg.capital - 1) * 100, 'max_drawdown_pct': max_dd,
        'trade_count': len(trades), 'win_rate': len(wins) / len(trades) * 100 if trades else None,
        'expectancy_r': sum(t['r'] for t in trades) / len(trades) if trades else None,
        'profit_factor': sum(t['pnl'] for t in wins) / -sum(t['pnl'] for t in losses) if losses else None,
        'modeled_fees': total_fees, 'modeled_slippage': total_slippage, 'skipped_entries': skipped}}


_WINDOW_RECORDS = {}


def available_window(settings, warmup=50):
    """Cache compact date metadata; never retain every symbol's OHLCV in memory."""
    universe = store.read('universes/' + settings.universe, {})
    summaries, missing = [], []
    for item in universe.get('instruments', []):
        name = 'bars/' + item['isin']
        path = store.DATA / (name + '.json')
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            signature = None
        cached = _WINDOW_RECORDS.get(str(path))
        if cached and cached[0] == signature:
            summary = cached[1]
        else:
            record = store.read(name)
            bars = record.get('bars', []) if record else []
            summary = {'dates': [b['date'] for b in bars],
                       'requested_start': record.get('requested_start') if record else None,
                       'requested_end': record.get('requested_end') if record else None}
            if len(_WINDOW_RECORDS) >= 2048:
                _WINDOW_RECORDS.clear()
            _WINDOW_RECORDS[str(path)] = (signature, summary)
        if not summary['dates']:
            missing.append(item['symbol'])
        summaries.append(summary)
    ready = [r for r in summaries if len(r['dates']) > warmup + 2]
    loaded = [r for r in summaries if r['dates']]
    result = {'start': None, 'end': None, 'warmup_sessions': warmup + 1,
              'ready_symbols': len(ready), 'total_symbols': len(summaries),
              'history_start': None, 'history_end': None, 'missing_symbols': missing}
    if loaded:
        result.update(history_start=min(r['dates'][0] for r in loaded),
                      history_end=max(r['dates'][-1] for r in loaded))
    if ready and not missing:
        start = max(max(r['dates'][warmup + 1], r['requested_start'] or r['dates'][0]) for r in ready)
        end = min(min(r['dates'][-1], r['requested_end'] or r['dates'][-1]) for r in loaded)
        if start < end:
            result.update(start=start, end=end)
    return result


def prepare(settings, cfg):
    if getattr(cfg, 'comparison_run_id', None):
        reference_run = store.read('runs/' + cfg.comparison_run_id)
        datasets = store.read('run_data/' + cfg.comparison_run_id, {})
        if not reference_run or not datasets:
            raise ValueError('The comparison run or its frozen input snapshot is unavailable.')
        if settings.universe != reference_run['universe']:
            raise ValueError('Select the comparison run\'s universe before using its frozen inputs.')
        if str(cfg.start) < reference_run['config']['start'] or str(cfg.end) > reference_run['config']['end']:
            raise ValueError('Comparison dates must stay within the reference run\'s saved test window.')
        warmup = max(required_warmup(cfg), cfg.minimum_warmup_sessions)
        eligible = {s: bars for s, bars in datasets.items() if sum(b['date'] < str(cfg.start) for b in bars) >= warmup}
        if not eligible:
            raise ValueError('Frozen inputs do not have enough warmup for this bearish screen.')
        extra = sorted(set(datasets) - set(eligible))
        return (reference_run['universe_snapshot'], eligible,
                [m for m in reference_run['manifest'] if m['symbol'] in eligible],
                sorted(set(reference_run.get('excluded', []) + extra)))
    universe = store.read('universes/' + settings.universe)
    if not universe:
        raise ValueError('Refresh the universe and fetch daily data first.')
    datasets, manifest, excluded = {}, [], []
    reference = market_history.evidence(snapshot=True)
    warmup = max(required_warmup(cfg), getattr(cfg, 'minimum_warmup_sessions', 50))
    for item in universe['instruments']:
        record = store.read('bars/' + item['isin'])
        if not record:
            raise ValueError(f"Missing data for {item['symbol']}. Complete ingestion before running.")
        if record['requested_end'] < str(cfg.end) or record['requested_start'] > str(cfg.start):
            raise ValueError(f"Your test requests {cfg.start} to {cfg.end}, but {item['symbol']} was downloaded for "
                             f"{record['requested_start']} to {record['requested_end']}. "
                             "Use the available dates shown above, or extend the requested history in Settings and fetch missing data in Market data.")
        bars, history = market_history.prepare(item, record, reference=reference)
        if not bars:
            excluded.append(item['symbol'])
            continue
        if cfg.pattern == 'ipo' and (not bars or bars[0].get('listing_metadata', {}).get('ipo_verified') is not True):
            excluded.append(item['symbol'])
            continue
        if len([b for b in bars if b['date'] < str(cfg.start)]) < warmup:
            excluded.append(item['symbol'])
            continue
        datasets[item['symbol']] = bars
        manifest.append({'symbol': item['symbol'], 'source': record['source'], 'bars': len(bars),
                         'first': bars[0]['date'], 'last': bars[-1]['date'],
                         'verified_repairs': record.get('verified_repairs', []),
                         'history_evidence': history,
                         'sha256': hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest()})
    if not datasets:
        window = available_window(settings, warmup)
        suggestion = f" Try {window['start']} to {window['end']}." if window['start'] else ' Fetch more history first.'
        reason = ' IPO screening also requires verified listing dates in metadata/listings.json.' if cfg.pattern in ('ipo', 'ipo_breakdown') else ''
        raise ValueError(f'No eligible symbols have the required {warmup} sessions before the test start.' + reason + suggestion)
    if not any(str(cfg.start) <= b['date'] <= str(cfg.end) for bars in datasets.values() for b in bars):
        raise ValueError('No actual candles fall within this test interval. Choose dates within downloaded history.')
    return universe, datasets, manifest, excluded


def run(settings, cfg, log, job_id):
    universe, datasets, manifest, excluded = prepare(settings, cfg)
    quality = data_quality.audit(datasets, end=cfg.end)
    data_quality.require_no_anomalies(quality)
    log(f'Testing {len(datasets)} symbols with one cash balance; {len(excluded)} excluded for warmup or IPO listing evidence.')
    intraday = getattr(cfg, 'execution_horizon', 'swing') == 'intraday'
    minute_inputs = None
    if intraday:
        from core.research import intraday_short, intraday_long, intraday_data
        engine = intraday_short if cfg.pattern in dict(bearish.SCREENS) else intraday_long
        plan = engine.entry_plan(datasets, cfg)
        minute_inputs = intraday_data.load_sessions(plan, universe, log)
        result = engine.simulate(datasets, cfg, minute_inputs, plan=plan)
    else:
        result = simulate(datasets, cfg)
    result.pop('state')  # Persistent execution state belongs to paper portfolios only.
    result.update(id=job_id, created_at=store.now(), config=cfg.model_dump(mode='json'),
                  universe=settings.universe, universe_snapshot=universe, manifest=manifest, excluded=excluded,
                  data_quality=quality,
                  provenance=provenance.capture(),
                  history_reference=market_history.evidence(snapshot=True),
                  warnings=['Current constituents only: survivorship bias remains. This is not an edge-validation result.',
                            'Corporate-action adjustments, exchange-calendar gaps and delisted history are not verified.',
                            'The Banana screen set and risk/exits are implemented, but historical membership and RS ranking still need a verified market-wide dataset.',
                            'All-in fee rates are your assumptions, not a verified historical tax/brokerage schedule.',
                            'No volume participation cap, circuit-limit or non-fill simulation; stops may fill worse in real markets.',
                            'This run is exploratory/in-sample. Reserve a later untouched period before judging the strategy.'])
    if cfg.pattern in dict(bearish.SCREENS):
        result['warnings'].extend([
            'Hypothetical short research: stock-borrow availability, recalls, dividends owed, margin calls and circuit-limit fills are not modeled.',
            '100% entry-notional collateral is reserved; short-sale proceeds cannot fund additional entries. This is a research capital constraint, not a broker margin schedule.',
            f'Annual borrow cost assumption: {cfg.borrow_cost_bps_year:g} bps, accrued on calendar days at the last marked short liability. Zero excludes borrow costs.',
            'Weak-market breadth and RS are computed on the prepared eligible universe; exclusions can change the cross-section.'
        ])
    if getattr(cfg, 'comparison_run_id', None):
        reference_run = store.read('runs/' + cfg.comparison_run_id)
        result['history_reference'] = reference_run.get('history_reference', {})
        result['comparison'] = {'run_id': cfg.comparison_run_id, 'source': 'frozen_backtest_snapshot',
                                'name': reference_run['config']['name']}
        result['warnings'].append('Uses the reference run\'s frozen data, membership and history evidence; the full snapshot is audited again before simulation.')
    if intraday:
        result['warnings'] = [w for w in result['warnings'] if not any(term in w for term in ('stock-borrow availability', 'Annual borrow cost', 'short research:', 'collateral is reserved'))]
        result['warnings'].extend([
            f'Intraday only: prior completed daily signals; {"sell" if cfg.pattern in dict(bearish.SCREENS) else "buy"} at 09:15 IST; compulsory exit at {cfg.square_off_time} IST using that five-minute bar\'s open. No overnight positions.',
            'Five-minute high/low do not reveal tick order. If both stop and target are hit in one bar, stop is assumed first. Stop/target exit times identify the candle, not the exact fill instant.',
            'Broker-specific intraday eligibility, margin/leverage, auto-square-off charges, circuit limits and actual order fills are not verified. Capital is constrained to 1x entry notional.',
            'Drawdown uses session-end equity and does not measure the worst intraday drawdown. Fixed percentage targets and stops are inherited research assumptions.'
        ])
        result['intraday_source'] = {'provider': 'Upstox historical V3', 'interval_minutes': 5,
                                     'stock_sessions': sum(len(days) for days in minute_inputs.values()),
                                     'square_off_time': cfg.square_off_time, 'timezone': 'Asia/Kolkata'}
        store.write('run_intraday/' + job_id, minute_inputs)
    store.write('run_data/' + job_id, datasets)
    store.write('runs/' + job_id, result)
    with store.LOCK:
        runs = store.read('runs_index', [])
        runs.insert(0, {k: result[k] for k in ('id', 'created_at', 'config', 'universe', 'metrics')})
        store.write('runs_index', runs)
    log(f"Recorded {len(result['trades'])} trades and the input/configuration snapshot.")
    return {'run_id': job_id}
