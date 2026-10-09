import unittest
from copy import deepcopy
from datetime import datetime
from core.research import momentum, fundamental_history
from tests import test_momentum as fixtures
from tests.test_company_review import financial


class MomentumFundamentalTests(unittest.TestCase):
    def test_relaxed_age_replaces_only_default_freshness_warning(self):
        f=fixtures.MomentumTests();f.setUp()
        f.cfg.fundamental_min_score=40;f.cfg.fundamental_min_coverage_pct=50
        f.cfg.fundamental_max_age_days=365
        value=dict(score=45,coverage_pct=55,period_age_days=250,
                   flags=['Financial period is more than 180 days old'])
        self.assertTrue(momentum.fundamental_gate(value,f.cfg)['allowed'])
        self.assertFalse(momentum.fundamental_gate({**value,'period_age_days':366},f.cfg)['allowed'])
        self.assertFalse(momentum.fundamental_gate({**value,'flags':value['flags']+['Auditor concern']},f.cfg)['allowed'])

    def test_gate_blocks_missing_weak_stale_incomplete_and_flagged(self):
        f=fixtures.MomentumTests();f.setUp()
        good=dict(score=70,coverage_pct=90,period_age_days=40,flags=[])
        self.assertTrue(momentum.fundamental_gate(good,f.cfg)['allowed'])
        for value in [None,{**good,'score':None},{**good,'score':59},
                      {**good,'coverage_pct':79},{**good,'period_age_days':181},
                      {**good,'flags':['Auditor concern']}]:
            self.assertFalse(momentum.fundamental_gate(value,f.cfg)['allowed'])

    def test_entry_gate_applies_to_actual_long_and_short_positions(self):
        for mode in ['follow','reverse']:
            f=fixtures.MomentumTests();f.setUp()
            f.cfg.require_fundamentals=True;f.cfg.execution_mode=mode
            calls=[]
            def scores(symbol,day,time):
                calls.append((symbol,day,time))
                return dict(score=None,coverage_pct=0,flags=['No evidence'])
            result=momentum.simulate(f.daily,f.cfg,f.minutes,f.plan,fundamental_scores=scores)
            self.assertEqual(result['trades'],[])
            self.assertEqual(calls,[('A','2025-02-03','09:25')])
            self.assertEqual(result['diagnostics']['fundamental_missing_entries'],1)
            self.assertEqual(result['diagnostics']['fundamental_checks'][0]['direction'],'long' if mode=='follow' else 'short')
        good=lambda *args:dict(score=70,coverage_pct=90,period_age_days=40,flags=[])
        result=momentum.simulate(f.daily,f.cfg,f.minutes,f.plan,fundamental_scores=good)
        self.assertEqual(len(result['trades']),1)
        self.assertTrue(result['trades'][0]['fundamentals']['allowed'])
        with self.assertRaisesRegex(ValueError,'Historical fundamental evidence'):
            momentum.simulate(f.daily,f.cfg,f.minutes,f.plan)

    def test_same_day_filing_not_available_until_its_publication_time(self):
        published='2025-02-03T10:00:00+05:30'
        snapshot=financial(period_end='2024-12-31',source=dict(title='Results',url='https://example.com/results',published_at=published))
        payload=dict(series={'A':[dict(available_at=published,snapshot=snapshot)]})
        payload['sha256']=fundamental_history.digest(payload)
        scores=fundamental_history.Scores(payload)
        early=scores('A','2025-02-03',at=datetime.fromisoformat('2025-02-03T09:25:00+05:30'))
        later=scores('A','2025-02-03',at=datetime.fromisoformat('2025-02-03T10:05:00+05:30'))
        self.assertIsNone(early['score'])
        self.assertEqual(later['score'],100)
        self.assertEqual(later['available_at'],published)
        self.assertIsNone(scores('A','2025-02-03')['score'])  # Daily API still checks the 09:15 open.
        broken=deepcopy(payload);broken['series']['A'][0]['snapshot']['roe_pct']=1
        with self.assertRaisesRegex(ValueError,'checksum'):
            fundamental_history.Scores(broken)
