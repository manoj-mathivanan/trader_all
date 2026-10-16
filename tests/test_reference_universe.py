import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date,timedelta
from core.research import store,market_history,reference_universe

class ExpansionTests(unittest.TestCase):
    def test_expansion_preserves_baseline_and_deduplicates_isins(self):
        rows=[dict(date=str(date(2026,1,1)+timedelta(days=i)),open=100,high=101,low=99,
                   close=100,volume=1000000) for i in range(254)]
        rows[-1]['date']='2026-09-30'
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'DATA',Path(folder)),\
             patch.object(market_history,'evidence',return_value={}),\
             patch.object(market_history,'prepare',side_effect=lambda item,record,**kw:(record['bars'],{})):
            old=dict(symbol='OLD',isin='ISIN-A')
            store.write('runs/test',dict(manifest=[dict(symbol='OLD',sha256=market_history.digest(rows))],
                                        universe_snapshot=dict(instruments=[old])))
            store.write('run_data/test',{'OLD':rows})
            store.write('universes/niftytotalmarket',dict(instruments=[dict(symbol='RENAMED',isin='ISIN-A'),
                dict(symbol='NEW',isin='ISIN-B'),dict(symbol='MISSING',isin='ISIN-C')]))
            store.write('bars/ISIN-B',dict(bars=rows,requested_end='2026-09-30'))
            base,expanded,coverage=reference_universe.cached_expansion('test')
            self.assertEqual(expanded['OLD'],base['OLD'])
            self.assertEqual(set(expanded),{'OLD','NEW'})
            self.assertEqual(coverage['added'],1)
            self.assertEqual(coverage['excluded'][0]['symbol'],'MISSING')
            store.write('run_data/test',{'OLD':rows[:-1]})
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                reference_universe.cached_expansion('test')

if __name__=='__main__':unittest.main()
