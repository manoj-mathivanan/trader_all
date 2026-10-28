"""Authentication, server-side roles and cross-user broker isolation."""
import os
import tempfile
import time
from uuid import uuid4
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from core.research import accounts, identity, store, jobs
from dashboard.api import main
from dashboard.api.accounts import REFRESH_PATHS

PASSWORD = 'test-only-password-2026'
HEADERS = {'X-Trader-Request': 'local-ui'}


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'TRADER_STORAGE':'postgres' if getattr(self,'postgres',False) else 'json', 'TRADER_USER_LOGIN':'1',
                             'TRADER_TOKEN_KEY':Fernet.generate_key().decode(), 'TRADER_PUBLIC_ORIGIN':''})
        self.env.start()
        if getattr(self,'postgres',False):
            from core.research import postgres_store as pg
            self.database_env=patch.dict(os.environ,TRADER_DB_DSN=os.environ['TRADER_TEST_DB_DSN'],TRADER_DB_NAMESPACE='auth_'+uuid4().hex)
            self.database_env.start();pg.initialize()
            store.write('reference/history_evidence',{})
        self.data = patch.object(store, 'DATA', Path(self.directory.name)); self.data.start()
        self.user = patch.object(main, 'USER', ''); self.user.start()
        self.client = TestClient(main.app)
        self.client.headers.update(HEADERS)
        accounts.create('manoj', PASSWORD, bootstrap=True)
        accounts.create('alice', PASSWORD)
        accounts.create('bob', PASSWORD)

    def tearDown(self):
        if getattr(self,'postgres',False):
            from core.research import postgres_store as pg
            with pg.transaction() as conn:
                for table in ('trade_records','runs','portfolios','jobs','credentials','migrations','artifacts','documents'):
                    conn.execute(f'DELETE FROM trader.{table} WHERE namespace=%s',(pg.namespace(),))
            pg.close();self.database_env.stop()
        self.client.close(); self.user.stop(); self.data.stop(); self.env.stop(); self.directory.cleanup()

    def login(self, name, password=PASSWORD, client=None):
        client = client or self.client
        response = client.post('/api/auth/login', json={'username':name,'password':password}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_no_anonymous_access_and_admin_only_account_creation(self):
        self.assertEqual(self.client.get('/api/bootstrap').status_code, 401)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.login('alice')
        self.assertEqual(self.client.get('/api/admin/users').status_code, 403)
        self.assertEqual(self.client.post('/api/admin/users',json={'username':'mallory','password':PASSWORD}).status_code,403)
        self.login('manoj')
        response = self.client.post('/api/admin/users',json={'username':'charlie','password':PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['is_admin'])
        self.assertEqual(self.client.post('/api/admin/users',json={'username':'mallory','password':PASSWORD,'is_admin':True}).status_code,422)
        users = self.client.get('/api/admin/users').text
        self.assertNotIn('password_hash', users)
        self.assertNotIn(PASSWORD, users)

    def test_every_shared_refresh_route_rejects_regular_users(self):
        self.login('alice')
        for path in REFRESH_PATHS:
            for suffix in ('','/'):
                response = self.client.post(path+suffix,json={})
                self.assertEqual(response.status_code,403,path+suffix)
        self.assertEqual(self.client.get('/api/data-quality').status_code,200)

    def test_cookie_logout_password_change_and_rate_limit(self):
        response = self.login('alice')
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly',cookie);self.assertIn('samesite=strict',cookie)
        self.assertNotIn('password',response.text)
        token = self.client.cookies.get(accounts.COOKIE)
        self.assertNotIn(token, '\n'.join(store.keys('auth/sessions/')))
        self.assertEqual(self.client.post('/api/auth/logout',json={}).status_code,200)
        self.assertIsNone(accounts.session(token))
        self.login('alice')
        changed=self.client.put('/api/auth/password',json={'current_password':PASSWORD,'password':'replacement-password-2026'})
        self.assertEqual(changed.status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,401)
        self.login('alice','replacement-password-2026')
        for _ in range(5):
            response=self.client.post('/api/auth/login',json={'username':'bob','password':'wrong-password-2026'})
            self.assertEqual(response.status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'bob','password':PASSWORD}).status_code,429)

    def test_password_minimum_is_six_for_creation_change_and_reset(self):
        self.login('manoj')
        self.assertEqual(self.client.post('/api/admin/users',json={'username':'charlie','password':'short'}).status_code,400)
        self.assertEqual(self.client.post('/api/admin/users',json={'username':'charlie','password':'sixsix'}).status_code,200)
        self.login('charlie','sixsix')
        self.assertEqual(self.client.put('/api/auth/password',json={'current_password':'sixsix','password':'short'}).status_code,422)
        self.assertEqual(self.client.put('/api/auth/password',json={'current_password':'sixsix','password':'newnew'}).status_code,200)
        self.login('charlie','newnew')
        self.login('manoj')
        self.assertEqual(self.client.put('/api/admin/users/charlie',json={'password':'short'}).status_code,422)
        self.assertEqual(self.client.put('/api/admin/users/charlie',json={'password':'reset6'}).status_code,200)
        self.login('charlie','reset6')

    def test_disable_revokes_existing_sessions_and_admin_cannot_be_disabled(self):
        alice=TestClient(main.app,headers=HEADERS)
        self.login('alice',client=alice);self.login('manoj')
        self.assertEqual(self.client.put('/api/admin/users/alice',json={'enabled':False}).status_code,200)
        self.assertEqual(alice.get('/api/bootstrap').status_code,401)
        self.assertEqual(self.client.put('/api/admin/users/manoj',json={'enabled':False}).status_code,400)
        self.assertEqual(self.client.put('/api/admin/users/Manoj',json={'password':PASSWORD}).status_code,400)
        alice.close()

    def test_trading_tokens_live_ledgers_and_runner_controls_are_private(self):
        from core.portfolio import live
        market='market-token-for-shared-data'
        store.save_token(market)
        for user in ('alice','bob'):
            self.login(user)
            token=user+'-private-trading-token'
            self.assertEqual(self.client.put('/api/connection',json={'access_token':token}).status_code,200)
            self.assertEqual(self.client.put('/api/live/connection',json={'expected_user_id':user}).status_code,200)
            with identity.scope({'username':user}):
                store.write('live/ledger',dict(account_id=user,orders=[],positions={},realized_pnl=0))
                self.assertEqual(store.token(trading=True),token)
                self.assertEqual(store.token(),market)
        for user in ('alice','bob'):
            self.login(user)
            response=self.client.get('/api/live')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['ledger']['account_id'],user)
        with identity.scope({'username':'alice'}):
            alice_stop=live.stop_event();alice_stop.set()
        with identity.scope({'username':'bob'}):
            bob_stop=live.stop_event();bob_stop.clear()
        self.assertIsNot(alice_stop,bob_stop)
        self.assertFalse(bob_stop.is_set())
        if store.database_enabled():
            from core.research import postgres_store as pg
            encrypted=bytes(pg.token('user:alice'))
        else:
            encrypted=(store.DATA/'private/user_tokens/alice.json').read_bytes()
        self.assertNotIn(b'alice-private-trading-token',encrypted)

    def test_shared_runs_and_portfolios_keep_the_creator_prefix(self):
        for user in ('alice','bob'):
            with identity.scope({'username':user}):
                store.write('runs/'+user,dict(id=user,config={'name':'Example'}))
                rows=store.read('runs_index',[])+[dict(id=user,config={'name':'Example'})]
                store.write('runs_index',rows)
                store.write('portfolio_scenarios/swing_patterns/'+user,dict(id=user,config={'name':'Paper example'}))
        self.assertEqual([r['config']['name'] for r in store.read('runs_index')],['alice: Example','bob: Example'])
        with identity.scope({'username':'bob'}):
            self.assertEqual(store.read('runs/alice')['config']['name'],'alice: Example')
            book=store.read('portfolio_scenarios/swing_patterns/alice')
            book['config']['name']='Adjusted'
            store.write('portfolio_scenarios/swing_patterns/alice',book)
        self.assertEqual(store.read('portfolio_scenarios/swing_patterns/alice')['config']['name'],'alice: Adjusted')

    def test_worker_keeps_username_after_request_context_ends(self):
        pool=ThreadPoolExecutor(max_workers=1)
        with patch.object(jobs,'POOL',pool), identity.scope({'username':'alice'}):
            job=jobs.submit('Test',lambda log,id: {'username':identity.username()})
        pool.shutdown(wait=True)
        saved=store.read('jobs')[0]
        self.assertEqual(saved['created_by'],'alice')
        self.assertEqual(saved['result']['username'],'alice')
        self.assertIsNone(identity.current())

    def test_services_are_admin_only_and_secrets_are_never_returned(self):
        self.login('manoj')
        secret='test-research-key-never-return'
        response=self.client.put('/api/admin/services',json={'research_key':secret,'research_model':'test-model'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn(secret,response.text)
        self.assertNotIn(secret,str(store.read('private/services/openai')))
        self.login('alice')
        self.assertEqual(self.client.get('/api/admin/services').status_code,403)
        self.assertEqual(self.client.put('/api/admin/services',json={'research_key':secret}).status_code,403)

    def test_legacy_broker_state_is_assigned_only_to_manoj(self):
        store.write('live/account',{'profile':{'user_id':'original-owner'}})
        store.save_token('original-owner-trading-token')
        accounts.migrate_legacy()
        for username,expected in [('manoj',{'profile':{'user_id':'original-owner'}}),('alice',None)]:
            with identity.scope({'username':username}):
                self.assertEqual(store.read('live/account'),expected)
        with identity.scope({'username':'manoj'}):
            self.assertEqual(store.token(trading=True),'original-owner-trading-token')

    def test_bootstrap_cannot_be_repeated_or_exposed_publicly(self):
        self.assertEqual(self.client.post('/api/auth/setup',json={'username':'manoj','password':PASSWORD}).status_code,400)
        with patch.dict(os.environ,TRADER_PUBLIC_ORIGIN='https://example.test'):
            self.assertEqual(self.client.post('/api/auth/setup',json={'username':'manoj','password':PASSWORD}).status_code,403)


@unittest.skipUnless(os.environ.get('TRADER_TEST_DB_DSN'),'requires disposable PostgreSQL')
class PostgresAccountTests(AccountTests):
    postgres=True


if __name__=='__main__':
    unittest.main()
