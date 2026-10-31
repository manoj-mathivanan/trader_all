import copy
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from core.research import store, four_indicator_swing as fs
from core.research.config import Settings
from core.portfolio import four_indicator_paper as paper, manager, scheduler, registry
from tests.test_four_indicator_swing import rows

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.rows=rows()
        self.cfg=SimpleNamespace(start=self.rows[100]['date'],end=self.rows[-1]['date'],capital=10000,
                                max_positions=1,slippage_bps=10,buy_cost_bps=10,sell_cost_bps=10)
        self.signals=[dict(exit=False,close=500,checks=[dict(passed=True,value=1) for _ in range(4)]) for _ in self.rows]

    def test_incremental_matches_single_replay_and_keeps_holdings(self):
        datasets={'A':self.rows}; signals={'A':self.signals}
        full=fs.simulate(datasets,signals,self.cfg,fs.RULES[1],liquidate=False)
        cut=self.rows[104]['date']
        first=fs.simulate(datasets,signals,SimpleNamespace(**{**vars(self.cfg),'end':cut}),fs.RULES[1],liquidate=False)
        self.assertEqual(len(first['ledger']['positions']),1)
        second=fs.simulate(datasets,signals,SimpleNamespace(**{**vars(self.cfg),'start':self.rows[105]['date']}),
                           fs.RULES[1],state=first['ledger'],liquidate=False,entry_start=self.cfg.start)
        self.assertEqual(second,full)
        p=full['ledger']['positions']['A']
        self.assertLess(p['signal_date'],p['entry_date'])
        self.assertAlmostEqual(full['metrics']['final_equity'],full['ledger']['cash']+p['quantity']*self.rows[-1]['close'])
        self.assertFalse(full['trades'])

    def test_paused_portfolio_exits_but_does_not_buy(self):
        self.signals[103]['exit']=True
        first=fs.simulate({'A':self.rows},{'A':self.signals},SimpleNamespace(**{**vars(self.cfg),'end':self.rows[103]['date']}),fs.RULES[1],liquidate=False)
        paused=fs.simulate({'A':self.rows},{'A':self.signals},SimpleNamespace(**{**vars(self.cfg),'start':self.rows[104]['date']}),fs.RULES[1],
                          state=first['ledger'],liquidate=False,entry_start=self.cfg.start,entries_allowed=False)
        self.assertFalse(paused['ledger']['positions'])
        self.assertEqual(len(paused['trades']),1)
        self.assertEqual(paused['trades'][0]['exit_date'],self.rows[104]['date'])
        self.assertEqual([o['side'] for o in paused['ledger']['orders']],['BUY','SELL'])

