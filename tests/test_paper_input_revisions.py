import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.research import store, intraday_data, four_indicator_swing as fs
from core.research.config import Settings
from core.portfolio import paper_input_revisions as revisions, four_indicator_paper as paper, manager
from tests.test_four_indicator_swing import rows


class RevisionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for p in [patch.dict(os.environ,{'TRADER_STORAGE':'json'}),patch.object(store,'DATA',Path(temp.name))]:
            p.start();self.addCleanup(p.stop)
        self.day='2026-10-29';self.item=dict(symbol='A',isin='A')
        raw=[[f'{self.day}T{m//60:02d}:{m%60:02d}:00+05:30',100,102,99,101,1] for m in range(555,930,5)]
        minute=intraday_data.normalize(raw,self.day)
        self.old=dict(date=self.day,timestamp=minute[0]['timestamp']-555*60000,open=100.,high=102.,low=99.,close=101.,volume=75.)
        self.published=dict(self.old,close=101.5,volume=76.)
        self.new=dict(self.old,date='2026-10-30',timestamp=self.old['timestamp']+86400000)
        self.frozen=dict(captured_at='2026-10-30T00:00:00+00:00',history={})
        self.record=dict(source='upstox_v3',provisional_daily={'2026-10-30':{'provisional':True}})
        self.minute=dict(source='Upstox current session V3',complete_session=True,
                         fetched_at='2026-10-29T12:00:00+00:00',bars=minute)
        store.write('intraday/5m/A/'+self.day,self.minute)

    def reconcile(self, frozen=None, current=None):
        return revisions.reconcile(self.frozen if frozen is None else frozen,'A',self.item,[self.old],
                                   current or [self.published,self.new],self.record)

    def test_verified_legacy_provisional_is_frozen_and_new_session_appended_with_audit(self):
        result,count=self.reconcile()
        self.assertEqual(result,[self.old,self.new]);self.assertEqual(count,1)
        audit=self.frozen['published_input_reconciliations']['A/'+self.day]
        self.assertEqual(audit['differences']['volume'],{'recorded':75.,'published':76.})
        self.assertEqual(audit['differences']['close'],{'recorded':101.,'published':101.5})
        self.assertEqual(self.reconcile()[1],0)
        self.assertEqual(len(self.frozen['published_input_reconciliations']),1)

    def test_explicit_captured_provenance_does_not_need_disposable_minute_cache(self):
        self.frozen['history']={'A':{'provisional_daily':{self.day:{'provisional':True}}}}
        with patch.object(store,'read',return_value={}):
            self.assertEqual(self.reconcile()[0][0],self.old)

    def test_unproven_revision_and_incomplete_or_late_evidence_stop(self):
        variants=[{},dict(self.minute,bars=self.minute['bars'][:-1]),
                  dict(self.minute,fetched_at='2026-10-30T01:00:00+00:00')]
        for record in variants:
            with self.subTest(record=record.keys()),patch.object(store,'read',return_value=record):
                with self.assertRaisesRegex(ValueError,'previously processed inputs changed'):
                    self.reconcile(copy.deepcopy(self.frozen))

    def test_second_published_revision_still_stops(self):
        self.reconcile()
        with self.assertRaisesRegex(ValueError,'revised again'):
            self.reconcile(current=[dict(self.published,volume=77),self.new])

    def test_published_reversion_to_original_values_still_stops(self):
        self.reconcile()
        with self.assertRaisesRegex(ValueError,'revised again'):
            self.reconcile(current=[self.old,self.new])

    def test_identical_first_publication_is_recorded_before_any_later_revision(self):
        self.frozen['history']={'A':{'provisional_daily':{self.day:{'provisional':True}}}}
        result,count=self.reconcile(current=[self.old,self.new])
        self.assertEqual(result,[self.old,self.new]);self.assertEqual(count,1)
        self.assertEqual(self.frozen['published_input_reconciliations']['A/'+self.day]['differences'],{})
        with self.assertRaisesRegex(ValueError,'revised again'):
            self.reconcile()

    def test_date_and_timestamp_revisions_still_stop(self):
        with self.assertRaisesRegex(ValueError,'input dates changed'):
            self.reconcile(current=[self.new])
        with self.assertRaisesRegex(ValueError,'previously processed inputs changed'):
            self.reconcile(current=[dict(self.published,timestamp=0),self.new])

    def test_still_provisional_changes_are_not_treated_as_publication(self):
        self.record['provisional_daily'][self.day]={'provisional':True}
        with self.assertRaisesRegex(ValueError,'previously processed inputs changed'):
            self.reconcile()

    def test_capture_adds_only_new_session_provenance(self):
        self.record['provisional_daily'][self.day]={'provisional':True}
        revisions.capture_provisional(self.frozen,'A',self.record,self.day,'2026-10-30')
        self.assertEqual(set(self.frozen['history']['A']['provisional_daily']),{'2026-10-30'})

    def test_benchmark_uses_the_same_reconciliation_policy(self):
        store.write('intraday/5m/NIFTY50/'+self.day,self.minute)
        result,count=revisions.reconcile(self.frozen,'NIFTY50',{'isin':'NIFTY50'},[self.old],
                                         [self.published,self.new],self.record)
        self.assertEqual(count,1);self.assertEqual(result[0],self.old)

    def test_cycle_keeps_existing_fills_positions_and_equity_history(self):
        bars=rows();initial=bars[:105];item=dict(symbol='A',isin='A')
        cfg=paper.PaperConfig(start_session=bars[100]['date'])
        paper.save(cfg,Settings(),create=True,portfolio_id='test')
        frozen=dict(datasets={'A':copy.deepcopy(initial)},universe={'instruments':[item]},
                    history={'A':{'provisional_daily':{initial[-1]['date']:{'provisional':True}}}},excluded=[],exclusion_reasons={})
        def features(data,*args,**kwargs):
            values={s:[None]*len(r) for s,r in data.items()}
            values['A'][100]=dict(exit=False,close=201,checks=[dict(passed=True,value=1) for _ in range(4)])
            return values
        store.write('bars/NIFTY50',{'bars':initial})
        with patch.object(fs,'features',side_effect=features),patch.object(fs,'prepare',return_value=frozen):
            paper.cycle(lambda _:None,'first',ingest=False,portfolio_id='test')
        before=manager.get(fs.STRATEGY,'test')
        self.assertIn('A',before['ledger']['positions'])
        revised=copy.deepcopy(bars);revised[104]['close']+=.25;revised[104]['volume']+=1
        store.write('bars/NIFTY50',{'bars':bars});store.write('bars/A',dict(bars=revised,source='upstox_v3',
                    provisional_daily={bars[-1]['date']:{'provisional':True}}))
        with patch.object(fs,'features',side_effect=features),patch.object(paper.market_history,'evidence',return_value={}), \
             patch.object(paper.market_history,'prepare',side_effect=lambda i,r,**kw:(r['bars'],{})):
            paper.cycle(lambda _:None,'next',ingest=False,portfolio_id='test')
        after=manager.get(fs.STRATEGY,'test');saved=store.read(after['input_reference'])
        self.assertEqual(after['ledger']['last_session'],bars[-1]['date'])
        for key in ('positions','orders','trades'):
            self.assertEqual(after['ledger'][key],before['ledger'][key])
        self.assertEqual(after['ledger']['curve'][:5],before['ledger']['curve'])
        self.assertEqual(saved['datasets']['A'][104],initial[104])
        self.assertIn(bars[-1]['date'],saved['history']['A']['provisional_daily'])
        self.assertEqual(fs.digest(store.read(before['input_reference'])),before['cycles'][-1]['input_sha256'])
