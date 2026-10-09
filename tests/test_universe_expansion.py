import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.research import store, upstox
from core.research.config import Settings


class UniverseExpansionTests(unittest.TestCase):
    def test_expansion_fetches_only_uncached_isins_and_preserves_paper_and_baseline(self):
        cfg = Settings(universe='niftytotalmarket')
        baseline = {'instruments': [{'symbol': 'OLD', 'isin': 'EXISTING'}]}
        target = {'instruments': [{'symbol': 'RENAMED', 'isin': 'EXISTING'},
                                  {'symbol': 'NEW', 'isin': 'ADDITIONAL'}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            store.write('universes/nifty500', baseline)
            store.write('bar_catalog', {'EXISTING': {'count': 100}, 'ADDITIONAL': {'count': 0}})
            store.write('portfolios/swing_patterns', {'ledger': {'cash': 123}, 'universe_snapshot': baseline})
            before = store.read('portfolios/swing_patterns')
            with patch.object(upstox, 'refresh_universe', return_value=target), patch.object(upstox, 'ingest', return_value={'symbols': 1, 'bars': 100}) as ingest:
                result = upstox.ingest_expansion(cfg, lambda _: None)
            self.assertEqual(ingest.call_args.kwargs['universe']['instruments'], [target['instruments'][1]])
            self.assertEqual(result['total_members'], 2)
            self.assertEqual(store.read('universes/nifty500'), baseline)
            self.assertEqual(store.read('portfolios/swing_patterns'), before)

    def test_expansion_does_not_require_a_nifty500_snapshot(self):
        target = {'instruments': [{'symbol': 'NEW', 'isin': 'ADDITIONAL'}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)), \
             patch.object(upstox, 'refresh_universe', return_value=target), \
             patch.object(upstox, 'ingest', return_value={'symbols': 1, 'bars': 100}) as ingest:
            result = upstox.ingest_expansion(Settings(), lambda _: None)
            self.assertEqual(ingest.call_args.kwargs['universe']['instruments'], target['instruments'])
            self.assertEqual(result['total_members'], 1)
