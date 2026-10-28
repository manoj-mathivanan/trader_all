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
    def test_indicator_snapshot_chart_and_integrity(self):
        from core.research.four_indicator_swing import digest
        from core.strategies.four_indicator import indicators
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            bars = [dict(date=str(date(2025, 1, 1) + timedelta(days=i)),
                         timestamp=1735689600000+i*86400000,
                         open=100+i, high=103+i, low=99+i, close=102+i, volume=10000)
                    for i in range(150)]
            trades = [dict(symbol='TEST', signal_date=bars[a-1]['date'], entry_date=bars[a]['date'],
                           exit_date=bars[b]['date'], entry=bars[a]['open'], exit=bars[b]['open'],
                           quantity=2, pnl=10, reason='Supertrend reversal') for a,b in [(105,110),(120,130)]]
            frozen = dict(datasets={'TEST':bars})
            store.write('run_data/123456abcdef', frozen)
            store.write('runs/123456abcdef', dict(strategy_id='four_indicator_swing',
                        config=dict(end=bars[-1]['date'],rule_set='bollinger'),
                        trades=trades,input_sha256=digest(frozen)))
            client = TestClient(app)
            response = client.get('/api/runs/123456abcdef/trades/1/chart')
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual([t['trade_index'] for t in data['trades']], [0,1])
            self.assertEqual(data['explanation']['signal']['date'], trades[1]['signal_date'])
            row = next(b for b in data['bars'] if b['date'] == bars[119]['date'])
            self.assertEqual(row['chart_values']['supertrend'], indicators(bars)[119]['supertrend'])
            self.assertEqual(row['chart_values']['rsi'], indicators(bars)[119]['rsi'])
            self.assertEqual({s['id'] for s in data['explanation']['series']},
                             {'supertrend','r1','upper_band','rsi','rsi_threshold'})
            self.assertEqual(len(data['explanation']['checks']), 4)
            self.assertEqual(row['chart_values']['rsi_threshold'],70)
            run=store.read('runs/123456abcdef')
            run['config'].update(rsi_threshold=65,bollinger_multiplier=2.5)
            store.write('runs/123456abcdef',run)
            balanced=client.get('/api/runs/123456abcdef/trades/1/chart').json()
            row=next(b for b in balanced['bars'] if b['date']==bars[119]['date'])
            self.assertEqual(row['chart_values']['rsi_threshold'],65)
            self.assertEqual(row['chart_values']['upper_band'],indicators(bars,bollinger_multiplier=2.5)[119]['upper_band'])
            self.assertIn('RSI threshold 65',{s['label'] for s in balanced['explanation']['series']})
            frozen['datasets']['TEST'][-1]['close'] = 9999
            store.write('run_data/123456abcdef', frozen)
            self.assertEqual(client.get('/api/runs/123456abcdef/trades/1/chart').status_code, 404)

    def reference_fixture(self):
        from core.research.config import BacktestConfig
        bars = [dict(date=str(date(2025, 1, 1) + timedelta(days=i)),
                     open=120, high=122, low=119, close=120, volume=1000000) for i in range(310)]
        cfg = BacktestConfig(simulation_model='banana_proxy_v1', pattern='blue_sky', entry_mode='pivot',
                             candidate_rank='rs_126', winner_exit='trail_50d', buy_cost_bps=25, sell_cost_bps=25, max_positions=10,
                             start=bars[253]['date'], end=bars[-1]['date'], acknowledge_limitations=True)
        trade = dict(symbol='PAYTM', entry_date=bars[300]['date'], exit_date=bars[305]['date'], entry=121, quantity=10)
        audit = dict(symbol='PAYTM', date=trade['entry_date'], decision_date=bars[299]['date'],
                     reason='Filled', pivot=120, rs=94.236, rs_population=433, median_turnover=5640768422.5,
                     positions_before=8, priority=1, sizing_constraint='risk')
        return bars, trade, dict(config=cfg.model_dump(mode='json'), candidate_audit=[audit])

    def test_reference_explanation_uses_recorded_fill_and_frozen_setup(self):
        from copy import deepcopy
        from core.research.trade_chart import explain_trade
        bars, trade, result = self.reference_fixture()
        original = deepcopy((bars, trade, result))
        explanation = explain_trade(result, {'PAYTM': bars}, trade, bars, 300, 305)
        checks = {c['label']: c for c in explanation['checks']}
        self.assertTrue(checks['Completed pattern setup']['passed'])
        self.assertEqual(checks['Weighted relative strength']['actual'], 94.236)
        self.assertIn('433 eligible stocks', checks['Weighted relative strength']['required'])
        self.assertEqual(checks['Median 20-session turnover (₹)']['actual'], 5640768422.5)
        self.assertTrue(checks['Open positions before entry']['passed'])
        self.assertEqual(checks['Position sizing constraint']['actual'], 'risk')
        self.assertEqual(explanation['candidate_rank'], 'weighted_rs')
        self.assertEqual((bars, trade, result), original)
        bars[306]['close'] = 1000000
        self.assertEqual(explain_trade(result, {'PAYTM': bars}, trade, bars, 300, 305)['checks'], explanation['checks'])

    def test_reference_missing_audit_is_explicit_without_invented_rs(self):
        from core.research.trade_chart import explain_trade
        bars, trade, result = self.reference_fixture()
        result['candidate_audit'][0]['reason'] = 'Book full'
        explanation = explain_trade(result, {}, trade, bars, 300, 305)
        self.assertGreater(len(explanation['checks']), 0)
        strength = next(c for c in explanation['checks'] if c['label'] == 'Weighted relative strength')
        self.assertIsNone(strength['actual'])
        self.assertIsNone(strength['passed'])
        self.assertTrue(any('no saved Filled audit' in n for n in explanation['notices']))

    def test_reference_next_open_uses_setup_before_breakout_session(self):
        from core.research.trade_chart import explain_trade
        bars, trade, result = self.reference_fixture()
        result['config']['entry_mode'] = 'next_open'
        result['candidate_audit'] = []
        bars[299]['close'] = 125
        explanation = explain_trade(result, {}, trade, bars, 300, 305)
        self.assertEqual(explanation['signal']['date'], bars[298]['date'])
        trigger = next(c for c in explanation['checks'] if c['label'] == 'Completed breakout close above pivot')
        self.assertEqual(trigger['actual'], 125)
        self.assertTrue(trigger['passed'])

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
