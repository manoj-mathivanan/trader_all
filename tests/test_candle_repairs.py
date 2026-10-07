import unittest
from copy import deepcopy
from core.research import candle_repairs, market_history, data_quality
from core.portfolio import paper
from datetime import date, timedelta


class CandleRepairTests(unittest.TestCase):
    def fixture(self):
        ref = market_history.evidence()
        repair = ref['candle_repairs']['INE03QK01018']['rows'][-1]
        bars = [{'date': repair['date'], 'timestamp': 123, **repair['expected']},
                {'date': '2020-03-24', 'open':87.6, 'high':108.2, 'low':87.6, 'close':103.55, 'volume':595554}]
        return bars, repair, ref

    def test_sourced_derived_repair_removes_false_gap_without_changing_cache(self):
        bars, repair, ref = self.fixture()
        original = deepcopy(bars)
        self.assertEqual(len(data_quality.audit({'COHANCE': bars})['findings']), 1)
        derived, history = market_history.prepare({'isin':'INE03QK01018','symbol':'COHANCE'}, {'bars':bars}, reference=ref)
        self.assertEqual(bars, original)
        self.assertEqual(derived[0]['close'],109.5)
        self.assertEqual(derived[0]['volume'],27914)
        self.assertEqual(derived[0]['timestamp'],123)
        self.assertEqual(data_quality.audit({'COHANCE':derived})['findings'],[])
        self.assertEqual(history['candle_repairs'],[repair])
        self.assertNotEqual(history['source_sha256'],history['derived_sha256'])

    def test_idempotence_and_revision_mismatch(self):
        bars, repair, _ = self.fixture()
        fixed, evidence = candle_repairs.apply(bars,[repair])
        again, same = candle_repairs.apply(fixed,[repair])
        self.assertEqual(fixed,again)
        self.assertEqual(evidence,same)
        bars[0]['close'] += 0.1
        with self.assertRaisesRegex(ValueError,'no longer matches'):
            candle_repairs.apply(bars,[repair])

    def test_invalid_evidence_rejected_before_use(self):
        bars, repair, _ = self.fixture()
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            candle_repairs.apply(bars,[repair,repair])
        bad = deepcopy(repair); bad['replacement']['volume'] = float('nan')
        with self.assertRaises(ValueError):
            candle_repairs.apply(bars,[bad])
        bad = deepcopy(repair); bad['replacement']['low'] = bad['replacement']['high']+1
        with self.assertRaises(ValueError):
            candle_repairs.apply(bars,[bad])

    def test_paper_history_change_requires_reconciliation_but_future_repairs_do_not(self):
        _, repair, _ = self.fixture()
        current = {'candle_repairs':[repair]}
        with self.assertRaisesRegex(ValueError,'Ledger unchanged'):
            candle_repairs.reconcile({},current,'2026-10-01')
        with self.assertRaises(ValueError):
            candle_repairs.reconcile(current,{},'2026-10-01')
        candle_repairs.reconcile(current,current,'2026-10-01')
        candle_repairs.reconcile({},current,'2020-03-20')
        candle_repairs.reconcile({},current,'2026-10-01',relevant_from='2025-01-01')
        with self.assertRaises(ValueError):
            candle_repairs.reconcile({},current,'2026-10-01',relevant_from=repair['date'])

    def test_context_covers_previous_patterns_market_gate_and_trailing_exit(self):
        rows = [{'date': (date(2020,1,1)+timedelta(days=i)).isoformat()} for i in range(700)]
        cfg = paper.PaperConfig(capital=100000,acknowledge_limitations=True)
        p = {'start_session':rows[600]['date'], 'cycles':[{'start':rows[600]['date'],'config':cfg.model_dump()}]}
        self.assertEqual(paper.repair_context_start(p,rows,cfg),rows[549]['date'])
        cfg.skip_weak_markets = True
        self.assertEqual(paper.repair_context_start(p,rows,cfg),rows[399]['date'])
        cfg.skip_weak_markets = False; cfg.winner_exit = 'trail_30w'
        self.assertEqual(paper.repair_context_start(p,rows,cfg),rows[449]['date'])
        p['cycles'][0]['config']['pattern'] = 'blue_sky'
        self.assertEqual(paper.repair_context_start(p,rows,cfg),rows[0]['date'])
        p['cycles'] = []
        self.assertIsNone(paper.repair_context_start(p,rows,cfg))

    def test_verified_replay_is_bound_to_entire_checkpoint_and_repair_policy(self):
        p = {'id':'test', 'ledger':{'cash':100}, 'config':{'pattern':'blue_sky'},
             'fingerprints':{'COHANCE':'input-hash'}, 'cycles':[], 'start_session':'2026-10-05',
             'universe_snapshot':{'instruments':[]}}
        ref = market_history.evidence()
        record = {**candle_repairs.checkpoint_identity(p,ref), 'result':'identical_ledgers'}
        self.assertTrue(candle_repairs.reconciliation_matches(record,p,ref))
        changed = deepcopy(p); changed['ledger']['cash'] += 1
        self.assertFalse(candle_repairs.reconciliation_matches(record,changed,ref))
        changed = deepcopy(p); changed['config']['pattern'] = 'vcp'
        self.assertFalse(candle_repairs.reconciliation_matches(record,changed,ref))
        changed = deepcopy(ref); changed['candle_repairs']['INE03QK01018']['rows'][0]['replacement']['close'] += 1
        self.assertFalse(candle_repairs.reconciliation_matches(record,p,changed))
        self.assertFalse(candle_repairs.reconciliation_matches({},p,ref))
