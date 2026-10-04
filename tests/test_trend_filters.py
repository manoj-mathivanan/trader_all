import unittest
from core.research.config import BacktestConfig
from core.research.backtest import required_warmup
from strategies.swing_patterns.patterns.signals import _trend_and_liquidity


class TrendFilterTests(unittest.TestCase):
    def cfg(self, **changes):
        return BacktestConfig(start='2025-04-01',end='2025-12-31',
                              acknowledge_limitations=True, min_turnover=0, **changes)

    def bars(self, prices):
        return [dict(close=p,volume=1000000) for p in prices]

    def test_short_rebound_in_long_downtrend_rejected(self):
        bars=self.bars([200-i*.5 for i in range(200)]+[110]*20+[115])
        self.assertTrue(_trend_and_liquidity(bars,220,self.cfg()))
        self.assertFalse(_trend_and_liquidity(bars,220,self.cfg(require_long_trend=True)))

    def test_rising_long_trend_uses_only_completed_prefix(self):
        bars=self.bars([100+i for i in range(220)])
        cfg=self.cfg(require_rising_long_trend=True)
        self.assertTrue(_trend_and_liquidity(bars,219,cfg))
        bars.extend(self.bars([1]*100))
        self.assertTrue(_trend_and_liquidity(bars,219,cfg))
        self.assertEqual(required_warmup(cfg),220)

    def test_price_rebound_above_falling_average_not_rising_trend(self):
        bars=self.bars([300-i for i in range(219)]+[400])
        self.assertTrue(_trend_and_liquidity(bars,219,self.cfg(require_long_trend=True)))
        self.assertFalse(_trend_and_liquidity(bars,219,self.cfg(require_rising_long_trend=True)))

if __name__=='__main__':
    unittest.main()
