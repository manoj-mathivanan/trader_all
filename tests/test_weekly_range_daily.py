from datetime import date, timedelta
import unittest

from core.research.weekly_range_daily import signals, simulate


class WeeklyRangeDailyTests(unittest.TestCase):
    def setUp(self):
        self.rows=[]
        day=date(2026,1,5)
        while len(self.rows)<45:
            if day.weekday()<5:
                self.rows.append(dict(date=str(day),open=100,high=101,low=99,close=100,volume=1000000))
            day+=timedelta(days=1)
        self.rows[24].update(close=105,high=106)

    def replay(self):
        return simulate({'TEST':self.rows},[r['date'] for r in self.rows],
                        self.rows[25]['date'],self.rows[-1]['date'])

    def test_causal_weekly_range(self):
        day=self.rows[24]['date']
        original=signals(self.rows)[day]
        self.assertTrue(original['bullish'])
        self.assertLess(original['last_input_date'],day)
        self.assertEqual(signals(self.rows[:25])[day],original)
        self.rows[25]['high']=99999
        self.assertEqual(signals(self.rows)[day],original)

    def test_gap_below_breakout_skips_entry(self):
        self.assertEqual(self.replay()['trades'],[])

    def test_next_open_entry_and_entry_day_stop(self):
        self.rows[25].update(open=104,high=105,low=90,close=95)
        result=self.replay()
        trade=result['trades'][0]
        self.assertEqual(trade['signal_date'],self.rows[24]['date'])
        self.assertEqual(trade['entry_date'],self.rows[25]['date'])
        self.assertEqual(trade['entry_date'],trade['exit_date'])
        self.assertEqual(trade['reason'],'stop')
        self.assertLess(trade['pnl'],0)
        self.assertEqual(result['curve'][-1]['positions'],0)
        self.assertAlmostEqual(result['curve'][-1]['cash'],1000000+sum(t['pnl'] for t in result['trades']))

    def test_overnight_gap_executes_beyond_stop(self):
        self.rows[25].update(open=104,high=106,low=100,close=105)
        self.rows[26].update(open=90,high=95,low=89,close=92)
        trade=self.replay()['trades'][0]
        self.assertEqual(trade['reason'],'gap_stop')
        self.assertEqual(trade['exit_date'],self.rows[26]['date'])
        self.assertAlmostEqual(trade['exit'],90*.999)
        self.assertLess(trade['exit'],trade['stop'])


if __name__=='__main__':
    unittest.main()
