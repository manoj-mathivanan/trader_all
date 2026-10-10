from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.research import market_data, price_backfill, store
from tests.test_market_data import candle


class PriceBackfillTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patched = patch.object(store, 'DATA', Path(folder.name))
        patched.start()
        self.addCleanup(patched.stop)
        self.item = dict(symbol='TEST', isin='TEST', key='test')

    def test_empty_earlier_response_is_remembered_without_inventing_candles(self):
        original = dict(bars=[candle('2026-06-01')], requested_start='2026-06-01', requested_end='2026-06-01')
        store.write('bars/TEST', original)
        with patch.object(market_data.upstox, 'fetch_range', return_value=[]) as fetch:
            for _ in range(2):
                self.assertEqual(market_data.save_daily(Mock(), self.item, 'test', date(2025,1,1),
                                 date(2026,6,1), allow_empty_prefix=True), 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(store.read('bars/TEST')['bars'], original['bars'])
        self.assertEqual(store.read('bars/TEST')['requested_start'], '2025-01-01')

    def test_empty_missing_internal_session_is_still_a_warning(self):
        store.write('bars/TEST', dict(bars=[candle('2026-06-01'), candle('2026-06-03')],
                                    requested_start='2026-06-01', requested_end='2026-06-03'))
        with patch.object(market_data.upstox, 'fetch_range', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'No daily candles'):
                market_data.save_daily(Mock(), self.item, 'test', date(2026,6,1), date(2026,6,3),
                                       sessions=['2026-06-01','2026-06-02','2026-06-03'], allow_empty_prefix=True)

    def test_unavailable_hole_does_not_discard_valid_earlier_download(self):
        store.write('bars/TEST', dict(bars=[candle('2026-06-01'),candle('2026-06-03')],
                                    requested_start='2026-06-01',requested_end='2026-06-03'))
        unavailable = []
        with patch.object(market_data.upstox, 'fetch_range', side_effect=[[candle('2026-05-29')],[]]), \
             patch.object(market_data.time, 'sleep'):
            count = market_data.save_daily(Mock(),self.item,'test',date(2026,5,29),date(2026,6,3),
                sessions=['2026-05-29','2026-06-01','2026-06-02','2026-06-03'],
                allow_empty_prefix=True, unavailable_ranges=unavailable)
        self.assertEqual(count,1)
        self.assertEqual(len(store.read('bars/TEST')['bars']),3)
        self.assertEqual(unavailable,[{'start':'2026-06-02','end':'2026-06-02'}])

    def test_backfill_uses_calendar_warmup_and_skips_sufficient_history(self):
        other = dict(symbol='OLD', isin='OLD', key='old')
        store.write('universes/niftytotalmarket', {'instruments':[self.item, other]})
        calendar = [candle(str(date(2025,1,1)+timedelta(days=i))) for i in range(70)]
        cfg = SimpleNamespace(start=date(2025,3,1), end=date(2025,3,10), minimum_warmup_sessions=50,
                              comparison_run_id=None)
        store.write('bars/OLD', dict(bars=calendar, requested_start='2025-01-01', requested_end='2025-03-10'))
        with patch.object(store, 'token', return_value='test'), \
             patch.object(price_backfill.backtest, 'required_warmup', return_value=50), \
             patch.object(price_backfill.market_history, 'evidence', return_value={}), \
             patch.object(price_backfill.market_history, 'prepare', side_effect=lambda i,r,**kw:(r['bars'],{})), \
             patch.object(market_data.upstox, 'fetch_range', return_value=calendar), \
             patch.object(market_data, 'save_daily', return_value=40) as save:
            result = price_backfill.backfill(SimpleNamespace(universe='niftytotalmarket'), cfg, Mock(), 'test')
        self.assertEqual(result['daily_start'], '2025-01-01')
        self.assertEqual(result['daily_bars'], 40)
        self.assertEqual(result['reused_symbols'], 1)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(save.call_args.args[1], self.item)

