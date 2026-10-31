from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

from cryptography.fernet import Fernet
from pydantic import ValidationError
from core.research import store,identity,indian_api
from core.portfolio import analyst_indicator_paper as analyst,manager,registry,refresh_followup
from core.research.config import Settings
from tests.test_analyst_consensus import payload


class AnalystPaperTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        for p in [patch.object(store,'DATA',Path(tmp.name)),patch.object(store,'database_enabled',return_value=False),
                  patch.object(store,'cipher',return_value=Fernet(Fernet.generate_key()))]:
            p.start();self.addCleanup(p.stop)
        scope=identity.scope({'username':'manoj'});scope.__enter__();self.addCleanup(scope.__exit__,None,None,None)

    def test_fixed_strategy_schema_and_api_identity(self):
        cfg=analyst.PaperConfig(start_session='2026-10-12')
        self.assertEqual(cfg.analyst_buy_threshold_pct,75)
        for change in [dict(analyst_buy_threshold_pct=70),dict(rule_set='rsi'),dict(candidate_ranking='rs_126')]:
            with self.assertRaises(ValidationError):analyst.PaperConfig(start_session='2026-10-12',**change)
        self.assertIs(registry.get_plugin(analyst.STRATEGY).config_model,analyst.PaperConfig)
        from dashboard.api import main
        with patch.object(main,'settings',return_value=Settings()):
            p=main.create_strategy_portfolio(analyst.STRATEGY,cfg.model_dump(mode='json'),portfolio_id='analyst_test')
        self.assertEqual(p['strategy_name'],analyst.STRATEGY)

    def test_credentials_encrypted_and_daily_collection_reused(self):
        indian_api.save_key('test-secret')
        self.assertEqual(indian_api.key(),'test-secret')
        self.assertNotIn('test-secret',str(store.read('private/indian_api/manoj')))
        data=payload();data['companyProfile']={'isInId':'ISIN00000001','exchangeCodeNse':'A'}
        obs=dict(observed_at=datetime.now(timezone.utc).isoformat(),payload=data)
        client=Mock();client.stock.return_value=obs
        with patch.object(indian_api,'IndianAPIClient',return_value=client),patch.object(indian_api,'_clients',{}):
            first=indian_api.collect({'symbol':'A','isin':'ISIN00000001'})
            second=indian_api.collect({'symbol':'A','isin':'ISIN00000001'})
        self.assertTrue(first['identity_verified']);self.assertEqual(first['observed_at'],second['observed_at']);client.stock.assert_called_once()

    def test_gate_uses_prior_snapshot_instead_of_newer_prefetch(self):
        old=dict(requested_symbol='A',observed_at='2026-10-12T12:00:00+00:00',identity_verified=True,payload=payload())
        future=dict(old,observed_at='2026-10-31T12:00:00+00:00',payload=payload(1,9))
        indian_api.remember(old);indian_api.remember(future)
        bars=[{'date':'2026-10-30'} for _ in range(101)]
        frozen={'datasets':{'A':bars},'universe':{'instruments':[{'symbol':'A','isin':'TEST'}]}}
        signals={'A':[dict(checks=[dict(passed=True)]*4)]*101}
        with patch.object(indian_api,'collect',return_value=future):
            gate=analyst.prepare_filter(frozen,{},signals,lambda _:None)
        self.assertTrue(gate('A','2026-10-12','2026-10-13')[0])
        self.assertFalse(gate('A','2026-10-11','2026-10-12')[0])
        self.assertEqual(frozen['analyst_observations']['A'][old['observed_at']],old)

    def test_after_refresh_dispatch_includes_new_strategy_and_no_duplicate_receipts(self):
        store.write(refresh_followup.KEY,dict(enabled=True,strategy_ids=[analyst.STRATEGY]))
        analyst.save(analyst.PaperConfig(start_session='2026-10-12'),Settings(),create=True,portfolio_id='analyst_test')
        with patch.object(analyst,'cycle',return_value={'sessions':0}) as cycle:
            first=refresh_followup.run(lambda _:None,'refresh',dict(completed_at=store.now(),daily_symbols=750))
            second=refresh_followup.run(lambda _:None,'refresh',dict(completed_at=store.now(),daily_symbols=750))
        self.assertEqual(first[0]['status'],'success');self.assertEqual(second,[])
        cycle.assert_called_once_with(unittest.mock.ANY,'refresh',ingest=False,portfolio_id='analyst_test')

    def test_cycle_forces_causal_filter_and_published_candles(self):
        with patch.object(analyst.four_indicator_paper,'cycle',return_value={'sessions':0}) as cycle:
            analyst.cycle(lambda _:None,'cycle',ingest=False,portfolio_id='analyst_test')
        self.assertTrue(cycle.call_args.kwargs['published_only'])
        self.assertIs(cycle.call_args.kwargs['entry_filter_factory'],analyst.prepare_filter)


if __name__=='__main__':unittest.main()
