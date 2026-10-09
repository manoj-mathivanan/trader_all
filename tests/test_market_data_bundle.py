import gzip
import json
from pathlib import Path
import tempfile
import unittest
import sqlite3
from contextlib import closing

from scripts.market_data_bundle import archive, candle_row, export


class MarketBundleTests(unittest.TestCase):
    def test_roundtrip_archives_and_counts_exclude_private_and_portfolio(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data'
            target = Path(directory) / 'bundle'
            for name in ('bars', 'private', 'portfolios', 'run_data'):
                (source / name).mkdir(parents=True)
            bar = {'date': '2026-10-08', 'open': 100, 'high': 105, 'low': 99, 'close': 104, 'volume': 10}
            record = {'instrument': {'isin': 'TEST', 'symbol': 'T', 'key': 'NSE_EQ|TEST'},
                      'fetched_at': '2026-10-08T18:00:00+05:30', 'bars': [bar]}
            original = json.dumps(record).encode()
            (source / 'bars/TEST.json').write_bytes(original)
            (source / 'private/upstox.json').write_text('{"access_token":"do-not-export"}')
            (source / 'portfolios/swing.json').write_text('{"cash":123}')
            (source / 'run_data/run1.json').write_text(json.dumps({'T': [bar]}))
            result = export(source, target, 'local')
            self.assertEqual(result['counts'], {'daily': 1, 'five_minute': 0})
            self.assertEqual({f['path'] for f in result['files']}, {'bars/TEST.json', 'run_data/run1.json'})
            item = next(f for f in result['files'] if f['path'].startswith('bars/'))
            with closing(sqlite3.connect(target / 'blobs.sqlite')) as blobs:
                compressed = blobs.execute('SELECT gzip_data FROM blobs WHERE sha256=?', (item['sha256'],)).fetchone()[0]
            self.assertEqual(gzip.decompress(compressed), original)
            self.assertEqual(result['coverage']['TEST:1440']['count'], 1)

    def test_rejects_invalid_and_misaligned_candles(self):
        instrument = {'isin': 'TEST'}
        bar = {'date': '2026-10-08', 'timestamp': 1791431100000, 'open': 100,
               'high': 105, 'low': 99, 'close': 104, 'volume': -10}
        with self.assertRaises(ValueError):
            candle_row(instrument, bar, 5, '2026-10-08T18:00:00+05:30')
        bar['volume'] = 10
        bar['timestamp'] = 1
        with self.assertRaises(ValueError):
            candle_row(instrument, bar, 5, '2026-10-08T18:00:00+05:30')

    def test_deduplicates_original_bytes_and_rejects_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blobs = root / 'blobs'
            blobs.mkdir()
            source = root / 'one.json'
            source.write_text('{"data":123}')
            first = archive(source, blobs)
            self.assertEqual(archive(source, blobs), first)
            self.assertEqual(len(list(blobs.glob('*.json.gz'))), 1)
            source.write_text('{"api_key":"secret"}')
            with self.assertRaisesRegex(ValueError, 'Credential'):
                archive(source, blobs)


if __name__ == '__main__':
    unittest.main()
