"""Causal session-aligned indicators. EMA state persists across regular sessions."""
from core.research import intraday_data


def aggregate(bars, minutes):
    """Drop trailing partial bins; never combine different sessions or missing bars."""
    count = minutes // 5
    result = []
    for start in range(0, len(bars)-count+1, count):
        group = bars[start:start+count]
        expected = [555+(start+i)*5 for i in range(count)]
        times = [int(b['time'][:2])*60+int(b['time'][3:]) for b in group]
        if times != expected or len({b['date'] for b in group}) != 1:
            raise ValueError('Indicator candles require contiguous session-aligned five-minute inputs.')
        result.append(dict(open=group[0]['open'], high=max(b['high'] for b in group),
                           low=min(b['low'] for b in group), close=group[-1]['close'],
                           timestamp=group[-1]['timestamp'], last_index=start+count-1))
    return result


def ema(values, period):
    """Seed with the first period's SMA, then apply alpha=2/(period+1)."""
    output, seed, state = [], [], None
    for value in values:
        if value is None:
            output.append(None)
            continue
        if state is None:
            seed.append(value)
            if len(seed) == period:
                state = sum(seed)/period
        else:
            state += 2/(period+1)*(value-state)
        output.append(state)
    return output


def features(sessions, candidate, day, current, minutes, mode):
    history = []
    for prior_day in candidate['history']:
        # Use the same fixed regular interval in every warmup session. Partial
        # terminal bins are discarded rather than carried across overnight gaps.
        bars = intraday_data.trading_bars(sessions[prior_day], '15:00')
        if any(prior_day < a['ex_date'] <= day for a in candidate['actions']):
            raise ValueError('Indicator warmup crosses a corporate action; independently verify intraday price basis before testing.')
        history.extend(aggregate(bars, minutes))
    minimum = 100 if mode in ('macd', 'ema_macd') else 60
    if len(history) < minimum:
        raise ValueError(f'Indicator warmup needs {minimum} complete {minutes}-minute candles; found {len(history)}.')
    candles = history+aggregate(current, minutes)
    closes = [b['close'] for b in candles]
    fast, slow = ema(closes, 9), ema(closes, 20)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    macd = [a-b if a is not None and b is not None else None for a,b in zip(e12,e26)]
    signal = ema(macd, 9)
    hist = [a-b if a is not None and b is not None else None for a,b in zip(macd,signal)]
    result, latest = {}, None
    completed = {b['last_index']:i for i,b in enumerate(candles[len(history):], len(history))}
    for j in range(len(current)):
        if j in completed:
            i = completed[j]
            latest = dict(minutes=minutes, timestamp=candles[i]['timestamp'], ema9=fast[i], ema20=slow[i],
                          previous_ema9=fast[i-1], macd=macd[i], histogram=hist[i],
                          previous_histogram=hist[i-1], close=closes[i], warmup_candles=len(history))
        result[j] = latest
    return result


def accepts(feature, sign, mode):
    if feature is None:
        return False
    trend = (sign*(feature['close']-feature['ema9']) > 0 and
             sign*(feature['ema9']-feature['ema20']) > 0 and
             sign*(feature['ema9']-feature['previous_ema9']) > 0)
    momentum = (sign*feature['macd'] > 0 and sign*feature['histogram'] > 0 and
                sign*(feature['histogram']-feature['previous_histogram']) > 0)
    return (trend if mode == 'ema' else momentum if mode == 'macd' else trend and momentum)
