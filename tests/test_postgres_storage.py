"""Run against a real disposable PostgreSQL database via TRADER_TEST_DB_DSN."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from core.research import store, postgres_store as pg
from scripts import migrate_storage as migration


@unittest.skipUnless(os.environ.get('TRADER_TEST_DB_DSN'),'requires disposable PostgreSQL')
class PostgresStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.namespace='test_'+uuid4().hex
        self.env=patch.dict(os.environ,dict(TRADER_STORAGE='postgres',
            TRADER_DB_DSN=os.environ['TRADER_TEST_DB_DSN'],TRADER_DB_NAMESPACE=self.namespace,
            TRADER_TOKEN_KEY=Fernet.generate_key().decode(),TRADER_USER_ID='owner'))
        self.env.start()
        self.data=patch.object(store,'DATA',self.root/'no-filesystem-data')
        self.data.start()
        pg.initialize()

    def tearDown(self):
        try:
            with pg.transaction() as conn:
                for table in ('trade_records','portfolios','runs','jobs','migrations','credentials','artifacts','documents'):
                    conn.execute(f'DELETE FROM trader.{table} WHERE namespace=%s',(self.namespace,))
                # This suite uses a disposable DB. In particular, don't leave
                # the deliberately corrupted unreferenced fixture for the next test.
                conn.execute('DELETE FROM trader.contents c WHERE NOT EXISTS (SELECT 1 FROM trader.documents d WHERE d.sha256=c.sha256) AND NOT EXISTS (SELECT 1 FROM trader.artifacts a WHERE a.sha256=c.sha256) AND NOT EXISTS (SELECT 1 FROM trader.runs r WHERE r.source_sha256=c.sha256) AND NOT EXISTS (SELECT 1 FROM trader.portfolios p WHERE p.source_sha256=c.sha256)')
        finally:
            pg.close();self.data.stop();self.env.stop();self.temp.cleanup()

    def test_roundtrip_transactions_and_namespace_isolation(self):
        store.write('config',{'value':1,'text':'café'})
        self.assertEqual(store.read('config')['text'],'café')
        with self.assertRaises(RuntimeError):
            with store.LOCK:
                store.write('config',{'value':2})
                store.write('new',[])
                raise RuntimeError('rollback')
        self.assertEqual(store.read('config')['value'],1)
        self.assertIsNone(store.read('new'))
        with patch.dict(os.environ,TRADER_DB_NAMESPACE='other_'+self.namespace):
            self.assertIsNone(store.read('config'))
        self.assertFalse(store.DATA.exists())

    def test_concurrent_process_updates_are_atomic(self):
        store.write('counter',{'value':0})
        script="""from core.research import store
for _ in range(12):
 with store.LOCK:
  value=store.read('counter');value['value']+=1;store.write('counter',value)
