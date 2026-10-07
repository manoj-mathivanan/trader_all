"""A trade chart must use the run snapshot, never the current market cache."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from core.research import store
from dashboard.api.main import app


class TradeChartTests(unittest.TestCase):
    def test_frozen_history_and_original_trade_index(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            bars = [{'date': (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
                     'timestamp': 1577836800000 + i * 86400000,
                     'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 10}
                    for i in range(150)]
            trades = [{'symbol': 'TEST', 'entry_date': bars[a]['date'],
                       'exit_date': bars[b]['date'], 'entry': 101, 'exit': 109,
                       'quantity': 2, 'pnl': 16, 'reason': 'Stop'} for a, b in [(65, 70), (90, 100)]]
            trades.append(dict(trades[0], symbol='OTHER'))
            store.write('runs/123456abcdef', {'config': {'end': bars[105]['date']}, 'trades': trades})
            store.write('run_data/123456abcdef', {'TEST': bars})
            store.write('bars/TEST00000001', {'bars': [{'close': 999}]})
            client = TestClient(app)
            data = client.get('/api/runs/123456abcdef/trades/1/chart').json()
            self.assertEqual(data['trade'], trades[1])
            self.assertEqual(data['source'], 'frozen_backtest_snapshot')
            self.assertEqual([t['trade_index'] for t in data['trades']], [0, 1])
            self.assertEqual([{k:v for k,v in b.items() if k != 'chart_values'} for b in data['bars']], bars[5:106])
            earlier = client.get('/api/runs/123456abcdef/trades/0/chart').json()
            self.assertEqual(earlier['trades'], data['trades'])
            self.assertEqual([b['date'] for b in earlier['bars']], [b['date'] for b in data['bars']])
            self.assertIn('sma_50', data['bars'][44]['chart_values'])
            self.assertEqual(data['explanation']['signal']['date'], bars[89]['date'])
            self.assertEqual(client.get('/api/runs/123456abcdef/trades/-1/chart').status_code, 404)
            self.assertEqual(client.get('/api/runs/123456abcdef/trades/3/chart').status_code, 404)
            self.assertEqual(client.get('/api/runs/invalid/trades/0/chart').status_code, 404)

    def test_missing_snapshot_never_falls_back(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            store.write('runs/123456abcdef', {'config': {'end': '2020-02-01'},
                        'trades': [{'symbol': 'TEST', 'entry_date': '2020-01-02', 'exit_date': '2020-01-03'}]})
            client = TestClient(app)
            response = client.get('/api/runs/123456abcdef/trades/0/chart')
            self.assertEqual(response.status_code, 404)
            self.assertIn('saved candles', response.json()['detail'])
