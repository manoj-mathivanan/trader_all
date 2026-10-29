"""Explain a recorded trade using only its frozen inputs and saved configuration."""
from bisect import bisect_left, bisect_right
from types import SimpleNamespace
from datetime import date
from core.research.config import TradingConfig
from core.research import store


def reference_trade_explanation(result, trade, bars, first, last):
    from statistics import median
    from core.research import corporate_actions
    from core.research.banana_reference import NOTICES, setup_proxy

    cfg = SimpleNamespace(**result['config'])
    audit = next((a for a in result.get('candidate_audit', [])
                  if a.get('symbol') == trade['symbol'] and a.get('date') == trade['entry_date']
                  and a.get('reason') == 'Filled'), None)
    decision_index = first - (1 if cfg.entry_mode == 'pivot' else 2)
    decision_day = audit.get('decision_date') if audit else None
    if decision_day:
        decision_index = next((i for i, b in enumerate(bars) if b['date'] == decision_day), -1)
    decision = bars[decision_index] if decision_index >= 0 else None
    checks = []

    def check(label, actual, required, passed=None):
        checks.append(dict(label=label, actual=actual, required=required, passed=passed))

    setup_pivot = None
    if decision:
        prior = corporate_actions.adjusted_bars(bars, decision['date'])
        qualified, setup_pivot = setup_proxy(prior, decision_index, cfg)
        check('Completed pattern setup', 'Qualified' if qualified else 'Did not qualify',
              'Saved fixed-rule '+cfg.pattern.replace('_', ' ')+' setup', qualified)
        if cfg.pattern == 'blue_sky' and setup_pivot:
            proximity = prior[decision_index]['close'] / setup_pivot * 100
            check('Close / highest historical close (%)', proximity, '80–100%', 80 <= proximity <= 100)
    else:
        check('Completed pattern setup', None, 'Completed setup-session candles required')

    # The audit pivot is in the entry session's price units. Older reports can
    # reconstruct it only from frozen setup candles and verified share actions.
    pivot = audit.get('pivot') if audit else setup_pivot
    if not audit and pivot is not None:
        for action in corporate_actions.actions(bars):
            if action['ex_date'] == trade['entry_date'] and action['price_basis'] == 'raw':
                pivot /= action['share_factor']
    trigger = bars[first] if cfg.entry_mode == 'pivot' else bars[first-1] if first else None
    actual = trigger['high' if cfg.entry_mode == 'pivot' else 'close'] if trigger else None
    check('Entry-session high above pivot' if cfg.entry_mode == 'pivot' else 'Completed breakout close above pivot',
          actual, f'> {pivot:.2f}' if pivot is not None else 'Saved pivot unavailable',
          actual > pivot if actual is not None and pivot is not None else None)
    strength = audit.get('rs') if audit else None
    floor = {'vcp': 70, 'blue_sky': 70, 'multiyear': 60, 'ipo': 0}[cfg.pattern]
    population = audit.get('rs_population') if audit else None
    check('Weighted relative strength', strength, f'≥ {floor}; '+(f'{population} eligible stocks' if population is not None else 'Saved rank unavailable'),
          strength >= floor if strength is not None else None)
    liquidity = audit.get('median_turnover') if audit else None
    if liquidity is None and decision:
        liquidity = median(b['close'] * b['volume'] for b in prior[max(0, decision_index-19):decision_index+1])
    check('Median 20-session turnover (₹)', liquidity, '≥ 10,000,000',
          liquidity >= 10000000 if liquidity is not None else None)
    if audit:
        positions = audit.get('positions_before')
        check('Open positions before entry', positions, f'< {cfg.max_positions}',
              positions < cfg.max_positions if positions is not None else None)
        check('Entry priority', audit.get('priority'), 'Higher weighted RS first, then turnover')
        check('Position sizing constraint', audit.get('sizing_constraint'), 'Recorded limiting factor')
        if audit.get('eligibility_checked'):
            passed = audit.get('eligibility_passed')
            check('Additional entry eligibility', 'Allowed' if passed else 'Blocked', 'Allowed', passed)
    notices = [*NOTICES,
               'Setup checks are reconstructed from frozen candles at the completed decision session. Breakout checks use the entry or completed breakout session.']
    notices.append('RS, turnover, priority and portfolio context come from this trade’s recorded Filled audit.' if audit else
                   'This older trade has no saved Filled audit. Its historical RS rank and portfolio context are unavailable; no current data is substituted.')
    if any(c['passed'] is False for c in checks):
        notices.append('A reconstructed check differs from the saved fill. Historical engine rules may differ; the recorded trade is unchanged.')
    enriched = [dict(b, chart_values={}) for b in bars]
    for i, row in enumerate(enriched):
        if i >= 49:
            row['chart_values']['sma_50'] = sum(b['close'] for b in bars[i-49:i+1])/50
        if first <= i <= last:
            row['chart_values']['initial_stop'] = trade['entry']*(1-cfg.stop_pct/100)
        if pivot is not None and max(0, decision_index) <= i <= last:
            row['chart_values']['trigger'] = pivot
    series = [dict(id='sma_50', label='SMA50 closing exit line', color='#d18b26'),
              dict(id='initial_stop', label='Initial entry-relative stop', color='#bd5869')]
    if pivot is not None:
        series.append(dict(id='trigger', label='Recorded entry pivot' if audit else 'Reconstructed entry pivot', color='#2596a2'))
    return dict(bars=enriched, pattern=cfg.pattern, entry_mode=cfg.entry_mode,
                winner_exit=cfg.winner_exit, candidate_rank='weighted_rs',
                signal={'date': decision['date']} if decision else None,
                checks=checks, series=series, notices=notices)


