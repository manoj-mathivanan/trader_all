"""Execution and restart tests use synthetic fixtures in temporary storage only."""
import tempfile
import unittest
import os
import sys
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from pydantic import ValidationError
from core.portfolio import paper, scheduler, manager, registry
from core.research import backtest, store, upstox, jobs
from core.research.config import Settings
from core.research.config import BacktestConfig
from dashboard.api.main import app


def candle(day, price=100, low=99):
    return {'date': str(day), 'open': price, 'high': price + 2,
            'low': low, 'close': price + 1, 'volume': 1000000}


def config(**kwargs):
    return paper.PaperConfig(**{'capital': 100000, 'acknowledge_limitations': True, **kwargs})


class EngineTests(unittest.TestCase):
    def test_final_close_entry_is_liquidated_with_both_costs(self):
        bars = [candle('2026-01-01'), candle('2026-01-02')]
        cfg = BacktestConfig(start='2026-01-01', end='2026-01-03', pattern='vcp', entry_mode='close',
                             acknowledge_limitations=True)
        with patch.object(backtest, 'signal', side_effect=lambda bars, i, cfg: i == 1):
            result = backtest.simulate({'TEST': bars}, cfg)
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['state']['positions'], {})
        self.assertGreater(result['trades'][0]['fees'], 0)

    def test_unreached_pivot_does_not_fill(self):
        bars = [candle('2026-01-01', 150, 149), candle('2026-01-02', 150, 149), candle('2026-01-03', 100, 99)]
        cfg = BacktestConfig(start='2026-01-01', end='2026-01-04', pattern='vcp', entry_mode='pivot',
                             acknowledge_limitations=True)
        with patch.object(backtest, 'signal', side_effect=lambda bars, i, cfg: i == 1):
            result = backtest.simulate({'TEST': bars}, cfg)
        self.assertEqual(result['state']['orders'], [])

    def test_pivot_entry_cannot_retroactively_stop_on_entry_low(self):
        bars = [candle('2026-01-01'), candle('2026-01-02', 100, 80), candle('2026-01-03')]
        cfg = BacktestConfig(start='2026-01-01', end='2026-01-04', pattern='vcp', entry_mode='pivot',
                             acknowledge_limitations=True)
        with patch.object(backtest, 'signal', side_effect=lambda bars, i, cfg: i == 0):
            result = backtest.simulate({'TEST': bars}, cfg)
        self.assertEqual(result['trades'][0]['exit_date'], '2026-01-03')
        self.assertEqual(result['trades'][0]['reason'], 'End of available test data')

    def test_incremental_equals_one_pass_and_keeps_positions(self):
        bars = [candle(date(2026, 1, 1) + timedelta(days=i)) for i in range(4)]
        bars[-1] = candle(date(2026, 1, 4), 80, 79)
        cfg = SimpleNamespace(**config().model_dump(), start='2026-01-02', end='2026-01-04')
        with patch.object(backtest, 'signal', side_effect=lambda bars, i, cfg: i == 0):
            full = backtest.simulate({'TEST': bars}, cfg, liquidate=False)
            cfg.end = '2026-01-02'
            first = backtest.simulate({'TEST': bars}, cfg, liquidate=False)
            self.assertIn('TEST', first['state']['positions'])
            self.assertEqual(first['trades'], [])
            before = first['state']['cash']
            cfg.end = '2026-01-04'
            second = backtest.simulate({'TEST': bars}, cfg, state=first['state'], liquidate=False)
        self.assertEqual(second, full)
        self.assertEqual(first['state']['cash'], before)
        self.assertEqual(second['trades'][0]['reason'], 'Gap through stop')
        self.assertAlmostEqual(second['state']['cash'], cfg.capital + second['trades'][0]['pnl'])
        self.assertGreater(second['metrics']['modeled_fees'], 0)

    def test_pause_manages_stop_and_prevents_buys(self):
        bars = [candle('2026-01-01'), candle('2026-01-02'), candle('2026-01-03', 80, 79)]
        cfg = SimpleNamespace(**config().model_dump(), start='2026-01-02', end='2026-01-02')
        with patch.object(backtest, 'signal', return_value=True):
            first = backtest.simulate({'TEST': bars}, cfg, liquidate=False)
            cfg.end = '2026-01-03'
            second = backtest.simulate({'TEST': bars, 'OTHER': bars}, cfg,
                                       state=first['state'], liquidate=False, allow_entries=False)
        self.assertEqual(len(second['state']['orders']), 2)
        self.assertEqual(second['state']['positions'], {})

    def test_existing_exit_rules_are_frozen(self):
        bars = [candle('2026-01-01'), candle('2026-01-02'), candle('2026-01-03')]
        cfg = SimpleNamespace(**config(max_hold_days=120).model_dump(), start='2026-01-02', end='2026-01-02')
        with patch.object(backtest, 'signal', return_value=True):
            first = backtest.simulate({'TEST': bars}, cfg, liquidate=False)
            cfg.max_hold_days, cfg.end = 1, '2026-01-03'
            second = backtest.simulate({'TEST': bars}, cfg, state=first['state'], liquidate=False)
        self.assertIn('TEST', second['state']['positions'])

    def test_breadth_filter_uses_signal_session(self):
        bars = [candle(date(2025, 1, 1) + timedelta(days=i)) for i in range(202)]
        bars[200] = candle(bars[200]['date'], 80, 79)
        bars[201] = candle(bars[201]['date'], 150, 149)
        cfg = SimpleNamespace(**config(skip_weak_markets=True).model_dump(), start=bars[201]['date'], end=bars[201]['date'])
        with patch.object(backtest, 'signal', return_value=True):
            result = backtest.simulate({'TEST': bars}, cfg, liquidate=False)
        self.assertEqual(result['state']['orders'], [])


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(store, 'DATA', Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.clock = patch.object(paper, 'local_now', return_value=datetime(2026, 1, 1, 17, tzinfo=paper.IST))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.bars = [candle(date(2025, 9, 1) + timedelta(days=i)) for i in range(124)]
        store.write('universes/nifty50', {'instruments': [{'symbol': 'TEST', 'isin': 'TEST00000001'}]})
        self.save_bars()
        self.portfolio = paper.save(config(), Settings(start=date(2025, 9, 1), end=date(2026, 1, 3)), create=True)

    def save_bars(self):
        store.write('bars/TEST00000001', {'bars': self.bars, 'requested_end': '2026-01-04'})

    def cycle(self, **kwargs):
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 17, tzinfo=paper.IST)), \
             patch.object(backtest, 'signal', return_value=True):
            return paper.cycle(lambda _: None, 'unit-cycle', ingest=False, **kwargs)

    def test_forward_only_atomic_checkpoint_and_retry(self):
        self.assertEqual(self.portfolio['start_session'], '2026-01-02')
        self.cycle()
        saved = store.read(paper.KEY)
        self.assertEqual([o['date'] for o in saved['ledger']['orders']], ['2026-01-02'])
        self.assertEqual(saved['ledger']['orders'][0]['mode'], 'paper')
        self.assertIn('TEST', saved['ledger']['positions'])
        self.assertEqual(self.cycle()['sessions'], 0)
        self.assertEqual(store.read(paper.KEY), saved)

    def test_revised_processed_input_halts_without_ledger_change(self):
        self.cycle()
        saved = store.read(paper.KEY)
        self.bars[-2]['close'] += .5
        self.save_bars()
        with self.assertRaisesRegex(ValueError, 'Processed candles changed'):
            self.cycle()
        self.assertEqual(store.read(paper.KEY), saved)

    def test_partial_ingestion_does_not_commit(self):
        with patch.object(upstox, 'ingest', side_effect=ValueError('Partial ingestion')):
            with self.assertRaisesRegex(ValueError, 'Partial ingestion'):
                paper.cycle(lambda _: None, 'failed')
        self.assertEqual(store.read(paper.KEY), self.portfolio)

    def test_creation_and_update_guards(self):
        with self.assertRaisesRegex(ValueError, 'already has'):
            paper.save(config(), Settings(), create=True)
        with self.assertRaisesRegex(ValueError, 'fixed'):
            paper.save(config(capital=200000), Settings())
        changed = paper.save(config(risk_pct=2), Settings())
        self.assertEqual(changed['config']['risk_pct'], 2)
        store.write('jobs', [{'status': 'queued'}])
        with self.assertRaisesRegex(ValueError, 'active job'):
            paper.set_status('paused')

    def test_api_security_and_no_live_mode(self):
        with patch('dashboard.api.main.PAPER_ENABLED', True), TestClient(app) as client:
            self.assertEqual(client.put('/api/paper/status', json={'status': 'paused'}).status_code, 403)
            headers = {'X-Trader-Request': 'local-ui'}
            self.assertEqual(client.put('/api/paper/status', headers=headers, json={'status': 'paused'}).status_code, 200)
            self.assertEqual(client.put('/api/paper/status', headers=headers, json={'status': 'live'}).status_code, 422)
            payload = config().model_dump(mode='json')
            payload['mode'] = 'live'
            self.assertEqual(client.put('/api/paper/portfolio', headers=headers, json=payload).status_code, 422)
            self.assertEqual(client.get('/api/bootstrap').json()['paper_portfolio']['mode'], 'paper')

    def test_scheduler_one_attempt_per_weekday(self):
        paper.save(config(auto_run=True), Settings())
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 16, 20, tzinfo=paper.IST)), \
             patch.object(scheduler.jobs, 'submit', return_value={'id': 'b' * 12}) as submit:
            scheduler.tick()
            scheduler.tick()
            submit.assert_called_once()

    def test_intraday_candles_are_not_processed(self):
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 14, tzinfo=paper.IST)):
            result = paper.cycle(lambda _: None, 'early', ingest=False)
        self.assertEqual(result['sessions'], 0)
        self.assertEqual(store.read(paper.KEY)['ledger'], {})

    def test_interrupted_job_recovery_does_not_repeat_committed_fills(self):
        self.cycle()
        saved = store.read(paper.KEY)
        store.write('jobs', [{'id': 'a' * 12, 'status': 'running', 'logs': []}])
        jobs.recover()
        self.assertEqual(store.read('jobs')[0]['status'], 'failed')
        self.assertEqual(self.cycle()['sessions'], 0)
        self.assertEqual(store.read(paper.KEY), saved)

    def test_scheduled_cycle_is_tracked_and_failure_keeps_portfolio(self):
        paper.save(config(auto_run=True), Settings())
        saved = store.read(paper.KEY)
        captured = []
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 16, 20, tzinfo=paper.IST)), \
             patch.object(jobs.POOL, 'submit', side_effect=captured.append):
            scheduler.tick()
        self.assertEqual(store.read('jobs')[0]['status'], 'queued')
        with patch.object(upstox, 'ingest', side_effect=ValueError('Provider unavailable')):
            captured[0]()
        job = store.read('jobs')[0]
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['logs'][-1]['message'], 'Provider unavailable')
        self.assertEqual(store.read(paper.KEY), saved)

    def test_weekends_and_busy_worker_do_not_claim_schedule(self):
        paper.save(config(auto_run=True), Settings())
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 3, 17, tzinfo=paper.IST)):
            scheduler.tick()
        self.assertIsNone(store.read('paper_schedule'))
        store.write('jobs', [{'status': 'queued'}])
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 17, tzinfo=paper.IST)):
            scheduler.tick()
        self.assertIsNone(store.read('paper_schedule'))

    def test_strategy_capital_configuration_and_ledgers_are_isolated(self):
        momentum = manager.save('intraday_momentum', config(capital=200000, risk_pct=2), Settings(),
                                create=True, clock=paper.local_now())
        self.assertNotEqual(momentum['id'], self.portfolio['id'])
        self.cycle()
        swing = manager.get('swing_patterns')
        self.assertIn('TEST', swing['ledger']['positions'])
        self.assertEqual(manager.get('intraday_momentum'), momentum)
        manager.save('intraday_momentum', config(capital=200000, risk_pct=3), Settings(), clock=paper.local_now())
        manager.set_status('intraday_momentum', 'paused')
        self.assertEqual(manager.get('swing_patterns'), swing)
        self.assertEqual(manager.get('intraday_momentum')['config']['risk_pct'], 3)
        with self.assertRaisesRegex(ValueError, 'already has'):
            manager.save('intraday_momentum', config(capital=200000), Settings(), create=True, clock=paper.local_now())
        with self.assertRaisesRegex(ValueError, 'Unknown strategy'):
            manager.get('../swing_patterns')

    def test_scoped_api_and_schema_support_future_strategy_plugin(self):
        class MomentumSettings(paper.PaperConfig):
            momentum_threshold: float = 3
        plugin = registry.PaperPlugin(MomentumSettings, lambda log, job_id: {'portfolio_id': 'intraday_momentum'})
        headers = {'X-Trader-Request': 'local-ui'}
        with patch.dict(registry.PLUGINS, {'intraday_momentum': plugin}), patch('dashboard.api.main.PAPER_ENABLED', True), TestClient(app) as client:
            payload = MomentumSettings(capital=200000, risk_pct=2, acknowledge_limitations=True).model_dump(mode='json')
            response = client.post('/api/strategies/intraday_momentum/paper/portfolio', headers=headers, json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['id'], 'intraday_momentum')
            payload['momentum_threshold'] = 5
            self.assertEqual(client.put('/api/strategies/intraday_momentum/paper/portfolio', headers=headers, json=payload).status_code, 200)
            bootstrap = client.get('/api/bootstrap').json()
            self.assertEqual(bootstrap['paper_portfolios']['swing_patterns'], self.portfolio)
            self.assertEqual(bootstrap['paper_portfolios']['intraday_momentum']['config']['momentum_threshold'], 5)
            self.assertIn('momentum_threshold', bootstrap['paper_schemas']['intraday_momentum']['properties'])
        with patch('dashboard.api.main.PAPER_ENABLED', True), TestClient(app) as client:
            self.assertEqual(client.post('/api/strategies/scalping/paper/portfolio', headers=headers, json=payload).status_code, 400)

    def test_fresh_process_restores_portfolio_and_continues_new_session(self):
        self.cycle()
        saved = manager.get('swing_patterns')
        child_code = ('import json; from core.research import jobs; from core.portfolio import manager, scheduler; '
                      'jobs.recover(); scheduler.recover_interrupted(); '
                      'print(json.dumps(manager.get("swing_patterns")))')
        output = subprocess.check_output([sys.executable, '-c', child_code],
                                         env={**os.environ, 'TRADER_DATA_DIR': self.temp.name}, timeout=30)
        self.assertEqual(json.loads(output), saved)
        self.bars.append(candle('2026-01-03'))
        self.save_bars()
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 3, 17, tzinfo=paper.IST)), \
             patch.object(backtest, 'signal', return_value=True):
            result = paper.cycle(lambda _: None, 'after-restart', ingest=False)
        restored = manager.get('swing_patterns')
        self.assertEqual(result['sessions'], 1)
        self.assertEqual(restored['ledger']['orders'], saved['ledger']['orders'])
        self.assertEqual(restored['ledger']['cash'], saved['ledger']['cash'])
        self.assertEqual(restored['ledger']['last_session'], '2026-01-03')
        self.assertEqual(len(restored['ledger']['curve']), 2)

    def test_failed_atomic_replace_preserves_previous_portfolio(self):
        saved = manager.get('swing_patterns')
        with patch.object(Path, 'replace', side_effect=OSError('Simulated crash before replace')):
            with self.assertRaises(OSError):
                self.cycle()
        self.assertEqual(manager.get('swing_patterns'), saved)
        self.cycle()
        self.assertEqual(len(manager.get('swing_patterns')['ledger']['orders']), 1)

    def test_editing_paper_settings_preserves_all_portfolio_history(self):
        self.cycle()
        saved = manager.get('swing_patterns')
        updated = paper.save(config(risk_pct=2, stop_pct=10, sell_cost_bps=20, auto_run=True), Settings())
        for field in ('id', 'created_at', 'start_session', 'ledger', 'cycles', 'fingerprints', 'metrics'):
            self.assertEqual(updated[field], saved[field])
        self.assertEqual(updated['config']['risk_pct'], 2)
        self.assertEqual(len(updated['config_history']), len(saved['config_history']) + 1)

    def test_normal_provider_failure_is_not_retried_in_a_restart_loop(self):
        store.write('jobs', [{'id': 'f' * 12, 'status': 'failed',
                              'logs': [{'message': 'Provider rejected access (401/403).'}]}])
        claim = {'attempt_day': '2026-01-02', 'job_id': 'f' * 12}
        store.write('paper_schedule', claim)
        jobs.recover()
        scheduler.recover_interrupted()
        self.assertEqual(store.read('paper_schedule'), claim)

    def test_restart_retries_interrupted_schedule_without_duplicate_fills(self):
        paper.save(config(auto_run=True), Settings())
        self.cycle()
        saved = manager.get('swing_patterns')
        store.write('jobs', [{'id': 'c' * 12, 'status': 'running', 'logs': [],
                              'payload': {'portfolio_id': 'swing_patterns'}}])
        store.write('paper_schedule', {'attempt_day': '2026-01-02', 'job_id': 'c' * 12})
        jobs.recover()
        scheduler.recover_interrupted()
        self.assertIsNone(store.read('paper_schedule')['attempt_day'])
        queued = []
        with patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 17, tzinfo=paper.IST)), \
             patch.object(jobs.POOL, 'submit', side_effect=queued.append):
            scheduler.tick()
            scheduler.tick()
        self.assertEqual(len(queued), 1)
        with patch.object(upstox, 'ingest', return_value={}), \
             patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 17, tzinfo=paper.IST)):
            queued[0]()
        self.assertEqual(manager.get('swing_patterns'), saved)
        self.assertEqual(store.read('jobs')[0]['status'], 'success')

    def test_each_strategy_has_its_own_scheduling_checkpoint(self):
        paper.save(config(auto_run=True), Settings())
        manager.save('intraday_momentum', config(capital=200000, auto_run=True), Settings(),
                     create=True, clock=paper.local_now())
        plugin = registry.PaperPlugin(paper.PaperConfig, lambda log, job_id: {})
        with patch.dict(registry.PLUGINS, {'intraday_momentum': plugin}), \
             patch.object(paper, 'local_now', return_value=datetime(2026, 1, 2, 17, tzinfo=paper.IST)), \
             patch.object(jobs, 'submit', side_effect=[{'id': 'd' * 12}, {'id': 'e' * 12}]) as submit:
            scheduler.tick()
        self.assertEqual(submit.call_count, 2)
        self.assertEqual(store.read(manager.schedule_key('intraday_momentum'))['job_id'], 'd' * 12)
        self.assertEqual(store.read(manager.schedule_key('swing_patterns'))['job_id'], 'e' * 12)


class ConfigurationTests(unittest.TestCase):
    def test_paper_requires_capital_acknowledgement_and_positive_costs(self):
        for changes in ({'capital': None}, {'acknowledge_limitations': False}, {'buy_cost_bps': 0},
                        {'sell_cost_bps': 0}, {'slippage_bps': 0}, {'entry_mode': 'close'}):
            with self.assertRaises(ValidationError):
                config(**changes)


if __name__ == '__main__':
    unittest.main()
