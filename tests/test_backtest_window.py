import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.research import store, backtest
from core.research.config import Settings


class WindowTests(unittest.TestCase):
    def test_cache_invalidates_after_ingestion_and_reports_missing_symbol(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, 'DATA', Path(folder)):
            store.write('universes/nifty50', {'instruments': [{'isin':'A','symbol':'A'}, {'isin':'B','symbol':'B'}]})
            bars=[{'date':f'2025-01-{i:02d}'} for i in range(1,16)]
            record={'bars':bars,'requested_start':'2025-01-01','requested_end':'2025-01-10'}
            store.write('bars/A', record)
            first=backtest.available_window(Settings(), 3)
            self.assertEqual(first['missing_symbols'], ['B'])
            self.assertIsNone(first['start'])
            store.write('bars/B',record)
            second=backtest.available_window(Settings(),3)
            self.assertEqual(second['end'],'2025-01-10')
            self.assertEqual(second['start'],'2025-01-05')
            with patch.object(store,'read', wraps=store.read) as read:
                self.assertEqual(backtest.available_window(Settings(),3),second)
                self.assertEqual([call.args[0] for call in read.call_args_list],['universes/nifty50'])
            store.write('bars/B',{**record,'requested_end':'2025-01-08'})
            self.assertEqual(backtest.available_window(Settings(),3)['end'],'2025-01-08')
