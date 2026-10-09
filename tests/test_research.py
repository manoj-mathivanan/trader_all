"""Isolated unit fixtures only; no generated market data enters the application."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from core.research.config import BacktestConfig, Settings
from core.research.backtest import simulate, signal, available_window
from core.research.upstox import validate_candles, merge_candles
from core.research import store
from core.strategies.registry import all_strategies, get_strategy
from dashboard.api.main import app


def config(**kwargs):
    return BacktestConfig(capital=100000, buy_cost_bps=10, sell_cost_bps=10,
                          acknowledge_limitations=True, start=date(2020, 1, 1), end=date(2020, 6, 1), **kwargs)


def candle(day, opening, high, low, close):
    return dict(date=day, open=opening, high=high, low=low, close=close, volume=1000000)


class ExecutionTests(unittest.TestCase):
    def test_15_percent_target_uses_close_and_preserves_25_percent_mode(self):
        bars = [candle('2020-01-01', 100, 101, 99, 100),
                candle('2020-01-02', 100, 116, 99, 100),
                candle('2020-01-03', 110, 116, 109, 114),
                candle('2020-01-04', 114, 117, 113, 116),
                candle('2020-01-05', 116, 121, 115, 120)]
        for mode, day, reason in [('take_8', '2020-01-03', 'Take profit +8%'),
                                  ('take_15', '2020-01-04', 'Take profit +15%'),
                                  ('take_25', '2020-01-05', 'End of available test data')]:
            with self.subTest(mode=mode), patch('core.research.backtest.signal', side_effect=lambda rows, i, cfg: i == 0):
                cfg = config(pattern='blue_sky', entry_mode='next_open', winner_exit=mode, slippage_bps=0)
                result = simulate({'TEST': bars}, cfg)
                self.assertEqual(len(result['trades']), 1)
                self.assertEqual(result['trades'][0]['exit_date'], day)
                self.assertEqual(result['trades'][0]['reason'], reason)

    def test_next_open_and_gap_stop_with_costs(self):
        bars = [candle('2020-01-01', 100, 105, 99, 104),
                candle('2020-01-02', 110, 112, 109, 111),
                candle('2020-01-03', 80, 85, 79, 83)]
        with patch('core.research.backtest.signal', side_effect=lambda bars, i, cfg: i == 0):
            result = simulate({'TEST': bars}, config())
        trade = result['trades'][0]
        self.assertEqual(trade['entry_date'], '2020-01-02')
        self.assertAlmostEqual(trade['entry'], 110 * 1.001)
        self.assertAlmostEqual(trade['exit'], 80 * .999)
        self.assertEqual(trade['reason'], 'Gap through stop')
        self.assertGreater(trade['fees'], 0)
        self.assertAlmostEqual(result['metrics']['final_equity'], 100000 + trade['pnl'], places=2)

    def test_shared_cash_does_not_buy_with_later_intraday_proceeds(self):
        bars = [candle('2020-01-01', 100, 101, 99, 100), candle('2020-01-02', 100, 110, 80, 105)]
        with patch('core.research.backtest.signal', return_value=True):
            result = simulate({str(i): bars for i in range(20)}, config(risk_pct=5))
        self.assertLessEqual(sum(t['entry'] * t['quantity'] * 1.001 for t in result['trades']), 100000)
        self.assertGreater(result['metrics']['skipped_entries'], 0)

    def test_trailing_stop_not_retroactive(self):
        bars = [candle('2020-01-01', 100, 101, 99, 100),
                candle('2020-01-02', 100, 125, 95, 120),
                candle('2020-01-03', 118, 120, 109, 111)]
        with patch('core.research.backtest.signal', side_effect=lambda bars, i, cfg: i == 0):
            result = simulate({'TEST': bars}, config())
        self.assertEqual(result['trades'][0]['exit_date'], '2020-01-03')
        self.assertAlmostEqual(result['trades'][0]['exit'], 120 * .92 * .999)

    def test_signal_ignores_future_and_current_bar_in_base(self):
        bars = [candle((date(2019, 1, 1) + timedelta(days=i)).isoformat(), 100, 101, 99, 100) for i in range(51)]
        bars[-1].update(close=105, high=106, volume=2000000)
        self.assertTrue(signal(bars, 50, config()))
        bars.append(candle('2019-03-01', 1, 1, 1, 1))
        self.assertTrue(signal(bars, 50, config()))

    def test_no_trade_metrics_are_not_fabricated(self):
        result = simulate({'TEST': [candle('2020-01-01',100,101,99,100)]}, config())
        self.assertEqual(result['metrics']['final_equity'], 100000)
        self.assertIsNone(result['metrics']['win_rate'])


class DataAndSecurityTests(unittest.TestCase):
    def test_strategy_registry_exposes_active_and_planned_plugins(self):
        definitions = all_strategies()
        self.assertEqual([x['id'] for x in definitions], ['swing_patterns', 'intraday_momentum', 'scalping'])
        self.assertEqual(get_strategy('swing_patterns').backtest_engine, 'daily_breakout')
        self.assertEqual(get_strategy('intraday_momentum').status, 'active')
        self.assertEqual(get_strategy('intraday_momentum').backtest_engine, 'opening_range_momentum')

    def test_incremental_merge_preserves_existing_and_replaces_duplicate(self):
        old = [candle('2026-01-01', 100, 101, 99, 100), candle('2026-01-02', 100, 102, 99, 101)]
        new = [candle('2026-01-02', 101, 103, 100, 102), candle('2026-01-03', 102, 104, 101, 103)]
        merged = merge_candles(old, new)
        self.assertEqual([x['date'] for x in merged], ['2026-01-01', '2026-01-02', '2026-01-03'])
        self.assertEqual(merged[1]['close'], 102)

    def test_backtest_dates_follow_actual_data_and_invalid_dates_do_not_queue(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            start = date(2026, 1, 1)
            bars = [candle((start + timedelta(days=i)).isoformat(), 100, 101, 99, 100) for i in range(80)]
            store.write('universes/nifty50', {'instruments': [{'symbol': 'TEST', 'isin': 'TEST00000001'}]})
            store.write('bars/TEST00000001', {'bars': bars, 'requested_start': '2026-01-01',
                                             'requested_end': bars[-1]['date'], 'source': 'unit_test'})
            window = available_window(Settings())
            self.assertEqual(window['start'], bars[51]['date'])
            self.assertEqual(window['end'], bars[-1]['date'])
            self.assertIsNone(available_window(Settings(), 100)['start'])
            with TestClient(app) as client:
                response = client.post('/api/jobs/backtest', headers={'X-Trader-Request':'local-ui'},
                                       json=config().model_dump(mode='json'))
                self.assertEqual(response.status_code, 400)
                self.assertIn('2026-01-01', response.json()['detail'])
                self.assertEqual(store.read('jobs', []), [])

    def test_invalid_and_duplicate_candles_rejected(self):
        row = ['2020-01-01T00:00:00+05:30', 100, 105, 95, 101, 20]
        for rows in ([row, row], [[row[0], 100, 99, 95, 101, 20]], [[row[0], 100, 105, 95, float('nan'), 20]]):
            with self.assertRaises(ValueError):
                validate_candles(rows, date(2020,1,1), date(2020,1,2))

    def test_local_api_boundary_and_private_token(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)/'data'), patch.dict('os.environ', {'TRADER_KEY_FILE': str(Path(temp)/'key')}):
            with TestClient(app) as client:
                headers={'X-Trader-Request':'local-ui'}
                token='unit-test-not-a-real-access-token'
                self.assertEqual(client.put('/api/connection', json={'access_token':token}).status_code,403)
                self.assertEqual(client.put('/api/connection', headers={**headers,'Origin':'https://untrusted.example'}, json={'access_token':token}).status_code,403)
                self.assertEqual(client.put('/api/connection',headers=headers,json={'access_token':token}).status_code,200)
                invalid = client.put('/api/connection',headers=headers,json={'access_token':'short-secret'})
                self.assertEqual(invalid.status_code,422)
                self.assertNotIn('short-secret', invalid.text)
                self.assertEqual(store.token(), token)
                self.assertEqual(json.loads((Path(temp)/'data/private/upstox.json').read_text())['access_token'], token)
                bootstrap = client.get('/api/bootstrap')
                self.assertNotIn(token, bootstrap.text)
                self.assertTrue(bootstrap.json()['token_saved'])
                self.assertEqual(client.get('/api/bootstrap', headers={'Host':'attacker.example'}).status_code,403)
                self.assertEqual(client.get('/api/bars/not-a-path').status_code,404)
                self.assertEqual(client.get('/api/runs/not-a-path').status_code,404)

    def test_remote_origin_and_private_storage_separation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)/'data'), patch.dict('os.environ', {'TRADER_PRIVATE_DIR': str(Path(temp)/'private')}), patch('dashboard.api.main.PUBLIC_ORIGIN', 'https://trader.example.com'):
            with TestClient(app, base_url='https://trader.example.com') as client:
                token = 'unit-test-not-a-real-access-token'
                headers = {'X-Trader-Request': 'local-ui', 'Origin': 'https://trader.example.com'}
                self.assertEqual(client.put('/api/connection', headers=headers, json={'access_token': token}).status_code, 200)
                self.assertTrue((Path(temp)/'private/upstox.json').exists())
                self.assertFalse((Path(temp)/'data/private/upstox.json').exists())
                self.assertNotIn(token, client.get('/api/bootstrap').text)
                self.assertEqual(client.put('/api/connection', headers={**headers, 'Origin': 'https://attacker.example'}, json={'access_token': token}).status_code, 403)
                self.assertEqual(client.get('/', headers={'Host': 'attacker.example'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
