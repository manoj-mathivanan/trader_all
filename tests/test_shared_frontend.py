"""Shared frontend forwards to production without local workers or shared cookies."""
import gzip
import subprocess
import sys
import unittest

import httpx
from fastapi.testclient import TestClient

from dashboard.shared import PRODUCTION, create_app


class SharedFrontendTests(unittest.TestCase):
    def test_entrypoint_does_not_load_database_or_worker_modules(self):
        result = subprocess.run([sys.executable, '-c',
            "import dashboard.shared,sys; assert not any(n.startswith('core.') for n in sys.modules)"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def client(self, handler):
        return TestClient(create_app(transport=httpx.MockTransport(handler)))

    def test_reads_and_writes_use_production_preserving_query_and_body(self):
        requests = []

        def upstream(request):
            requests.append(request)
            return httpx.Response(200, json={'storage': {'namespace': 'production'}})

        with self.client(upstream) as client:
            self.assertEqual(client.get('/api/bootstrap').json()['storage']['namespace'], 'production')
            result = client.put('/api/settings?name=a%2Fb&name=c', json={'universe': 'total'},
                                headers={'X-Trader-Request': 'local-ui', 'Origin': 'http://testserver',
                                         'X-Forwarded-Host': 'attacker.example'})
            self.assertEqual(result.status_code, 200)
        self.assertEqual(str(requests[0].url), PRODUCTION+'/api/bootstrap')
        self.assertEqual(str(requests[1].url), PRODUCTION+'/api/settings?name=a%2Fb&name=c')
        self.assertEqual(requests[1].headers['origin'], PRODUCTION)
        self.assertNotIn('x-forwarded-host', requests[1].headers)
        self.assertEqual(requests[1].read(), b'{"universe":"total"}')

    def test_login_cookie_remains_private_and_is_not_shared_between_clients(self):
        received = []

        def upstream(request):
            received.append(request.headers.get('cookie', ''))
            if request.url.path.endswith('/login'):
                return httpx.Response(200, json={'user': {'username': 'manoj'}},
                                      headers={'set-cookie': 'trader_session=secret; Secure; HttpOnly; SameSite=Strict; Path=/'})
            if request.url.path.endswith('/logout'):
                return httpx.Response(200, json={}, headers={'set-cookie': 'trader_session=""; Max-Age=0; Secure; HttpOnly; SameSite=Strict; Path=/'})
            return httpx.Response(401, json={'detail': 'Sign in to continue.'})

        with self.client(upstream) as first, self.client(upstream) as second:
            login = first.post('/api/auth/login', json={}, headers={'X-Trader-Request': 'local-ui'})
            cookie = login.headers['set-cookie']
            self.assertNotIn('Secure', cookie)
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Strict', cookie)
            first.get('/api/auth/session')
            self.assertEqual(second.get('/api/bootstrap').status_code, 401)
            first.post('/api/auth/logout', headers={'X-Trader-Request': 'local-ui'})
            first.get('/api/auth/session')
        self.assertEqual(received, ['', 'trader_session=secret', '', 'trader_session=secret', ''])

    def test_boundary_rejects_remote_hosts_and_cross_origin_mutations(self):
        requests = []
        with self.client(lambda r: requests.append(r)) as client:
            self.assertEqual(client.get('/api/bootstrap', headers={'host': 'attacker.example'}).status_code, 403)
            self.assertEqual(client.post('/api/settings').status_code, 403)
            self.assertEqual(client.post('/api/settings', headers={'X-Trader-Request': 'local-ui',
                             'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(requests, [])
        with TestClient(create_app(), client=('192.168.1.1', 1234)) as client:
            self.assertEqual(client.get('/').status_code, 403)

    def test_outage_never_falls_back_or_retries_a_write(self):
        requests = []

        def upstream(request):
            requests.append(request)
            raise httpx.ReadTimeout('private upstream diagnostic')

        with self.client(upstream) as client:
            result = client.post('/api/jobs/backtest', json={}, headers={'X-Trader-Request': 'local-ui'})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn('private', result.text)
        self.assertEqual(len(requests), 1)

    def test_compressed_responses_errors_and_static_files(self):
        def upstream(request):
            return httpx.Response(403, content=gzip.compress(b'{"detail":"Admin required"}'),
                                  headers={'Content-Encoding': 'gzip', 'Content-Type': 'application/json',
                                           'Connection': 'keep-alive, x-private-hop', 'X-Private-Hop': 'drop'})

        with self.client(upstream) as client:
            result = client.get('/api/admin/users')
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result.json(), {'detail': 'Admin required'})
            self.assertNotIn('content-encoding', result.headers)
            self.assertNotIn('x-private-hop', result.headers)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/static/app.js').status_code, 200)


if __name__ == '__main__':
    unittest.main()
