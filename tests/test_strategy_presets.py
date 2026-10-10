import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from fastapi.testclient import TestClient

from core.research import store, strategy_presets
from core.research.config import BacktestConfig
from core.portfolio.paper import PaperConfig
from dashboard.api.main import app


class StrategyPresetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.storage=patch.object(store,'DATA',Path(self.temp.name))
        self.storage.start()
        self.client=TestClient(app)

    def tearDown(self):
        self.storage.stop()
        self.temp.cleanup()

    def preset(self):
        return next(p for p in strategy_presets.available() if p['name']=='Blue Sky Fundamental Ranking')

    def test_archive_hides_local_and_bundled_copies_and_is_reversible(self):
        preset=self.preset()
        store.write('screens',[preset])
        store.write('archived_screens',[preset])
        self.assertNotIn(preset['id'],[p['id'] for p in strategy_presets.available()])
        store.write('archived_screens',[])
        self.assertEqual(1,len([p for p in strategy_presets.available() if p['id']==preset['id']]))

    def test_bundled_strategy_available_without_local_state_and_valid_for_both_engines(self):
        preset=self.preset()
        cfg=preset['trading_defaults']
        self.assertEqual(cfg['pattern'],'blue_sky')
        self.assertEqual(cfg['candidate_rank'],'fundamental_score')
        self.assertEqual(cfg['max_positions'],5)
        self.assertEqual(cfg['buy_cost_bps'],35)
        self.assertEqual(cfg['sell_cost_bps'],50)
        backtest=BacktestConfig(**cfg,start='2025-01-01',end='2026-01-01',
                               minimum_warmup_sessions=preset['minimum_warmup_sessions'],acknowledge_limitations=True)
        paper=PaperConfig(**cfg,acknowledge_limitations=True)
        self.assertEqual(backtest.minimum_warmup_sessions,260)
        self.assertEqual(paper.candidate_rank,backtest.candidate_rank)
        self.assertFalse(paper.auto_run)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,200)
        self.assertIn(preset['id'],[p['id'] for p in self.client.get('/api/bootstrap').json()['screens']])
        self.assertIsNone(store.read('portfolios/swing_patterns'))

    def test_api_roundtrip_keeps_full_strategy_and_does_not_duplicate_bundled_preset(self):
        payload={k:v for k,v in self.preset().items() if k in strategy_presets.ScreenInput.model_fields}
        reply=self.client.post('/api/screens',json=payload,headers={'X-Trader-Request':'local-ui'})
        self.assertEqual(reply.status_code,200,reply.text)
        saved=reply.json()
        self.assertEqual(saved['trading_defaults'],payload['trading_defaults'])
        self.assertEqual(saved['source_run_id'],'88d4e0a95376')
        self.assertEqual(len([p for p in strategy_presets.available() if p['id']==saved['id']]),1)
        self.assertEqual(store.read('screens')[0]['minimum_warmup_sessions'],260)

    def test_zerodha_candidate_has_causal_exit_and_valid_tariff_defaults(self):
        preset=next(p for p in strategy_presets.available() if p['name']=='Blue Sky Stalled Exit - Zerodha')
        values=preset['trading_defaults']
        self.assertEqual(values['fee_model'],'zerodha_equity')
        self.assertEqual(values['winner_exit'],'trail_50d')
        self.assertEqual(values['stalled_exit_sessions'],10)
        self.assertEqual(values['stalled_min_r'],.5)
        self.assertEqual(values['buy_cost_bps'],0)
        self.assertEqual(values['sell_cost_bps'],0)
        self.assertIn('Exploratory',preset['description'])
        BacktestConfig(**values,start='2025-03-03',end='2026-10-08',acknowledge_limitations=True)
        PaperConfig(**values,acknowledge_limitations=True)
        self.assertIsNone(store.read('portfolios/swing_patterns'))

    def test_legacy_screen_and_conflicting_filters(self):
        simple=strategy_presets.ScreenInput(name='Only a screen',pattern='vcp')
        self.assertIsNone(simple.trading_defaults)
        payload={k:v for k,v in self.preset().items() if k in strategy_presets.ScreenInput.model_fields}
        payload['volume_multiple']=2
        with self.assertRaisesRegex(ValidationError,'Conflicting'):
            strategy_presets.ScreenInput(**payload)
        payload['volume_multiple']=payload['trading_defaults']['volume_multiple']
        payload['pattern']='vcp'
        with self.assertRaisesRegex(ValidationError,'same pattern'):
            strategy_presets.ScreenInput(**payload)

    def test_emerging_rs_preset_preserves_filters_without_activating_portfolio(self):
        preset = next(p for p in strategy_presets.available() if p['name'] == 'VCP Improving RS - Experimental')
        cfg = preset['trading_defaults']
        self.assertEqual((cfg['rs_short_lookback'], cfg['min_short_rs_rating'], cfg['rs_improvement_sessions'], cfg['min_rs_improvement']), (63, 70, 20, 10))
        self.assertEqual(preset['min_rs_improvement'], 10)
        self.assertIn('Underperformed', preset['description'])
        PaperConfig(**cfg, acknowledge_limitations=True)
        self.assertIsNone(store.read('portfolios/swing_patterns'))


if __name__=='__main__':
    unittest.main()
