"""Chart recorded paper fills against the portfolio's available daily candles."""
from core.research import store


def chart_data(portfolio, symbol, entry_date, exit_date=''):
    ledger = portfolio.get('ledger', {})
    trades = [dict(t) for t in ledger.get('trades', []) if t['symbol'] == symbol]
    position = ledger.get('positions', {}).get(symbol)
    if position:
        trades.append(dict(position, symbol=symbol))
    selected = next((t for t in trades if t['entry_date'] == entry_date
                     and (t.get('exit_date') or '') == exit_date), None)
    if not selected:
        raise ValueError('Trade not found in this paper portfolio.')

    reference = portfolio.get('input_reference')
    if reference:
        frozen = store.read(reference)
        from core.research.four_indicator_swing import digest
        expected = (portfolio.get('cycles') or [{}])[-1].get('input_sha256')
        if not frozen or not expected or digest(frozen) != expected:
            raise ValueError('Saved paper candles are unavailable or changed.')
        bars = frozen.get('datasets', {}).get(symbol, [])
        notice = 'Daily candles from the latest saved paper cycle; markers show recorded simulated fills.'
    else:
        instruments = portfolio.get('universe_snapshot', {}).get('instruments', [])
        item = next((i for i in instruments if i['symbol'] == symbol), None)
        bars = store.read('bars/' + item['isin'], {}).get('bars', []) if item else []
        notice = 'Daily candles from the current local market-data cache; these candles are not a frozen execution snapshot. Markers show recorded simulated fills.'
    through = ledger.get('last_session')
    bars = sorted((b for b in bars if not through or b['date'] <= through), key=lambda b: b['date'])
    dates = {b['date']: i for i, b in enumerate(bars)}
    required = [t[key] for t in trades for key in ('entry_date', 'exit_date') if t.get(key)]
    if not bars or any(day not in dates for day in required):
        raise ValueError('Daily candles for these paper fills are unavailable. Refresh the portfolio market data and try again.')
    first = min(dates[t['entry_date']] for t in trades)
    last = len(bars) - 1 if position else max(dates[t['exit_date']] for t in trades)
    explanation = None
    if reference:
        from core.research.trade_chart import indicator_trade_explanation
        explanation = indicator_trade_explanation({'config': portfolio['config']}, selected, bars)
        bars = explanation.pop('bars')
    return dict(symbol=symbol, trade=selected, trades=trades,
                bars=bars[max(0, first - 60):last + 21], notice=notice,
                explanation=explanation)
