import unittest
from unittest.mock import patch
from fastapi import HTTPException
from dashboard.api import main

class AuditApiTests(unittest.TestCase):
    def test_archive_is_selected_from_the_owned_portfolio_cycle(self):
        p=dict(id='scenario',cycles=[dict(job_id='cycle-one',candidate_audit_reference='ignored')])
        with patch.object(main.portfolios,'get',return_value=p),patch.object(main.store,'read',return_value={'records':[1]}) as read:
            self.assertEqual(main.get_strategy_opportunities('swing_patterns','scenario')['records'],[1])
            self.assertEqual(read.call_args.args[0],'paper_candidate_audits/scenario/cycle-one')
            self.assertEqual(main.get_strategy_opportunities('swing_patterns','scenario','other')['records'],[])

    def test_identity_mismatch_and_invalid_cycle_cannot_read_another_archive(self):
        for p in [dict(id='other',cycles=[]),dict(id='scenario',cycles=[dict(job_id='../private',candidate_audit_reference='x')])]:
            with patch.object(main.portfolios,'get',return_value=p),patch.object(main.store,'read') as read:
                with self.assertRaises(HTTPException):main.get_strategy_opportunities('swing_patterns','scenario')
                read.assert_not_called()

if __name__=='__main__':unittest.main()
