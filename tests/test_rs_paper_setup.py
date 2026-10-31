from datetime import date,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.research import store,identity,four_indicator_swing as fs
from core.portfolio import manager
from scripts import start_rs_paper_comparisons as setup


class SetupTests(unittest.TestCase):
    def test_all_six_are_atomic_idempotent_and_preserve_sources(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False),identity.scope({'username':'manoj'}):
            rows=[dict(date=str(date(2026,10,29)-timedelta(days=149-i)),timestamp=i,open=100+i,
                       close=101+i,high=102+i,low=99+i,volume=10000) for i in range(150)]
            universe=dict(instruments=[dict(symbol='A',isin='TEST',sector='IT')])
            frozen=dict(datasets={'A':rows},universe=universe,exclusion_reasons={})
            before={}
            for source,start,_ in setup.SOURCES:
                ref='paper_inputs/'+source+'/original'
                p=dict(id=source,universe='niftytotalmarket',start_session=start,ledger={'last_session':'2026-10-29'},
                       input_reference=ref,cycles=[dict(input_sha256=fs.digest(frozen))])
                store.write(ref,frozen)
                key=manager.key(fs.STRATEGY,source);store.write(key,p);before[key]=fs.digest(store.read(key))
            store.write('bars/NIFTY50',{'bars':rows})
            store.write('jobs',[dict(id='setup',status='running')])
            result=setup.create(lambda _:None,'setup')
            self.assertEqual(len(result['portfolios']),6)
            self.assertTrue(result['existing_portfolios_preserved'])
            self.assertEqual(sum(p['slot_scale']==.75 for p in result['portfolios']),2)
            for _,pid,cfg in setup.specs():
                p=manager.get(fs.STRATEGY,pid)
                self.assertEqual(p['config'],cfg.model_dump(mode='json'))
                self.assertTrue(p['config']['auto_run'])
                self.assertEqual(p['status'],'active')
                self.assertEqual(fs.digest(store.read(p['input_reference'])),p['cycles'][-1]['input_sha256'])
            for key,digest in before.items():self.assertEqual(fs.digest(store.read(key)),digest)
            digests={key:fs.digest(p) for key,p in store.records('portfolio_scenarios/'+fs.STRATEGY+'/')}
            self.assertTrue(setup.create(lambda _:None,'setup')['already_created'])
            self.assertEqual(digests,{key:fs.digest(p) for key,p in store.records('portfolio_scenarios/'+fs.STRATEGY+'/')})

    def test_partial_existing_group_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            _,pid,_=next(setup.specs())
            key=manager.key(fs.STRATEGY,pid);original={'id':pid,'ledger':{'cash':42}}
            store.write(key,original)
            with self.assertRaisesRegex(ValueError,'some comparison portfolios'):
                setup.create(lambda _:None,'setup')
            self.assertEqual(store.read(key),original)


if __name__=='__main__':unittest.main()
