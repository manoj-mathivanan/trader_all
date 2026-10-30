import unittest
try:
    import numpy as np
except ImportError:
    np = None
from datetime import datetime, timezone, timedelta

from scripts.research_four_indicator_early_stop import simulate, paired_diagnostics
from scripts.research_four_indicator_5m import simulate as reference


@unittest.skipIf(np is None, 'Optional NumPy research runtime unavailable')
class EarlyStopTests(unittest.TestCase):
    def fixture(self):
        zone = timezone(timedelta(hours=5,minutes=30))
        stamps = np.array([int(datetime.fromisoformat(t).replace(tzinfo=zone).timestamp()*1000) for t in
                           ('2026-01-02T15:20','2026-01-02T15:25','2026-01-05T09:15','2026-01-05T09:20')])
        prices = np.full((4,2),100.)
        entries = np.array([[1,0],[0,0],[0,0],[0,0]],dtype=bool)
        exits = np.zeros((4,2),dtype=bool)
        cfg = dict(capital=10000.,max_positions=1,slippage_bps=10)
        return prices, prices.copy(), entries, exits, prices.copy(), stamps, ['A','B'], cfg

    def test_disabled_is_exact_reference(self):
        args = self.fixture()
        self.assertEqual(simulate(*args),reference(*args))

    def test_entry_bar_stop_includes_slippage_and_fees(self):
        args = self.fixture()
        low = args[0].copy();low[0,0]=98
        result = simulate(*args,lows=low,stop_pct=1)
        trade = result['trades'][0]
        self.assertAlmostEqual(trade['exit'],100.1*.99*.999)
        self.assertEqual(trade['exit_timestamp'],int(args[5][0])+300000)
        self.assertLess(trade['pnl'],-.01*trade['entry']*trade['quantity'])
        self.assertAlmostEqual(result['metrics']['final_equity'],10000+trade['pnl'])

    def test_overnight_gap_fills_at_worse_open(self):
        args = self.fixture()
        args[0][2:,0]=90
        low = args[0].copy()
        trade = simulate(*args,lows=low,stop_pct=1)['trades'][0]
        self.assertAlmostEqual(trade['exit'],90*.999)
        self.assertEqual(trade['exit_timestamp'],int(args[5][2]))
        self.assertIn('gap',trade['reason'])

    def test_intrabar_proceeds_cannot_fund_same_open_entries(self):
        args = self.fixture()
        args[2][1,1]=True
        low = args[0].copy();low[1,0]=98
        result = simulate(*args,lows=low,stop_pct=1)
        self.assertEqual(len(result['trades']),1)
        self.assertEqual(result['metrics']['skipped_entries'],1)

    def test_next_open_supertrend_exit_precedes_bar_low(self):
        args = self.fixture();args[3][1,0]=True
        low = args[0].copy();low[1,0]=90
        trade = simulate(*args,lows=low,stop_pct=1)['trades'][0]
        self.assertIn('Supertrend',trade['reason'])
        self.assertAlmostEqual(trade['exit'],99.9)

    def test_fixed_entry_diagnostic_counts_sacrificed_winner(self):
        args = self.fixture();args[1][-1,0]=110
        baseline = reference(*args)
        low = args[0].copy();low[0,0]=98
        result = paired_diagnostics(baseline,args[0],low,args[5],args[6],args[7],1)
        self.assertEqual(result['baseline_winners_cut'],1)
        self.assertEqual(result['worsened_trades'],1)
        self.assertLess(result['fixed_entry_delta_pnl'],0)
        import json
        json.dumps(result)


if __name__ == '__main__':
    unittest.main()
