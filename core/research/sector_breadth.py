"""Completed-session stock breadth within captured sector classifications."""
from collections import Counter, defaultdict
from core.research import corporate_actions


class SectorBreadth:
    def __init__(self, data, instruments, threshold=40, minimum_coverage=80):
        self.threshold, self.minimum_coverage = threshold, minimum_coverage
        labels = {item['symbol']: item.get('sector', '').strip() for item in instruments}
        self.sectors = {symbol: labels.get(symbol, '') for symbol in data}
        self.sizes = Counter(sector for sector in self.sectors.values() if sector)
        self.counts = defaultdict(lambda: [0, 0])
        for symbol, bars in data.items():
            sector = self.sectors[symbol]
            if not sector:
                continue
            for i in range(199, len(bars)):
                day = bars[i]['date']
                context = corporate_actions.adjusted_bars(bars, day)
                average = sum(row['close'] for row in context[i-199:i+1]) / 200
                count = self.counts[(sector, day)]
                count[0] += 1
                count[1] += context[i]['close'] > average

    def decision(self, symbol, day):
        sector = self.sectors.get(symbol, '')
        total = self.sizes.get(sector, 0)
        eligible, above = self.counts.get((sector, day), (0, 0))
        coverage = eligible / total * 100 if total else 0
        breadth = above / eligible * 100 if eligible else 0
        allowed = bool(total and eligible and coverage >= self.minimum_coverage
                       and breadth >= self.threshold)
        reason = ('missing_sector_mapping' if not total else
                  'insufficient_sector_history' if not eligible or coverage < self.minimum_coverage else
                  'sector_breadth_weak' if breadth < self.threshold else 'allowed')
        return dict(symbol=symbol, day=day, index=sector, sector=sector,
            mapping_method='frozen_current_sector_label', allowed=allowed, reason=reason,
            sector_size=total, eligible_peers=eligible, above_sma200=above,
            coverage_pct=coverage, breadth_pct=breadth)
