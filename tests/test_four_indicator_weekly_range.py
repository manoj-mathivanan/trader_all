from datetime import date,timedelta
import unittest

from scripts.research_four_indicator_weekly_range import with_weekly_gate


class FourIndicatorWeeklyGateTests(unittest.TestCase):
    def test_gate_is_causal_and_only_adds_entry_check(self):
        rows=[];day=date(2026,1,5)
        while len(rows)<30:
            if day.weekday()<5:
                rows.append(dict(date=str(day),open=100,high=101,low=99,close=100,volume=1000))
            day+=timedelta(days=1)
        rows[24].update(high=106,close=105)
        features=[dict(checks=[dict(passed=True) for _ in range(4)],entry=True,exit=True,close=r['close']) for r in rows]
        filtered=with_weekly_gate({'X':rows},{'X':features})['X']
        self.assertTrue(filtered[24]['entry'])
        self.assertFalse(filtered[23]['entry'])
        self.assertTrue(all(s['exit'] for s in filtered))
        self.assertTrue(all(len(s['checks'])==4 and s['entry'] for s in features))
        self.assertEqual(with_weekly_gate({'X':rows[:25]},{'X':features[:25]})['X'][-1],filtered[24])
        rows[25]['high']=99999
        self.assertEqual(with_weekly_gate({'X':rows},{'X':features})['X'][24],filtered[24])


if __name__=='__main__':unittest.main()
