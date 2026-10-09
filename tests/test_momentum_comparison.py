import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from core.research import momentum, store


class MomentumComparisonTests(unittest.TestCase):
    def test_fundamental_pair_uses_one_identical_archive_and_costs(self):
        from core.research import fundamental_history
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            cfg,_=self.setup_reference();seen=[]
            archive={'series':{},'sha256':'fixture'}
            def run(settings,config,log,run_id,*,fundamental_evidence=None):
                seen.append((config,fundamental_evidence))
                store.write('runs/'+run_id,dict(metrics={'return_pct':-1},evaluation={'segments':[]},diagnostics={}))
            with patch.object(momentum,'run',side_effect=run),patch.object(fundamental_history,'capture',return_value=archive) as capture:
                momentum.compare(SimpleNamespace(universe='nifty50'),'abcdef123456',lambda m:None,'123456abcdef','fundamentals')
            capture.assert_called_once()
            self.assertEqual([c.require_fundamentals for c,_ in seen],[False,True])
            self.assertTrue(all(e is archive for _,e in seen))
            self.assertTrue(all((c.buy_cost_bps,c.sell_cost_bps,c.slippage_bps)==(17,23,8) for c,_ in seen))

    def test_failed_trials_remain_visible_and_later_trials_continue(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            self.setup_reference();seen=[]
            def run(settings,config,log,run_id):
                seen.append(config)
                if config.indicator_filter!='none':
                    raise ValueError('Indicator warmup crosses a corporate action.')
                store.write('runs/'+run_id,dict(metrics={'return_pct':-1},evaluation={'segments':[]},diagnostics={}))
            with patch.object(momentum,'run',side_effect=run):
                response=momentum.compare(SimpleNamespace(universe='nifty50'),'abcdef123456',lambda m:None,'123456abcdef','indicators')
            saved=store.read('momentum_comparisons/123456abcdef')
            self.assertEqual(len(saved['trials']),7)
            self.assertEqual(saved['failed_trials'],4)
            self.assertTrue(response['partial'])
            self.assertIsNone(saved['trials'][2]['metrics']['return_pct'])
            self.assertEqual(saved['trials'][2]['config']['indicator_filter'],'ema')

    def setup_reference(self):
        cfg=momentum.MomentumConfig(start='2025-02-03',end='2025-02-04',acknowledge_limitations=True,
                                   buy_cost_bps=17,sell_cost_bps=23,slippage_bps=8)
        rows=[dict(date=(date(2025,1,12)+timedelta(days=i)).isoformat(),open=100,high=102,low=98,close=100,volume=10000) for i in range(24)]
        manifest=[dict(symbol='A',sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest())]
        reference=dict(strategy_id='intraday_momentum',universe='nifty50',config=cfg.model_dump(mode='json'),
                       universe_snapshot={'instruments':[]},manifest=manifest,excluded=[])
        store.write('runs/abcdef123456',reference)
        store.write('run_data/abcdef123456',{'A':rows})
        return cfg,reference

    def test_frozen_hash_dates_and_warmup_enforced(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            cfg,_=self.setup_reference();cfg.comparison_run_id='abcdef123456'
            settings=SimpleNamespace(universe='nifty50')
            momentum.prepare(settings,cfg)
            cfg.volume_lookback=50
            with self.assertRaisesRegex(ValueError,'lack the requested warmup'):
                momentum.prepare(settings,cfg)
            cfg.volume_lookback=14
            datasets=store.read('run_data/abcdef123456');datasets['A'][0]['close']=99
            store.write('run_data/abcdef123456',datasets)
            with self.assertRaisesRegex(ValueError,'hash changed'):
                momentum.prepare(settings,cfg)

    def test_all_trials_keep_reference_costs_and_do_not_change_defaults(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            cfg,_=self.setup_reference();seen=[]
            def run(settings,config,log,run_id):
                seen.append(config)
                store.write('runs/'+run_id,dict(metrics={'return_pct':-1},evaluation={'segments':[]},diagnostics={}))
            with patch.object(momentum,'run',side_effect=run):
                momentum.compare(SimpleNamespace(universe='nifty50'),'abcdef123456',lambda m:None,'123456abcdef')
            self.assertEqual(len(seen),6)
            self.assertTrue(all(c.comparison_run_id=='abcdef123456' for c in seen))
            self.assertTrue(all((c.buy_cost_bps,c.sell_cost_bps,c.slippage_bps)==(17,23,8) for c in seen))
            self.assertEqual(len(store.read('momentum_comparisons/123456abcdef')['trials']),6)
            self.assertFalse(cfg.require_vwap)
            self.assertEqual(cfg.breakout_buffer_atr,0)

    def test_research_suite_preserves_costs_and_saves_every_variant(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            cfg,_=self.setup_reference();seen=[]
            def run(settings,config,log,run_id):
                seen.append(config)
                store.write('runs/'+run_id,dict(metrics={'return_pct':-1},evaluation={'segments':[]},diagnostics={}))
            with patch.object(momentum,'run',side_effect=run):
                momentum.compare(SimpleNamespace(universe='nifty50'),'abcdef123456',lambda m:None,'123456abcdef',suite='research')
            self.assertEqual({c.confirmation_minutes for c in seen},{5,10,60})
            self.assertTrue(all((c.buy_cost_bps,c.sell_cost_bps,c.slippage_bps)==(17,23,8) for c in seen))
            result=store.read('momentum_comparisons/123456abcdef')
            self.assertEqual(len(result['trials']),len(momentum.RESEARCH_IDEAS))
            self.assertEqual(result['trials'][0]['changes'],{})
            self.assertEqual(result['suite'],'research')
