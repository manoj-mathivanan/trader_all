import tempfile
import unittest
from pathlib import Path
from datetime import datetime, date
from unittest.mock import Mock, patch
from core.research import store
from core.portfolio import refresh_followup as followup, four_indicator_paper as paper, scheduler


class FollowupTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        p=patch.object(store,'DATA',Path(directory.name));p.start();self.addCleanup(p.stop)
        store.write(followup.KEY,dict(enabled=True,strategy_ids=['four_indicator_swing']))
        self.refresh=dict(completed_at='2026-10-30T01:00:00Z',daily_symbols=750,minute_symbols=751,partial=True)
        self.portfolios=[dict(id='a',config={'auto_run':True,'name':'A'}),dict(id='b',config={'auto_run':True,'name':'B'}),dict(id='manual',config={'auto_run':False})]

    def test_warning_refresh_runs_both_portfolios_on_cached_data_and_receipts_prevent_duplicates(self):
        with patch.object(followup.manager,'list_portfolios',return_value=self.portfolios), \
             patch.object(paper,'cycle',return_value={'sessions':1}) as cycle:
            self.assertEqual(len(followup.run(Mock(),'morning',self.refresh)),2)
            self.assertEqual(cycle.call_count,2)
            self.assertFalse(cycle.call_args.kwargs['ingest'])
            self.assertEqual(followup.run(Mock(),'morning',self.refresh),[])
            self.assertEqual(cycle.call_count,2)
            self.assertEqual(len(followup.run(Mock(),'evening',self.refresh)),2)
            self.assertEqual(cycle.call_count,4)

    def test_failed_or_unfinished_refresh_does_not_run_paper(self):
        with patch.object(paper,'cycle') as cycle:
            for result in [dict(self.refresh,daily_symbols=0,minute_symbols=0),dict(daily_symbols=750)]:
                self.assertEqual(followup.run(Mock(),'job',result),[])
            cycle.assert_not_called()

    def test_failure_of_one_portfolio_does_not_block_the_other(self):
        with patch.object(followup.manager,'list_portfolios',return_value=self.portfolios), \
             patch.object(paper,'cycle',side_effect=[ValueError('Missing held-stock candle'),{'sessions':1}]):
            results=followup.run(Mock(),'job',self.refresh)
        self.assertEqual([r['status'] for r in results],['failed','success'])
        self.assertEqual(store.read('paper_refresh_cycles/a/job')['message'],'Missing held-stock candle')

    def test_legacy_scheduler_does_not_submit_an_independent_indicator_cycle(self):
        p=dict(id='a',config=dict(auto_run=True,run_hour=16,run_minute=15))
        with patch.object(scheduler.manager,'list_portfolios',return_value=[p]), \
             patch.object(scheduler.paper,'local_now',return_value=datetime(2026,10,30,17,tzinfo=paper.paper.IST)), \
             patch.object(scheduler,'registry') as registry,patch.object(scheduler.jobs,'submit') as submit:
            registry.PLUGINS={'four_indicator_swing':Mock(trigger_mode='batch')}
            scheduler.tick()
            submit.assert_not_called()

    def test_paper_uses_today_only_after_completed_session_cutoff(self):
        cfg=paper.PaperConfig(start_session='2026-10-12')
        store.write('portfolio_scenarios/four_indicator_swing/a',dict(id='a',config=cfg.model_dump(mode='json'),ledger={},cycles=[],universe='niftytotalmarket'))
        store.write('bars/NIFTY50',{'bars':[{'date':'2026-10-29'},{'date':'2026-10-30'}]})
        for hour,expected in [(6,date(2026,10,29)),(17,date(2026,10,30))]:
            clock=datetime(2026,10,30,hour,tzinfo=paper.paper.IST)
            with patch.object(paper.paper,'local_now',return_value=clock), \
                 patch.object(paper.fs,'prepare',side_effect=ValueError('probe')) as prepare:
                with self.assertRaisesRegex(ValueError,'probe'):
                    paper.cycle(Mock(),'job',ingest=False,portfolio_id='a')
                self.assertEqual(prepare.call_args.args[1].end,expected)


if __name__=='__main__':
    unittest.main()
