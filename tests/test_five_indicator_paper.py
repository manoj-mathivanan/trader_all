from copy import deepcopy
from datetime import date,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from core.research import store,identity,four_indicator_swing as fs
from core.research.config import Settings
from core.portfolio import five_indicator_paper as five,manager,registry,refresh_followup


class FiveIndicatorTests(unittest.TestCase):
    def test_fixed_fifth_indicator_and_normal_slots(self):
        cfg=five.PaperConfig(start_session='2026-10-12')
        self.assertEqual((cfg.rule_set,cfg.candidate_ranking,cfg.slot_scale),('bollinger','rs_126',1))
        for fields in (dict(candidate_ranking='turnover'),dict(rule_set='rsi'),dict(slot_scale=.75)):
            with self.assertRaises(ValidationError):five.PaperConfig(start_session='2026-10-12',**fields)
        self.assertIs(registry.get_plugin(five.STRATEGY).config_model,five.PaperConfig)

    def test_separate_storage_save_update_cycle_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            rows=[dict(date=str(date(2026,10,29)-timedelta(days=149-i)),timestamp=i,open=100+i,
                       close=101+i,high=102+i,low=99+i,volume=10000) for i in range(150)]
            cfg=five.PaperConfig(start_session='2026-10-12')
            universe=dict(instruments=[dict(symbol='A',isin='ISIN00000001')])
            frozen=dict(datasets={'A':rows},benchmark=rows,universe=universe,exclusion_reasons={})
            signals={'A':[dict(close=b['close'],exit=False,checks=[dict(passed=True,value=100) for _ in range(4)]) for b in rows]}
            store.write('bars/NIFTY50',{'bars':rows})
            store.write('universes/niftytotalmarket',universe)
            oldkey=manager.key('four_indicator_swing','original');old=dict(id='original',ledger={'cash':123})
            store.write(oldkey,old)
            five.save(cfg,Settings(),create=True,portfolio_id='five_test')
            self.assertEqual(manager.list_portfolios('four_indicator_swing'),[old])
            with patch.object(fs,'prepare',return_value=deepcopy(frozen)),patch.object(fs,'features',return_value=signals):
                result=five.cycle(lambda _:None,'five_job',ingest=False,portfolio_id='five_test')
            p=manager.get(five.STRATEGY,'five_test')
            self.assertEqual(p['strategy_name'],five.STRATEGY)
            self.assertGreater(result['sessions'],0)
            self.assertEqual(len(p['ledger']['positions']),1)
            self.assertEqual(fs.digest(store.read(p['input_reference'])),p['cycles'][-1]['input_sha256'])
            self.assertEqual(store.read(oldkey),old)
            self.assertEqual(five.cycle(lambda _:None,'repeat',ingest=False,portfolio_id='five_test')['sessions'],0)
            updated=five.save(cfg.model_copy(update={'name':'Five renamed'}),Settings(),portfolio_id='five_test')
            self.assertEqual(updated['config']['name'],'Five renamed')
            self.assertEqual(updated['ledger'],p['ledger'])

    def test_refresh_followup_dispatches_five_scenario(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            store.write(refresh_followup.KEY,dict(enabled=True,strategy_ids=[five.STRATEGY]))
            cfg=five.PaperConfig(start_session='2026-10-12')
            five.save(cfg,Settings(),create=True,portfolio_id='five_test')
            with patch.object(five,'cycle',return_value={'sessions':1}) as run:
                result=refresh_followup.run(lambda _:None,'refresh',dict(completed_at='2026-10-30',daily_symbols=1))
            run.assert_called_once_with(unittest.mock.ANY,'refresh',ingest=False,portfolio_id='five_test')
            self.assertEqual(result[0]['status'],'success')

    def test_api_dispatch_keeps_five_identity(self):
        from dashboard.api import main
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            cfg=five.PaperConfig(start_session='2026-10-12')
            with patch.object(main,'settings',return_value=Settings()):
                p=main.create_strategy_portfolio(five.STRATEGY,cfg.model_dump(mode='json'),'api_five')
            self.assertEqual(p['strategy_name'],five.STRATEGY)
            self.assertEqual(manager.get(five.STRATEGY,'api_five')['id'],'api_five')

    def test_requested_two_replays_preserve_existing_portfolios_and_enable_followup(self):
        from scripts import start_five_indicator_paper as setup
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False),identity.scope({'username':'manoj'}):
            rows=[dict(date=str(date(2026,10,29)-timedelta(days=149-i)),timestamp=i,open=100+i,
                       close=101+i,high=102+i,low=99+i,volume=10000) for i in range(150)]
            frozen=dict(datasets={'A':rows},benchmark=rows,universe=dict(instruments=[dict(symbol='A',isin='TEST')]),exclusion_reasons={})
            oldkey=manager.key('four_indicator_swing','old_rs')
            store.write(oldkey,dict(id='old_rs',ledger={'cash':42}));before=fs.digest(store.read(oldkey))
            store.write('bars/NIFTY50',{'bars':rows})
            store.write('universes/niftytotalmarket',frozen['universe'])
            store.write('jobs',[dict(id='setup',status='running')])
            store.write(refresh_followup.KEY,dict(enabled=True,strategy_ids=['four_indicator_swing']))
            with patch.object(fs,'prepare',return_value=frozen):
                result=setup.create(lambda _:None,'setup')
            self.assertEqual(len(result['portfolios']),2)
            self.assertEqual({p['start'] for p in result['portfolios']},{'2026-09-30','2026-10-12'})
            self.assertEqual(fs.digest(store.read(oldkey)),before)
            self.assertTrue(refresh_followup.enabled(five.STRATEGY))
            self.assertTrue(setup.create(lambda _:None,'setup')['already_created'])

    def test_published_end_defers_provisional_benchmark_and_stock_candles(self):
        universe=dict(instruments=[dict(symbol='A',isin='TEST')])
        bars=[dict(date='2026-10-29'),dict(date='2026-10-30')]
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            store.write('bars/NIFTY50',dict(bars=bars,provisional_daily={'2026-10-30':{}}))
            store.write('bars/TEST',dict(bars=bars,provisional_daily={'2026-10-30':{}}))
            self.assertEqual(five.published_end(universe,date(2026,10,30)),date(2026,10,29))
            store.write('bars/NIFTY50',dict(bars=bars,provisional_daily={}))
            self.assertEqual(five.published_end(universe,date(2026,10,30)),date(2026,10,29))
            store.write('bars/TEST',dict(bars=bars,provisional_daily={}))
            self.assertEqual(five.published_end(universe,date(2026,10,30)),date(2026,10,30))


if __name__=='__main__':unittest.main()
