import unittest
from unittest.mock import patch
from core.research import backtest
from core.research.config import BacktestConfig, TradingConfig
from scripts.research_stock_call_accuracy import interval, outcome, summarize


def bars(prices):
    return [dict(date=f'2025-01-{i+1:02}', open=o, high=h, low=l, close=c, volume=1000000)
            for i, (o,h,l,c) in enumerate(prices)]


class AccuracyTests(unittest.TestCase):
    def cfg(self, **changes):
        return TradingConfig(pattern='blue_sky', entry_mode='next_open', stop_pct=8,
                             breakeven_r=1.25, winner_exit='take_15', slippage_bps=0,
                             buy_cost_bps=0, sell_cost_bps=0, **changes)

    def test_natural_target_matches_existing_engine(self):
        rows = bars([(98,100,97,99), (100,108,99,107), (108,120,106,116)])
        cfg = self.cfg()
        result = outcome(rows, 0, cfg)
        self.assertEqual(result['status'], 'correct')
        self.assertAlmostEqual(result['return_pct'], 16)
        engine_cfg = BacktestConfig(**cfg.model_dump(), start='2025-01-01', end='2025-01-03',
                                   acknowledge_limitations=True)
        with patch.object(backtest, 'signal', side_effect=lambda rows,i,cfg: i==0):
            engine = backtest.simulate({'TEST':rows}, engine_cfg)
        trade = engine['trades'][0]
        self.assertEqual((result['entry'], result['exit'], result['reason']),
                         (trade['entry'], trade['exit'], trade['reason']))

    def test_gap_is_filled_at_open(self):
        rows = bars([(99,100,98,99), (100,101,99,100), (85,90,80,86)])
        result = outcome(rows,0,self.cfg())
        self.assertEqual(result['reason'], 'Gap through stop')
        self.assertAlmostEqual(result['return_pct'], -15)

    def test_entry_day_stop_for_next_open(self):
        rows = bars([(99,100,98,99), (100,102,90,101)])
        result = outcome(rows,0,self.cfg())
        self.assertEqual(result['status'],'incorrect')
        self.assertAlmostEqual(result['return_pct'],-8)

    def test_breakeven_activates_next_session(self):
        rows = bars([(99,100,98,99), (100,114,93,111), (105,106,99,100)])
        result = outcome(rows,0,self.cfg())
        self.assertEqual(result['status'],'correct')  # 111 close raises trail to 102.12.
        self.assertAlmostEqual(result['exit'],102.12)

    def test_unfinished_is_censored(self):
        rows = bars([(99,100,98,99), (100,104,99,103)])
        result = outcome(rows,0,self.cfg())
        self.assertEqual(result['status'],'open')
        self.assertIsNone(summarize([result])['accuracy_pct'])
        self.assertEqual(outcome(rows,1,self.cfg())['status'],'no_next_session')

    def test_overlapping_calls_are_both_scored(self):
        rows = bars([(99,100,98,99), (100,104,99,103), (103,120,102,119)])
        calls = [outcome(rows,i,self.cfg()) for i in (0,1)]
        self.assertEqual(summarize(calls)['closed'],2)
        self.assertEqual(summarize(calls)['accuracy_pct'],100)

    def test_confidence_and_flat(self):
        self.assertEqual(interval(0,0),(None,None))
        self.assertLess(interval(1,1)[0],30)
        rows = bars([(99,100,98,99), (100,112,99,111), (101,102,99,100)])
        # Use a smaller trail so the stop stays at the entry price.
        cfg = self.cfg().model_copy(update={'trail_pct':20})
        result = outcome(rows,0,cfg)
        self.assertEqual(result['status'],'flat')
        self.assertEqual(summarize([result])['accuracy_pct'],0)


if __name__ == '__main__':
    unittest.main()
