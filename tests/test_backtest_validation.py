import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.api.main import app
from core.research.config import BacktestConfig, Settings


class BacktestValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = {'X-Trader-Request': 'local-ui'}
        self.values = dict(pattern='vcp', start='2024-09-30', end='2025-01-01',
                           fee_model='zerodha_equity', entry_mode='next_open',
                           acknowledge_limitations=True)

    def test_legacy_tariff_selection_uses_plus_for_earlier_dates(self):
        config = BacktestConfig(**self.values)
        self.assertEqual(config.fee_model,'upstox_plus')

    def test_supported_dates_and_custom_costs_queue_long_backtests(self):
        for changes in ({'start': '2024-10-01'}, {'fee_model': 'custom_bps'},
                        {'pattern': None, 'fee_model': 'custom_bps'}):
            values = {**self.values, **changes}
            if values['pattern'] is None:
                del values['pattern']  # Older clients rely on the long default.
            with self.subTest(changes=changes), patch('dashboard.api.main.settings', return_value=Settings()), \
                    patch('dashboard.api.main.backtest.prepare') as prepare, \
                    patch('dashboard.api.main.jobs.submit', return_value={'status': 'queued'}):
                response = self.client.post('/api/jobs/backtest', json=values, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIs(type(prepare.call_args.args[1]), BacktestConfig)

    def test_bearish_history_uses_bearish_config(self):
        values = {**self.values, 'pattern': 'new_lows', 'fee_model': 'custom_bps'}
        with patch('dashboard.api.main.store.token'), \
                patch('dashboard.api.main.settings', return_value=Settings()), \
                patch('dashboard.api.main.jobs.submit', return_value={'status': 'queued'}) as submit:
            response = self.client.post('/api/jobs/backtest-history', json=values, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(submit.call_args.args[2]['pattern'], 'new_lows')
        self.assertEqual(submit.call_args.args[2]['borrow_cost_bps_year'], 0)
