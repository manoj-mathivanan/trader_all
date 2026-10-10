"""Long-only daily breakout research with next-open fills."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from core.execution.paper import PaperBrokerAdapter
from core.risk.position_sizer import percent_risk_size
from core.research import store, data_quality, market_history, provenance, corporate_actions, sector
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


def simulate(datasets, cfg, *, state=None, liquidate=True, allow_entries=True, entry_warmup=0, entry_check=None, fundamental_scores=None, sector_gate=None, sector_observe_only=False):
    """One daily engine for research and durable paper sessions.

    State is copied: a failed cycle never mutates the last committed ledger.
    """
    if getattr(cfg, 'execution_horizon', 'swing') == 'intraday':
        raise ValueError('Intraday backtests require five-minute inputs. Use the backtest job workflow.')
    if getattr(cfg, 'sector_filter', 'off') != 'off':
        if cfg.entry_mode != 'next_open' or cfg.pattern in dict(bearish.SCREENS):
            raise ValueError('Sector filters require long swing next-session-open entries.')
        if sector_gate is None:
            raise ValueError('Sector filter requires explicit captured index inputs.')
    if cfg.candidate_rank == 'fundamental_score' and fundamental_scores is None:
        raise ValueError('Fundamental ranking requires dated financial evidence.')
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
    sector_checks = []
    context_cache = {}
    action_log = state.get('corporate_actions', [])
    applied = {x['id'] for x in action_log}
    refinement_keys = ('max_open_gap_pct', 'require_open_above_pivot', 'max_extension_pct',
                       'reentry_cooldown_sessions', 'stalled_exit_sessions', 'stalled_min_r',
                       'failed_breakout_sessions')
    exit_keys = ('pattern', 'stop_pct', 'breakeven_r', 'winner_exit', 'trail_pct', 'max_hold_days',
                 'stalled_exit_sessions', 'stalled_min_r', 'failed_breakout_sessions')
    refined = cfg.fee_model != 'custom_bps' or cfg.winner_exit == 'trail_pct' or any(
        getattr(cfg, k) for k in refinement_keys if k != 'stalled_min_r')
    skip_reasons = dict(state.get('entry_filter_rejections', {}))
    last_exit_dates = {t['symbol']: t['exit_date'] for t in trades}
    market_stats = {}
    all_days = sorted({b['date'] for bs in datasets.values() for b in bs}) if cfg.market_breadth_trend_sessions else []
    day_indices = {d: i for i, d in enumerate(all_days)}

    def context(symbol, day):
        key = (symbol, day)
        if key not in context_cache:
            context_cache[key] = corporate_actions.adjusted_bars(datasets[symbol], day)
        return context_cache[key]
    rs_enabled = getattr(cfg, 'min_rs_rating', 0) > 0 or getattr(cfg, 'candidate_rank', 'alphabetical') == 'rs_126'
    date_indices = {s: {b['date']: i for i, b in enumerate(bars)} for s, bars in datasets.items()} if cfg.skip_weak_markets or rs_enabled or cfg.market_risk_scale != 1 else {}
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
        market_stats[day] = above / eligible * 100 if eligible else 0
        market_cache[day] = (eligible > 0 and coverage >= getattr(cfg, 'market_min_coverage_pct', 80)
                             and above / eligible >= getattr(cfg, 'market_breadth_pct', 40) / 100)
        if market_cache[day] and cfg.market_breadth_trend_sessions:
            earlier = day_indices.get(day, -1) - cfg.market_breadth_trend_sessions
            if earlier < 0:
                market_cache[day] = False
            else:
                prior_day = all_days[earlier]
                market_is_strong(prior_day)
                market_cache[day] = market_stats[day] >= market_stats[prior_day]
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
        intraday = day == p['entry_date']
        if intraday and cfg.fee_model == 'zerodha_equity':
            from core.execution.zerodha import equity_charges
            actual_buy = equity_charges(p['entry'], p['quantity'], 'buy', day, intraday=True)
            correction = actual_buy['total'] - p['entry_fee']
            cash -= correction
            total_fees += correction
            p['entry_cost'] += correction
            p['entry_fee'] = actual_buy['total']
            p['entry_charges'] = actual_buy
            order = next(o for o in reversed(orders) if o['symbol'] == symbol and o['side'] == 'buy' and o['date'] == day)
            order.update(fees=actual_buy['total'], charges=actual_buy)
        execution = broker.fill(price, p['quantity'], 'sell', day=day, intraday=intraday)
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
        last_exit_dates[symbol] = day
        if 'charges' in execution:
            orders[-1]['charges'] = execution['charges']
            trades[-1]['charges'] = {k: p.get('entry_charges', {}).get(k, 0) + execution['charges'].get(k, 0)
                                    for k in execution['charges']}
            trades[-1]['gross_pnl'] = fill * p['quantity'] - (p['entry_cost'] - p['entry_fee'])
        if 'stop_trace' in p:
            trades[-1]['stop_trace'] = p['stop_trace']
        if 'fundamentals' in p:
            trades[-1]['fundamentals'] = p['fundamentals']
        if 'sector' in p:
            trades[-1]['sector'] = p['sector']

    for day in sorted(events):
        context_cache.clear()
        session = events[day]
        # Rebase eligible holdings before checking their stop against the ex-date
        # open. Original fills and cash remain untouched. Replay is idempotent.
        for symbol in list(positions):
            if symbol not in datasets:
                continue  # Suspended paper holdings retain their last recorded mark.
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
            if b['open'] <= p['stop'] or p.get('pending_exit') or p['age'] >= p.get('exit_config', {}).get('max_hold_days', cfg.max_hold_days):
                close(symbol, b['open'], day, 'Gap through stop' if b['open'] <= p['stop'] else p.get('pending_exit', 'Time exit'))
                exited.add(symbol)
        equity_at_open = cash + sum(p['quantity'] * (session[s][1]['open'] if s in session else marks[s]) for s, p in positions.items())
        # Ranking uses only the completed signal session, never the entry-day close.
        def priority(symbol):
            if cfg.candidate_rank == 'fundamental_score':
                from core.research.fundamental_history import rank_key
                return rank_key(fundamental_scores(symbol, day), symbol)
            idx, _ = session[symbol]
            signal_idx = idx if cfg.entry_mode == 'close' and cfg.pattern != 'breakout' else idx - 1
            score = relative_strength(datasets[symbol][signal_idx]['date']).get(symbol, (-1, -1)) if signal_idx >= 0 else (-1, -1)
            return (-score[0], -score[1], symbol)

        candidates = sorted(session, key=priority) if cfg.candidate_rank in ('rs_126', 'fundamental_score') else sorted(session)
        for symbol in candidates:
            if not allow_entries:
                break
            i, b = session[symbol]
            signal_idx = i if cfg.entry_mode == 'close' and cfg.pattern != 'breakout' else i - 1
            if symbol in positions or symbol in exited or (cfg.pattern == 'breakout' and i < 1) or signal_idx < entry_warmup or signal_idx < 0 or not signal(context(symbol, datasets[symbol][signal_idx]['date']), signal_idx, cfg):
                continue
            signal_day = datasets[symbol][signal_idx]['date']
            denial = None
            signal_bars = context(symbol, signal_day)
            if cfg.max_open_gap_pct and (b['open'] / signal_bars[signal_idx]['close'] - 1) * 100 > cfg.max_open_gap_pct:
                denial = 'Opening gap too large'
            elif cfg.max_extension_pct and (signal_bars[signal_idx]['close'] /
                    moving_average(signal_bars, signal_idx, 50) - 1) * 100 > cfg.max_extension_pct:
                denial = 'Signal too extended'
            elif cfg.require_open_above_pivot and b['open'] < (pivot_for(context(symbol, day), signal_idx, cfg) or b['open']):
                denial = 'Open below breakout'
            elif cfg.reentry_cooldown_sessions and symbol in last_exit_dates:
                elapsed = sum(last_exit_dates[symbol] < row['date'] <= day for row in datasets[symbol])
                if elapsed <= cfg.reentry_cooldown_sessions:
                    denial = 'Reentry cooldown'
            if denial:
                skipped += 1
                skip_reasons[denial] = skip_reasons.get(denial, 0) + 1
                continue
            sector_decision = None
            if sector_gate is not None:
                sector_decision = sector_gate.decision(symbol, signal_day)
                sector_decision['enforced'] = not sector_observe_only
                sector_checks.append(dict(sector_decision, entry_date=day))
                if not sector_decision['allowed'] and not sector_observe_only:
                    skipped += 1
                    continue
            if entry_check is not None and not entry_check(symbol,day):
                skipped += 1
                continue
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
            sizing_cfg = cfg
            if cfg.market_risk_scale != 1 and not market_is_strong(signal_day):
                sizing_cfg = SimpleNamespace(**{**vars(cfg), 'risk_pct': cfg.risk_pct * cfg.market_risk_scale})
            qty = percent_risk_size(equity_at_open, cash, fill, stop, sizing_cfg, day=day)
            if qty < 1:
                skipped += 1
                continue
            execution = broker.fill(raw_fill, qty, 'buy', day=day)
            fee = execution['fees']
            cash -= qty * fill + fee
            total_fees += fee
            total_slippage += execution['slippage']
            orders.append({'id': f"{symbol}:{day}:buy", 'symbol': symbol, 'date': day, 'side': 'buy',
                           'quantity': qty, 'price': fill, 'fees': fee, 'status': 'FILLED', 'reason': 'Completed-bar signal'})
            if sector_decision is not None:
                orders[-1]['sector'] = sector_decision
            if fundamental_scores is not None:
                orders[-1]['fundamentals'] = fundamental_scores(symbol, day)
            positions[symbol] = {'entry': fill, 'entry_date': day, 'entry_cost': qty * fill + fee,
                                 'entry_fee': fee, 'quantity': qty, 'stop': stop, 'best_close': fill,
                                 'initial_risk': qty * (fill - stop), 'age': 0,
                                 'exit_config': {k: getattr(cfg, k) for k in exit_keys}}
            if refined:
                positions[symbol]['stop_trace'] = []
                positions[symbol]['entry_pivot'] = pivot_for(context(symbol, day), signal_idx, cfg)
            if 'charges' in execution:
                positions[symbol]['entry_charges'] = execution['charges']
                orders[-1]['charges'] = execution['charges']
            if sector_decision is not None:
                positions[symbol]['sector'] = sector_decision
            if fundamental_scores is not None:
                positions[symbol]['fundamentals'] = fundamental_scores(symbol, day)
            marks[symbol] = b['open']
            entered_today.add(symbol)
        for symbol in sorted(list(positions)):
            if symbol not in session:
                continue
            idx, b = session[symbol]
            p = positions[symbol]
            exit_cfg = SimpleNamespace(**{'stalled_exit_sessions': 0, 'stalled_min_r': .5, 'failed_breakout_sessions': 0,
                                         **p.get('exit_config', {k: getattr(cfg, k) for k in exit_keys})})
            if 'stop_trace' in p:
                p['stop_trace'].append({'date': day, 'stop': p['stop']})
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
                if cfg.fee_model == 'zerodha_equity':
                    from core.execution.zerodha import breakeven_price
                    breakeven = breakeven_price(p['entry_cost'], p['quantity'], day, cfg.slippage_bps)
                else:
                    breakeven = p['entry_cost'] / p['quantity'] / ((1 - sell_fee) * (1 - slip))
                if exit_cfg.pattern == 'breakout':
                    trailing = None
                elif exit_cfg.winner_exit == 'trail_30w':
                    trailing = moving_average(context(symbol, day), idx, 150)
                elif target_pct is not None or exit_cfg.winner_exit == 'trail_pct':
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
            if (exit_cfg.failed_breakout_sessions and p['age'] <= exit_cfg.failed_breakout_sessions
                    and p.get('entry_pivot') and b['close'] < p['entry_pivot']):
                p['pending_exit'] = 'Early breakout failure (next open)'
            elif (exit_cfg.stalled_exit_sessions and p['age'] >= exit_cfg.stalled_exit_sessions
                  and p['best_close'] < p['entry'] * (1 + exit_cfg.stop_pct / 100 * exit_cfg.stalled_min_r)):
                p['pending_exit'] = 'Stalled trade (next open)'
            marks[symbol] = b['close']
            future = datasets[symbol]
            if liquidate and (idx == len(future) - 1 or future[idx + 1]['date'] > str(cfg.end)):
                close(symbol, b['close'], day, 'End of available test data')
        equity = cash + sum(p['quantity'] * marks[s] for s, p in positions.items())
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
        curve.append({'date': day, 'equity': round(equity, 2), 'drawdown_pct': round((peak - equity) / peak * 100, 4)})
    # Bisection breakeven fills leave tiny floating-point residues. Preserve
    # historical custom-bps metrics, but don't label Zerodha flat exits wins.
    tolerance = 1e-6 if cfg.fee_model == 'zerodha_equity' else 0
    wins, losses = [t for t in trades if t['pnl'] > tolerance], [t for t in trades if t['pnl'] < -tolerance]
    return {'trades': trades, 'curve': curve, 'corporate_actions': action_log, 'sector_checks': sector_checks,
        'entry_filter_rejections': skip_reasons,
        'state': {'cash': cash, 'positions': positions, 'marks': marks, 'trades': trades, 'curve': curve,
                  'entry_filter_rejections': skip_reasons,
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
            # Atomic replacements may have the same size and timestamp on Windows.
            # Include file identity so ingestion cannot reuse an obsolete summary.
            signature = (stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns, stat.st_size)
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
    if ready:
        start = max(max(r['dates'][warmup + 1], r['requested_start'] or r['dates'][0]) for r in ready)
        end = min(min(r['dates'][-1], r['requested_end'] or r['dates'][-1]) for r in ready)
        if start < end:
            result.update(start=start, end=end)
    return result


def prepare(settings, cfg):
    if getattr(cfg, 'comparison_run_id', None):
        reference_run = store.read('runs/' + cfg.comparison_run_id)
        datasets = store.read('run_data/' + cfg.comparison_run_id, {})
        if not reference_run or not datasets:
            raise ValueError('The comparison run or its frozen input snapshot is unavailable.')
        hashes = {row['symbol']:row.get('sha256') for row in reference_run['manifest']}
        if getattr(cfg, 'sector_filter', 'off') != 'off' and any(not hashes.get(s) for s in datasets):
            raise ValueError('Sector comparisons require hashed frozen stock inputs.')
        if any(hashes.get(symbol) and market_history.digest(bars) != hashes[symbol] for symbol,bars in datasets.items()):
            raise ValueError('Frozen stock inputs are missing or changed.')
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
            excluded.append(item['symbol'])
            continue
        if record['requested_end'] < str(cfg.end) or record['requested_start'] > str(cfg.start):
            excluded.append(item['symbol'])
            continue
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
        raise ValueError(f'No eligible symbols cover the requested test dates with the required {warmup} sessions before the test start.' + reason + suggestion)
    if not any(str(cfg.start) <= b['date'] <= str(cfg.end) for bars in datasets.values() for b in bars):
        raise ValueError('No actual candles fall within this test interval. Choose dates within downloaded history.')
    return universe, datasets, manifest, excluded


def run(settings, cfg, log, job_id, *, fundamental_evidence=None, sector_evidence=None):
    universe, datasets, manifest, excluded = prepare(settings, cfg)
    quality = data_quality.audit(datasets, end=cfg.end)
    datasets = data_quality.exclude_anomalies(datasets, quality, log)
    if not datasets:
        raise ValueError('No eligible stocks remain after excluding unresolved price gaps.')
    manifest = [row for row in manifest if row['symbol'] in datasets]
    excluded = list(dict.fromkeys([*excluded, *quality['excluded_symbols']]))
    log(f'Testing {len(datasets)} symbols with one cash balance; {len(excluded)} excluded for price gaps, missing history, date coverage, warmup or IPO listing evidence.')
    intraday = getattr(cfg, 'execution_horizon', 'swing') == 'intraday'
    if sector_evidence is None and cfg.comparison_run_id:
        saved_reference = store.read('runs/'+cfg.comparison_run_id, {}).get('sector_reference')
        if saved_reference:
            sector_evidence = store.read('run_sector/'+cfg.comparison_run_id, {})
            sector.verify(sector_evidence, saved_reference['sha256'])
        elif cfg.sector_filter != 'off':
            raise ValueError('Reference run has no frozen sector inputs. Use Compare sector filters to capture one shared snapshot.')
    if sector_evidence is None and cfg.sector_filter != 'off':
        sector_evidence = sector.capture(universe)
    sector_gate = sector.Gate(sector_evidence, cfg.sector_filter) if cfg.sector_filter != 'off' else None
    fundamental_scores = None
    if fundamental_evidence is not None or cfg.candidate_rank == 'fundamental_score':
        from core.research import fundamental_history
        if fundamental_evidence is None and cfg.comparison_run_id:
            reference = store.read('runs/'+cfg.comparison_run_id, {}).get('fundamental_reference')
            if reference:
                fundamental_evidence = store.read('run_fundamentals/'+cfg.comparison_run_id)
                if not fundamental_evidence or fundamental_evidence.get('sha256') != reference['sha256']:
                    raise ValueError('Frozen financial evidence is missing or changed.')
        if fundamental_evidence is None:
            fundamental_evidence = fundamental_history.capture(universe, log)
        fundamental_scores = fundamental_history.Scores(fundamental_evidence, cfg.entry_mode)
    minute_inputs = None
    if intraday:
        from core.research import intraday_short, intraday_long, intraday_data
        engine = intraday_short if cfg.pattern in dict(bearish.SCREENS) else intraday_long
        plan = engine.entry_plan(datasets, cfg, fundamental_scores=fundamental_scores) if cfg.pattern not in dict(bearish.SCREENS) else engine.entry_plan(datasets, cfg)
        minute_inputs = intraday_data.load_sessions(plan, universe, log)
        result = engine.simulate(datasets, cfg, minute_inputs, plan=plan)
    else:
        result = simulate(datasets, cfg, fundamental_scores=fundamental_scores, sector_gate=sector_gate)
    result.pop('state')  # Persistent execution state belongs to paper portfolios only.
    result.update(id=job_id, created_at=store.now(), config=cfg.model_dump(mode='json'),
                  universe=settings.universe, universe_snapshot=universe, manifest=manifest, excluded=excluded,
                  data_quality=quality,
                  provenance=provenance.capture(),
                  history_reference=market_history.evidence(snapshot=True),
                  warnings=['Current constituents only: survivorship bias remains. This is not an edge-validation result.',
                            'Corporate-action adjustments, exchange-calendar gaps and delisted history are not verified.',
                            'Screens use independent research approximations inspired by Banana Patterns; detector parity is unverified and historical membership/market-wide RS need verified data.',
                            'All-in fee rates are your assumptions, not a verified historical tax/brokerage schedule.',
                            'No volume participation cap, circuit-limit or non-fill simulation; stops may fill worse in real markets.',
                            'This run is exploratory/in-sample. Reserve a later untouched period before judging the strategy.'])
    result['warnings'].extend(quality['warnings'])
    if cfg.pattern in dict(bearish.SCREENS):
        result['warnings'].extend([
            'Hypothetical short research: stock-borrow availability, recalls, dividends owed, margin calls and circuit-limit fills are not modeled.',
            '100% entry-notional collateral is reserved; short-sale proceeds cannot fund additional entries. This is a research capital constraint, not a broker margin schedule.',
            f'Annual borrow cost assumption: {cfg.borrow_cost_bps_year:g} bps, accrued on calendar days at the last marked short liability. Zero excludes borrow costs.',
            'Weak-market breadth and RS are computed on the prepared eligible universe; exclusions can change the cross-section.'
        ])
    if fundamental_evidence is not None:
        store.write('run_fundamentals/'+job_id, fundamental_evidence)
        result['fundamental_reference'] = {k: fundamental_evidence[k] for k in ('sha256','captured_at','method','notice')}
        result['warnings'].append(fundamental_evidence['notice'])
    if cfg.fee_model == 'zerodha_equity':
        from core.execution.zerodha import SOURCES
        result['cost_model'] = dict(name='Zerodha NSE cash equity', reviewed_at='2026-10-10', sources=SOURCES,
            notice='Resident-individual tariff; delivery plus same-day intraday reclassification. Includes DP on delivery sells. '
                   'Trade-level estimates differ from contract-note rounding. Account AMC and personal income tax excluded. Slippage is separate.')
        result['warnings'] = [w for w in result['warnings'] if not w.startswith('All-in fee rates')]
        result['warnings'].append(result['cost_model']['notice'])
    if sector_evidence is not None:
        sector.verify(sector_evidence)
        store.write('run_sector/'+job_id, sector_evidence)
        result['sector_reference'] = {k:sector_evidence[k] for k in ('sha256','captured_at','mapping_captured_at','notice')}
        result['warnings'].append(sector_evidence['notice'])
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
    return {'run_id': job_id, 'partial': bool(quality['excluded_symbols']),
            'price_gap_exclusions': quality['excluded_symbols']}


def compare_sectors(settings, reference_id, log, job_id):
    from core.research.config import BacktestConfig
    reference = store.read('runs/'+reference_id, {})
    values = reference.get('config', {})
    if reference.get('strategy_id') or values.get('execution_horizon', 'swing') != 'swing' or values.get('entry_mode') != 'next_open' or values.get('pattern') in dict(bearish.SCREENS):
        raise ValueError('Choose a long swing next-open backtest for sector comparison.')
    if not values:
        raise ValueError('Reference backtest is unavailable.')
    if not all(row.get('sha256') for row in reference.get('manifest', [])):
        raise ValueError('Sector comparisons require hashed frozen stock inputs.')
    snapshot = store.read('run_sector/'+reference_id) if reference.get('sector_reference') else sector.capture(reference['universe_snapshot'])
    sector.verify(snapshot or {}, reference.get('sector_reference', {}).get('sha256'))
    if not snapshot['mappings'] or not any(v.get('bars') for k,v in snapshot['prices'].items() if k != 'benchmark'):
        raise ValueError('Fetch sector data before running the comparison.')
    financial = store.read('run_fundamentals/'+reference_id) if reference.get('fundamental_reference') else None
    if reference.get('fundamental_reference') and (not financial or financial.get('sha256') != reference['fundamental_reference']['sha256']):
        raise ValueError('Frozen financial evidence is missing or changed.')
    trials = []
    for mode, label in [('off','Filter off'), ('trend','Sector trend'), ('trend_rs','Sector trend + relative strength')]:
        cfg = BacktestConfig(**{**values, 'name':label, 'sector_filter':mode, 'comparison_run_id':reference_id})
        identifier = job_id+'_'+mode
        run(settings, cfg, log, identifier, fundamental_evidence=financial, sector_evidence=snapshot)
        result = store.read('runs/'+identifier)
        checks = result.get('sector_checks', [])
        trials.append(dict(label=label, run_id=identifier, metrics=result['metrics'],
                           blocked_signals=sum(not x['allowed'] for x in checks)))
    comparison = dict(id=job_id, reference_id=reference_id, trials=trials, sector_sha256=snapshot['sha256'],
        notice='Same frozen stock data, mapping, index history, costs and ranking. Unmapped stocks are blocked in filtered trials, so coverage can confound filter effects. Current mappings are historically biased; reserve untouched validation dates.')
    store.write('sector/comparison/'+job_id, comparison)
    with store.LOCK:
        index = store.read('sector/comparisons', [])
        store.write('sector/comparisons', [comparison, *index])
    return dict(comparison_id=job_id)
