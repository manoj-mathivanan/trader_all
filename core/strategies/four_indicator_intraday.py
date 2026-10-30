"""Causal intraday entry variants for the four-indicator research strategy."""


def completed_trend(rows, evaluator):
    """Map completed 15-minute Supertrend(10,3) to five-minute closes.

    Inputs contain complete regular sessions, with 75 candles per session.
    The first 15-minute result becomes available at the third five-minute close.
    """
    import numpy as np
    if len(rows) % 75:
        raise ValueError('Expected complete 75-bar regular sessions.')
    groups = rows.reshape(-1, 3, 6)
    aggregate = np.column_stack((groups[:,0,0], groups[:,0,1], groups[:,:,2].max(axis=1),
        groups[:,:,3].min(axis=1), groups[:,-1,4], groups[:,:,5].sum(axis=1)))
    _, supertrend, up, _ = evaluator(aggregate, 2.5)
    passed = up & (aggregate[:,4] > supertrend)
    result = np.zeros(len(rows), dtype=bool)
    result[2:] = np.repeat(passed, 3)[:len(rows)-2]
    return result


def pullback_signals(rows, base, rsi, supertrend, up, r1, *, expiry_bars=6):
    """An all-four setup, later SMA20 touch, then completed bullish resumption.

    Setup expires after six five-minute candles or at session end. A later bar
    must touch SMA20 while Supertrend remains up. A still-later bar must close
    above the preceding high, its open, SMA20, Supertrend and prior-day R1,
    with RSI >65. The upper Bollinger test is replaced only at resumption.
    """
    import numpy as np
    if expiry_bars < 2:
        raise ValueError('Pullback setup requires at least two later bars.')
    middle = np.full(len(rows), np.nan)
    middle[19:] = np.lib.stride_tricks.sliding_window_view(rows[:,4],20).mean(axis=1)
    result = np.zeros(len(rows), dtype=bool)
    armed = touched = None
    for i, bar in enumerate(rows):
        # A regular session boundary cannot carry an unfilled setup overnight.
        if i % 75 == 0 or not up[i] or (armed is not None and i-armed > expiry_bars):
            armed = touched = None
        if armed is not None and i > armed:
            if (touched is not None and i > touched and bar[4] > rows[i-1,2]
                    and bar[4] > max(bar[1], middle[i], supertrend[i], r1[i]) and rsi[i] > 65):
                result[i] = True
                armed = touched = None
                continue
            if bar[3] <= middle[i] and bar[4] > supertrend[i]:
                touched = i
        if armed is None and base[i] and up[i]:
            armed = i
    return result
