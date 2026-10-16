import unittest
from copy import deepcopy
from core.research.video_keltner import settle
from core.research.video_costs import reprice,break_even_extra_bps


class CostsTest(unittest.TestCase):
    def fixture(self,direction=1):
        t=dict(date='2026-07-01',symbol='AAA',entry_raw=100,entry=100*(1+direction*.0002),
               stop=100-direction,exit_raw=100+direction*2,market_exit=True,direction=direction,
               exit_legs=[dict(raw=100+direction*2,market=True,index=1)],entry_at=1,exit_at=2)
        return settle(t,50)

    def test_repricing_is_adverse_both_directions_and_preserves_orders(self):
        for d in (1,-1):
            t=self.fixture(d);original=deepcopy(t)
            stressed=reprice([t],1)[0]
            self.assertLess(stressed['net_pnl'],t['net_pnl'])
            for key in ('quantity','entry_at','exit_at','exit_legs','stop'):
                self.assertEqual(stressed[key],t[key])
            self.assertEqual(t,original)
            self.assertAlmostEqual(reprice([t],0)[0]['net_pnl'],t['net_pnl'])

    def test_break_even_brackets_profit_and_handles_losses(self):
        t=self.fixture();edge=break_even_extra_bps([t])
        self.assertGreater(edge,0)
        self.assertGreater(reprice([t],edge-.01)[0]['net_pnl'],0)
        self.assertLess(reprice([t],edge+.01)[0]['net_pnl'],0)
        loser=deepcopy(t);loser['exit_legs'][0]['raw']=98
        self.assertIsNone(break_even_extra_bps([settle(loser,50)]))
        self.assertIsNone(break_even_extra_bps([]))

    def test_limit_exit_does_not_receive_market_exit_slippage(self):
        t=self.fixture();t['exit_legs'][0]['market']=False
        base=reprice([t],0)[0];stress=reprice([t],1)[0]
        self.assertEqual(base['exit'],stress['exit'])
        self.assertLess(stress['net_pnl'],base['net_pnl'])


if __name__=='__main__':unittest.main()
