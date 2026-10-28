"""Shared four-indicator rules, evaluated on completed candles only."""
from statistics import mean, pstdev


def indicators(bars, *, bollinger_multiplier=2):
    """Wilder RSI(14), Supertrend(10,3), configurable 20-period Bollinger band."""
    result = []
    atr = gain = loss = upper = lower = trend = None
    ranges, gains, losses = [], [], []
    closes = [b['close'] for b in bars]
    for i, b in enumerate(bars):
        prior = closes[i-1] if i else b['close']
        ranges.append(max(b['high']-b['low'], abs(b['high']-prior), abs(b['low']-prior)))
        if i:
            gains.append(max(b['close']-prior, 0))
            losses.append(max(prior-b['close'], 0))
        if i == 9:
            atr = mean(ranges)
        elif i > 9:
            atr = (atr*9+ranges[-1])/10
        if i == 14:
            gain, loss = mean(gains), mean(losses)
        elif i > 14:
            gain, loss = (gain*13+gains[-1])/14, (loss*13+losses[-1])/14
        rsi = None if gain is None else (50 if gain == loss == 0 else 100 if loss == 0 else 100-100/(1+gain/loss))
        if atr is not None:
            basic_upper = (b['high']+b['low'])/2+3*atr
            basic_lower = (b['high']+b['low'])/2-3*atr
            upper = basic_upper if upper is None or basic_upper < upper or prior > upper else upper
            lower = basic_lower if lower is None or basic_lower > lower or prior < lower else lower
            if trend is None:
                trend = -1
            elif trend == -1 and b['close'] > upper:
                trend = 1
            elif trend == 1 and b['close'] < lower:
                trend = -1
        window = closes[max(0, i-19):i+1]
        result.append(dict(rsi=rsi, supertrend=(lower if trend == 1 else upper),
                           uptrend=trend == 1,
                           upper_band=mean(window)+bollinger_multiplier*pstdev(window) if i >= 19 else None))
    return result


def decision(bar, values, previous_day, *, rsi_threshold=70, bollinger_multiplier=2):
    pivot = sum(previous_day[k] for k in ('high', 'low', 'close'))/3
    r1 = 2*pivot-previous_day['low']
    checks = [
        dict(name='Above Supertrend (10, 3)', passed=values['uptrend'] and bar['close'] > values['supertrend'], value=values['supertrend']),
        dict(name=f'RSI (14) above {rsi_threshold:g}', passed=values['rsi'] is not None and values['rsi'] > rsi_threshold, value=values['rsi']),
        dict(name='Close above prior-day R1', passed=bar['close'] > r1, value=r1),
        dict(name=f'Close above Bollinger (20, {bollinger_multiplier:g})', passed=values['upper_band'] is not None and bar['close'] > values['upper_band'], value=values['upper_band']),
    ]
    return dict(checks=checks, entry=all(c['passed'] for c in checks),
                exit=not values['uptrend'], signal_time=bar['time'],
                signal_timestamp=bar['timestamp'], close=bar['close'])
