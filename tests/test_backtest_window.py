import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from core.research import store, backtest
from core.research.config import BacktestConfig, Settings


class WindowTests(unittest.TestCase):
    def test_cache_invalidates_after_ingestion_and_reports_missing_symbol(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)):
            store.write('universes/niftytotalmarket', {'instruments': [{'isin':'A','symbol':'A'}, {'isin':'B','symbol':'B'}]})
            bars=[{'date':f'2025-01-{i:02d}'} for i in range(1,16)]
            record={'bars':bars,'requested_start':'2025-01-01','requested_end':'2025-01-10'}
            store.write('bars/A', record)
            first=backtest.available_window(Settings(), 3)
            self.assertEqual(first['missing_symbols'], ['B'])
            self.assertEqual(first['start'], '2025-01-05')
            store.write('bars/B',record)
            second=backtest.available_window(Settings(),3)
            self.assertEqual(second['end'],'2025-01-10')
            self.assertEqual(second['start'],'2025-01-05')
            with patch.object(store,'read', wraps=store.read) as read:
                self.assertEqual(backtest.available_window(Settings(),3),second)
                self.assertEqual([call.args[0] for call in read.call_args_list],['universes/niftytotalmarket'])
            before = (Path(folder)/'bars/B.json').stat()
            store.write('bars/B',{**record,'requested_end':'2025-01-08'})
            # Equal-length replacement with an equal timestamp must invalidate too.
            os.utime(Path(folder)/'bars/B.json', ns=(before.st_atime_ns,before.st_mtime_ns))
            self.assertEqual(backtest.available_window(Settings(),3)['end'],'2025-01-08')


class EligibilityTests(unittest.TestCase):
    def test_partial_universe_runs_and_reports_excluded_stocks(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)):
            symbols = ['MAZDOCK', 'MISSING', 'STALE', 'EMPTY', 'WARMUP', 'ELIGIBLE']
            store.write('universes/niftytotalmarket', {'instruments': [
                {'isin': symbol, 'symbol': symbol} for symbol in symbols]})
            bars = [dict(date=(date(2016, 8, 1) + timedelta(days=i)).isoformat(),
                         open=100, high=101, low=99, close=100, volume=1000000)
                    for i in range(120)]
            record = dict(bars=bars, requested_start='2016-08-01',
                          requested_end='2026-10-08', source='unit_test')
            store.write('bars/ELIGIBLE', record)
            store.write('bars/MAZDOCK', {**record, 'requested_start': '2018-10-01'})
            store.write('bars/STALE', {**record, 'requested_end': '2026-10-07'})
            store.write('bars/EMPTY', {**record, 'bars': []})
            store.write('bars/WARMUP', {**record, 'bars': bars[80:]})
            cfg = BacktestConfig(start=date(2016, 10, 26), end=date(2026, 10, 8),
                                 acknowledge_limitations=True)
            logs = []
            backtest.run(Settings(), cfg, logs.append, 'partial-universe')
            result = store.read('runs/partial-universe')
            self.assertEqual([row['symbol'] for row in result['manifest']], ['ELIGIBLE'])
            self.assertEqual(result['excluded'], symbols[:-1])
            self.assertIn('Testing 1 symbols', logs[0])
            self.assertIn('5 excluded', logs[0])
            self.assertEqual(store.read('runs/partial-universe')['excluded'], symbols[:-1])

    def test_all_symbols_outside_coverage_fail_clearly(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)):
            store.write('universes/niftytotalmarket', {'instruments': [{'isin': 'A', 'symbol': 'A'}]})
            store.write('bars/A', dict(bars=[], requested_start='2018-10-01', requested_end='2026-10-09'))
            cfg = BacktestConfig(start=date(2016, 10, 26), end=date(2026, 10, 8),
                                 acknowledge_limitations=True)
            with self.assertRaisesRegex(ValueError, 'No eligible symbols cover the requested test dates'):
                backtest.prepare(Settings(), cfg)
