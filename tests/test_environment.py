"""Environment isolation: local research never starts production paper activity."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from core.research import store
from dashboard.api.main import app


class EnvironmentTests(unittest.TestCase):
    def test_local_blocks_all_paper_routes_and_never_starts_scheduler(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)), \
                patch('dashboard.api.main.PAPER_ENABLED', False), \
                patch('dashboard.api.main.scheduler.start') as start, \
                patch('dashboard.api.main.scheduler.recover_interrupted') as recover:
            store.write('portfolios/swing_patterns', {'mode': 'paper'})
            with TestClient(app) as client:
                bootstrap = client.get('/api/bootstrap').json()
                self.assertFalse(bootstrap['paper_enabled'])
                self.assertIsNone(bootstrap['paper_portfolio'])
                self.assertEqual(bootstrap['paper_portfolios'], {})
                for method, path in [('POST', '/api/paper/portfolio'), ('PUT', '/api/paper/portfolio'),
                                     ('PUT', '/api/paper/status'), ('POST', '/api/jobs/paper'),
                                     ('GET', '/api/strategies/swing_patterns/paper/portfolio'),
                                     ('POST', '/api/strategies/swing_patterns/paper/portfolio'),
                                     ('PUT', '/api/strategies/swing_patterns/paper/status'),
                                     ('POST', '/api/strategies/swing_patterns/paper/cycle')]:
                    self.assertEqual(client.request(method, path, headers={'X-Trader-Request': 'local-ui'}).status_code, 403)
            start.assert_not_called()
            recover.assert_not_called()

    def test_production_starts_and_stops_exactly_one_scheduler(self):
        stop, thread = Mock(), Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)), \
                patch('dashboard.api.main.PAPER_ENABLED', True), \
                patch('dashboard.api.main.scheduler.start', return_value=(stop, thread)) as start, \
                patch('dashboard.api.main.scheduler.recover_interrupted') as recover:
            with TestClient(app) as client:
                self.assertTrue(client.get('/api/bootstrap').json()['paper_enabled'])
                self.assertEqual(client.get('/api/strategies/swing_patterns/paper/portfolio').status_code, 200)
            start.assert_called_once()
            recover.assert_called_once()
            stop.set.assert_called_once()
            thread.join.assert_called_once_with(timeout=2)
