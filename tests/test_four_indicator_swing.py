import copy
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from core.research import four_indicator_swing as fs, store
from core.strategies.four_indicator import indicators, decision


def rows():
    start=date(2025,1,1)
    return [dict(date=(start+timedelta(days=i)).isoformat(),timestamp=i*86400000,
                 open=100+i,high=102+i,low=99+i,close=101+i,volume=1000) for i in range(110)]


class SwingTests(unittest.TestCase):
    def setUp(self):
        self.rows=rows()
        self.cfg=fs.SwingConfig(start=self.rows[100]['date'],end=self.rows[-1]['date'],capital=10000,max_positions=1,rule_set='all',
                               slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0)
        self.signals=[dict(exit=False,close=500,checks=[dict(passed=False,value=1) for _ in range(4)]) for _ in self.rows]
        self.signals[100]=dict(exit=False,close=500,checks=[dict(passed=True,value=1) for _ in range(4)])

    def simulate(self,cfg=None,signals=None):
        return fs.simulate({'A':self.rows},{'A':signals or self.signals},cfg or self.cfg,fs.RULES[3])

    def test_balanced_defaults_and_legacy_frozen_rerun(self):
        cfg=fs.SwingConfig(start='2025-10-09',end='2026-10-09')
        self.assertEqual(cfg.rule_set,'bollinger')
        self.assertEqual({k:getattr(cfg,k) for k in fs.ALL_FOUR_DEFAULTS},fs.ALL_FOUR_DEFAULTS)
        with patch.object(store,'read',return_value={'config':{'rule_set':'bollinger','max_positions':5}}):
            old=fs.SwingConfig(start='2025-10-09',end='2026-10-09',comparison_run_id='aabbccddeeff',max_positions=5)
        self.assertEqual((old.rsi_threshold,old.bollinger_multiplier),(70,2))
        with patch.object(store,'read',return_value={'config':cfg.model_dump(mode='json')}):
            new=fs.SwingConfig(start='2025-10-09',end='2026-10-09',comparison_run_id='aabbccddeeff')
        self.assertEqual((new.rsi_threshold,new.bollinger_multiplier),(65,2.5))

    def test_configured_thresholds_and_bands_reach_signals(self):
        bars=self.rows
        old=indicators(bars)
        new=indicators(bars,bollinger_multiplier=2.5)
        for a,b in zip(old[20:],new[20:]):
            self.assertEqual(a['supertrend'],b['supertrend'])
            self.assertEqual(a['rsi'],b['rsi'])
            self.assertGreater(b['upper_band'],a['upper_band'])
        value=dict(uptrend=True,supertrend=100,rsi=67,upper_band=110)
        bar=dict(close=120,time='close',timestamp=1)
        prior=dict(high=105,low=90,close=100)
        self.assertFalse(decision(bar,value,prior)['entry'])
        self.assertTrue(decision(bar,value,prior,rsi_threshold=65,bollinger_multiplier=2.5)['entry'])
        self.assertFalse(decision(bar,dict(value,rsi=65),prior,rsi_threshold=65)['entry'])
        signals=fs.features({'A':bars},rsi_threshold=65,bollinger_multiplier=2.5)['A']
        self.assertEqual(signals[-1]['checks'][3]['value'],new[-1]['upper_band'])
        self.assertIn('65',signals[-1]['checks'][1]['name'])

    def test_daily_entry_and_reversal_next_open_and_accounting(self):
        self.signals[103]['exit']=True
        r=self.simulate()
        t=r['trades'][0]
        self.assertEqual(t['signal_date'],self.rows[100]['date'])
        self.assertEqual(t['entry_date'],self.rows[101]['date'])
        self.assertEqual(t['exit_date'],self.rows[104]['date'])
        self.assertEqual(t['entry'],self.rows[101]['open'])
        self.assertEqual(t['exit'],self.rows[104]['open'])
        self.assertAlmostEqual(r['metrics']['final_equity'],self.cfg.capital+sum(t['pnl'] for t in r['trades']))
        self.assertTrue(all(x['cash']>=0 for x in r['curve']))

    def test_terminal_close_and_explicit_costs(self):
        cfg=self.cfg.model_copy(update=dict(slippage_bps=10,buy_cost_bps=10,sell_cost_bps=10))
        r=self.simulate(cfg)
        t=r['trades'][0]
        self.assertEqual(t['exit_date'],self.rows[-1]['date'])
        self.assertIn('final observed close',t['reason'])
        self.assertAlmostEqual(t['exit'],self.rows[-1]['close']*.999)
        self.assertGreater(r['metrics']['modeled_fees'],0)
        self.assertGreater(r['metrics']['modeled_slippage'],0)
        self.assertAlmostEqual(r['metrics']['final_equity'],cfg.capital+t['pnl'])

    def test_position_limit_turnover_priority_and_no_leverage(self):
        other=copy.deepcopy(self.rows)
        for b in other:b['volume']*=2
        r=fs.simulate({'A':self.rows,'B':other},{'A':self.signals,'B':self.signals},self.cfg,fs.RULES[3])
        self.assertEqual([t['symbol'] for t in r['trades']],['B'])
        self.assertEqual(r['metrics']['skipped_entries'],1)
        self.assertTrue(all(x['positions']<=1 and x['cash']>=0 for x in r['curve']))

    def test_no_entry_from_pre_window_signal(self):
        self.signals[99]=self.signals[100]
        self.signals[100]=dict(exit=False,close=500,checks=[dict(passed=False,value=1) for _ in range(4)])
        self.assertEqual(self.simulate()['metrics']['trade_count'],0)

    def test_available_history_waits_for_each_stocks_own_warmup(self):
        cfg=self.cfg.model_copy(update=dict(start=date(2025,1,1),coverage_mode='available_history'))
        self.signals[50]=copy.deepcopy(self.signals[100])
        r=self.simulate(cfg)
        self.assertEqual(r['metrics']['trade_count'],1)
        self.assertEqual(r['trades'][0]['entry_date'],self.rows[101]['date'])

    def test_available_history_includes_late_stocks_but_rejects_missing_sessions(self):
        cfg=self.cfg.model_copy(update=dict(start=date(2024,1,1),coverage_mode='available_history'))
        universe={'instruments':[dict(symbol='A',isin='ISINA')]}
        cached={'universes/test':universe,'bars/NIFTY50':{'bars':self.rows}}
        with patch.object(fs.store,'read',side_effect=lambda key,default=None:cached.get(key,default)),patch.object(fs,'read_many',return_value={'bars/ISINA':{'bars':self.rows}}),patch.object(fs.market_history,'evidence',return_value={}),patch.object(fs.market_history,'prepare',side_effect=lambda item,record,**kw:(record['bars'],{})):
            frozen=fs.prepare(SimpleNamespace(universe='test'),cfg,lambda _:None)
            self.assertIn('A',frozen['datasets'])
            self.assertEqual(frozen['coverage']['A']['eligible_from'],self.rows[100]['date'])
            with self.assertRaisesRegex(ValueError,'No cached stocks'):
                fs.prepare(SimpleNamespace(universe='test'),cfg.model_copy(update={'coverage_mode':'full_window'}),lambda _:None)
            incomplete=self.rows[:105]+self.rows[106:]
            with patch.object(fs,'read_many',return_value={'bars/ISINA':{'bars':incomplete}}),self.assertRaisesRegex(ValueError,'contiguous'):
                fs.prepare(SimpleNamespace(universe='test'),cfg,lambda _:None)

    def test_main_group_saves_exactly_four_matching_runs(self):
        frozen=dict(datasets={'A':self.rows},universe={'instruments':[]},excluded=[],exclusion_reasons={},source='test')
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            with patch.object(fs,'prepare',return_value=frozen):
                result=fs.run(SimpleNamespace(universe='niftytotalmarket'),self.cfg.model_copy(update={'rule_set':'main'}),lambda _:None,'abcdef123456')
            self.assertEqual(len(result['run_ids']),4)
            self.assertEqual({r['config']['rule_set'] for r in store.read('runs_index')},{'supertrend','rsi','r1','bollinger'})

    def test_full_history_keeps_a_later_continuous_segment(self):
        cfg=self.cfg.model_copy(update=dict(start=date(2024,1,1),coverage_mode='available_history'))
        universe={'instruments':[dict(symbol='A',isin='ISINA')]}
        cached={'universes/test':universe,'bars/NIFTY50':{'bars':self.rows}}
        fragmented=self.rows[:5]+self.rows[6:]
        with patch.object(fs.store,'read',side_effect=lambda key,default=None:cached.get(key,default)),patch.object(fs,'read_many',return_value={'bars/ISINA':{'bars':fragmented}}),patch.object(fs.market_history,'evidence',return_value={}),patch.object(fs.market_history,'prepare',side_effect=lambda item,record,**kw:(record['bars'],{})):
            frozen=fs.prepare(SimpleNamespace(universe='test'),cfg,lambda _:None)
        self.assertEqual(frozen['datasets']['A'][0]['date'],self.rows[6]['date'])
        self.assertEqual(frozen['coverage']['A']['eligible_from'],self.rows[106]['date'])
        self.assertEqual(frozen['history_fragments']['A']['last_gap'],self.rows[5]['date'])

    def test_four_checks_no_rsi_cap_and_daily_future_independence(self):
        values=fs.features({'A':self.rows})['A']
        changed=copy.deepcopy(self.rows)
        for b in changed[105:]:b.update(open=1000,high=1002,low=999,close=1001)
        self.assertEqual(values[:105],fs.features({'A':changed})['A'][:105])
        v=dict(uptrend=True,supertrend=100,rsi=95,upper_band=110)
        b=dict(close=120,time='close',timestamp=1)
        prior=dict(high=105,low=90,close=100)
        self.assertTrue(decision(b,v,prior)['entry'])
        self.assertFalse(decision(b,dict(v,rsi=70),prior)['entry'])

    def test_normal_run_storage_and_frozen_rerun(self):
        frozen=dict(datasets={'A':self.rows},universe={'instruments':[]},excluded=[],exclusion_reasons={},source='test')
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DATA',Path(tmp)),patch.object(store,'database_enabled',return_value=False):
            with patch.object(fs,'prepare',return_value=frozen):
                result=fs.run(SimpleNamespace(universe='niftytotalmarket'),self.cfg,lambda _:None,'aabbccddeeff')
            self.assertEqual(len(result['run_ids']),5)
            self.assertEqual(len(store.read('runs_index')),5)
            r=store.read('runs/'+result['run_id'])
            self.assertEqual(r['strategy_id'],'four_indicator_swing')
            cfg=self.cfg.model_copy(update={'comparison_run_id':r['id'],'rule_set':'supertrend'})
            self.assertEqual(fs.prepare(None,cfg,lambda _:None),frozen)
            store.write('run_data/'+r['id'],dict(frozen,source='changed'))
            with self.assertRaisesRegex(ValueError,'changed'):
                fs.prepare(None,cfg,lambda _:None)

    def test_shared_backtest_api_and_options_disabled(self):
        from dashboard.api.main import app
        client=TestClient(app)
        with patch('dashboard.api.main.jobs.submit',return_value={'id':'aabbccddeeff'}) as submit:
            response=client.post('/api/jobs/backtest',json=self.cfg.model_dump(mode='json'),headers={'X-Trader-Request':'local-ui'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(submit.call_args.args[0],'Daily four-indicator swing backtest')
        self.assertTrue(submit.call_args.kwargs['allow_queue'])
        self.assertEqual(client.post('/api/option-paper/start',headers={'X-Trader-Request':'local-ui'}).status_code,404)


if __name__=='__main__':unittest.main()
