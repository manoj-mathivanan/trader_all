import copy
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from core.portfolio import manager, midday, paper, scheduler
from core.research import backtest, store
from core.research.config import Settings


class MiddayScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_patch = patch.object(store, 'DATA', Path(self.tmp.name))
        self.data_patch.start()
        self.clock = datetime(2026, 1, 2, 12, 30, tzinfo=paper.IST)
        self.cfg = paper.PaperConfig(capital=100000, pattern='blue_sky', candidate_rank='alphabetical',
                                    execution_time='midday', run_hour=12, run_minute=30,
                                    max_sector_positions=2, acknowledge_limitations=True)
        rows = []
        for i in range(100):
            day = date(2025, 9, 24) + timedelta(days=i)
            rows.append(dict(date=day.isoformat(), open=100, high=101, low=99, close=100, volume=1000000))
        self.data = {s: copy.deepcopy(rows) for s in ('A', 'B', 'C')}
        self.items = [dict(symbol=s, isin=s, sector='Finance', key='NSE_EQ|' + s) for s in self.data]
        self.portfolio = dict(id='scenario_a', status='active', ledger={}, cycles=[], config=self.cfg.model_dump(mode='json'),
                              universe_snapshot={'instruments': self.items})
        self.checks = {s: dict(score=70, coverage_pct=100, flags=[], buy_allowed=True, block_reasons=[]) for s in self.data}

    def tearDown(self):
        self.data_patch.stop()
        self.tmp.cleanup()

    def quotes(self, clock=None, bid=109, ask=110):
        clock = clock or self.clock
        return {s: dict(timestamp=clock.isoformat(), last_trade_time=str(int(clock.timestamp() * 1000)),
                        last_price=(bid + ask) / 2, ohlc={'open': 70},
                        depth={'buy': [{'price': bid, 'quantity': 100000}], 'sell': [{'price': ask, 'quantity': 100000}]}) for s in self.data}

    def run_quotes(self, portfolio=None, q=None, clock=None):
        with patch.object(backtest, 'signal', return_value=True):
            return midday.execute(portfolio or self.portfolio, self.cfg, self.data, self.checks,
                                  q or self.quotes(), clock or self.clock, 'unit')

    def test_midday_ask_not_morning_open_and_sector_limit(self):
        saved, result = self.run_quotes()
        self.assertEqual(result['orders'], 2)
        self.assertEqual(len(saved['ledger']['positions']), 2)
        self.assertAlmostEqual(saved['ledger']['orders'][0]['price'], 110 * 1.001)
        self.assertEqual(saved['ledger']['orders'][0]['at'], self.clock.isoformat())
        self.assertEqual(self.portfolio['ledger'], {})

    def test_same_session_retry_no_duplicate_fills(self):
        first, _ = self.run_quotes()
        second, result = self.run_quotes(portfolio=first)
        self.assertEqual(result['orders'], 0)
        self.assertEqual(first, second)

    def test_stale_quotes_block_entries_and_held_state(self):
        stale = self.quotes(self.clock - timedelta(minutes=2))
        first, result = self.run_quotes(q=stale)
        self.assertEqual(result['orders'], 0)
        held, _ = self.run_quotes()
        later = self.clock + timedelta(days=3)
        before = copy.deepcopy(held)
        with self.assertRaisesRegex(ValueError, 'Fresh quotes missing'):
            self.run_quotes(portfolio=held, q=stale, clock=later)
        self.assertEqual(held, before)

    def test_observed_stop_uses_current_bid(self):
        first, _ = self.run_quotes()
        later = self.clock + timedelta(days=3)
        first['status'] = 'paused'
        saved, result = self.run_quotes(portfolio=first, q=self.quotes(later, bid=90, ask=91), clock=later)
        self.assertEqual(result['orders'], 2)
        self.assertEqual(len(saved['ledger']['positions']), 0)
        self.assertAlmostEqual(saved['ledger']['trades'][0]['exit'], 90 * .999)
        self.assertIn('Stop observed', saved['ledger']['trades'][0]['reason'])

    def test_manager_isolates_portfolios_and_rejects_paths(self):
        universe = {'instruments': self.items}
        for item in self.items:
            store.write('bars/' + item['isin'], {'bars': self.data[item['symbol']]})
        settings = Settings(start='2025-01-01', end='2026-01-02')
        for identity in ('scenario_a', 'scenario_b'):
            manager.save('swing_patterns', self.cfg, settings, create=True, clock=self.clock,
                         portfolio_id=identity, universe_snapshot=universe)
        manager.set_status('swing_patterns', 'paused', 'scenario_a')
        self.assertEqual(manager.get('swing_patterns', 'scenario_b')['status'], 'active')
        self.assertIsNone(manager.get('swing_patterns'))
        self.assertEqual(len(manager.list_portfolios('swing_patterns')), 2)
        with self.assertRaises(ValueError):
            manager.get('swing_patterns', '../private')

    def test_native_sector_cap_matches_isolated_research(self):
        from scripts.run_sector_forward_test import engine
        from core.research.config import BacktestConfig
        cfg = BacktestConfig(start='2025-12-20', end='2026-01-01', pattern='blue_sky', capital=100000,
                             acknowledge_limitations=True)
        sectors = {s: 'Finance' for s in self.data}
        with patch.object(backtest, 'signal', return_value=True):
            isolated = engine(2, sectors, [])(self.data, cfg, liquidate=False)
            native = backtest.simulate(self.data, cfg.model_copy(update={'max_sector_positions': 2}),
                                       sector_instruments=self.items, liquidate=False)
        self.assertEqual(native['trades'], isolated['trades'])
        self.assertEqual(native['curve'], isolated['curve'])
        self.assertEqual(native['state']['orders'], isolated['state']['orders'])

    def test_midday_does_not_silently_ignore_unsupported_filters(self):
        with self.assertRaises(ValidationError):
            paper.PaperConfig(**{**self.cfg.model_dump(), 'max_open_gap_pct': 3})

    def test_scheduler_claims_each_scenario_separately_and_skips_after_hours(self):
        for identity in ('scenario_a', 'scenario_b'):
            p = copy.deepcopy(self.portfolio)
            p.update(id=identity, strategy_name='swing_patterns')
            p['config']['auto_run'] = True
            store.write(manager.key('swing_patterns', identity), p)
        with patch.object(paper, 'local_now', return_value=self.clock), patch.object(scheduler.jobs, 'submit', return_value={'id': 'unit'}) as submit:
            scheduler.tick()
            self.assertEqual(submit.call_count, 2)
            ids = {call.args[2]['portfolio_id'] for call in submit.call_args_list}
            self.assertEqual(ids, {'scenario_a', 'scenario_b'})
            scheduler.tick()
            self.assertEqual(submit.call_count, 2)
        late = self.clock.replace(hour=16)
        with patch.object(paper, 'local_now', return_value=late), patch.object(scheduler.jobs, 'submit') as submit:
            scheduler.tick()
            submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
