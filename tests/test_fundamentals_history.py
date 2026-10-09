import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from core.research import store
from scripts import pull_fundamentals_history as history

class FundamentalHistoryTests(unittest.TestCase):
    def test_sources_do_not_mix_basis_or_include_future_annuals(self):
        sources=[dict(period_end=p,basis=b,url=p+b) for p in
                 ('2026-06-30','2026-03-31','2025-12-31','2025-06-30','2025-03-31','2024-12-31')
                 for b in ('consolidated','standalone')]
        selected=history.sources_for_period(sources,'2025-12-31')
        self.assertTrue(all(s['basis']=='consolidated' for s in selected))
        self.assertTrue(all(s['period_end']<='2025-12-31' for s in selected))
        self.assertEqual(history.periods(sources),['2026-06-30','2026-03-31','2025-12-31','2025-06-30'])

    def test_retrospective_history_preserves_current_and_collection_time(self):
        item={'isin':'INE467B01029','symbol':'TCS'}
        at=datetime(2026,10,9,tzinfo=timezone.utc)
        snapshot={'isin':item['isin'],'company_type':'non_financial','basis':'consolidated',
                  'period_end':'2025-12-31','revenue_growth_pct':12,
                  'source':{'url':'https://nsearchives.nseindia.com/example','published_at':'2026-01-20T12:00:00+05:30','title':'test'}}
        result={'snapshot':snapshot,'documents':[]}
        with tempfile.TemporaryDirectory() as directory,patch.object(store,'DATA',Path(directory)), \
             patch.object(history.fundamentals,'validate',return_value={'status':'passed'}), \
             patch.object(history.company_review,'score',return_value={'score':10}):
            key='company/fundamentals/'+item['isin']
            store.write(key,{'snapshot':{**snapshot,'period_end':'2026-06-30','id':'latest'},'validation':{'status':'passed'}})
            self.assertEqual(history.install(item,result,at),'added')
            self.assertEqual(store.read(key)['snapshot']['id'],'latest')
            saved=list((Path(directory)/key/'history').glob('*.json'))
            archived=store.read(key+'/history/'+saved[0].stem)
            self.assertEqual(archived['snapshot']['recorded_at'],at.isoformat())
            self.assertEqual(archived['snapshot']['source']['published_at'],'2026-01-20T12:00:00+05:30')
            self.assertEqual(history.install(item,result,at),'retained')
            self.assertEqual(len(list((Path(directory)/key/'history').glob('*.json'))),1)

if __name__=='__main__': unittest.main()
