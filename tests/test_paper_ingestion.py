"""Forward paper refresh must not revisit invalid pre-listing provider history."""
import tempfile
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
from core.research import upstox, store
from core.portfolio.paper import PaperIngestionRange


def candle(day, price=100):
    return {'date': day, 'open': price, 'high': price + 2, 'low': price - 1,
            'close': price + 1, 'volume': 1000}


class PaperIngestionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for target, value in [('DATA', Path(directory.name)), ('token', lambda: 'synthetic-token')]:
            replacement = patch.object(store, target, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        client = patch.object(upstox.httpx, 'Client')
        client.start()
        self.addCleanup(client.stop)
        delay = patch.object(upstox.time, 'sleep')
        delay.start()
        self.addCleanup(delay.stop)
        self.universe = {'instruments': [{'symbol': 'MAZDOCK', 'isin': 'TEST00000001', 'key': 'synthetic'}]}
        self.settings = PaperIngestionRange(universe='nifty500', start='2016-10-01', end='2026-10-05')
        self.original = {'bars': [candle('2020-10-12'), candle('2026-10-01')],
                         'requested_start': '2018-10-01', 'requested_end': '2026-10-01'}
        store.write('bars/TEST00000001', self.original)

    def test_paper_fetches_only_later_boundary_and_preserves_history(self):
        def provider(client, instrument, token, start, end):
            if start < date(2020, 10, 12):
                raise ValueError('Invalid pre-listing zero-price candle.')
            return [candle('2026-10-05')]
        with patch.object(upstox, 'fetch_range', side_effect=provider) as fetch:
            result = upstox.ingest(self.settings, lambda _: None, universe=self.universe, extend_history=False)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[-2:], (date(2026, 10, 2), date(2026, 10, 5)))
        saved = store.read('bars/TEST00000001')
        self.assertEqual([b['date'] for b in saved['bars']], ['2020-10-12', '2026-10-01', '2026-10-05'])
        self.assertEqual(saved['requested_start'], self.original['requested_start'])
        self.assertEqual(result['symbols'], 1)

    def test_empty_later_response_does_not_claim_earlier_backfill(self):
        with patch.object(upstox, 'fetch_range', return_value=[]):
            upstox.ingest(self.settings, lambda _: None, universe=self.universe, extend_history=False)
        saved = store.read('bars/TEST00000001')
        self.assertEqual(saved['requested_start'], self.original['requested_start'])
        self.assertEqual(saved['bars'], self.original['bars'])

    def test_research_still_rejects_invalid_earlier_provider_data(self):
        with patch.object(upstox, 'fetch_range', side_effect=ValueError('Invalid OHLCV candle detected.')):
            with self.assertRaisesRegex(ValueError, 'Partial ingestion'):
                upstox.ingest(self.settings, lambda _: None, universe=self.universe)
        self.assertEqual(store.read('bars/TEST00000001'), self.original)

    def test_invalid_later_candle_is_rejected_without_replacing_history(self):
        with patch.object(upstox, 'fetch_range', return_value=[candle('2026-10-05', 0)]):
            with self.assertRaisesRegex(ValueError, 'Partial ingestion'):
                upstox.ingest(self.settings, lambda _: None, universe=self.universe, extend_history=False)
        self.assertEqual(store.read('bars/TEST00000001'), self.original)

    def test_missing_paper_history_requires_recovery_without_provider_request(self):
        store.write('bars/TEST00000001', {'bars': []})
        with patch.object(upstox, 'fetch_range') as fetch:
            with self.assertRaisesRegex(ValueError, 'Partial ingestion'):
                upstox.ingest(self.settings, lambda _: None, universe=self.universe, extend_history=False)
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
