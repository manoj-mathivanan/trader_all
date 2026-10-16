"""Declared stock suitability score using only completed prior daily candles."""
import math
from statistics import mean


def score(prior, turnover, minimum_turnover):
    rows = prior[-20:]
    if len(rows) < 20:
        return dict(total=0.0, components={}, reason='Insufficient prior daily context')
    ranges = [max(b['high']-b['low'], abs(b['high']-a['close']), abs(b['low']-a['close']))
              for a, b in zip(prior[-15:-1], prior[-14:])]
    atr_pct = mean(ranges)/rows[-1]['close']*100
    path = sum(abs(b['close']-a['close']) for a, b in zip(rows, rows[1:]))
    efficiency = abs(rows[-1]['close']-rows[0]['close'])/path if path else 0.0
    average_volume = mean(b['volume'] for b in rows)
    activity = mean(b['volume'] for b in rows[-5:])/average_volume if average_volume else 0.0
    components = dict(
        liquidity=20*min(1.0, max(0.0, math.log10(max(1.0, turnover/max(minimum_turnover, 1)))/2)),
        movement=35*min(1.0, atr_pct/2),
        trend_consistency=30*min(1.0, efficiency),
        volume_activity=15*min(1.0, max(0.0, activity-0.5)),
    )
    return dict(total=round(sum(components.values()), 6), components=components,
                atr_pct=atr_pct, efficiency=efficiency, volume_ratio=activity,
                as_of=rows[-1]['date'])
