import unittest
from datetime import date, timedelta
from unittest.mock import patch
from pydantic import ValidationError
from core.research.config import BacktestConfig
from core.research.backtest import required_warmup, simulate
from core.research.relative_strength import StrengthHistory
from strategies.swing_patterns.patterns.signals import vcp_setup, vcp


class EmergingStrengthTests(unittest.TestCase):
    def data(self):
        data = {}
        for symbol, prices in [('A', [100]*100 + [110]*10 + [140]*20),
                               ('B', [100+i*.2 for i in range(130)]),
                               ('C', [100-i*.1 for i in range(130)])]:
            data[symbol] = [dict(date=(date(2025, 1, 1)+timedelta(days=i)).isoformat(),
                                 open=p, close=p, high=p+1, low=p-1, volume=10000)
                            for i, p in enumerate(prices)]
        return data

    def cfg(self, **changes):
        return BacktestConfig(**dict(start='2025-04-21', end='2025-04-22', pattern='vcp',
                              entry_mode='next_open', acknowledge_limitations=True,
                              min_short_rs_rating=70, min_rs_improvement=10, **changes))

    def test_historical_percentile_and_future_invariance(self):
        data = self.data()
        cfg = self.cfg()
        day = data['A'][110]['date']
        strength = StrengthHistory(data)
        value = strength.measure('A', day, cfg)
        self.assertEqual(value['short_rs_rating'], 100)
        self.assertEqual(value['prior_short_rs_rating'], 50)
        self.assertEqual(value['rs_improvement'], 50)
        self.assertTrue(strength.passes('A', day, cfg))
        data['B'][111]['close'] = 100000
        self.assertEqual(StrengthHistory(data).measure('A', day, cfg), value)

    def test_missing_history_fails_and_ties_use_midrank(self):
        data = self.data()
        strength = StrengthHistory(data)
        self.assertFalse(strength.passes('A', data['A'][70]['date'], self.cfg()))
        tied = {'A': data['A'], 'B': data['A']}
        self.assertEqual(StrengthHistory(tied).ratings(data['A'][90]['date'], 63), {'A': 50, 'B': 50})
        self.assertEqual(required_warmup(self.cfg()), 83)

    def test_entry_uses_signal_date_not_entry_close(self):
        data = self.data()
        data['B'][111]['close'] = 100000
        with patch('core.research.backtest.signal', return_value=True):
            result = simulate(data, self.cfg(max_positions=1))
        self.assertEqual([t['symbol'] for t in result['trades']], ['A'])
        self.assertEqual(result['trades'][0]['entry_date'], '2025-04-22')

    def test_intraday_cannot_silently_ignore_filters(self):
        with self.assertRaises(ValidationError):
            self.cfg(execution_horizon='intraday')

    def test_split_adjustments_use_each_historical_date(self):
        data = self.data()
        for i, row in enumerate(data['A']):
            row['close'] = 100 if i < 100 else 55
        data['A'][0]['corporate_actions'] = [dict(id='split', ex_date=data['A'][100]['date'],
            share_factor=2, price_basis='raw', volume_basis='raw')]
        value = StrengthHistory(data).measure('A', data['A'][110]['date'], self.cfg())
        self.assertEqual(value['short_rs_rating'], 50)  # +10%, rather than an unadjusted -45%.
        self.assertEqual(value['prior_short_rs_rating'], 50)
        self.assertEqual(value['rs_improvement'], 0)

    def test_watchlist_setup_does_not_buy_before_breakout(self):
        rows = [dict(close=100, high=101, low=99, volume=100) for _ in range(91)]
        for start, high, low, volume in [(60, 110, 90, 100), (70, 105, 95, 80), (80, 101, 99, 20)]:
            for row in rows[start:start+10]:
                row.update(high=high, low=low, volume=volume)
        cfg = self.cfg(min_turnover=0)
        rows[90]['close'] = 100.5
        self.assertTrue(vcp_setup(rows, 90, cfg))
        self.assertFalse(vcp(rows, 90, cfg))
        rows[90].update(close=102, high=103, volume=200)
        self.assertTrue(vcp(rows, 90, cfg))


if __name__ == '__main__':
    unittest.main()
