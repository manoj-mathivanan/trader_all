import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from core.research import jobs, store


class JobCompletionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        replacement = patch.object(store, 'DATA', Path(directory.name))
        replacement.start()
        self.addCleanup(replacement.stop)

    def run_job(self, function):
        pending = []
        with patch.object(jobs.POOL, 'submit', side_effect=pending.append):
            jobs.submit('Fetch market history', function)
        pending[0]()
        return store.read('jobs')[0]

    def test_partial_completed_data_is_warning_with_full_result(self):
        result = dict(partial=True, daily_symbols=749, minute_symbols=750, failures=[{'symbol':'MISSING'}])
        job = self.run_job(lambda log, job_id:result)
        self.assertEqual(job['status'], 'warning')
        self.assertEqual(job['result'], result)

    def test_backtests_queue_behind_running_work_and_continue_after_failure(self):
        started, release = Event(), Event()
        order = []
        def paper(log, job_id):
            order.append('paper')
            started.set()
            if not release.wait(5):
                raise ValueError('Test worker timed out.')
            raise ValueError('Paper refresh failed.')
        def backtest(log, job_id):
            order.append('backtest')
            return {'saved': True}
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(jobs, 'POOL', pool):
            try:
                first = jobs.submit('Paper daily cycle', paper)
                self.assertTrue(started.wait(2))
                second = jobs.submit('Backtest', backtest, allow_queue=True)
                self.assertEqual(order, ['paper'])
                self.assertEqual(store.read('jobs')[0]['status'], 'queued')
                with self.assertRaisesRegex(ValueError, 'Another job is active'):
                    jobs.submit('Fetch market history', backtest)
            finally:
                release.set()
        records = {job['id']: job for job in store.read('jobs')}
        self.assertEqual(order, ['paper', 'backtest'])
        self.assertEqual(records[first['id']]['status'], 'failed')
        self.assertEqual(records[second['id']]['status'], 'success')

    def test_provider_rejection_and_empty_coverage_remain_failed(self):
        def rejected(log, job_id):
            raise ValueError('Provider rejected access (401/403).')
        self.assertEqual(self.run_job(rejected)['status'], 'failed')
        self.assertEqual(jobs.completion_status(dict(partial=True,daily_symbols=0,minute_symbols=0)), 'failed')
        self.assertEqual(jobs.completion_status(dict(partial=True,counts={'failed':5})), 'failed')

    def test_recovery_reclassifies_only_historical_completed_partial_jobs(self):
        old = dict(id='partial',status='failed',result={'partial':True,'daily_symbols':1,'minute_symbols':1},
                   logs=[{'message':'Completed all stocks with failures; inspect the result and logs, then retry.'}])
        broken = dict(id='broken',status='failed',logs=[{'message':'Provider rejected access (401/403).'}])
        store.write('jobs',[old,broken])
        jobs.recover()
        records = store.read('jobs')
        self.assertEqual([j['status'] for j in records],['warning','failed'])
        self.assertEqual(records[0]['result'],old['result'])
