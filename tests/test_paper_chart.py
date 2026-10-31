import unittest
from unittest.mock import patch

from core.portfolio.paper_chart import chart_data


class PaperChartTests(unittest.TestCase):
    def setUp(self):
        self.closed = dict(symbol='TEST', entry_date='2026-10-01', exit_date='2026-10-02',
                           entry=100, exit=110, quantity=2, pnl=20)
        self.open = dict(entry_date='2026-10-03', entry=105, quantity=1)
        self.bars = [dict(date=f'2026-10-0{i}', timestamp=i, open=100, high=110,
                          low=90, close=105, volume=10) for i in range(1, 6)]
        self.portfolio = dict(universe_snapshot=dict(instruments=[dict(symbol='TEST', isin='TESTISIN')]),
                              ledger=dict(trades=[self.closed], positions={'TEST': self.open},
                                          last_session='2026-10-04'))

    def test_repeated_symbol_includes_closed_and_open_fills_without_future_bars(self):
        with patch('core.research.store.read', return_value={'bars': self.bars}) as read:
            result = chart_data(self.portfolio, 'TEST', '2026-10-03')
        read.assert_called_once_with('bars/TESTISIN', {})
        self.assertEqual(len(result['trades']), 2)
        self.assertEqual(result['trade']['entry'], 105)
        self.assertNotIn('exit_date', result['trades'][-1])
        self.assertEqual(result['bars'][-1]['date'], '2026-10-04')
        self.assertIn('not a frozen', result['notice'])

    def test_unrecorded_stock_or_trade_cannot_request_market_data(self):
        with patch('core.research.store.read') as read:
            with self.assertRaisesRegex(ValueError, 'Trade not found'):
                chart_data(self.portfolio, '../other', '2026-10-01')
            with self.assertRaisesRegex(ValueError, 'Trade not found'):
                chart_data(self.portfolio, 'TEST', '2026-10-01', '2026-10-03')
        read.assert_not_called()

    def test_missing_fill_candle_reports_unavailability(self):
        with patch('core.research.store.read', return_value={'bars': self.bars[1:]}):
            with self.assertRaisesRegex(ValueError, 'candles.*unavailable'):
                chart_data(self.portfolio, 'TEST', '2026-10-01', '2026-10-02')

    def test_changed_frozen_inputs_do_not_fall_back_to_cache(self):
        self.portfolio.update(input_reference='saved/input', cycles=[{'input_sha256': 'wrong'}])
        with patch('core.research.store.read', return_value={'datasets': {'TEST': self.bars}}) as read:
            with self.assertRaisesRegex(ValueError, 'unavailable or changed'):
                chart_data(self.portfolio, 'TEST', '2026-10-03')
        read.assert_called_once_with('saved/input')

    def test_saved_indicator_inputs_supply_lines_and_open_entry_marker_context(self):
        from tests.test_four_indicator_swing import rows
        from core.research.four_indicator_swing import digest
        bars = rows()
        position = dict(symbol='TEST', signal_date=bars[100]['date'],
                        entry_date=bars[101]['date'], entry=100, quantity=1)
        frozen = {'datasets': {'TEST': bars}}
        portfolio = dict(config={'rule_set': 'bollinger'}, input_reference='saved/input',
                         cycles=[{'input_sha256': digest(frozen)}],
                         ledger=dict(positions={'TEST': position}, trades=[], last_session=bars[-1]['date']))
        with patch('core.research.store.read', return_value=frozen):
            result = chart_data(portfolio, 'TEST', position['entry_date'])
        self.assertEqual(result['explanation']['signal']['date'], position['signal_date'])
        self.assertIn('supertrend', [s['id'] for s in result['explanation']['series']])
        self.assertIn('rsi', result['bars'][-1]['chart_values'])
        self.assertNotIn('exit_date', result['trade'])

    def test_api_uses_requested_scenario_and_reports_missing_trade(self):
        from fastapi.testclient import TestClient
        from dashboard.api.main import app
        client = TestClient(app)
        with patch('dashboard.api.main.PAPER_ENABLED', True), \
             patch('dashboard.api.main.portfolios.get', return_value=self.portfolio) as get, \
             patch('core.research.store.read', return_value={'bars': self.bars}):
            response = client.get('/api/strategies/swing_patterns/paper/chart', params={
                'portfolio_id': 'scenario_test', 'symbol': 'TEST', 'entry_date': '2026-10-03'})
            self.assertEqual(response.status_code, 200, response.text)
            get.assert_called_with('swing_patterns', 'scenario_test')
            self.assertEqual(len(response.json()['trades']), 2)
            response = client.get('/api/strategies/swing_patterns/paper/chart', params={
                'symbol': 'UNKNOWN', 'entry_date': '2026-10-03'})
            self.assertEqual(response.status_code, 404)
