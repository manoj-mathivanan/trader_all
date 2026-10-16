import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError
from core.portfolio import paper, manager
from core.research import backtest, banana_reference as ref, fundamentals, store, strategy_presets
from core.research.config import Settings


class ReferencePaperTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(date=str(date(2025,1,1)+timedelta(days=i)),open=100,high=101,
                          low=99,close=100,volume=1000000) for i in range(256)]
        self.rows[0]['listing_metadata'] = dict(listing_date='2025-01-01',ipo_date='2025-01-01',
                                               verified=True,ipo_verified=True,source='test')
        self.rows[253].update(open=99,high=111,low=98,close=110)
        self.rows[254].update(open=110,high=111,low=97,close=99)
        self.rows[255].update(open=96,high=99,low=95,close=98)
        preset=next(p for p in strategy_presets.available() if p['name']=='Banana reference - IPO base')
        self.cfg=paper.PaperConfig(**{**preset['paper_defaults'],'acknowledge_limitations':True,'slippage_bps':0})

    def sim(self, end, state=None, **kwargs):
        cfg=SimpleNamespace(**self.cfg.model_dump(),start=self.rows[253]['date'],end=self.rows[end]['date'])
        with patch.object(ref,'setup_proxy',side_effect=lambda bs,i,c,*a:(i==252,100)):
            return backtest.simulate({'A':self.rows},cfg,state=state,liquidate=False,**kwargs)

    def test_incremental_equals_full_with_pending_sma_exit_and_settlement(self):
        full=self.sim(255)
        first=self.sim(253)
        original=deepcopy(first)
        second=self.sim(254,first['state'])
        self.assertIn('pending',second['state']['positions']['A'])
        final=self.sim(255,second['state'])
        self.assertEqual(final,full)
        self.assertEqual(first,original)
        self.assertGreater(final['state']['unsettled'],0)
        self.assertEqual(len(final['state']['orders']),2)
        # Repeated processing never duplicates trades or orders.
        self.assertEqual(self.sim(255,final['state']),final)

    def test_paused_portfolio_still_exits_and_blocked_entries_are_logged(self):
        first=self.sim(253)
        final=self.sim(255,first['state'],allow_entries=False)
        self.assertEqual(len(final['trades']),1)
        blocked=self.sim(255,entry_check=lambda s,d:False)
        self.assertFalse(blocked['state']['orders'])
        self.assertEqual(blocked['entry_filter_rejections']['Entry eligibility filter'],1)

    def test_slippage_is_charged_on_both_sides(self):
        zero=self.sim(255)
        self.cfg.slippage_bps=10
        costed=self.sim(255)
        self.assertGreater(costed['metrics']['modeled_slippage'],0)
        self.assertGreater(costed['trades'][0]['entry'],zero['trades'][0]['entry'])
        self.assertLess(costed['trades'][0]['exit'],zero['trades'][0]['exit'])
        self.assertLess(costed['metrics']['final_equity'],zero['metrics']['final_equity'])

    def test_legacy_ledger_cannot_enter_reference_engine(self):
        with self.assertRaisesRegex(ValueError,'legacy ledgers'):
            self.sim(255,{'cash':1000000,'positions':{}})

    def test_reference_entry_day_cannot_skip_stop_when_close_is_below_stop(self):
        self.cfg.reference_same_day='reference'
        self.rows[253].update(open=90,high=110,low=80,close=91)
        result=self.sim(255)
        self.assertEqual(result['trades'][0]['exit_date'],self.rows[253]['date'])
        self.assertEqual(result['trades'][0]['exit'],92)

    def test_audit_records_opportunities_before_position_limits(self):
        self.cfg.max_positions=1
        cfg=SimpleNamespace(**self.cfg.model_dump(),start=self.rows[253]['date'],end=self.rows[255]['date'])
        with patch.object(ref,'setup_proxy',side_effect=lambda bs,i,c,*a:(i==252,100)):
            result=backtest.simulate({'A':self.rows,'B':deepcopy(self.rows)},cfg,liquidate=False)
        audit=result['candidate_audit']
        self.assertEqual([(a['symbol'],a['reason']) for a in audit],[('A','Filled'),('B','Book full')])
        self.assertEqual(audit[0]['decision_date'],self.rows[252]['date'])
        self.assertEqual(audit[0]['cash_before'],self.cfg.capital)
        self.assertEqual(audit[1]['positions_before'],1)
        self.assertTrue(all(a['technical_eligible'] for a in audit))
        self.assertEqual(audit[0]['sizing_constraint'],'risk')

    def test_separate_rs_population_does_not_trade_additional_stocks_or_use_future_prices(self):
        cfg=SimpleNamespace(**self.cfg.model_dump(),start=self.rows[253]['date'],end=self.rows[253]['date'])
        peer=deepcopy(self.rows)
        for row in peer[253:]:row['close']=1000000
        with patch.object(ref,'setup_proxy',side_effect=lambda bs,i,c,*a:(i==252,100)):
            result=ref.simulate({'A':self.rows},cfg,rs_data={'A':self.rows,'B':peer})
        self.assertEqual(result['candidate_audit'][0]['rs_population'],2)
        self.assertEqual(result['candidate_audit'][0]['rs'],50)
        self.assertEqual(set(result['state']['positions']),{'A'})
        with self.assertRaisesRegex(ValueError,'exact traded-stock'):
            ref.simulate({'A':self.rows},cfg,rs_data={'B':peer})

    def test_reference_configuration_rejects_midday_and_news_exits(self):
        for values in [dict(investor_news_exits=True),dict(execution_time='midday',run_hour=12),
                       dict(winner_exit='take_8'),dict(candidate_rank='fundamental_score')]:
            with self.assertRaises(ValidationError):
                paper.PaperConfig(**{**self.cfg.model_dump(),**values})

    def test_quarantined_holding_retains_mark_and_quantity(self):
        first=self.sim(253)
        cfg=SimpleNamespace(**self.cfg.model_dump(),start=self.rows[254]['date'],end=self.rows[255]['date'])
        # Another eligible instrument supplies the completed sessions.
        with patch.object(ref,'setup_proxy',return_value=(False,100)):
            r=backtest.simulate({'B':self.rows},cfg,state=first['state'],liquidate=False)
        self.assertEqual(r['state']['positions']['A'],first['state']['positions']['A'])
        self.assertEqual(r['state']['marks']['A'],first['state']['marks']['A'])

    def test_portfolio_cycle_enforces_or_observes_fundamentals_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            universe={'instruments':[{'symbol':'A','isin':'TEST00000001'}]}
            store.write('universes/niftytotalmarket',universe)
            store.write('bars/TEST00000001',{'bars':self.rows,'requested_end':self.rows[-1]['date']})
            clock=datetime.fromisoformat(self.rows[252]['date']+'T17:00:00+05:30')
            screen=fundamentals.BuyScreen().model_dump()
            for identity,mode in [('required','required'),('observe','observe')]:
                cfg=paper.PaperConfig(**{**self.cfg.model_dump(),'fundamental_mode':mode})
                p=manager.save('swing_patterns',cfg,Settings(start='2025-01-01',end=self.rows[-1]['date']),
                               create=True,clock=clock,portfolio_id=identity)
                p['fundamental_screen']=screen
                store.write(manager.key('swing_patterns',identity),p)
            check=dict(buy_allowed=False,score=10,coverage_pct=100,block_reasons=['low score'],snapshot={},screen=screen)
            now=datetime.fromisoformat(self.rows[-1]['date']+'T17:00:00+05:30')
            with patch.object(paper,'local_now',return_value=now),patch.object(fundamentals,'buy_check',return_value=check),\
                 patch.object(ref,'setup_proxy',side_effect=lambda bs,i,c,*a:(i==252,100)):
                paper.cycle(lambda _:None,'required-test',ingest=False,portfolio_id='required')
                paper.cycle(lambda _:None,'observe-test',ingest=False,portfolio_id='observe')
                saved=manager.get('swing_patterns','observe')
                self.assertEqual(paper.cycle(lambda _:None,'retry',ingest=False,portfolio_id='observe')['sessions'],0)
            required=manager.get('swing_patterns','required')
            self.assertFalse(required['ledger']['orders'])
            self.assertEqual(len(saved['ledger']['orders']),2)
            self.assertFalse(saved['cycles'][0]['fundamental_checks'][0]['buy_allowed'])
            self.assertEqual(saved['cycles'][0]['fundamental_checks'][0]['policy'],'observe')
            self.assertNotIn('candidate_audit',saved['ledger'])
            archive=store.read(saved['cycles'][0]['candidate_audit_reference'])
            self.assertEqual(archive['records'][0]['reason'],'Filled')
            self.assertEqual(saved['cycles'][0]['candidate_audit_count'],len(archive['records']))
            self.assertEqual(manager.get('swing_patterns','observe'),saved)
            changed=paper.PaperConfig(**{**saved['config'],'stop_pct':9})
            with self.assertRaisesRegex(ValueError,'separate reference scenario'):
                manager.save('swing_patterns',changed,Settings(start='2025-01-01',end=self.rows[-1]['date']),clock=now,portfolio_id='observe')

if __name__=='__main__':
    unittest.main()
