"""Optional causal allocation controls shared by daily research and paper trading."""
from collections import defaultdict
from math import fsum
from typing import Literal

from pydantic import BaseModel, Field


class AllocationConfig(BaseModel):
    candidate_ranking: Literal['turnover', 'relative_volume', 'rs_126'] = Field('turnover', title='Rank eligible signals by')
    slot_scale: float = Field(1, gt=0, le=1, title='Cash slot multiplier (1 = normal; 0.75 = 25% smaller)')
    target_atr_pct: float = Field(0, ge=0, le=20, title='ATR(20) allocation target (%; 0 disables)')
    max_slot_multiplier: float = Field(1.25, ge=1, le=2, title='Maximum volatility allocation / equal slot')
    max_position_pct: float = Field(100, gt=0, le=100, title='Maximum cash allocation per stock (%)')
    market_weak_scale: float = Field(1, gt=0, le=1, title='New-position multiplier in weak market (1 disables)')
    sector_weak_scale: float = Field(1, gt=0, le=1, title='New-position multiplier in weak sector (1 disables)')
    breadth_threshold_pct: float = Field(50, ge=0, le=100, title='Strong breadth: stocks above SMA(50) (%)')
    breadth_coverage_pct: float = Field(80, gt=0, le=100, title='Minimum breadth data coverage (%)')
    sector_min_peers: int = Field(3, ge=1, le=100, title='Minimum stocks for sector breadth')
    max_sector_pct: float = Field(100, gt=0, le=100, title='Maximum sector cash exposure (%; 100 disables)')


class AllocationContext:
    def __init__(self, datasets, config, instruments=(), benchmark=()):
        self.config = AllocationConfig(**{k: getattr(config, k) for k in AllocationConfig.model_fields if hasattr(config, k)})
        index = {b['date']: b['close'] for b in benchmark}
        if self.config.candidate_ranking == 'rs_126' and (not index or len(index) != len(benchmark) or any(v <= 0 for v in index.values())):
            raise ValueError('RS126 requires a valid frozen Nifty benchmark. Create a new run with benchmark history.')
        self.sectors = {i['symbol']: (i.get('sector') or '').strip() for i in instruments}
        self.values = {}
        self.counts = defaultdict(lambda: [0, 0, 0])  # observed, eligible, above
        self.starts = {s: rows[0]['date'] for s, rows in datasets.items() if rows}
        self.sizes = defaultdict(list)
        for symbol, start in self.starts.items():
            self.sizes[self.sectors.get(symbol, '')].append(start)
        for symbol, rows in datasets.items():
            sector = self.sectors.get(symbol, '')
            ranges = []
            values = []
            for i, bar in enumerate(rows):
                prior = rows[i-1]['close'] if i else bar['close']
                ranges.append(max(bar['high']-bar['low'], abs(bar['high']-prior), abs(bar['low']-prior)))
                volume = fsum(b['volume'] for b in rows[i-20:i])/20 if i >= 20 else 0
                atr_pct = fsum(ranges[i-19:i+1])/20/bar['close']*100 if i >= 19 and bar['close'] > 0 else None
                above = bar['close'] > fsum(b['close'] for b in rows[i-49:i+1])/50 if i >= 49 else None
                first = rows[i-126] if i >= 126 else None
                a, z = index.get(first['date']) if first else None, index.get(bar['date'])
                rs126 = ((bar['close']/first['close'])/(z/a)-1)*100 if a and z else None
                values.append(dict(relative_volume=bar['volume']/volume if volume > 0 else None, atr_pct=atr_pct, rs126=rs126))
                for group in (None, sector):
                    count = self.counts[(bar['date'], group)]
                    count[0] += 1
                    count[1] += above is not None
                    count[2] += above is True
            self.values[symbol] = values

    def breadth(self, day, sector=None):
        starts = self.starts.values() if sector is None else self.sizes[sector]
        total = sum(start <= day for start in starts)
        _, eligible, above = self.counts[(day, sector)]
        coverage = eligible/total*100 if total else 0
        breadth = above/eligible*100 if eligible else None
        minimum = 1 if sector is None else self.config.sector_min_peers
        known = bool((sector is None or sector) and eligible >= minimum and coverage >= self.config.breadth_coverage_pct)
        return dict(breadth_pct=breadth, coverage_pct=coverage, eligible=eligible, total=total,
                    status='strong' if known and breadth >= self.config.breadth_threshold_pct else 'weak' if known else 'unknown')

    def rank(self, symbol, i, bar):
        turnover = bar['close']*bar['volume']
        if self.config.candidate_ranking == 'rs_126':
            value = self.values[symbol][i]['rs126']
            return (value is None, -value if value is not None else 0, -turnover, symbol)
        if self.config.candidate_ranking == 'relative_volume':
            relative = self.values[symbol][i]['relative_volume']
            return (-(relative if relative is not None else -1), -turnover, symbol)
        return (-turnover, symbol)

    def allocation(self, symbol, i, day, equity, slots):
        cfg = self.config
        value = self.values[symbol][i]
        sector = self.sectors.get(symbol, '')
        market, sector_state = self.breadth(day), self.breadth(day, sector)
        volatility = 1
        if cfg.target_atr_pct:
            atr = value['atr_pct']
            volatility = min(cfg.max_slot_multiplier, max(.5, cfg.target_atr_pct/atr)) if atr and atr > 0 else .5
        market_scale = 1 if market['status'] == 'strong' else cfg.market_weak_scale
        sector_scale = 1 if sector_state['status'] == 'strong' else cfg.sector_weak_scale
        multiplier = volatility*market_scale*sector_scale*cfg.slot_scale
        budget = min(equity/slots*multiplier, equity*cfg.max_position_pct/100)
        return dict(**value, sector=sector or 'Unknown', market=market, sector_breadth=sector_state,
                    volatility_multiplier=volatility, market_multiplier=market_scale, sector_multiplier=sector_scale,
                    slot_scale=cfg.slot_scale, multiplier=multiplier, requested_budget=budget, signal_date=day)


def allocation_notice(config):
    cfg = AllocationConfig(**{k: getattr(config, k) for k in AllocationConfig.model_fields if hasattr(config, k)})
    return (f'Allocation: {cfg.candidate_ranking} ranking; cash slot multiplier {cfg.slot_scale:g}; ATR(20) target {cfg.target_atr_pct:g}% (0 disables), '
            f'maximum slot multiplier {cfg.max_slot_multiplier:g}; stock cap {cfg.max_position_pct:g}%; '
            f'weak/unknown market and sector multipliers {cfg.market_weak_scale:g}/{cfg.sector_weak_scale:g}; '
            f'sector cap {cfg.max_sector_pct:g}%. Breadth uses completed-session SMA50, '
            f'threshold {cfg.breadth_threshold_pct:g}%, coverage {cfg.breadth_coverage_pct:g}%, '
            f'minimum sector peers {cfg.sector_min_peers}. Current frozen sector labels are retrospectively biased; '
            'missing labels share an Unknown exposure bucket. Relative volume excludes the signal candle from its '
            '20-session average; RS126 is the stock gross return divided by Nifty gross return minus one over 126 stock sessions, using matching dates. Missing RS ranks last, with turnover as tie-breaker. ATR is the simple mean of 20 true ranges. Multipliers affect new entries only; '
            'existing exposure is not rebalanced. This is a sizing heuristic, not a calibrated probability or protective stop.')
