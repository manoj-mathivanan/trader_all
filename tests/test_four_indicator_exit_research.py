import copy
from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from core.research import four_indicator_swing as fs
from scripts import research_four_indicator_exits as study


class ExitResearchTests(unittest.TestCase):
    def setUp(self):
        start=date(2025,1,1)
        self.bars=[dict(date=str(start+timedelta(days=i)),open=100.,high=101.,low=99.,close=100.,volume=1000)
                   for i in range(108)]
        self.cfg=SimpleNamespace(start=self.bars[100]['date'],end=self.bars[-1]['date'],capital=10000.,
                                 max_positions=1,slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0)
        self.signals=[dict(exit=False,checks=[dict(passed=i==100,value=1) for _ in range(4)]) for i in range(108)]

    def simulate(self,plan,bars=None):
        data={'A':bars or self.bars}
        return study.simulate(data,{'A':self.signals},study.exit_features(data),self.cfg,plan)

    def test_partial_fills_next_open_not_target_and_counts_one_position(self):
        self.bars[101].update(close=130,high=131)
        self.bars[102].update(open=80,close=80,low=79)
        self.bars[-1].update(close=140,high=141)
        r=self.simulate(study.ExitPlan('Partial',partial_profit_pct=20))
        sells=[o for o in r['orders'] if o['side']=='SELL']
        self.assertEqual([(o['quantity'],o['price']) for o in sells],[(50,80),(50,140)])
        self.assertEqual(sells[0]['date'],self.bars[102]['date'])
        self.assertEqual(r['metrics']['trade_count'],1)
        self.assertEqual(r['metrics']['sell_fill_count'],2)
        self.assertEqual(r['metrics']['partial_positions'],1)
        self.assertAlmostEqual(r['metrics']['net_pnl'],1000)

    def test_partial_fees_and_production_baseline_parity(self):
        self.cfg.slippage_bps=self.cfg.buy_cost_bps=self.cfg.sell_cost_bps=10
        data={'A':self.bars}; levels=study.exit_features(data)
        r=study.simulate(data,{'A':self.signals},levels,self.cfg,study.ExitPlan())
        base=fs.simulate(data,{'A':self.signals},self.cfg,fs.RULES[3])
        self.assertEqual(r['curve'],base['curve'])
        for key in base['metrics']:
            if key in r['metrics']:self.assertEqual(r['metrics'][key],base['metrics'][key])
        self.bars[101].update(close=130,high=131)
        partial=self.simulate(study.ExitPlan('Partial',partial_profit_pct=20))
        self.assertEqual(partial['metrics']['partial_positions'],1)
        self.assertAlmostEqual(sum(t['fees'] for t in partial['trades']),partial['metrics']['modeled_fees'])
        self.assertAlmostEqual(sum(t['pnl'] for t in partial['trades']),partial['metrics']['net_pnl'])

    def test_sma_closes_next_session_and_does_not_reenter_same_day(self):
        self.bars[101].update(close=80,low=79)
        self.bars[102]['open']=70
        r=self.simulate(study.ExitPlan('SMA50',sma_days=50))
        self.assertEqual(len(r['trades']),1)
        self.assertEqual(r['trades'][0]['exit_date'],self.bars[102]['date'])
        self.assertEqual(r['trades'][0]['exit'],70)

    def test_atr_ratchets_and_obeys_completed_close(self):
        for i,close in [(101,130),(102,120),(103,110)]:
            self.bars[i].update(close=close,high=close+2,low=close-2)
        self.bars[104]['open']=90
        data={'A':self.bars}; levels=study.exit_features(data)
        for row in levels['A']:row['atr']=5
        plan=study.ExitPlan('ATR3',atr_multiple=3)
        r=study.simulate(data,{'A':self.signals},levels,self.cfg,plan)
        self.assertEqual(r['trades'][0]['exit_date'],self.bars[104]['date'])
        self.assertEqual(r['trades'][0]['exit'],90)
        changed=copy.deepcopy(data);changed['A'][104].update(high=10000,close=9000)
        future=study.simulate(changed,{'A':self.signals},levels,self.cfg,plan)
        self.assertEqual(r['orders'],future['orders'])


if __name__=='__main__':unittest.main()
