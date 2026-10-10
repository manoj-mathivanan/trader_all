"""Point-in-time cross-sectional return percentiles for emerging leadership."""
from bisect import bisect_left, bisect_right
from core.research import corporate_actions


def enabled(cfg):
    return getattr(cfg, 'min_short_rs_rating', 0) > 0 or getattr(cfg, 'min_rs_improvement', 0) > 0


class StrengthHistory:
    def __init__(self, datasets, context=None):
        self.datasets = datasets
        self.indices = {s: {b['date']: i for i, b in enumerate(rows)} for s, rows in datasets.items()}
        self.context = context or (lambda s, day: corporate_actions.adjusted_bars(datasets[s], day))
        self.cache = {}

    def ratings(self, day, lookback):
        key = day, lookback
        if key not in self.cache:
            returns = {}
            for symbol in self.datasets:
                i = self.indices[symbol].get(day)
                if i is None or i < lookback:
                    continue
                rows = self.context(symbol, day)
                returns[symbol] = rows[i]['close'] / rows[i-lookback]['close'] - 1
            values = sorted(returns.values())
            self.cache[key] = {s: (bisect_left(values, v) + bisect_right(values, v) - 1)
                               / 2 / max(len(values)-1, 1) * 100 for s, v in returns.items()}
        return self.cache[key]

    def measure(self, symbol, day, cfg):
        current = self.ratings(day, cfg.rs_short_lookback).get(symbol)
        i = self.indices.get(symbol, {}).get(day)
        prior_day = self.datasets[symbol][i-cfg.rs_improvement_sessions]['date'] if i is not None and i >= cfg.rs_improvement_sessions else None
        prior = self.ratings(prior_day, cfg.rs_short_lookback).get(symbol) if prior_day else None
        return dict(short_rs_rating=current, prior_short_rs_rating=prior,
                    rs_improvement=current-prior if current is not None and prior is not None else None,
                    prior_rs_date=prior_day)

    def passes(self, symbol, day, cfg):
        value = self.measure(symbol, day, cfg)
        return ((cfg.min_short_rs_rating == 0 or value['short_rs_rating'] is not None and value['short_rs_rating'] >= cfg.min_short_rs_rating)
                and (cfg.min_rs_improvement == 0 or value['rs_improvement'] is not None and value['rs_improvement'] >= cfg.min_rs_improvement))