class PortfolioTests(unittest.TestCase):
    def test_legacy_schedule_edits_normalize_new_defaults_and_allocation_freezes(self):
        from core.strategies.four_indicator_allocation import AllocationConfig
        paper.save(self.cfg, Settings(), create=True, portfolio_id='legacy')
        key = manager.key(fs.STRATEGY, 'legacy')
        old = store.read(key)
        for name in AllocationConfig.model_fields:
            old['config'].pop(name)
        store.write(key, old)
        updated = paper.save(self.cfg.model_copy(update={'name':'Updated schedule'}), Settings(), portfolio_id='legacy')
        self.assertEqual(updated['config']['candidate_ranking'], 'turnover')
        self.assertEqual(updated['config']['target_atr_pct'], 0)
        with self.assertRaisesRegex(ValueError, 'freeze'):
            paper.save(self.cfg.model_copy(update={'target_atr_pct':2}), Settings(), portfolio_id='legacy')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'TRADER_STORAGE':'json'})
        self.env.start()
        self.data=patch.object(store,'DATA',Path(self.temp.name));self.data.start()
        self.rows=rows()
        self.item=dict(symbol='A',isin='TESTISIN0001')
        self.universe=dict(instruments=[self.item])
        self.cfg=paper.PaperConfig(name='RSI paper',rule_set='rsi',start_session=self.rows[100]['date'])
        store.write('universes/niftytotalmarket',self.universe)

    def tearDown(self):
        self.data.stop();self.env.stop();self.temp.cleanup()

    def test_all_four_default_adoption_preserves_holdings_and_audits_rules(self):
        defaults=paper.PaperConfig(start_session=self.rows[100]['date'])
        self.assertEqual(defaults.rule_set,'bollinger')
        self.assertEqual((defaults.max_positions,defaults.rsi_threshold,defaults.bollinger_multiplier),(10,65,2.5))
        cfg=self.cfg.model_copy(update=dict(rule_set='bollinger'))
        paper.save(cfg,Settings(),create=True,portfolio_id='all4')
        key=manager.key(fs.STRATEGY,'all4')
        before=store.read(key)
        # Pre-upgrade records have no indicator parameter fields.
        for k in fs.LEGACY_PARAMETERS:before['config'].pop(k,None)
        before.update(ledger=dict(last_session='2026-10-23',cash=500,positions={'A':{'quantity':10}}),
                      metrics={'final_equity':2000},cycles=[{'config':copy.deepcopy(before['config'])}])
        store.write(key,before)
        after=paper.adopt_all_four_defaults('all4')
        for k in ('ledger','metrics','cycles','status','replay_through'):
            self.assertEqual(after[k],before[k])
        self.assertEqual(after['config']['capital'],before['config']['capital'])
        self.assertEqual(after['config_history'][0]['effective_after_session'],'2026-10-23')
        self.assertEqual(after['config_history'][0]['previous_config'],before['config'])
        self.assertEqual((after['config']['max_positions'],after['config']['rsi_threshold'],after['config']['bollinger_multiplier']),(10,65,2.5))
        self.assertEqual(paper.adopt_all_four_defaults('all4'),after)
        paper.save(self.cfg,Settings(),create=True,portfolio_id='rsi')
        with self.assertRaisesRegex(ValueError,'all-four'):
            paper.adopt_all_four_defaults('rsi')
        store.write('jobs',[{'id':'busy','status':'running'}])
        with self.assertRaisesRegex(ValueError,'active job'):
            paper.adopt_all_four_defaults('all4')

    def test_legacy_cycle_passes_original_thresholds_and_new_cycle_uses_defaults(self):
        for identity in ('legacy','balanced'):
            config=paper.PaperConfig(start_session=self.rows[100]['date'])
            paper.save(config,Settings(),create=True,portfolio_id=identity)
        legacy=manager.get(fs.STRATEGY,'legacy')
        for k in fs.LEGACY_PARAMETERS:legacy['config'].pop(k)
        store.write(manager.key(fs.STRATEGY,'legacy'),legacy)
        initial=self.rows[:105]
        frozen=dict(datasets={'A':initial},universe=self.universe,exclusion_reasons={},excluded=[])
        store.write('bars/NIFTY50',{'bars':initial})
        for identity,threshold,multiplier in [('legacy',70,2),('balanced',65,2.5)]:
            with patch.object(fs,'prepare',return_value=frozen),patch.object(fs,'features',wraps=fs.features) as features:
                paper.cycle(lambda _:None,identity,ingest=False,portfolio_id=identity)
            self.assertEqual(features.call_args.kwargs,dict(rsi_threshold=threshold,bollinger_multiplier=multiplier))

    def test_separate_scenarios_and_frozen_configuration(self):
        paper.save(self.cfg,Settings(),create=True,portfolio_id='rsi')
        paper.save(self.cfg.model_copy(update={'rule_set':'bollinger'}),Settings(),create=True,portfolio_id='all4')
        self.assertEqual(len(manager.list_portfolios(fs.STRATEGY)),2)
        with self.assertRaises(ValueError):
            paper.save(self.cfg.model_copy(update={'capital':20000}),Settings(),portfolio_id='rsi')
        self.assertNotEqual(manager.schedule_key(fs.STRATEGY,'rsi'),manager.schedule_key(fs.STRATEGY,'all4'))

    def test_idempotent_cycle_and_revised_candles_do_not_change_ledger(self):
        paper.save(self.cfg,Settings(),create=True,portfolio_id='rsi')
        initial=self.rows[:105]
        frozen=dict(datasets={'A':initial},universe=self.universe,exclusion_reasons={},excluded=[])
        store.write('bars/NIFTY50',{'bars':initial})
        with patch.object(fs,'prepare',return_value=frozen):
            result=paper.cycle(lambda _:None,'first',ingest=False,portfolio_id='rsi')
        self.assertEqual(result['sessions'],5)
        before=manager.get(fs.STRATEGY,'rsi')
        self.assertEqual(paper.cycle(lambda _:None,'repeat',ingest=False,portfolio_id='rsi')['sessions'],0)
        self.assertEqual(manager.get(fs.STRATEGY,'rsi'),before)
        store.write('bars/NIFTY50',{'bars':self.rows})
        revised=copy.deepcopy(self.rows);revised[102]['close']+=1
        with patch.object(paper.market_history,'evidence',return_value={}),patch.object(paper.market_history,'prepare',return_value=(revised,{})):
            with self.assertRaisesRegex(ValueError,'processed inputs changed'):
                paper.cycle(lambda _:None,'bad',ingest=False,portfolio_id='rsi')
        self.assertEqual(manager.get(fs.STRATEGY,'rsi'),before)
        with patch.object(paper.market_history,'evidence',return_value={}),patch.object(paper.market_history,'prepare',return_value=(self.rows,{})):
            paper.cycle(lambda _:None,'next',ingest=False,portfolio_id='rsi')
        after=manager.get(fs.STRATEGY,'rsi')
        self.assertEqual(len(after['cycles']),2)
        self.assertEqual(after['ledger']['curve'][:5],before['ledger']['curve'])
        self.assertEqual(after['ledger']['last_session'],self.rows[-1]['date'])
        self.assertTrue(all(o['mode']=='historical_replay' for o in after['ledger']['orders']))

    def test_scheduler_binds_each_scenario(self):
        for identity in ('rsi','all4'):
            paper.save(self.cfg,Settings(),create=True,portfolio_id=identity)
        clock=SimpleNamespace(weekday=lambda:0,hour=17,minute=0,date=lambda:date(2026,10,26))
        with patch.object(scheduler.paper,'local_now',return_value=clock),patch.object(scheduler.jobs,'submit',return_value={'id':'job'}) as submit:
            scheduler.tick()
        self.assertEqual(submit.call_count,2)
        self.assertEqual({c.args[1].keywords['portfolio_id'] for c in submit.call_args_list},{'rsi','all4'})

    def test_first_completed_day_marks_equity_without_pre_start_entry(self):
        paper.save(self.cfg,Settings(),create=True,portfolio_id='rsi')
        initial=self.rows[:101]
        store.write('bars/NIFTY50',{'bars':initial})
        frozen=dict(datasets={'A':initial},universe=self.universe,exclusion_reasons={},excluded=[])
        with patch.object(fs,'prepare',return_value=frozen):
            paper.cycle(lambda _:None,'first',ingest=False,portfolio_id='rsi')
        p=manager.get(fs.STRATEGY,'rsi')
        self.assertEqual(p['ledger']['last_session'],self.rows[100]['date'])
        self.assertFalse(p['ledger']['orders'])
        self.assertEqual(p['metrics']['final_equity'],self.cfg.capital)

if __name__=='__main__':unittest.main()
