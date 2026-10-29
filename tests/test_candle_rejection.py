import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from core.research.candle_rejection import Rules, exit_trigger, rejection, signals, simulate, size
from scripts.research_candle_rejection import exact_session, prepare_plan


def candles():
    start = datetime.fromisoformat('2025-01-02T09:15:00+05:30')
    return [dict(date='2025-01-02', time=(start+timedelta(minutes=5*i)).strftime('%H:%M'),
                 timestamp=int((start+timedelta(minutes=5*i)).timestamp()*1000),
                 open=101, high=101.3, low=100.9, close=101.1, volume=10000)
            for i in range(75)]


class CandleRejectionTests(unittest.TestCase):
    def setUp(self):
        self.rules = Rules()
        self.bars = candles()
        self.bars[2].update(open=100.8, high=101.2, low=100, close=101)
        self.context = dict(symbol='A', atr=2, previous_low=100, previous_high=105)

    def test_wick_geometry_and_zero_range(self):
        self.assertTrue(rejection(self.bars[2], 1, self.rules))
        self.assertFalse(rejection(self.bars[2], -1, self.rules))
        self.assertFalse(rejection(dict(open=100, high=100, low=100, close=100), 1, self.rules))

    def test_completed_bar_entry_and_no_future_change(self):
        original = signals(self.bars, self.context, 'rejection', 1)
        self.assertIn(3, original)
        self.assertEqual(original[3]['signal_index'], 2)
        self.assertNotIn(2, original)
        self.bars[20].update(high=200, close=199)
        self.assertEqual(signals(self.bars, self.context, 'rejection', 1)[3], original[3])

    def test_confirmation_waits_and_expires(self):
        self.bars[3].update(open=101, high=101.5, low=100.5, close=101.4)
        result = signals(self.bars, self.context, 'confirmation', 1)
        self.assertNotIn(3, result)
        self.assertIn(4, result)
        self.assertEqual(result[4]['signal_index'], 3)
        self.bars[3].update(low=99.9)
        self.assertNotIn(4, signals(self.bars, self.context, 'confirmation', 1))
        self.bars[3].update(low=100.5, close=101)
        self.bars[5].update(high=101.6, close=101.5)
        self.assertNotIn(6, signals(self.bars, self.context, 'confirmation', 1))

    def test_stop_first_gaps_and_time_exit(self):
        position = dict(stop=99, target=103, entry_index=3)
        bar = dict(open=101, high=104, low=98, time='10:00')
        self.assertEqual(exit_trigger(position, bar, 4, 1, self.rules), (99, 'stop', True))
        self.assertEqual(exit_trigger(position, dict(bar, open=98), 4, 1, self.rules), (98, 'gap_stop', False))
        self.assertEqual(exit_trigger(position, dict(bar, time='15:00'), 60, 1, self.rules), (101, 'time_exit', False))
        self.assertEqual(exit_trigger(dict(stop=103,target=99,entry_index=3), bar, 4, -1, self.rules), (103, 'stop', True))

    def test_exact_session_rejects_missing_and_extra_candles(self):
        self.assertEqual(len(exact_session({'bars': self.bars}, '2025-01-02')), 75)
        with self.assertRaises(ValueError):
            exact_session({'bars': self.bars[:-1]}, '2025-01-02')
        with self.assertRaises(ValueError):
            exact_session({'bars': self.bars+[self.bars[-1]]}, '2025-01-02')

    def test_sizing_includes_fees_and_capital_for_both_sides(self):
        from core.research.intraday_costs import upstox_cash_fees
        for sign in (1,-1):
            stop = 100-sign
            qty = size(100, stop, 1_000_000, 100_000, sign, '2025-01-02', .001, self.rules, 1)
            side = 'buy' if sign==1 else 'sell'
            fees = upstox_cash_fees(100,qty,side,'2025-01-02')
            exit_fill = stop*(1-sign*.001)
            total_risk = sign*(100-exit_fill)*qty+fees+upstox_cash_fees(exit_fill,qty,'sell' if sign==1 else 'buy','2025-01-02')
            self.assertLessEqual(100*qty+fees,100_000)
            self.assertLessEqual(total_risk,2500)

    def test_accounting_and_entry_candle_protection(self):
        self.bars[3].update(open=101, high=104, low=99, close=102)
        result = simulate({'A': {'2025-01-02': self.bars}}, {'2025-01-02': [self.context]}, 'rejection', 1, 5)
        first = result['trades'][0]
        self.assertEqual(first['reason'],'stop')
        self.assertEqual(first['entry_timestamp'],first['exit_timestamp'])
        self.assertGreater(first['fees'],0)
        self.assertGreaterEqual(first['entry_timestamp']-first['signal_timestamp'],300000)
        self.assertAlmostEqual(result['metrics']['final_equity']-self.rules.capital, sum(t['pnl'] for t in result['trades']))
        self.assertLessEqual(sum(t['entry']*t['quantity']+t['entry_fee'] for t in result['trades']),self.rules.capital)

    def test_intrabar_exit_cannot_free_same_open_slot(self):
        other = [dict(b) for b in self.bars]
        other[2].update(open=101,low=100.9,high=101.2,close=101)
        other[3].update(open=100.8,low=100,high=101.2,close=101)
        self.bars[4].update(low=98)
        result=simulate({'A':{'2025-01-02':self.bars},'B':{'2025-01-02':other}},
                        {'2025-01-02':[self.context,dict(self.context,symbol='B')]},
                        'rejection',1,5,replace(self.rules,max_positions=1))
        self.assertFalse(any(t['symbol']=='B' and t['entry_time']=='09:35' for t in result['trades']))

    def test_selection_ignores_current_day_volume_and_price(self):
        first=datetime(2025,1,1)
        calendar=[(first+timedelta(days=i)).date().isoformat() for i in range(22)]
        daily={f'A{i:02d}':[dict(date=d,open=100,high=101,low=99,close=100,volume=1_000_000) for d in calendar]
               for i in range(51)}
        day=calendar[-1]
        plan,_=prepare_plan(daily,calendar,day,day)
        self.assertEqual(len(plan[day]),50)
        self.assertNotIn('A50',[c['symbol'] for c in plan[day]])
        daily['A50'][-1].update(volume=10**15,close=1_000_000,high=2_000_000)
        changed,_=prepare_plan(daily,calendar,day,day)
        self.assertEqual(plan,changed)


if __name__ == '__main__':
    unittest.main()
