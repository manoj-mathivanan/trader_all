import unittest
import tempfile
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from fastapi.testclient import TestClient
from core.research import backtest, store, strategy_presets
from core.research.config import BacktestConfig
from core.research.sector_breadth import SectorBreadth


def inputs():
    data = {}
    for symbol in ('A', 'B', 'C', 'D', 'E'):
        data[symbol] = [dict(date=str(date(2025,1,1)+timedelta(days=i)),
            open=100, high=160, low=99, close=100 if i<199 else 150 if symbol in ('A','B') else 50,
            volume=1000000) for i in range(202)]
    instruments = [dict(symbol=s,sector='Test sector') for s in data]
    return data, instruments


class SectorBreadthTests(unittest.TestCase):
    def test_threshold_coverage_unknown_mapping_and_future_prices(self):
        data, instruments = inputs()
        day = data['A'][199]['date']
        gate = SectorBreadth(data,instruments,40,80)
        self.assertTrue(gate.decision('A',day)['allowed'])
        self.assertEqual(gate.decision('A',day)['breadth_pct'],40)
        self.assertFalse(gate.decision('A',data['A'][198]['date'])['allowed'])
        self.assertFalse(gate.decision('UNKNOWN',day)['allowed'])
        future = deepcopy(data)
        for rows in future.values():
            rows[200]['close'] = 1000000
        self.assertEqual(gate.decision('A',day),SectorBreadth(future,instruments,40,80).decision('A',day))
        missing = deepcopy(data)
        missing['E'] = missing['E'][:199]
        self.assertTrue(SectorBreadth(missing,instruments,40,80).decision('A',day)['allowed'])
        missing['D'] = missing['D'][:199]
        self.assertEqual(SectorBreadth(missing,instruments,40,80).decision('A',day)['reason'],'insufficient_sector_history')

    def test_engine_uses_signal_session_and_enforces_gate_in_paper_observation_mode(self):
        data, instruments = inputs()
        cfg = BacktestConfig(start=data['A'][200]['date'],end=data['A'][201]['date'],
            pattern='blue_sky', entry_mode='next_open', capital=100000,
            skip_weak_markets=True,market_breadth_scope='sector',market_breadth_pct=60,
            max_positions=1,acknowledge_limitations=True)
        # Entry-session closes rise, but the completed signal session has only 40% breadth.
        for rows in data.values():
            rows[200]['close'] = 150
        with patch.object(backtest,'signal',side_effect=lambda rows,i,c:i==199):
            result = backtest.simulate(data,cfg,sector_instruments=instruments,sector_observe_only=True)
        self.assertEqual(result['metrics']['trade_count'],0)
        self.assertTrue(result['sector_checks'])
        self.assertTrue(all(not check['allowed'] for check in result['sector_checks']))
        self.assertTrue(all(check['day']==data['A'][199]['date'] for check in result['sector_checks']))
        with self.assertRaisesRegex(ValueError,'captured stock sector'):
            backtest.simulate(data,cfg)

    def test_scope_validation_and_legacy_default(self):
        values=dict(start='2025-01-01',end='2025-02-01',acknowledge_limitations=True)
        self.assertEqual(BacktestConfig(**values).market_breadth_scope,'market')
        for changes in (dict(entry_mode='close'),dict(market_risk_scale=.5),
                        dict(market_breadth_trend_sessions=5),dict(execution_horizon='intraday')):
            with self.assertRaises(ValidationError):
                BacktestConfig(**{**values,'skip_weak_markets':True,'market_breadth_scope':'sector',
                                  'entry_mode':'next_open',**changes})

    def test_frozen_form_window_does_not_use_current_universe_history(self):
        from dashboard.api.main import app
        with tempfile.TemporaryDirectory() as directory, patch.object(store,'DATA',Path(directory)):
            store.write('runs/123456789abc', dict(config=dict(start='2025-03-03',end='2026-10-08'),
                manifest=[dict(symbol='A')], universe_snapshot=dict(instruments=[dict(symbol='A'),dict(symbol='B')]),
                excluded=['B']))
            with patch.object(backtest,'available_window',side_effect=AssertionError('Current history must not determine a frozen window')):
                response=TestClient(app).get('/api/backtest/window?warmup=260&reference_id=123456789abc')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['start'],'2025-03-03')
            self.assertEqual(response.json()['history_end'],'2026-10-08')
            self.assertEqual(response.json()['missing_symbols'],['B'])

    def test_saved_sector_preset_preserves_scope_and_both_thresholds(self):
        preset=next(p for p in strategy_presets.available() if p['name']=='Blue Sky BE10 Sector 60 - Zerodha')
        values=preset['trading_defaults']
        cfg=BacktestConfig(**values,start='2025-03-03',end='2026-10-08',acknowledge_limitations=True)
        self.assertTrue(cfg.skip_weak_markets)
        self.assertEqual((cfg.market_breadth_scope,cfg.market_breadth_pct,cfg.market_min_coverage_pct),('sector',60,80))


if __name__ == '__main__':
    unittest.main()
