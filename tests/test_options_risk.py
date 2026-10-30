from datetime import datetime
import unittest

from scripts.analyse_options_risk import drawdown, trade_marks
from core.research.options_costs import fees


class RiskDiagnosisTests(unittest.TestCase):
    def test_drawdown_tracks_peak_and_percent_independently(self):
        result=drawdown([100000,120000,90000,130000,105000])
        self.assertEqual(result,dict(rupees=30000,percent=25))

    def test_marks_include_costs_terminal_exit_and_missing_minutes(self):
        start=int(datetime.fromisoformat('2026-04-08T10:00:00+05:30').timestamp()*1000)
        entry_fee=fees(250,65,'buy','2026-04-08')['total']
        trade=dict(entry_timestamp=start,exit_timestamp=start+180000,
                   entry=250,quantity=65,entry_fee=entry_fee,pnl=-500)
        result,marks=trade_marks(trade,[(start,260,10),(start+60000,240,0)],10)
        expected=(260*.999-250)*65-entry_fee-fees(260*.999,65,'sell','2026-04-08')['total']
        self.assertAlmostEqual(marks[0][1],expected)
        self.assertEqual(marks[0][0],start+60000)
        self.assertEqual(result['missing_or_zero_volume_minutes'],2)
        self.assertEqual(result['adverse_excursion_net'],-500)
        self.assertAlmostEqual(result['favorable_excursion_net'],expected)

    def test_no_marks_still_reports_terminal_loss_without_fabricating_path(self):
        trade=dict(entry_timestamp=0,exit_timestamp=60000,pnl=-100)
        result,marks=trade_marks(trade,[],10)
        self.assertEqual(marks,[])
        self.assertEqual(result['missing_or_zero_volume_minutes'],1)
        self.assertEqual(result['adverse_excursion_net'],-100)
        self.assertEqual(result['favorable_excursion_net'],0)


if __name__=='__main__':
    unittest.main()
