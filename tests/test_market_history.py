import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from core.research import market_history, store, provenance, data_quality
from scripts.refresh_listing_evidence import parse_master


class MarketHistoryTests(unittest.TestCase):
    def test_recent_ipo_proof_survives_exchange_master_and_coverage_keeps_unknowns(self):
        item = {'isin': 'INE0V6F01027', 'symbol': 'HYUNDAI'}
        venue = {'symbol': 'HYUNDAI', 'listing_date': '2024-10-22',
                 'verified': True, 'source': 'official-exchange-master'}
        ref = market_history.evidence()
        ref['listings'] = market_history.merge_listings(ref['listings'], {item['isin']: venue,
            'OTHER': {'symbol': 'SECONDARY', 'listing_date': '2024-10-22',
                      'verified': True, 'source': 'official-exchange-master'}})
        metadata = market_history.listing_for(item, ref['listings'])
        self.assertTrue(metadata['ipo_verified'])
        self.assertEqual(metadata['ipo_date'], '2024-10-22')
        self.assertIn('hyundai.com', metadata['ipo_source'])
        report = data_quality.listing_evidence_coverage([item, {'isin':'OTHER', 'symbol':'SECONDARY'},
                                                        {'isin':'UNKNOWN', 'symbol':'UNKNOWN'}], ref)
        self.assertEqual(report['verified_ipo_symbols'], ['HYUNDAI'])
        self.assertEqual(report['verified_exchange_listing_symbols'], ['HYUNDAI', 'SECONDARY'])
        self.assertEqual(report['missing_ipo_symbols'], ['SECONDARY', 'UNKNOWN'])

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.context = patch.object(store, 'DATA', Path(temp.name)); self.context.start(); self.addCleanup(self.context.stop)

    def test_prelisting_bars_removed_from_derived_inputs_and_evidence_frozen(self):
        raw = [{'date': day, 'close': 100} for day in ('2018-01-01', '2022-05-10', '2022-05-11')]
        before = deepcopy(raw)
        item = {'isin': 'INE961O01016', 'symbol': 'RAINBOW'}
        rows, details = market_history.prepare(item, {'bars': raw})
        self.assertEqual([x['date'] for x in rows], ['2022-05-10', '2022-05-11'])
        self.assertEqual(details['removed_prelisting_bars'], 1)
        self.assertTrue(rows[0]['listing_metadata']['verified'])
        self.assertEqual(raw, before)
        self.assertNotEqual(details['source_sha256'], details['derived_sha256'])

    def test_changed_isin_uses_explicit_sourced_symbol_without_guessing(self):
        item = {'isin': 'INE732I01021', 'symbol': 'ANGELONE'}
        rows, details = market_history.prepare(item, {'bars': [{'date':'2020-10-05','close':100}]})
        self.assertEqual(rows[0]['listing_metadata']['listing_date'], '2020-10-05')
        unknown, details = market_history.prepare({'isin':'UNKNOWN','symbol':'OTHER'}, {'bars':[{'date':'2018-01-01','close':100}]})
        self.assertNotIn('listing_metadata', unknown[0])

    def test_quarantine_never_becomes_a_split_factor(self):
        rows, details = market_history.prepare({'isin':'INE959A01019','symbol':'PRIVISCL'},
                                              {'bars':[{'date':'2018-01-01','close':.05}]})
        self.assertEqual(rows, [])
        self.assertIn('quarantine', details)

    def test_provenance_includes_source_and_lock_hashes_without_secrets(self):
        result = provenance.capture()
        self.assertEqual(len(result['source_tree_sha256']), 64)
        self.assertIn('requirements-lock.txt', result['source_files'])
        self.assertIn('core/research/corporate_actions.py', result['source_files'])
        self.assertFalse(any('private' in x or x.startswith('data/') for x in result['source_files']))

    def test_official_master_parser_uses_listing_column_including_trade_to_trade_equities(self):
        header='SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n'
        row='TEST,Test Company,BE,10-MAY-2022,10,1,INE000000001,10\n'
        result=parse_master((header+row).encode())
        self.assertEqual(result['INE000000001']['listing_date'],'2022-05-10')
        self.assertTrue(result['INE000000001']['verified'])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            parse_master((header+row+row).encode())


if __name__ == '__main__':
    unittest.main()
