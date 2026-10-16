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

    def test_tariff_error_only_validates_selected_strategy(self):
        for path in ('backtest', 'backtest-history'):
            with self.subTest(path=path), patch('dashboard.api.main.jobs.submit') as submit:
                response = self.client.post('/api/jobs/' + path, json=self.values, headers=self.headers)
                self.assertEqual(response.status_code, 422)
                errors = response.json()['detail']
                self.assertEqual(len(errors), 1)
                self.assertIn('Custom buy/sell bps for earlier tests', errors[0]['msg'])
                self.assertNotIn('function-after', str(errors))
                self.assertNotIn('breakdown', str(errors))
                submit.assert_not_called()

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
