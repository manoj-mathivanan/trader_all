"""Explain a recorded trade using only its frozen inputs and saved configuration."""
from bisect import bisect_left, bisect_right
from types import SimpleNamespace
from datetime import date
from core.research.config import TradingConfig


def explain_trade(result, datasets, trade, bars, first, last):
    if trade.get('direction') == 'short':
        from core.research.short_trade_chart import explain_trade as explain_short
        return explain_short(result, datasets, trade, bars, first, last)
    cfg = SimpleNamespace(**{**TradingConfig().model_dump(), **result['config']})
    signal_idx = first if cfg.entry_mode == 'close' and cfg.pattern != 'breakout' else first - 1
    signal = bars[signal_idx] if signal_idx >= 0 else None
    checks, series = [], []
    enriched = [dict(b, chart_values={}) for b in bars]
    lengths = sorted({cfg.sma_days, 50, 200} | ({150} if cfg.winner_exit == 'trail_30w' else set()))
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
        check('Price above trend average', signal['close'], f'> SMA {cfg.sma_days}: {sma:.2f}' if sma is not None else 'More history required', signal['close'] > sma if sma is not None else None)
        if ceiling is not None:
            check('Close above breakout level', signal['close'], f'> {ceiling:.2f}', signal['close'] > ceiling)
        preceding = bars[max(0, signal_idx - 50):signal_idx]
        if len(preceding) == 50:
            volume = sum(b['volume'] for b in preceding) / 50
            turnover = sum(b['close'] * b['volume'] for b in preceding) / 50
            check('Breakout volume / prior 50-session mean', signal['volume'] / volume if volume else None,
                  f'≥ {cfg.volume_multiple:g}×', signal['volume'] >= volume * cfg.volume_multiple)
            check('Average daily turnover (₹)', turnover, f'≥ {cfg.min_turnover:,.0f}', turnover >= cfg.min_turnover)
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
            trail = averages[length][i] if cfg.pattern != 'breakout' and cfg.winner_exit not in ('take_8', 'take_15', 'take_25') else None
            stop = max(stop, breakeven, trail if trail is not None else best * (1 - cfg.trail_pct / 100))
    series.append({'id': 'protective_stop', 'label': 'Reconstructed active stop', 'color': '#d34848'})
    notices = ['Indicators use the full saved history before the chart is cropped. Signal checks use only the completed signal session.',
               'The active stop is reconstructed from saved settings and fills; older engine versions may differ. BUY/SELL markers are the recorded ledger.']
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
    return {'bars': enriched, 'series': series, 'signal': {'date': signal['date'], 'timestamp': signal['timestamp'], 'price': signal['close']} if signal else None,
            'checks': checks, 'notices': notices, 'pattern': cfg.pattern, 'entry_mode': cfg.entry_mode,
            'candidate_rank': cfg.candidate_rank, 'winner_exit': cfg.winner_exit}
