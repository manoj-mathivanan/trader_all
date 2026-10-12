import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from core.research import investor_database as database,store,jobs
from scripts.sync_investor_data import bundle,batches

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
    def tearDown(self):self.data.stop();self.temp.cleanup()

    def test_complete_archive_includes_working_views_job_history_and_validation(self):
        store.write('investor/latest/INE000A01001',dict(id='review'))
        store.write('investor/full_articles/article',dict(text='Entire article'))
        store.write('jobs',[dict(id='investor',type='Investor monitoring',status='success'),dict(id='other',type='Paper trading',secret='unrelated')])
        store.write('private/upstox',dict(access_token='credential-must-not-be-archived'))
        store.write('private/investor-local-validation-20261012',dict(tests=104))
        result=bundle(store.DATA)
        self.assertTrue({'latest','full_articles','analysis_jobs','validation_reports'}<={r['kind'] for r in result['documents']})
        self.assertNotIn('credential-must-not-be-archived',json.dumps(result))
        self.assertNotIn('unrelated',json.dumps(result))

    def test_chunking_preserves_every_record_and_import_bound(self):
        source=dict(environment='local',articles=[],documents=[dict(id=str(i),record='x'*300) for i in range(9)])
        chunks=list(batches(source,max_bytes=2000))
        self.assertGreater(len(chunks),1)
        self.assertEqual([r for c in chunks for r in c['documents']],source['documents'])
        self.assertTrue(all(len(json.dumps(c,sort_keys=True).encode())<2000 for c in chunks))
        with self.assertRaises(ValueError):list(batches(source,max_bytes=1100))

    def test_shared_read_sends_query_as_data_and_redacts_failures(self):
        query=dict(operation='document',environment='production',kind='reviews',id="'; DROP TABLE documents;--")
        with patch.object(database,'connection',return_value=('existing-host',Path('key'))),patch.object(database.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'{"record":{"id":"saved"}}')) as run:
            self.assertEqual(database.read(query)['record']['id'],'saved')
            self.assertEqual(json.loads(run.call_args.kwargs['input']),query)
            self.assertNotIn(query['id'],str(run.call_args.args[0]))
        with patch.object(database,'connection',return_value=('host',Path('key'))),patch.object(database.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr=b'private connection details')):
            with self.assertRaisesRegex(ValueError,'working analysis is unchanged'):database.read(query)

    def test_job_archives_final_status_including_failed_analysis(self):
        class ImmediatePool:
            def submit(self,fn):fn()
        archived=[]
        def fail(log,job_id):raise ValueError('Provider unavailable')
        with patch.object(jobs,'POOL',ImmediatePool()):
            job=jobs.submit('Investor interpretation',fail,after_complete=lambda:archived.extend(store.read('jobs')))
        self.assertEqual(archived[0]['id'],job['id'])
        self.assertEqual(archived[0]['status'],'failed')

    def test_database_outage_keeps_completed_analysis_and_reports_warning(self):
        class ImmediatePool:
            def submit(self,fn):fn()
        with patch.object(jobs,'POOL',ImmediatePool()):
            jobs.submit('Investor monitoring',lambda log,id:dict(candidates=48),after_complete=lambda:(_ for _ in ()).throw(ValueError('Database unavailable')))
        result=store.read('jobs')[0]
        self.assertEqual(result['result']['candidates'],48)
        self.assertEqual(result['status'],'warning')

    def test_explicit_environment_is_passed_to_database_reader(self):
        from dashboard.api import investor_intelligence as api
        with patch.object(database,'read',return_value={}) as read:
            api.shared_history('production')
        self.assertEqual(read.call_args.args[0]['environment'],'production')
