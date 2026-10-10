import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.research import fundamental_history as history, official_filings, store
from tests.test_official_filings import ITEM, URL, document


class HistoricalCalculationCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data = patch.object(store, 'DATA', Path(self.directory.name))
        self.data.start()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.data.stop)
        self.universe = {'instruments': [ITEM]}
        self.save_document(document())

    def save_document(self, html):
        raw = html.encode()
        sha = hashlib.sha256(raw).hexdigest()
        self.artifact = 'company/filings/'+sha+'.html'
        path = store.DATA/self.artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        store.write('company/fundamentals/'+ITEM['isin'],
                    {'validation': {'status': 'passed'}, 'documents': [
                        dict(url=URL, sha256=sha, artifact=self.artifact)]})

    def test_repeat_reuses_calculation_but_detects_corrupt_artifact(self):
        first = history.capture(self.universe)
        with patch.object(official_filings, 'parse', side_effect=AssertionError('must reuse')), \
             patch.object(history, 'reconstruct', side_effect=AssertionError('must reuse')):
            self.assertEqual(history.capture(self.universe)['series'], first['series'])
            (store.DATA/self.artifact).write_bytes(b'corrupt')
            rejected = history.capture(self.universe)
        self.assertEqual(rejected['series'], {})
        self.assertIn('checksum mismatch', rejected['excluded'][0]['reason'])

    def test_new_filing_and_calculation_version_rebuild(self):
        first = history.capture(self.universe)
        self.save_document(document(profit='1400'))
        with patch.object(official_filings, 'parse', wraps=official_filings.parse) as parse:
            updated = history.capture(self.universe)
            self.assertEqual(parse.call_count, 1)
        self.assertNotEqual(updated['series'], first['series'])
        with patch.object(history, 'calculation_version', return_value='new-rules'), \
             patch.object(official_filings, 'parse', wraps=official_filings.parse) as parse:
            self.assertEqual(history.capture(self.universe)['series'], updated['series'])
            self.assertEqual(parse.call_count, 1)

    def test_corrupt_derived_cache_is_rebuilt(self):
        first = history.capture(self.universe)
        cached = store.read('cache/historical_calculations')
        cached['companies'][ITEM['isin']]['versions'][0]['snapshot']['period_end'] = '2000-01-01'
        store.write('cache/historical_calculations', cached)
        with patch.object(official_filings, 'parse', wraps=official_filings.parse) as parse:
            self.assertEqual(history.capture(self.universe)['series'], first['series'])
            self.assertEqual(parse.call_count, 1)


if __name__ == '__main__':
    unittest.main()
