from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.research import options_backtest as bt
from scripts import forward_options_paper as forward
from tests import test_options_backtest as fixture


class ForwardOptionsTests(unittest.TestCase):
    def test_first_session_does_not_backdate_after_open_or_on_weekend(self):
        for instant,expected in [('2026-10-30T08:45:00+05:30','2026-10-30'),
                                 ('2026-10-30T09:15:00+05:30','2026-11-02'),
                                 ('2026-10-31T08:45:00+05:30','2026-11-02')]:
            self.assertEqual(str(forward.first_session(datetime.fromisoformat(instant))),expected)

    def test_freeze_is_idempotent_and_detects_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            clock=datetime.fromisoformat('2026-10-30T08:00:00+05:30')
            plan=forward.freeze(root,clock)
            self.assertEqual(plan,forward.freeze(root,clock))
            with patch.object(forward,'digest',return_value='changed'):
                with self.assertRaisesRegex(ValueError,'Frozen source changed'):
                    forward.freeze(root,clock)

    def test_rejects_late_or_pre_activation_catalog(self):
        snapshot=dict(session='2026-10-30',captured_at='2026-10-30T09:15:00+05:30',expiry='2026-11-03',contracts=[])
        with self.assertRaises(ValueError):
            forward.validate_snapshot(snapshot,dict(first_eligible_session='2026-10-30'))
        snapshot['captured_at']='2026-10-30T08:45:00+05:30'
        with self.assertRaises(ValueError):
            forward.validate_snapshot(snapshot,dict(first_eligible_session='2026-11-02'))

    def test_empty_forward_study_imports_no_historical_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=forward.evaluate(Path(tmp),{})
            self.assertEqual(result['closed_trades'],0)
            self.assertEqual(result['completed_observed_sessions'],0)
            self.assertEqual(result['status'],'waiting_for_first_completed_session')

    def test_replay_uses_session_catalog_instead_of_future_universe(self):
        audit,bars,catalogs,expiries=fixture.ReplayTests().sample()
        future=fixture.catalog(key='future',strike=25100)
        bars['future']=fixture.prices({'09:59':250,'10:00':250,'10:03':1000})
        catalogs['2026-10-20'].append(future)
        result=bt.replay(audit,bars,catalogs,expiries,bt.ReplayConfig(),
                         session_catalogs={'2026-10-20':{'2026-10-20':[fixture.catalog()]}})
        self.assertEqual(result['trades'][0]['key'],'call')
        self.assertEqual(result['selection_coverage'][0]['catalog_candidates'],1)
        missing=bt.replay(audit,bars,catalogs,expiries,bt.ReplayConfig(),session_catalogs={})
        self.assertEqual(missing['trades'],[])
        self.assertTrue(missing['skipped_entries'])

    def test_snapshot_capture_outside_premarket_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(forward.h,'request') as request:
            result=forward.capture_catalog(None,'test',Path(tmp),dict(first_eligible_session='2026-10-30'),
                datetime.fromisoformat('2026-10-30T10:00:00+05:30'))
            self.assertIsNone(result)
            request.assert_not_called()