def indicator_trade_explanation(result, trade, bars):
    from core.strategies.four_indicator import indicators, decision
    from core.research.four_indicator_swing import RULES, stored_parameters
    params = stored_parameters(result['config'])
    values = indicators(bars, bollinger_multiplier=params['bollinger_multiplier'])
    rule = next(r for r in RULES if r[0] == result['config']['rule_set'])
    series = [dict(id=key, label=label, color=color, pane=pane) for key, label, color, pane in (
        ('supertrend', 'Supertrend (10, 3)', '#2596a2', 'price'),
        ('r1', 'Prior-day R1', '#d18b26', 'price'),
        ('upper_band', f"Bollinger upper (20, {params['bollinger_multiplier']:g})", '#5879c6', 'price'),
        ('rsi', 'RSI (14)', '#9766c5', 'rsi'),
        ('rsi_threshold', f"RSI threshold {params['rsi_threshold']:g}", '#8c998c', 'rsi'))]
    enriched = []
    signal = None
    checks = []
    for i, (bar, value) in enumerate(zip(bars, values)):
        levels = {k: value[k] for k in ('supertrend', 'upper_band', 'rsi') if value[k] is not None}
        levels['rsi_threshold'] = params['rsi_threshold']
        if i:
            prior = bars[i-1]
            levels['r1'] = 2 * (prior['high'] + prior['low'] + prior['close']) / 3 - prior['low']
        enriched.append(dict(bar, chart_values=levels))
        if bar['date'] == trade['signal_date'] and i:
            signal = dict(date=bar['date'], timestamp=bar['timestamp'], price=bar['close'])
            conditions = decision(dict(bar, time='close'), value, bars[i-1], **params)['checks']
            for n in rule[2]:
                c = conditions[n]
                checks.append(dict(label=c['name'], actual=c['value'], required='Required entry condition', passed=c['passed']))
            if rule[3]:
                checks.append(dict(label='Close below prior-day R1', actual=bar['close'],
                                   required=f"< {levels['r1']}", passed=bar['close'] < levels['r1']))
    return dict(bars=enriched, series=series, signal=signal, checks=checks,
                pattern=result.get('rule_label', rule[1]), entry_mode='next_open',
                winner_exit='Supertrend reversal at next open; final liquidation at test end',
                candidate_rank='prior_turnover',
                notices=['Indicators use this run’s complete frozen candle history before cropping. Only the selected variant’s conditions qualify entries; the other plotted lines provide context.',
                         'BUY and SELL markers use recorded fills, including modeled slippage. RSI has its own panel.'])


