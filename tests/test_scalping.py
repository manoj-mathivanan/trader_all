import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from core.research import intraday_data, scalping, store
from dashboard.api.main import app


def session(day, base=110, step=.02):
    start = datetime.fromisoformat(day+'T09:15:00+05:30')
    return [dict(date=day, time=(start+timedelta(minutes=i)).strftime('%H:%M'),
                 timestamp=int((start+timedelta(minutes=i)).timestamp()*1000),
                 open=base+i*step, close=base+(i+1)*step,
                 high=max(base+i*step, base+(i+1)*step)+.01,
                 low=min(base+i*step, base+(i+1)*step)-.01, volume=100000) for i in range(375)]


def pullback(bars, index=31):
    x = bars[index]['open']
    for offset, o, h, l, c in [(0, x, x+.02, x-.14, x-.12),
                              (1, x-.12, x-.10, x-.18, x-.16),
                              (2, x-.16, x+.15, x-.17, x+.12)]:
        bars[index+offset].update(open=o, high=h, low=l, close=c)
    bars[index+3].update(open=x+.12, high=x+.16, low=x+.10, close=x+.14)


class ScalpingTests(unittest.TestCase):
    def setUp(self):
        self.day = '2025-02-05'
        self.cfg = scalping.ScalpingConfig(start=self.day, end='2025-02-06',
                    liquid_universe_size=3, max_positions=1, first_entry_time='09:45',
                    buy_cost_bps=0, sell_cost_bps=0, slippage_bps=0, acknowledge_limitations=True)
        self.minutes = {'A': {'2025-02-03':session('2025-02-03', 100, .005),
                              '2025-02-04':session('2025-02-04', 102, .005), self.day:session(self.day)}}
        pullback(self.minutes['A'][self.day])
        self.candidate = dict(symbol='A', turnover=1e8, history=['2025-02-03','2025-02-04'], daily_open=110)
        self.plan = {self.day:[self.candidate]}

    def simulate(self, cfg=None, minutes=None, plan=None):
        return scalping.simulate({}, cfg or self.cfg, minutes or self.minutes, plan or self.plan)

    def test_completed_signal_next_open_and_cost_accounting(self):
        report = self.simulate()
        self.assertGreater(len(report['trades']), 0)
        t = report['trades'][0]
        self.assertEqual(t['signal_time'], '09:48')
        self.assertEqual(t['entry_time'], '09:49')
        self.assertEqual(t['entry'], self.minutes['A'][self.day][34]['open'])
        self.assertAlmostEqual(report['metrics']['final_equity'], self.cfg.capital+sum(t['pnl'] for t in report['trades']))
        cfg = self.cfg.model_copy(update={'slippage_bps':5, 'buy_cost_bps':5, 'sell_cost_bps':5})
        costly = self.simulate(cfg)
        self.assertGreater(costly['metrics']['modeled_fees'], 0)
        self.assertGreater(costly['metrics']['modeled_slippage'], 0)
        self.assertAlmostEqual(costly['metrics']['final_equity'], cfg.capital+sum(t['pnl'] for t in costly['trades']))

    def test_future_candles_do_not_change_earlier_features_or_signal(self):
        bars, f = scalping.features(self.minutes['A'], self.candidate, self.day, self.cfg)
        original = scalping.signal(bars, f, 33, self.cfg)
        self.assertIsNotNone(original)
        for b in self.minutes['A'][self.day][34:]:
            b.update(open=500, high=501, low=499, close=500)
        later, lf = scalping.features(self.minutes['A'], self.candidate, self.day, self.cfg)
        self.assertEqual(f[:34], lf[:34])
        self.assertEqual(original, scalping.signal(later, lf, 33, self.cfg))

    def test_only_completed_five_minute_candles_update_trend(self):
        _, f = scalping.features(self.minutes['A'], self.candidate, self.day, self.cfg)
        self.assertEqual(f[29]['fast'], f[33]['fast'])
        self.assertNotEqual(f[33]['fast'], f[34]['fast'])

    def test_stop_first_if_both_hit_and_gap_fill_at_open(self):
        self.minutes['A'][self.day][34].update(high=115, low=100)
        r = self.simulate()
        self.assertEqual(r['trades'][0]['reason'], 'Pullback stop loss')
        self.assertEqual(r['metrics']['ambiguous_stop_target_bars'], 1)
        self.setUp()
        self.minutes['A'][self.day][35].update(open=109, high=109.1, low=108, close=108.5)
        t = self.simulate()['trades'][0]
        self.assertEqual(t['reason'], 'Gap through pullback stop')
        self.assertEqual(t['exit'], 109)

    def test_short_symmetry_and_no_overnight_positions(self):
        # Mirror all prices about 110; volume and time remain unchanged.
        for rows in self.minutes['A'].values():
            for b in rows:
                o,h,l,c = [b[k] for k in ('open','high','low','close')]
                b.update(open=220-o, high=220-l, low=220-h, close=220-c)
        self.candidate['daily_open'] = 110
        cfg = self.cfg.model_copy(update={'direction':'short'})
        r = self.simulate(cfg)
        self.assertGreater(len(r['trades']), 0)
        self.assertTrue(all(t['direction'] == 'short' for t in r['trades']))
        self.assertAlmostEqual(r['metrics']['final_equity'], cfg.capital+sum(t['pnl'] for t in r['trades']))
        self.assertEqual(r['metrics']['overnight_positions'], 0)

    def test_reentries_obey_cooldown_and_trade_cap(self):
        pullback(self.minutes['A'][self.day], 61)
        r = self.simulate()
        self.assertGreaterEqual(len(r['trades']), 2)
        capped = self.simulate(self.cfg.model_copy(update={'max_trades_per_symbol':1}))
        self.assertEqual(len(capped['trades']), 1)
        cooled = self.simulate(self.cfg.model_copy(update={'cooldown_minutes':120}))
        self.assertEqual(len(cooled['trades']), 1)

    def test_simultaneous_signals_position_limit_and_capital_reservation(self):
        import copy
        self.minutes['B'] = copy.deepcopy(self.minutes['A'])
        plan = {self.day:[self.candidate, {**self.candidate,'symbol':'B'}]}
        r = self.simulate(plan=plan)
        self.assertEqual({t['symbol'] for t in r['trades']}, {'A'})
        cfg = self.cfg.model_copy(update={'max_positions':2})
        r = self.simulate(cfg, plan=plan)
        first = r['trades'][:2]
        self.assertEqual({t['symbol'] for t in first}, {'A', 'B'})
        self.assertLessEqual(sum(t['entry']*t['quantity'] for t in first), cfg.capital)

    def test_daily_loss_pause_and_signal_volume_cap(self):
        self.minutes['A'][self.day][34].update(high=111, low=100)
        pullback(self.minutes['A'][self.day], 61)
        cfg = self.cfg.model_copy(update={'daily_loss_pct':.001})
        r = self.simulate(cfg)
        self.assertEqual(len(r['trades']), 1)
        self.assertEqual(r['diagnostics']['daily_loss_halt_sessions'], 1)
        self.setUp()
        self.minutes['A'][self.day][33]['volume'] = 100
        r = self.simulate()
        self.assertEqual(r['trades'][0]['quantity'], 1)

    def test_missing_minute_or_warmup_fails(self):
        del self.minutes['A'][self.day][10]
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self.simulate()
        self.setUp()
        del self.minutes['A']['2025-02-03'][10]
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self.simulate()

    def test_filters_and_validator(self):
        bars, f = scalping.features(self.minutes['A'], self.candidate, self.day, self.cfg)
        self.assertIsNotNone(scalping.signal(bars,f,33,self.cfg))
        f[33]['vwap'] = 1000
        self.assertIsNone(scalping.signal(bars,f,33,self.cfg.model_copy(update={'entry_filter':'ema_vwap'})))
        f[33]['fast'] = 0
        self.assertIsNone(scalping.signal(bars,f,33,self.cfg))
        self.assertIsNotNone(scalping.signal(bars,f,33,self.cfg.model_copy(update={'entry_filter':'candles'})))
        for changes in ({'square_off_time':'15:99'}, {'trend_fast':25}, {'min_stop_pct':1}, {'acknowledge_limitations':False}):
            with self.assertRaises(ValueError):
                scalping.ScalpingConfig(**{**self.cfg.model_dump(), **changes})

    def test_one_minute_ingestion_is_separate_and_reuses_cache(self):
        rows = [[f"{self.day}T{b['time']}:00+05:30",b['open'],b['high'],b['low'],b['close'],b['volume']] for b in self.minutes['A'][self.day]]
        response = Mock(); response.json.return_value = {'status':'success','data':{'candles':rows}}
        universe = {'instruments':[{'symbol':'A','isin':'ISIN','key':'NSE_EQ|ISIN'}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), patch.object(store,'token',return_value='token'), patch.object(intraday_data.upstox,'get',return_value=response) as get:
            r = intraday_data.load_ranges({self.day:[{'symbol':'A'}]},universe,lambda _:None,1)
            self.assertEqual(len(r['A'][self.day]),375)
            self.assertIn('/minutes/1/',get.call_args.args[1])
            self.assertIsNone(store.read(intraday_data.cache_key('ISIN',self.day)))
            intraday_data.load_ranges({self.day:[{'symbol':'A'}]},universe,lambda _:None,1)
            self.assertEqual(get.call_count,1)

    def test_frozen_replay_missing_and_tampered_data_halts(self):
        cfg = self.cfg.model_copy(update={'comparison_run_id':'abcdef123456'})
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)):
            store.write('runs/'+cfg.comparison_run_id,{'intraday_source':{'sha256':scalping.digest(self.minutes)}})
            with self.assertRaises(ValueError):
                scalping.frozen_sessions(cfg)
            store.write('run_intraday/'+cfg.comparison_run_id,self.minutes)
            self.assertEqual(scalping.frozen_sessions(cfg),self.minutes)
            self.minutes['A'][self.day][33]['close'] += .1
            store.write('run_intraday/'+cfg.comparison_run_id,self.minutes)
            with self.assertRaisesRegex(ValueError,'changed'):
                scalping.frozen_sessions(cfg)

    def test_api_dispatch_and_frozen_trade_chart(self):
        client = TestClient(app)
        with patch('dashboard.api.main.scalping.prepare'), patch('dashboard.api.main.jobs.submit',return_value={'id':'abcdef123456'}) as submit:
            response = client.post('/api/jobs/scalping',json=self.cfg.model_dump(mode='json'),headers={'X-Trader-Request':'local-ui'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(submit.call_args.args[0],'Scalping backtest')
        report = self.simulate()
        daily = {'A':[dict(date=self.day,open=110,high=120,low=100,close=111,volume=100000)]}
        report.update(id='abcdef123456',strategy_id='scalping',config=self.cfg.model_dump(mode='json'),
                      selection_plan=self.plan,
                      manifest=[dict(symbol='A',sha256=scalping.digest(daily['A']))],intraday_source={'sha256':scalping.digest(self.minutes)})
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), patch.object(scalping,'entry_plan',return_value=(self.plan,{})):
            store.write('runs/abcdef123456',report)
            store.write('run_data/abcdef123456',daily)
            store.write('run_intraday/abcdef123456',self.minutes)
            response = client.get('/api/runs/abcdef123456/trades/0/chart')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['interval_minutes'],1)
            self.assertEqual(response.json()['explanation']['pattern'],'Scalping pullback continuation')
            store.write('run_intraday/abcdef123456',{})
            self.assertEqual(client.get('/api/runs/abcdef123456/trades/0/chart').status_code,404)

    def test_run_persists_and_three_variant_comparison_reuses_frozen_inputs(self):
        settings = SimpleNamespace(universe='nifty50')
        daily = {'A':[dict(date=self.day,open=110,high=120,low=100,close=111,volume=100000)]}
        universe = {'instruments':[dict(symbol='A',isin='ISIN',key='KEY')]}
        manifest = [dict(symbol='A',sha256=scalping.digest(daily['A']))]
        original_prepare = scalping.prepare
        def prepare(settings, cfg):
            return original_prepare(settings, cfg) if cfg.comparison_run_id else (universe,daily,manifest,[])
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), patch.object(scalping,'prepare',side_effect=prepare), patch.object(scalping,'entry_plan',return_value=(self.plan,{})), patch.object(scalping.data_quality,'audit',return_value={'anomalies':[]}), patch.object(scalping.data_quality,'require_no_anomalies'), patch.object(intraday_data,'load_ranges',return_value=self.minutes) as load:
            scalping.run(settings,self.cfg,lambda _:None,'abcdef123456')
            self.assertEqual(store.read('runs_index')[0]['strategy_id'],'scalping')
            self.assertEqual(store.read('run_intraday/abcdef123456'),self.minutes)
            scalping.compare(settings,'abcdef123456',lambda _:None,'abcdef123457')
            self.assertEqual(load.call_count,1)
            comparison = store.read('scalping_comparisons/abcdef123457')
            self.assertEqual([t['label'] for t in comparison['trials']],['Candles only','EMA confirmation','EMA + VWAP'])
            self.assertTrue(all(t['status']=='success' for t in comparison['trials']),comparison)
            for t in comparison['trials']:
                result = store.read('runs/'+t['run_id'])
                self.assertEqual(result['intraday_source']['sha256'],scalping.digest(self.minutes))
                self.assertEqual(result['config']['slippage_bps'],self.cfg.slippage_bps)


if __name__ == '__main__':
    unittest.main()
