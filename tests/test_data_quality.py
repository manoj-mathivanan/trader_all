import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from dashboard.api.main import app

from core.research import backtest, data_quality, store
from core.research.config import BacktestConfig, Settings
from strategies.swing_patterns.patterns.signals import ipo
from scripts.audit_data import audit_directory, audit_frozen_runs


def candles(count=60):
    return [dict(date=(date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                 open=100, high=101, low=99, close=100, volume=1000) for i in range(count)]


def config(**changes):
    return BacktestConfig(**{'start': '2025-02-21', 'end': '2025-03-01',
                             'acknowledge_limitations': True, 'min_turnover': 0, **changes})


class DataQualityTests(unittest.TestCase):
    def test_gap_scan_bounds_boundary_and_source_preservation(self):
        rows = candles(4)
        rows[1]['open'] = 65
        rows[2]['open'] = 135
        rows[3]['open'] = 64
        before = deepcopy(rows)
        report = data_quality.audit({'TEST': rows}, start=rows[1]['date'], end=rows[2]['date'])
        self.assertEqual([x['gap_pct'] for x in report['findings']], [-35, 35])
        self.assertEqual(rows, before)
        with self.assertRaisesRegex(ValueError, 'TEST on 2025-01-02'):
            data_quality.require_no_anomalies(report)
        report = data_quality.audit({'TEST': rows}, after=rows[2]['date'])
        self.assertEqual([x['date'] for x in report['findings']], [rows[3]['date']])

    def test_no_gap_does_not_assert_adjustment_verified(self):
        report = data_quality.audit({'TEST': candles()})
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['adjustment_status'], 'unverified')

    def test_ipo_requires_sourced_listing_and_age_at_signal(self):
        rows = candles()
        rows[50].update(close=105, high=106, volume=2000)
        cfg = config(pattern='ipo', ipo_max_age_days=60)
        self.assertFalse(ipo(rows, 50, cfg))
        evidence = {'listing_date': '2025-01-01', 'source': 'unit-test initial IPO notice', 'verified': True, 'ipo_verified': True}
        enriched = data_quality.with_listing_metadata(rows, evidence)
        self.assertTrue(ipo(enriched, 50, cfg))
        exchange_only = data_quality.with_listing_metadata(rows, {**evidence, 'ipo_verified': False})
        self.assertFalse(ipo(exchange_only, 50, cfg))
        enriched.append(dict(rows[-1], date='2030-01-01'))
        self.assertTrue(ipo(enriched, 50, cfg))
        enriched[0]['listing_metadata']['listing_date'] = '2024-01-01'
        self.assertFalse(ipo(enriched, 50, cfg))
        enriched[0]['listing_metadata']['listing_date'] = '2026-01-01'
        self.assertFalse(ipo(enriched, 50, cfg))
        self.assertNotIn('listing_metadata', rows[0])
        with self.assertRaises(ValueError):
            data_quality.with_listing_metadata(rows, {'listing_date': '2025-01-01'})

    def test_breadth_blocks_missing_and_partial_history_allows_exact_200(self):
        rows = candles(201)
        rows[199]['close'] = 105
        cfg = config(start=rows[200]['date'], end='2025-08-01', skip_weak_markets=True)
        with patch.object(backtest, 'signal', return_value=True):
            result = backtest.simulate({'TEST': rows}, cfg)
            self.assertTrue(result['state']['orders'])
            partial = backtest.simulate({'TEST': rows, 'YOUNG': rows[180:]}, cfg)
            self.assertEqual(partial['state']['orders'], [])
            missing = backtest.simulate({'YOUNG': rows[180:]}, cfg)
            self.assertEqual(missing['state']['orders'], [])

    def test_backtest_gap_halts_before_report_or_inputs_are_written(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            rows = candles()
            rows[55]['open'] = 50
            store.write('universes/nifty50', {'instruments': [{'symbol': 'TEST', 'isin': 'TEST'}]})
            store.write('bars/TEST', {'bars': rows, 'requested_start': '2025-01-01',
                                     'requested_end': '2025-03-01', 'source': 'unit-test'})
            with self.assertRaisesRegex(ValueError, 'Price discontinuity'):
                backtest.run(Settings(), config(), lambda _: None, 'test-run')
            self.assertIsNone(store.read('runs/test-run'))
            self.assertIsNone(store.read('run_data/test-run'))

    def test_directory_audit_matches_isin_to_trade_symbol_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            rows = candles(3)
            rows[1]['open'] = 50
            store.write('universes/nifty50', {'instruments': [{'isin': 'INE000', 'symbol': 'TEST'}]})
            store.write('bars/INE000', {'bars': rows})
            run = {'id': 'old', 'trades': [{'symbol': 'TEST', 'entry_date': rows[0]['date'], 'exit_date': rows[2]['date']}]}
            store.write('runs/old', run)
            report = audit_directory(Path(temp))
            self.assertEqual(report['findings'][0]['symbol'], 'TEST')
            self.assertEqual(len(report['runs'][0]['holding_period_overlaps']), 1)
            self.assertEqual(store.read('runs/old'), run)

    def test_audit_api_reports_gaps_missing_history_without_changing_prices(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            rows = candles(3)
            rows[1]['open'] = 50
            store.write('universes/nifty50', {'instruments': [{'isin': 'INE000', 'symbol': 'TEST'},
                                                            {'isin': 'INE001', 'symbol': 'MISSING'}]})
            store.write('bars/INE000', {'bars': rows})
            with TestClient(app) as client:
                response = client.get('/api/data-quality')
            self.assertEqual(response.status_code, 200)
            report = response.json()
            self.assertEqual(report['symbols_scanned'], 1)
            self.assertEqual(report['findings'][0]['symbol'], 'TEST')
            self.assertEqual(report['missing_symbols'], ['MISSING'])
            self.assertEqual(report['adjustment_status'], 'unverified')
            self.assertEqual(store.read('bars/INE000')['bars'], rows)

    def test_frozen_audit_replays_sourced_prelisting_fix_in_separate_artifact(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DATA', Path(temp)):
            rows = candles(65)
            for i, row in enumerate(rows):
                row['date'] = (date(2022, 5, 10) + timedelta(days=i)).isoformat()
            raw = [dict(rows[0], date='2018-01-01', close=.1), *rows]
            cfg = config(start='2022-07-01', end='2022-07-20')
            original = {'id':'old', 'config':cfg.model_dump(mode='json'), 'metrics':{'final_equity':12345},
                        'universe_snapshot':{'instruments':[{'symbol':'RAINBOW','isin':'INE961O01016'}]}}
            store.write('runs/old', original)
            store.write('run_data/old', {'RAINBOW':raw})
            report = audit_frozen_runs(Path(temp), Path(temp)/'replays')
            self.assertEqual(report['runs'][0]['replay_status'], 'replayed')
            self.assertEqual(report['runs'][0]['history_changes'][0]['removed_prelisting_bars'],1)
            self.assertTrue((Path(temp)/'replays/old.json').exists())
            self.assertEqual(store.read('runs/old'), original)
            self.assertEqual(store.read('run_data/old')['RAINBOW'], raw)


if __name__ == '__main__':
    unittest.main()
