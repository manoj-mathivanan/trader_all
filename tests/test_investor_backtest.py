"""Investor scanner replay must use completed signals and frozen evidence."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from core.research import backtest, investor_breakouts, store, trade_chart
from core.research.config import BacktestConfig, Settings, TradingConfig
from dashboard.api.main import app


def candles(breaks=True):
    rows = []
    for i in range(101):
        close = 80 + i * .2 if i < 80 else 99 + (i - 80) * .025
        spread = 1 if i < 95 else .3
        rows.append(dict(date=(date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                         timestamp=1735689600000 + i * 86400000,
                         open=close, high=close + spread, low=close - spread, close=close,
                         volume=500000 if i < 95 else 200000))
    if breaks:
        pivot = max(b['high'] for b in rows[-41:-1])
        rows[-1].update(close=pivot * 1.01, high=pivot * 1.012, volume=800000)
    for i in (101, 102):
        rows.append(dict(rows[-1], date=(date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                         timestamp=1735689600000 + i * 86400000,
                         open=102, high=103, low=101, close=102, volume=500000))
    return rows


class InvestorBacktestTests(unittest.TestCase):
    def config(self, **changes):
        bars = candles()
        return BacktestConfig(**{**dict(pattern='investor_early_breakout', entry_mode='next_open',
                                       start=bars[101]['date'], end=bars[102]['date'],
                                       acknowledge_limitations=True), **changes})

    def test_scanner_parity_and_future_independence(self):
        cfg, bars = self.config(), candles()
        self.assertEqual(investor_breakouts.setup(bars[:101], cfg.investor_rules)['stage'], 'early_breakout')
        self.assertTrue(backtest.signal(bars, 100, cfg))
        bars[101].update(close=1, high=100000, volume=0)
        self.assertTrue(backtest.signal(bars, 100, cfg))
        self.assertFalse(backtest.signal(candles(False), 100, cfg))
        self.assertFalse(backtest.signal(candles(), 99, cfg))
        self.assertFalse(backtest.signal(candles(), 100, self.config(investor_rules={'min_breakout_volume_ratio': 5})))
        self.assertEqual(backtest.required_warmup(cfg), 100)

    def test_next_open_fill_and_costs(self):
        cfg, bars = self.config(), candles()
        result = backtest.simulate({'TEST': bars}, cfg)
        trade = result['trades'][0]
        self.assertEqual(trade['entry_date'], bars[101]['date'])
        self.assertAlmostEqual(trade['entry'], bars[101]['open'] * 1.001)
        self.assertGreater(result['metrics']['modeled_fees'], 0)
        self.assertGreater(result['metrics']['modeled_slippage'], 0)
        explanation = trade_chart.explain_trade({'config': cfg.model_dump(mode='json')},
                                               {'TEST': bars}, trade, bars, 101, 102)
        self.assertEqual(explanation['signal']['date'], bars[100]['date'])
        self.assertTrue(all(c['passed'] is not False for c in explanation['checks']))
        labels = [c['label'] for c in explanation['checks']]
        self.assertIn('Breakout volume / prior 20-session mean', labels)
        self.assertNotIn('Breakout volume / prior 50-session mean', labels)
        self.assertEqual(next(s for s in explanation['series'] if s['id'] == 'trigger')['label'], 'Signal breakout level')

    def test_rejects_same_day_intraday_financial_ranking_and_paper(self):
        for values in ({'entry_mode': 'close'}, {'execution_horizon': 'intraday'},
                       {'candidate_rank': 'fundamental_score'}, {'require_long_trend': True}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.config(**values)
        with self.assertRaises(ValidationError):
            TradingConfig(pattern='investor_early_breakout')
        with self.assertRaises(ValidationError):
            self.config(pattern='vcp', investor_rules={})

    def test_api_routes_to_long_simulator_and_keeps_rules(self):
        with patch('dashboard.api.main.settings', return_value=Settings()), \
                patch('dashboard.api.main.backtest.prepare') as prepare, \
                patch('dashboard.api.main.jobs.submit', return_value={'status': 'queued'}):
            response = TestClient(app).post('/api/jobs/backtest', json=self.config().model_dump(mode='json'),
                                            headers={'X-Trader-Request': 'local-ui'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(prepare.call_args.args[1].investor_rules.resistance_sessions, 40)

    def test_saved_run_replays_without_current_scan_or_news(self):
        cfg, bars = self.config(), candles()
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)), \
                patch.object(backtest, 'prepare', return_value=({'instruments': []}, {'TEST': bars},
                             [{'symbol': 'TEST', 'sha256': backtest.market_history.digest(bars)}], [])):
            backtest.run(Settings(), cfg, lambda message: None, '123456abcdef')
            report = store.read('runs/123456abcdef')
            replay = BacktestConfig(**report['config'])
            store.write('investor/rules', {'min_breakout_volume_ratio': 5})
            result = backtest.simulate(store.read('run_data/123456abcdef'), replay)
            self.assertEqual(result['trades'], report['trades'])
            self.assertTrue(any('financial assessments are excluded' in w for w in report['warnings']))


if __name__ == '__main__':
    unittest.main()