def explain_trade(result, datasets, trade, bars, first, last):
    if result.get('strategy_id') == 'four_indicator_swing':
        return indicator_trade_explanation(result, trade, bars)
    if result['config'].get('simulation_model') == 'banana_proxy_v1':
        return reference_trade_explanation(result, trade, bars, first, last)
    if trade.get('direction') == 'short':
        from core.research.short_trade_chart import explain_trade as explain_short
        return explain_short(result, datasets, trade, bars, first, last)
    cfg = SimpleNamespace(**{**TradingConfig().model_dump(), **result['config']})
    investor = cfg.pattern == 'investor_early_breakout'
    if investor:
        from core.research.investor_rules import Rules
        cfg.investor_rules = Rules(**cfg.investor_rules)
    signal_idx = first if cfg.entry_mode == 'close' and cfg.pattern != 'breakout' else first - 1
    signal = bars[signal_idx] if signal_idx >= 0 else None
    checks, series = [], []
    enriched = [dict(b, chart_values={}) for b in bars]
    lengths = sorted({cfg.sma_days, 50, 200} | ({150} if cfg.winner_exit == 'trail_30w' else set()))
    if investor:
        lengths = sorted(set(lengths) | {20, 100})
    averages = {}
    for length in lengths:
        total, values = 0, []
        for i, bar in enumerate(bars):
            total += bar['close']
            if i >= length:
                total -= bars[i - length]['close']
            values.append(total / length if i + 1 >= length else None)
        averages[length] = values
        key = f'sma_{length}'
        series.append({'id': key, 'label': f'SMA {length}',
                       'color': {50: '#d18b26', 150: '#9766c5', 200: '#5879c6'}.get(length, '#2596a2')})
        for i, row in enumerate(enriched):
            if values[i] is not None:
                row['chart_values'][key] = values[i]

    def check(label, actual, required, passed):
        checks.append({'label': label, 'actual': actual, 'required': required, 'passed': passed})

    lookback = cfg.vcp_window_days if cfg.pattern == 'vcp' else min(cfg.blue_sky_lookback_days, max(signal_idx, 0)) if cfg.pattern == 'blue_sky' else cfg.multiyear_base_days if cfg.pattern == 'multiyear' else cfg.base_days
    if investor:
        lookback = cfg.investor_rules.resistance_sessions
    prior = bars[max(0, signal_idx - lookback):signal_idx] if signal_idx > 0 else []
    pivot_days = lookback if cfg.pattern != 'vcp' else cfg.base_days
    pivot_bars = bars[max(0, signal_idx - pivot_days):signal_idx] if signal_idx > 0 else []
    ceiling = max((b['high'] for b in prior), default=None)
    floor = min((b['low'] for b in prior), default=None)
    pivot = max((b['high'] for b in pivot_bars), default=None)
    levels = [('trigger', 'Signal breakout level', ceiling, '#2596a2'),
              ('base_floor', 'Prior base low', floor if cfg.pattern != 'blue_sky' else None, '#8c998c'),
              ('initial_stop', 'Initial stop', trade['entry'] * (1 - cfg.stop_pct / 100), '#bd5869'),
              ('activation', 'Breakeven activation', trade['entry'] * (1 + cfg.stop_pct / 100 * cfg.breakeven_r), '#ac8c49')]
    if cfg.entry_mode == 'pivot' and pivot is not None and pivot != ceiling:
        levels.append(('pivot', 'Entry pivot', pivot, '#5965a9'))
    if cfg.winner_exit in ('take_8', 'take_15', 'take_25'):
        target_pct = {'take_8': 8, 'take_15': 15, 'take_25': 25}[cfg.winner_exit]
        levels.append(('target', f'+{target_pct}% profit target', trade['entry'] * (1 + target_pct / 100), '#4b9b64'))
    for key, label, value, color in levels:
        if value is None:
            continue
        series.append({'id': key, 'label': label, 'color': color})
        for i, row in enumerate(enriched):
            if (max(0, signal_idx - lookback) <= i <= last if key in ('trigger', 'base_floor', 'pivot') else first <= i <= last):
                row['chart_values'][key] = value

    if signal is not None:
        if cfg.pattern == 'ipo':
            metadata = bars[0].get('listing_metadata', {})
            age = ((date.fromisoformat(signal['date']) - date.fromisoformat(metadata.get('ipo_date', metadata['listing_date']))).days
                   if metadata.get('verified') is True and metadata.get('source') and metadata.get('ipo_verified') is True else None)
            check('Verified listing age (calendar days)', age, f'0–{cfg.ipo_max_age_days}',
                  0 <= age <= cfg.ipo_max_age_days if age is not None else False)
        sma = averages[cfg.sma_days][signal_idx]
        if not investor:
            check('Price above trend average', signal['close'], f'> SMA {cfg.sma_days}: {sma:.2f}' if sma is not None else 'More history required', signal['close'] > sma if sma is not None else None)
        if ceiling is not None:
            check('Close above breakout level', signal['close'], f'> {ceiling:.2f}', signal['close'] > ceiling)
        preceding = bars[max(0, signal_idx - 50):signal_idx]
        if len(preceding) == 50 and not investor:
            volume = sum(b['volume'] for b in preceding) / 50
            turnover = sum(b['close'] * b['volume'] for b in preceding) / 50
            check('Breakout volume / prior 50-session mean', signal['volume'] / volume if volume else None,
                  f'≥ {cfg.volume_multiple:g}×', signal['volume'] >= volume * cfg.volume_multiple)
            check('Average daily turnover (₹)', turnover, f'≥ {cfg.min_turnover:,.0f}', turnover >= cfg.min_turnover)
        if investor:
            from core.research.investor_breakouts import setup
            rules = cfg.investor_rules
            measured = setup(bars[:signal_idx + 1], rules)
            check('Investor early-breakout qualification', measured.get('stage') if measured else None,
                  'early_breakout', bool(measured and measured['stage'] == 'early_breakout'))
            if measured:
                for label, actual, limit, minimum in (
                        ('Extension above resistance (%)', measured['distance_pct'], rules.max_extension_pct, False),
                        ('Prior 20-session base range (%)', measured['base_range_pct'], rules.max_base_range_pct, False),
                        ('Recent / earlier daily range', measured['contraction_ratio'], rules.max_contraction_ratio, False),
                        ('Breakout volume / prior 20-session mean', measured['volume_ratio'], rules.min_breakout_volume_ratio, True),
                        ('Average 20-session turnover (₹)', measured['average_turnover'], rules.min_turnover_rupees, True)):
                    check(label, actual, f'{"≥" if minimum else "≤"} {limit:g}', actual >= limit if minimum else actual <= limit)
                check('Trend alignment', ' / '.join(f'{measured[k]:.2f}' for k in ('close', 'ma20', 'ma50', 'ma100')),
                      'Close ≥ SMA20 ≥ SMA50 ≥ SMA100; rising SMA50' if rules.strict_trend else 'Close ≥ SMA50 ≥ SMA100; rising SMA50', True)
        if cfg.require_long_trend or cfg.require_rising_long_trend:
            long = averages[200][signal_idx]
            check('Price above SMA 200', signal['close'], f'> {long:.2f}' if long is not None else 'More history required', signal['close'] > long if long is not None else None)
        if cfg.require_rising_long_trend:
            long, old = averages[200][signal_idx], averages[200][signal_idx - 20] if signal_idx >= 20 else None
            check('SMA 200 rising over 20 sessions', long, f'> {old:.2f}' if old is not None else 'More history required', long > old if long is not None and old is not None else None)
        if cfg.pattern == 'vcp' and signal_idx >= 3 * cfg.vcp_window_days:
            ranges, volumes = [], []
            for offset in (3, 2, 1):
                window = bars[signal_idx - cfg.vcp_window_days * offset:signal_idx - cfg.vcp_window_days * (offset - 1)]
                high = max(b['high'] for b in window)
                ranges.append((high - min(b['low'] for b in window)) / high * 100)
                volumes.append(sum(b['volume'] for b in window) / len(window))
            check('VCP range contraction (%)', ' → '.join(f'{r:.2f}' for r in ranges), 'Each window smaller than the previous', ranges[0] > ranges[1] > ranges[2])
            check('VCP average volume contraction', ' → '.join(f'{v:,.0f}' for v in volumes), 'Each window lower than the previous', volumes[0] > volumes[1] > volumes[2])
            if len(preceding) == 50:
                check('VCP final volume / 50-session mean', volumes[-1] / volume if volume else None,
                      f'≤ {cfg.vcp_volume_multiple:g}×', volumes[-1] <= volume * cfg.vcp_volume_multiple)
        elif prior and cfg.pattern in ('multiyear', 'ipo', 'breakout'):
            depth = (ceiling - floor) / ceiling * 100
            limit = cfg.multiyear_max_depth_pct if cfg.pattern == 'multiyear' else cfg.max_depth_pct
            check('Base depth (%)', depth, f'≤ {limit:g}%', depth <= limit)
        from core.research import relative_strength
        if relative_strength.enabled(cfg):
            strength = relative_strength.StrengthHistory(datasets).measure(trade['symbol'], signal['date'], cfg)
            check(f'{cfg.rs_short_lookback}-session RS percentile', strength['short_rs_rating'],
                  f'≥ {cfg.min_short_rs_rating:g}', strength['short_rs_rating'] is not None and strength['short_rs_rating'] >= cfg.min_short_rs_rating)
            if cfg.min_rs_improvement:
                check(f'RS gain over {cfg.rs_improvement_sessions} sessions (percentile points)', strength['rs_improvement'],
                      f'≥ {cfg.min_rs_improvement:g}', strength['rs_improvement'] is not None and strength['rs_improvement'] >= cfg.min_rs_improvement)
        if cfg.min_rs_rating > 0 or cfg.candidate_rank == 'rs_126' or cfg.skip_weak_markets:
            returns, above, eligible = {}, 0, 0
            for symbol, rows in datasets.items():
                idx = next((i for i, row in enumerate(rows) if row['date'] == signal['date']), None)
                if idx is None:
                    continue
                if idx >= 126:
                    returns[symbol] = rows[idx]['close'] / rows[idx - 126]['close'] - 1
                if idx >= 199:
                    eligible += 1
                    above += rows[idx]['close'] > sum(b['close'] for b in rows[idx - 199:idx + 1]) / 200
            values = sorted(returns.values())
            if trade['symbol'] in returns:
                value = returns[trade['symbol']]
                rating = (bisect_left(values, value) + bisect_right(values, value) - 1) / 2 / max(len(values) - 1, 1) * 100
                check('126-session RS percentile', rating, f'≥ {cfg.min_rs_rating:g}' if cfg.min_rs_rating > 0 else 'No minimum; informational', rating >= cfg.min_rs_rating if cfg.min_rs_rating > 0 else None)
            if cfg.skip_weak_markets:
                coverage = eligible / len(datasets) * 100 if datasets else 0
                check('Breadth history coverage (%)', coverage, f'≥ {cfg.market_min_coverage_pct:g}',
                      eligible > 0 and coverage >= cfg.market_min_coverage_pct)
                check('Market breadth (%)', above / eligible * 100 if eligible else None,
                      f'≥ {cfg.market_breadth_pct:g}; {eligible} eligible symbols', above / eligible * 100 >= cfg.market_breadth_pct if eligible else False)

    # This trace is reconstructed from recorded fills, not asserted to be a saved engine trace.
    stop, best = trade['entry'] * (1 - cfg.stop_pct / 100), trade['entry']
    slip, buy_fee, sell_fee = cfg.slippage_bps / 10000, cfg.buy_cost_bps / 10000, cfg.sell_cost_bps / 10000
    recorded_model = result.get('config', {}).get('fee_model', 'custom_bps')
    if recorded_model in ('upstox_plus', 'zerodha_equity'):
        if recorded_model == 'upstox_plus':
            from core.execution.upstox import breakeven_price, equity_charges
        else:
            from core.execution.zerodha import breakeven_price, equity_charges
        quantity = trade['quantity']
        entry_fee = equity_charges(trade['entry'], quantity, 'buy', trade['entry_date'])['total']
        breakeven = breakeven_price(trade['entry']*quantity+entry_fee, quantity, trade['entry_date'], cfg.slippage_bps)
    else:
        breakeven = trade['entry'] * (1 + buy_fee) / ((1 - sell_fee) * (1 - slip))
    early_stop = None
    for i in range(first, last + 1):
        enriched[i]['chart_values']['protective_stop'] = stop
        if i == first and cfg.pattern != 'breakout' and cfg.entry_mode in ('pivot', 'close'):
            continue
        bar = bars[i]
        if bar['open'] <= stop or bar['low'] <= stop:
            if i < last:
                early_stop = bar['date']
            break
        best = max(best, bar['close'])
        if bar['close'] >= trade['entry'] * (1 + cfg.stop_pct / 100 * cfg.breakeven_r):
            length = 150 if cfg.winner_exit == 'trail_30w' else 50
            trail = averages[length][i] if cfg.pattern != 'breakout' and cfg.winner_exit not in ('take_8', 'take_15', 'take_25', 'trail_pct') else None
            stop = max(stop, breakeven, trail if trail is not None else best * (1 - cfg.trail_pct / 100))
    series.append({'id': 'protective_stop', 'label': 'Reconstructed active stop', 'color': '#d34848'})
    if trade.get('stop_trace'):
        trace = {x['date']: x['stop'] for x in trade['stop_trace']}
        for row in enriched:
            row['chart_values']['protective_stop'] = trace.get(row['date'])
        series[-1]['label'] = 'Recorded active stop'
        early_stop = None
    notices = ['Indicators use the full saved history before the chart is cropped. Signal checks use only the completed signal session.',
               ('The active stop uses the recorded engine trace. BUY/SELL markers are the recorded ledger.' if trade.get('stop_trace') else
                'The active stop is reconstructed from saved settings and fills; older engine versions may differ. BUY/SELL markers are the recorded ledger.')]
    if investor:
        notices.append('Technical investor baseline only. Approaching-breakout rows do not enter; financial assessments and news interpretations are excluded.')
    if any(x.get('symbol') == trade['symbol'] and trade['entry_date'] < x['date'] <= trade['exit_date']
           for x in result.get('corporate_actions', [])):
        for row in enriched:
            row['chart_values'].pop('protective_stop', None)
        series = [x for x in series if x['id'] != 'protective_stop']
        notices.append('This position crossed a share action. Original entry quantity and exit quantity differ; the reconstructed stop trace is omitted. Recorded cash P&L remains authoritative.')
    if any(c['passed'] is False for c in checks):
        notices.append('Some reconstructed checks fail. This historical run may use different engine rules; the explanation does not rewrite its ledger.')
    if early_stop:
        notices.append(f'The reconstructed stop is reached on {early_stop}, earlier than the recorded exit. The stop trace ends there; it is not an exact historical engine trace.')
    if cfg.pattern == 'vcp':
        notices.append('The VCP signal uses its contraction-window high; pivot execution can use a different base-days high. VCP base-depth and market-cap filters are not enforced by this engine.')
    if result.get('fundamental_reference'):
        from core.research.fundamental_history import Scores
        payload = store.read('run_fundamentals/'+result['id'])
        if not payload or payload.get('sha256') != result['fundamental_reference']['sha256']:
            raise ValueError('Frozen financial evidence is missing or changed.')
        financial = Scores(payload, cfg.entry_mode)(trade['symbol'],trade['entry_date'])
        check('Entry fundamental score / 100', financial['score'], 'Ranking context; higher first', None)
        check('Fundamental evidence coverage (%)', financial['coverage_pct'], 'Tie-break context; higher first', None)
        notices.append('Financial period: '+str(financial['period_end'])+'; evidence available: '+str(financial['available_at'])+'. '+result['fundamental_reference']['notice'])
    return {'bars': enriched, 'series': series, 'signal': {'date': signal['date'], 'timestamp': signal['timestamp'], 'price': signal['close']} if signal else None,
            'checks': checks, 'notices': notices, 'pattern': cfg.pattern, 'entry_mode': cfg.entry_mode,
            'candidate_rank': cfg.candidate_rank, 'winner_exit': cfg.winner_exit}
