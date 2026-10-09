import unittest
from copy import deepcopy
from datetime import date, timedelta
from core.research import momentum_indicators as indicators
from tests.test_momentum import session


class IndicatorTests(unittest.TestCase):
    def test_sma_seed_and_recursive_ema(self):
        self.assertEqual(indicators.ema([1,2,3,4],3), [None,None,2,3])

    def context(self):
        history = [(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(14)]
        sessions = {d:session(d,100+i) for i,d in enumerate(history)}
        return sessions, dict(history=history, actions=[]), session('2025-02-03',115)

    def test_no_partial_candle_or_future_information(self):
        sessions, candidate, bars = self.context()
        before = indicators.features(sessions,candidate,'2025-02-03',bars,10,'ema_macd')
        self.assertIsNone(before[0])
        self.assertEqual(before[1],before[2])
        changed = deepcopy(bars)
        for b in changed[4:]:
            b.update(close=1000, high=1001)
        after = indicators.features(sessions,candidate,'2025-02-03',changed,10,'ema_macd')
        self.assertEqual([before[i] for i in range(4)],[after[i] for i in range(4)])
        hourly = indicators.features(sessions,candidate,'2025-02-03',bars,60,'ema')
        self.assertIsNone(hourly[10])
        self.assertEqual(hourly[11]['warmup_candles'],70)
        self.assertEqual(hourly[11],hourly[12])

    def test_missing_bars_and_corporate_action_halt(self):
        sessions,candidate,bars = self.context()
        broken = deepcopy(bars);broken.pop(1)
        with self.assertRaisesRegex(ValueError,'contiguous'):
            indicators.aggregate(broken,10)
        candidate['actions']=[{'ex_date':'2025-01-10'}]
        with self.assertRaisesRegex(ValueError,'corporate action'):
            indicators.features(sessions,candidate,'2025-02-03',bars,10,'ema')

    def test_directional_rules_and_minimum_history(self):
        feature = dict(close=110,ema9=108,ema20=107,previous_ema9=106,
                       macd=1,histogram=.5,previous_histogram=.4)
        self.assertTrue(indicators.accepts(feature,1,'ema_macd'))
        self.assertFalse(indicators.accepts(feature,-1,'ema_macd'))
        mirrored = {k:-v for k,v in feature.items()}
        self.assertTrue(indicators.accepts(mirrored,-1,'ema_macd'))
        sessions,candidate,bars = self.context()
        candidate['history']=candidate['history'][:1]
        with self.assertRaisesRegex(ValueError,'warmup needs'):
            indicators.features(sessions,candidate,'2025-02-03',bars,10,'macd')