"""
        children=[subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(3)]
        for child in children:
            out,error=child.communicate(timeout=60)
            self.assertEqual(child.returncode,0,error.decode())
        self.assertEqual(store.read('counter')['value'],36)
        with ThreadPoolExecutor(max_workers=24) as executor:
            self.assertEqual(list(executor.map(lambda _:store.read('counter')['value'],range(48))),[36]*48)

    def test_prefix_lookup_versions_and_binary_artifacts(self):
        for name in ('news/a_1','news/ax1','news/a_1/deep','news/a_2'):
            store.write(name,{'value':name})
        self.assertEqual(store.keys('news/a_'),['news/a_1','news/a_2'])
        self.assertEqual(len(store.keys('news/',recursive=True)),4)
        version=store.version('news/a_1')
        store.write('news/a_1',{'value':'changed'})
        self.assertNotEqual(version,store.version('news/a_1'))
        store.write_bytes('company/filings/test.html',b'<html>archived bytes</html>')
        self.assertEqual(store.read_bytes('company/filings/test.html'),b'<html>archived bytes</html>')
        with self.assertRaises(FileNotFoundError):store.read_bytes('missing.html')
        with self.assertRaises(ValueError):store.read('../config')

    def test_encrypted_owner_credentials_and_immutable_snapshots(self):
        store.save_token('test-token-do-not-log')
        self.assertEqual(store.token(),'test-token-do-not-log')
        with pg.transaction() as conn:
            raw=conn.execute('SELECT encrypted_value FROM trader.credentials WHERE namespace=%s',(self.namespace,)).fetchone()[0]
        self.assertNotIn(b'test-token-do-not-log',bytes(raw))
        with patch.dict(os.environ,TRADER_USER_ID='different-user'):
            self.assertFalse(store.token_saved())
        snapshot={'ABC':[{'close':10}]}
        store.write('run_data/first',snapshot);store.write('run_data/second',snapshot)
        with pg.transaction() as conn:
            rows=conn.execute('SELECT DISTINCT sha256 FROM trader.documents WHERE namespace=%s AND name LIKE %s',(self.namespace,'run_data/%')).fetchall()
        self.assertEqual(len(rows),1)
        with self.assertRaises(ValueError):store.write('run_data/first',{'changed':True})
        self.assertEqual(store.read('run_data/first'),snapshot)

    def test_migration_verifies_all_data_and_ui_runs_without_files(self):
        source=self.root/'original';source.mkdir()
        def save(name,value):
            path=source/(name+'.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
        bar=dict(date='2026-10-01',open=10,high=12,low=9,close=11,volume=100)
        save('bars/TEST',{'bars':[bar]})
        save('intraday/5m/TEST/2026-10-01',{'bars':[dict(bar,time='09:15')]})
        save('runs/fixture',{'id':'fixture','config':{'capital':100},'metrics':{'return_pct':2},'trades':[{'symbol':'TEST','pnl':2}]})
        save('run_data/fixture',{'TEST':[bar]})
        save('portfolio_scenarios/swing_patterns/observe',dict(id='observe',strategy_name='swing_patterns',status='active',config={},ledger={'cash':95,'trades':[{'symbol':'TEST','pnl':1}]}))
        save('investor/articles/fixture',dict(id='fixture',text='News from database',published_at='2026-10-01'))
        save('company/fundamentals/TEST/history/fixture',{'snapshot':{'id':'fixture'}})
        save('jobs',[{'id':'job','status':'success'}])
        save('private/upstox',{'access_token':'migration-secret'})
        (source/'company/filings').mkdir(parents=True)
        (source/'company/filings/example.html').write_bytes(b'original filing')
        bundle=self.root/'export.tar'
        with patch.dict(os.environ,TRADER_PRIVATE_DIR=str(source/'private')):
            migration.export(source,bundle,stopped=True,log=lambda *a,**k:None)
        self.assertNotIn(b'migration-secret',bundle.read_bytes())
        receipt=migration.restore(bundle,log=lambda *a,**k:None)
        self.assertEqual(receipt['status'],'verified')
        store.ensure_ready()
        self.assertEqual(store.token(),'migration-secret')
        source.rename(self.root/'original-offline')
        self.assertEqual(store.read('run_data/fixture')['TEST'][0]['close'],11)
        self.assertEqual(store.read_bytes('company/filings/example.html'),b'original filing')
        from core.portfolio import manager
        self.assertEqual(manager.list_portfolios('swing_patterns')[0]['id'],'observe')
        with pg.transaction() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM trader.candles WHERE namespace=%s',(self.namespace,)).fetchone()[0],1)
            session=conn.execute('SELECT candle_count,bars FROM trader.intraday_sessions WHERE namespace=%s',(self.namespace,)).fetchone()
            self.assertEqual(session[0],1)
            self.assertEqual(session[1][0]['close'],11)
            self.assertEqual(conn.execute('SELECT count(*) FROM trader.trade_records WHERE namespace=%s',(self.namespace,)).fetchone()[0],2)
        from dashboard.api.main import bootstrap
        self.assertEqual(bootstrap()['storage']['backend'],'postgres')
        self.assertFalse(store.DATA.exists())
        migration.restore(bundle,verify_only=True,log=lambda *a,**k:None)
        migration.restore(bundle,log=lambda *a,**k:None)  # Safe idempotent resume.
        with pg.transaction() as conn:
            conn.execute('UPDATE trader.contents SET content=%s WHERE sha256=(SELECT sha256 FROM trader.documents WHERE namespace=%s AND name=%s)',(gzip.compress(b'corrupted'),self.namespace,'runs/fixture'))
        with self.assertRaises(ValueError):migration.restore(bundle,verify_only=True,log=lambda *a,**k:None)

    def test_readiness_gate_and_database_outage_do_not_fall_back(self):
        with store.application_lock():
            with self.assertRaisesRegex(ValueError,'busy'):
                with store.application_lock():pass
        with self.assertRaises(ValueError):store.ensure_ready()
        with patch.dict(os.environ,TRADER_DB_DSN='postgresql://127.0.0.1:1/unavailable'):
            with self.assertRaisesRegex(ValueError,'No filesystem fallback'):store.read('config')
        self.assertFalse(store.DATA.exists())

    def test_sql_coverage_matches_json_and_history_reads_current_database(self):
        from datetime import date,timedelta
        from types import SimpleNamespace
        from core.research import backtest,investor_database
        records={'universes/test':{'instruments':[dict(isin='A',symbol='AAA'),dict(isin='B',symbol='BBB'),dict(isin='C',symbol='CCC')]}}
        for identity,length in (('A',20),('B',14)):
            bars=[dict(date=str(date(2026,9,1)+timedelta(days=i)),open=10,high=12,low=9,close=11,volume=100) for i in range(length)]
            records['bars/'+identity]=dict(bars=bars,requested_start='2026-09-03',requested_end='2026-09-12')
        source=self.root/'comparison'
        with patch.dict(os.environ,TRADER_STORAGE='json'),patch.object(store,'DATA',source):
            for name,value in records.items():store.write(name,value)
            expected=backtest.available_window(SimpleNamespace(universe='test'),warmup=4)
        for name,value in records.items():store.write(name,value)
        self.assertEqual(backtest.available_window(SimpleNamespace(universe='test'),warmup=4),expected)
        self.assertEqual(dict(store.records('bars/')), {k:v for k,v in records.items() if k.startswith('bars/')})
        store.write('investor/reviews/review',dict(id='review',as_of='2026-10-16',company={'isin':'TEST'},outlook='current'))
        inventory=investor_database.read(dict(operation='inventory',environment='local'))
        self.assertEqual(inventory['counts']['reviews'],1)
        listed=investor_database.read(dict(operation='list',environment='local',kind='reviews'))['documents'][0]
        saved=investor_database.read(dict(operation='document',environment='local',kind='reviews',id=listed['id'],sha256=listed['sha256']))
        self.assertEqual(saved['record']['outlook'],'current')
        store.write('mutable',{'value':1});first=pg.pack({'value':1})
        store.write('run_data/shared',{'value':1})
        store.write('mutable',{'value':2})
        self.assertEqual(store.read('run_data/shared'),{'value':1})
        with pg.transaction() as conn:
            self.assertIsNotNone(conn.execute('SELECT 1 FROM trader.contents WHERE sha256=%s',(__import__('hashlib').sha256(first).hexdigest(),)).fetchone())

    def test_workspace_cleanup_keeps_latest_reference_and_archives_paper(self):
        from scripts.cleanup_workspace import apply
        from core.research import investor_paper,strategy_presets
        store.write('storage/migration_ready',{'status':'verified'})
        store.write('strategy_catalog',strategy_presets.bundled_presets())
        runs=[dict(id='old',created_at='2026-10-01',config={'simulation_model':'banana_proxy_v1'}),
              dict(id='keep',created_at='2026-10-15',config={'simulation_model':'banana_proxy_v1','pattern':'blue_sky'}),
              dict(id='other',created_at='2026-10-16',config={'simulation_model':'legacy'})]
        store.write('runs_index',runs)
        portfolio=dict(id='observe',strategy_name='swing_patterns',status='active',config={},ledger={'trades':[{'pnl':3}]})
        store.write('portfolio_scenarios/swing_patterns/observe',portfolio)
        store.write('live/ledger',{'real_broker_state':'preserved'})
        store.write('investor/assessments/composite-paper-state',{'trades':[{'pnl':5}]})
        receipt=apply(clear_paper=True,reference_strategies_only=True)
        self.assertEqual([r['id'] for r in store.read('runs_index')],['keep'])
        self.assertEqual(receipt['archived_backtests'],2)
        self.assertEqual(receipt['paper_portfolios_remaining'],0)
        self.assertIsNone(store.read('portfolio_scenarios/swing_patterns/observe'))
        self.assertEqual(store.read(receipt['archive']+'/portfolio_scenarios/swing_patterns/observe'),portfolio)
        self.assertEqual(store.read('live/ledger'),{'real_broker_state':'preserved'})
        self.assertEqual(investor_paper.run(None)['status'],'disabled')
        self.assertEqual(len(strategy_presets.selectable()),4)
        self.assertTrue(all((p.get('backtest_defaults') or {}).get('simulation_model')=='banana_proxy_v1' for p in strategy_presets.selectable()))
        self.assertTrue(all('banana' not in p['name'].lower() for p in strategy_presets.selectable()))
        with self.assertRaises(ValueError):strategy_presets.require_reference({'simulation_model':'legacy'})
        strategy_presets.require_reference({'simulation_model':'banana_proxy_v1'})
        with pg.transaction() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM trader.portfolios WHERE namespace=%s',(self.namespace,)).fetchone()[0],0)
        self.assertEqual(apply(clear_paper=True)['archived_backtests'],0)

    def test_reference_promotion_preserves_inputs_and_destination_credentials(self):
        from scripts.cleanup_workspace import apply
        store.write('storage/migration_ready',{'status':'verified'})
        store.write('strategy_catalog',[])
        store.save_token('destination-token')
        identity='012345abcdef'
        result=dict(id=identity,created_at='2026-10-16',config={'simulation_model':'banana_proxy_v1','pattern':'blue_sky'},
                    universe='test',metrics={'return_pct':2},trades=[])
        values={'runs/'+identity:result,'run_data/'+identity:{'TEST':[{'close':11}]}}
        records=[]
        bundle=self.root/'reference.tar'
        with tarfile.open(bundle,'w') as archive:
            def add(name,raw):
                info=tarfile.TarInfo(name);info.size=len(raw);archive.addfile(info,io.BytesIO(raw))
            for name,value in values.items():
                raw=pg.pack(value);digest=hashlib.sha256(raw).hexdigest()
                records.append(dict(kind='document',name=name,sha256=digest,source_sha256=digest,raw_bytes=len(raw),metadata=pg.metadata(name,value)))
                add('contents/'+digest+'.gz',gzip.compress(raw))
            raw=pg.pack(dict(version=1,run_id=identity,records=records,credentials=[]))
            add('manifest.json',raw);add('manifest.sha256',hashlib.sha256(raw).hexdigest().encode())
        store.write('runs_index',[dict(id='old',created_at='2026-01-01',config={'simulation_model':'legacy'})])
        receipt=apply(reference_bundle=bundle,clear_paper=True)
        self.assertEqual(receipt['kept_backtest'],identity)
        self.assertEqual(store.read('run_data/'+identity),values['run_data/'+identity])
        self.assertEqual(store.token(),'destination-token')
        self.assertEqual(len(store.read('archived_runs_index')),1)

    def test_interrupted_import_resumes_only_committed_batches(self):
        source=self.root/'resume-source';source.mkdir()
        (source/'state').mkdir()
        for index in range(130):
            (source/'state'/f'{index:03}.json').write_text(json.dumps({'index':index}))
        bundle=self.root/'resume.tar'
        migration.export(source,bundle,stopped=True,log=lambda *a,**k:None)
        original=migration.checked_content
        def interrupt(archive,record):
            if record['name']=='state/080':raise RuntimeError('Simulated process interruption')
            return original(archive,record)
        with patch.object(migration,'checked_content',interrupt),self.assertRaises(RuntimeError):
            migration.restore(bundle,log=lambda *a,**k:None)
        self.assertEqual(len(store.keys('state/')),64)
        self.assertIsNone(store.read('storage/migration_ready'))
        migration.restore(bundle,log=lambda *a,**k:None)
        self.assertEqual(len(store.keys('state/')),130)
        self.assertEqual(store.read('state/080'),{'index':80})


if __name__=='__main__':unittest.main()
