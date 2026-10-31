import copy
from datetime import date,timedelta
import unittest

from core.research import four_indicator_swing as fs
from core.portfolio.four_indicator_paper import PaperConfig
from scripts.research_four_indicator_selection import SelectionFeatures,Plan,simulate


class RSPaperTests(unittest.TestCase):
    def setUp(self):
        start=date(2025,1,1)
        rows=[dict(date=str(start+timedelta(days=i)),timestamp=i*86400000,open=100+i,
                   high=102+i,low=99+i,close=101+i,volume=1000) for i in range(150)]
        self.data={'A':rows,'B':[dict(b,close=b['close']+i*.5) for i,b in enumerate(rows)]}
        self.index=[dict(b,close=100+i*.1) for i,b in enumerate(rows)]
        self.items=[dict(symbol=s,sector='IT') for s in self.data]
        self.cfg=fs.SwingConfig(start=rows[130]['date'],end=rows[-1]['date'],capital=100000,max_positions=1)
        self.signals={s:[dict(close=b['close'],exit=i==140,checks=[dict(passed=i in (130,144),value=100) for _ in range(4)])
                         for i,b in enumerate(bars)] for s,bars in self.data.items()}

    def test_rs126_and_smaller_slots_match_research_with_open_holdings(self):
        for rank,scale in [('turnover',1),('rs_126',1),('rs_126',.75)]:
            cfg=self.cfg.model_copy(update=dict(candidate_ranking=rank,slot_scale=scale))
            actual=fs.simulate(self.data,self.signals,cfg,fs.RULES[3],liquidate=False,instruments=self.items,benchmark=self.index)
            context=SelectionFeatures(self.data,self.index,self.items,self.cfg)
            expected=simulate(self.data,self.signals,self.cfg,context,Plan(rank_sessions=126 if rank=='rs_126' else 0),liquidate=False,slot_scale=scale)
            self.assertEqual(actual['curve'],expected['curve'])
            self.assertEqual(actual['metrics'],expected['metrics'])
            self.assertEqual(set(actual['ledger']['positions']),set(expected['ledger']['positions']))
            self.assertEqual(actual['ledger']['cash'],expected['ledger']['cash'])

    def test_rs126_incremental_paper_is_identical_to_full_replay(self):
        cfg=self.cfg.model_copy(update=dict(candidate_ranking='rs_126',slot_scale=.75))
        full=fs.simulate(self.data,self.signals,cfg,fs.RULES[3],liquidate=False,benchmark=self.index)
        first=fs.simulate(self.data,self.signals,cfg.model_copy(update={'end':date.fromisoformat(self.index[139]['date'])}),fs.RULES[3],liquidate=False,benchmark=self.index[:140])
        second=fs.simulate(self.data,self.signals,cfg.model_copy(update={'start':date.fromisoformat(self.index[140]['date'])}),fs.RULES[3],
                           liquidate=False,benchmark=self.index,state=first['ledger'],entry_start=cfg.start)
        self.assertEqual(full,second)

    def test_rs_requires_captured_benchmark_and_ignores_future_prices(self):
        cfg=self.cfg.model_copy(update=dict(candidate_ranking='rs_126'))
        with self.assertRaisesRegex(ValueError,'frozen Nifty'):
            fs.simulate(self.data,self.signals,cfg,fs.RULES[3])
        result=fs.simulate(self.data,self.signals,cfg,fs.RULES[3],liquidate=False,benchmark=self.index)
        index=copy.deepcopy(self.index);index[-1]['close']*=100
        changed=fs.simulate(self.data,self.signals,cfg,fs.RULES[3],liquidate=False,benchmark=index)
        self.assertEqual(result,changed)

    def test_paper_schema_exposes_ranking_and_slot_scale(self):
        c=PaperConfig(start_session='2026-10-12',candidate_ranking='rs_126',slot_scale=.75)
        self.assertEqual(c.slot_scale,.75)
        self.assertIn('rs_126',PaperConfig.model_json_schema()['properties']['candidate_ranking']['enum'])


if __name__=='__main__':unittest.main()
