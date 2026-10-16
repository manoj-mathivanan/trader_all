import unittest
from core.research import failed_breakout as strategy
from tests.test_scalping import session


class FailedBreakoutTests(unittest.TestCase):
    def setUp(self):
        self.day = '2025-02-05'
        self.cfg = strategy.FailedBreakoutConfig(start=self.day, end='2025-02-06',
                    max_stop_pct=5, acknowledge_limitations=True)
        self.candidate = dict(symbol='A', turnover=1e9, history=['2025-02-03', '2025-02-04'], daily_open=100)
        bars = session(self.day, 100, 0)
        for b in bars[:15]:
            b.update(open=100, close=100, high=102, low=98, volume=200000)
        bars[15].update(open=103, close=103.2, high=103.3, low=102.8)
        bars[16].update(open=103.1, close=101.5, high=103.2, low=101.4)
        bars[17].update(open=101.6, close=100.1, high=101.7, low=99.9)
        self.sessions = {'A': {self.day: bars, '2025-02-03': session('2025-02-03',100,0),
                              '2025-02-04': session('2025-02-04',100,0)}}

    def test_completed_reentry_next_open_midpoint_target_and_cash(self):
        plan = strategy.select({self.day: [self.candidate]}, self.sessions, self.cfg)
        report = strategy.simulate({}, self.cfg, self.sessions, plan)
        self.assertEqual(len(report['trades']), 1)
        t = report['trades'][0]
        self.assertEqual(t['direction'], 'short')
        self.assertEqual(t['signal_time'], '09:31')
        self.assertEqual(t['entry_time'], '09:32')
        self.assertEqual(t['target'], 100)
        self.assertEqual(t['reason'], 'Profit target')
        self.assertAlmostEqual(report['metrics']['final_equity'], self.cfg.capital+t['pnl'])

    def test_future_candles_do_not_change_selection_or_signal(self):
        plan = strategy.select({self.day: [self.candidate]}, self.sessions, self.cfg)
        bars, values = strategy.features(self.sessions['A'], plan[self.day][0], self.day, self.cfg)
        original = strategy.signal(bars, values, 16, self.cfg)
        for b in self.sessions['A'][self.day][17:]:
            b.update(close=1e6, high=1e6, volume=1e12)
        revised = strategy.select({self.day: [self.candidate]}, self.sessions, self.cfg)
        self.assertEqual(plan, revised)
        later, values = strategy.features(self.sessions['A'], revised[self.day][0], self.day, self.cfg)
        self.assertEqual(original, strategy.signal(later, values, 16, self.cfg))

    def test_no_signal_before_opening_range_completion(self):
        plan = strategy.select({self.day: [self.candidate]}, self.sessions, self.cfg)
        bars, values = strategy.features(self.sessions['A'], plan[self.day][0], self.day, self.cfg)
        self.assertTrue(all(strategy.signal(bars, values, j, self.cfg) is None for j in range(16)))

    def test_cost_gate_rejects_tiny_reward_and_entry_past_target(self):
        setup = dict(sign=1)
        self.assertFalse(strategy.entry_allowed(setup,100,100.1,100.2,1,self.cfg))
        self.assertFalse(strategy.entry_allowed(setup,101,101.1,100,1,self.cfg))
        self.assertTrue(strategy.entry_allowed(setup,100,100.1,102,1,self.cfg))

    def test_failure_timeout_and_selection_tie(self):
        plan = strategy.select({self.day:[dict(self.candidate,symbol='B'),self.candidate]},
                               {**self.sessions,'B':self.sessions['A']},self.cfg)
        self.assertEqual([c['symbol'] for c in plan[self.day]],['A','B'])
        bars, values = strategy.features(self.sessions['A'], plan[self.day][0], self.day, self.cfg)
        for b in bars[15:21]:
            b.update(open=103,close=103.2,high=103.3,low=102.8)
        bars[21].update(open=103,close=101.5,high=103.2,low=101.4)
        self.assertIsNone(strategy.signal(bars,values,21,self.cfg))

    def test_long_reversal_and_stop_first_for_ambiguous_entry_candle(self):
        for bars in self.sessions['A'].values():
            for b in bars:
                b.update(open=200-b['open'], close=200-b['close'], high=200-b['low'], low=200-b['high'])
        plan = strategy.select({self.day:[self.candidate]},self.sessions,self.cfg)
        report = strategy.simulate({},self.cfg,self.sessions,plan)
        self.assertEqual(report['trades'][0]['direction'],'long')
        self.assertEqual(report['trades'][0]['target'],100)
        self.assertEqual(report['trades'][0]['reason'],'Profit target')
        self.sessions['A'][self.day][17].update(high=101,low=96)
        stopped = strategy.simulate({},self.cfg,self.sessions,plan)
        self.assertEqual(stopped['trades'][0]['reason'],'Failed-breakout stop loss')
        self.assertEqual(stopped['metrics']['ambiguous_stop_target_bars'],1)

    def test_next_open_beyond_midpoint_is_rejected(self):
        plan = strategy.select({self.day:[self.candidate]},self.sessions,self.cfg)
        self.sessions['A'][self.day][17].update(open=99,close=99,high=100,low=98)
        result = strategy.simulate({},self.cfg,self.sessions,plan)
        self.assertEqual(result['metrics']['trade_count'],0)


if __name__ == '__main__':
    unittest.main()
