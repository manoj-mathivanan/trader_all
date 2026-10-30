import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.research import store, four_indicator_swing as fs
from core.research.config import Settings
from core.portfolio import four_indicator_paper as paper, manager
from tests.test_four_indicator_swing import rows


class MissingUnheldTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for p in [patch.dict(os.environ,{'TRADER_STORAGE':'json'}),patch.object(store,'DATA',Path(temp.name))]:
            p.start();self.addCleanup(p.stop)
        self.rows=rows()
        self.universe={'instruments':[dict(symbol=s,isin=s) for s in ('A','B')]}
        cfg=paper.PaperConfig(start_session=self.rows[100]['date'])
        paper.save(cfg,Settings(),create=True,portfolio_id='test')
        initial=self.rows[:105]
        frozen=dict(datasets={s:copy.deepcopy(initial) for s in ('A','B')},universe=self.universe,excluded=[],exclusion_reasons={})
        store.write('bars/NIFTY50',{'bars':initial})
        self.features=patch.object(fs,'features',side_effect=lambda data,*a,**kw:{s:[None]*len(b) for s,b in data.items()})
        self.features.start();self.addCleanup(self.features.stop)
        with patch.object(fs,'prepare',return_value=frozen):
            paper.cycle(lambda _:None,'initial',ingest=False,portfolio_id='test')
        self.before=manager.get(fs.STRATEGY,'test')
        store.write('bars/NIFTY50',{'bars':self.rows})
        store.write('bars/A',{'bars':self.rows})
        store.write('bars/B',{'bars':initial})

    def cycle(self):
        with patch.object(paper.market_history,'evidence',return_value={}), \
             patch.object(paper.market_history,'prepare',side_effect=lambda item,record,**kw:(record['bars'],{})):
            return paper.cycle(lambda _:None,'next',ingest=False,portfolio_id='test')

    def test_unheld_missing_stock_is_audited_and_other_prices_advance_without_rewriting_history(self):
        result=self.cycle();after=manager.get(fs.STRATEGY,'test')
        self.assertEqual(result['sessions'],5)
        self.assertEqual(after['ledger']['last_session'],self.rows[-1]['date'])
        self.assertEqual(after['ledger']['curve'][:5],self.before['ledger']['curve'])
        frozen=store.read(after['input_reference'])
        self.assertNotIn('B',frozen['datasets'])
        self.assertIn('B',frozen['excluded'])
        self.assertEqual(frozen['suspended_inputs']['B']['missing_sessions'],[r['date'] for r in self.rows[105:]])
        self.assertIn('B',store.read(self.before['input_reference'])['datasets'])
        self.assertEqual(paper.cycle(lambda _:None,'repeat',ingest=False,portfolio_id='test')['sessions'],0)

    def test_held_missing_stock_stops_and_preserves_the_entire_ledger(self):
        held=copy.deepcopy(self.before);held['ledger']['positions']['B']={'quantity':1}
        store.write(manager.key(fs.STRATEGY,'test'),held)
        with self.assertRaisesRegex(ValueError,'B: missing completed-session'):
            self.cycle()
        self.assertEqual(manager.get(fs.STRATEGY,'test'),held)

    def test_partial_gap_is_not_suspended_using_future_knowledge(self):
        store.write('bars/B',{'bars':self.rows[:107]})
        with self.assertRaisesRegex(ValueError,'B: missing completed-session'):
            self.cycle()
        self.assertEqual(manager.get(fs.STRATEGY,'test'),self.before)

    def test_old_price_revision_still_stops_even_for_an_unheld_stock(self):
        revised=copy.deepcopy(self.rows[:105]);revised[-1]['close']+=1
        store.write('bars/B',{'bars':revised})
        with self.assertRaisesRegex(ValueError,'previously processed inputs changed'):
            self.cycle()
        self.assertEqual(manager.get(fs.STRATEGY,'test'),self.before)
