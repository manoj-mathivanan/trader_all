import unittest
from unittest.mock import patch
from core.research.upstox import match_constituents, apply_verified_overrides


class UniverseMatchingTests(unittest.TestCase):
    def row(self, symbol, isin):
        return {'Symbol':symbol,'ISIN Code':isin,'Company Name':symbol}

    def test_cash_series_and_explicit_dummy_exclusion(self):
        rows=[self.row('A','INE1'),self.row('B','INE2'),self.row('R','INE3'),self.row('DUMMYX','DUM1')]
        master=[dict(isin=f'INE{i}',segment='NSE_EQ',instrument_type=series,
                     instrument_key=f'NSE_EQ|INE{i}') for i,series in enumerate(['EQ','BE','RR'],1)]
        matched,excluded=match_constituents(rows,master)
        self.assertEqual([x['series'] for x in matched],['EQ','BE','RR'])
        self.assertEqual([x['symbol'] for x in excluded],['DUMMYX'])

    def test_unmatched_real_or_ambiguous_instrument_fails(self):
        with self.assertRaises(ValueError):
            match_constituents([self.row('REAL','INE1')],[])
        master=[dict(isin='INE1',segment='NSE_EQ',instrument_type='BE',instrument_key=x) for x in ['A','B']]
        with self.assertRaises(ValueError):
            match_constituents([self.row('REAL','INE1')],master)

    def test_eq_priority_and_other_exchange_not_substituted(self):
        master=[dict(isin='INE1',segment=segment,instrument_type=series,instrument_key=key)
                for segment,series,key in [('NSE_EQ','BE','N1'),('NSE_EQ','EQ','N2'),('BSE_EQ','EQ','B1')]]
        matched,_=match_constituents([self.row('REAL','INE1')],master)
        self.assertEqual(matched[0]['key'],'N2')

    def test_verified_volume_repair_requires_exact_bad_provider_bar(self):
        bad=['2024-08-30T00:00:00+05:30',16.44,16.44,15.39,15.64,-81259413]
        good=bad[:5]+[4213707883]
        repair={'date':'2024-08-30','provider_values':bad[1:6],'verified_candle':good}
        with patch('core.research.upstox.store.read',return_value={'repairs':[repair]}):
            self.assertEqual(apply_verified_overrides([bad],'TEST'),[good])
            revised=bad.copy();revised[4]=15.65
            self.assertEqual(apply_verified_overrides([revised],'TEST'),[revised])

if __name__=='__main__':
    unittest.main()
