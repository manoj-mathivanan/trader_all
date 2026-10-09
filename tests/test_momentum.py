import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from core.research import momentum, intraday_data


def session(day, price=100, volume=100):
    start = datetime.fromisoformat(day+'T09:15:00+05:30')
    return [dict(date=day, time=(start+timedelta(minutes=i*5)).strftime('%H:%M'),
                 timestamp=int((start+timedelta(minutes=i*5)).timestamp()*1000),
                 open=price, high=price+1, low=price-1, close=price, volume=volume) for i in range(70)]


class MomentumTests(unittest.TestCase):
    def setUp(self):
        self.cfg = momentum.MomentumConfig(start='2025-02-03', end='2025-02-04', acknowledge_limitations=True,
                    min_relative_volume=1, capital=10000, risk_pct=1, max_positions=2, liquid_universe_size=2,
                    slippage_bps=0, buy_cost_bps=0, sell_cost_bps=0, stop_atr=.5)
        self.daily = {'A':[dict(date='2025-02-03',open=100,high=110,low=99,close=105,volume=10000)]}
        self.minutes = {'A':{'2025-02-03':session('2025-02-03'), '2025-01-31':session('2025-01-31')}}
        bars = self.minutes['A']['2025-02-03']
        bars[0].update(close=100.5,volume=200)
        bars[1].update(high=102,close=102)
        bars[2].update(open=102,high=103,low=101,close=102)
        for b in bars[3:]:
            b.update(open=102, high=103, low=101, close=102)
        self.plan = {'2025-02-03':[dict(symbol='A',atr=4,turnover=100000,history=['2025-01-31'],daily_open=100,actions=[])]}

    def simulate(self):
        return momentum.simulate(self.daily,self.cfg,self.minutes,self.plan)

    def test_reverse_buy_signal_keeps_confirmation_and_uses_short_protection(self):
        baseline = self.simulate()['trades'][0]
        self.cfg.execution_mode = 'reverse'
        self.cfg.require_vwap = True
        self.cfg.min_close_strength = .7
        self.cfg.min_confirmation_body_atr = .1
        reversed_trade = self.simulate()['trades'][0]
        self.assertEqual(reversed_trade['signal_direction'], 'long')
        self.assertEqual(reversed_trade['direction'], 'short')
        self.assertEqual(reversed_trade['entry_time'], baseline['entry_time'])
        self.assertEqual(reversed_trade['trigger'], baseline['trigger'])
        self.assertEqual(reversed_trade['initial_stop'], 104)
        self.assertEqual(reversed_trade['confirmation_quality']['close_strength'], 1)
        self.minutes['A']['2025-02-03'][3].update(high=105)
        self.assertEqual(self.simulate()['trades'][0]['exit'], 104)

    def test_reverse_sell_signal_uses_buy_costs_and_long_entry_check(self):
        bars = self.minutes['A']['2025-02-03']
        bars[0].update(close=99.5)
        bars[1].update(close=98, low=97)
        for bar in bars[2:]:
            bar.update(open=98, high=99, low=97, close=98)
        self.cfg.execution_mode = 'reverse'
        self.cfg.target_r = 2
        self.cfg.slippage_bps = 10
        self.cfg.buy_cost_bps = 15
        self.cfg.sell_cost_bps = 25
        result = self.simulate()
        trade = result['trades'][0]
        self.assertEqual((trade['signal_direction'], trade['direction']), ('short', 'long'))
        self.assertAlmostEqual(trade['entry'], 98 * 1.001)
        self.assertLess(trade['initial_stop'], trade['entry'])
        self.assertGreater(trade['target'], trade['entry'])
        self.assertAlmostEqual(trade['fees'], trade['quantity'] * (trade['entry'] * .0015 + trade['exit'] * .0025))
        self.assertAlmostEqual(result['metrics']['final_equity'], self.cfg.capital + trade['pnl'])
        checked = []
        def reject(symbol, day, clock):
            checked.append((symbol, day, clock))
            return False
        blocked = momentum.simulate(self.daily, self.cfg, self.minutes, self.plan, entry_check=reject)
        self.assertEqual(blocked['trades'], [])
        self.assertEqual(checked, [('A', '2025-02-03', '09:25')])

    def test_explicit_exclusions_are_local_and_unknown_symbols_fail(self):
        universe = {'instruments': [{'symbol': 'A'}, {'symbol': 'B'}]}
        datasets = {'A': [1], 'B': [2]}
        manifest = [{'symbol': 'A'}, {'symbol': 'B'}]
        self.cfg.exclude_symbols = ['B']
        _, kept, rows, excluded = momentum.exclude_inputs(universe, datasets, manifest, [], self.cfg)
        self.assertEqual(kept, {'A': [1]})
        self.assertEqual(rows, [{'symbol': 'A'}])
        self.assertEqual(excluded, ['B'])
        self.assertEqual(datasets, {'A': [1], 'B': [2]})
        self.cfg.exclude_symbols = ['TYPO']
        with self.assertRaisesRegex(ValueError, 'Unknown research exclusions'):
            momentum.exclude_inputs(universe, datasets, manifest, [], self.cfg)

    def test_2024_muhurat_is_not_regular_opening_volume_context(self):
        start = datetime(2024, 10, 1)
        rows = [dict(date=(start+timedelta(days=i)).date().isoformat(),
                     open=100, high=102, low=98, close=100, volume=10000) for i in range(61)]
        self.cfg.start = '2024-11-01'
        self.cfg.end = '2024-11-30'
        self.cfg.min_turnover = 0
        self.cfg.min_atr_pct = 0
        plan, requests = momentum.entry_plan({'A': rows}, self.cfg)
        self.assertNotIn('2024-11-01', plan)
        self.assertEqual(plan['2024-11-02'], [])
        self.assertTrue(plan['2024-11-16'])
        self.assertNotIn('2024-11-01', requests)

    def test_stock_session_exclusion_covers_volume_context_only_for_that_stock(self):
        start = datetime(2025, 1, 1)
        rows = [dict(date=(start+timedelta(days=i)).date().isoformat(),
                     open=100, high=102, low=98, close=100, volume=10000) for i in range(60)]
        self.cfg.start = '2025-02-03'
        self.cfg.end = '2025-02-28'
        self.cfg.min_turnover = self.cfg.min_atr_pct = 0
        self.cfg.exclude_stock_sessions = ['A:2025-02-03']
        plan, requests = momentum.entry_plan({'A': rows, 'B': rows}, self.cfg)
        self.assertEqual([c['symbol'] for c in plan['2025-02-03']], ['B'])
        self.assertEqual([c['symbol'] for c in plan['2025-02-04']], ['B'])
        self.assertEqual({c['symbol'] for c in plan['2025-02-18']}, {'A', 'B'})
        self.assertNotIn({'symbol': 'A'}, requests.get('2025-02-03', []))
        with self.assertRaisesRegex(ValueError, 'SYMBOL:YYYY-MM-DD'):
            momentum.MomentumConfig(start='2025-02-03', end='2025-02-04',
                                    exclude_stock_sessions=['A:bad-date'], acknowledge_limitations=True)

    def test_prospective_buy_check_blocks_long_fill_and_default_replay_stays_unchanged(self):
        self.assertTrue(self.simulate()['trades'])
        checked=[]
        def reject(symbol,day,clock):
            checked.append((symbol,day,clock))
            return False
        blocked=momentum.simulate(self.daily,self.cfg,self.minutes,self.plan,entry_check=reject)
        self.assertEqual(blocked['trades'],[])
        self.assertEqual(checked,[('A','2025-02-03','09:25')])

    def test_next_bar_entry_and_cutoff_has_no_future_prices(self):
        bars = self.minutes['A']['2025-02-03']
        bars[-1].update(open=105,high=200,low=1,close=1)
        t = self.simulate()['trades'][0]
        self.assertEqual((t['entry_time'],t['entry'],t['exit_time'],t['exit']),('09:25',102,'15:00',105))
        self.assertEqual(t['signal_time'],'09:20')
        self.assertEqual(t['pnl'],3*t['quantity'])
        # Opening-bar high alone cannot trigger an entry during the opening range.
        bars[1].update(close=100)
        for b in bars[2:]:
            b.update(close=100)
        self.assertEqual(self.simulate()['trades'],[])

    def test_indicator_rejects_breakout_until_completed_trend_aligns(self):
        from unittest.mock import patch
        self.cfg.indicator_filter='ema'
        denied=dict(minutes=10,timestamp=0,ema9=105,ema20=106,previous_ema9=105,
                    macd=-1,histogram=-.1,previous_histogram=-.1,close=102)
        allowed={**denied,'ema9':101,'ema20':100,'previous_ema9':100,'close':102}
        signals={j:denied if j<5 else allowed for j in range(70)}
        with patch.object(momentum.momentum_indicators,'features',return_value=signals):
            result=self.simulate()
        self.assertEqual(result['trades'][0]['entry_time'],'09:45')
        self.assertEqual(result['trades'][0]['signal_indicators'],allowed)
        self.assertGreater(result['diagnostics']['indicator_rejected_signals'],0)

    def test_short_stop_first_and_gap(self):
        bars=self.minutes['A']['2025-02-03']
        bars[0].update(close=99.5)
        bars[1].update(close=98,low=97)
        bars[2].update(open=98,high=101,low=93,close=98)
        self.cfg.target_r=2
        t=self.simulate()['trades'][0]
        self.assertEqual((t['direction'],t['exit']),('short',100))
        self.assertEqual(self.simulate()['metrics']['ambiguous_stop_target_bars'],1)
        bars[2].update(high=99,low=97)
        bars[3].update(open=105,high=106,low=104,close=105)
        self.assertEqual(self.simulate()['trades'][0]['exit'],105)

    def test_larger_confirmation_waits_for_session_aligned_close(self):
        bars=self.minutes['A']['2025-02-03']
        self.cfg.confirmation_minutes=10
        # A breakout at 09:25 is halfway through the 09:25–09:35 candle.
        bars[1].update(close=100)
        bars[2].update(close=102)
        bars[3].update(close=100)
        bars[4].update(close=102)
        bars[5].update(close=102)
        trade=self.simulate()['trades'][0]
        self.assertEqual((trade['signal_time'],trade['entry_time']),('09:40','09:45'))
        # A huge high/close on the future second constituent cannot enter early.
        bars[5].update(high=500,close=500)
        self.assertEqual(self.simulate()['trades'][0]['entry_time'],'09:45')

    def test_hourly_confirmation_and_five_minute_stops(self):
        self.cfg.confirmation_minutes=60
        bars=self.minutes['A']['2025-02-03']
        bars[12].update(open=102,low=99,high=103,close=102)
        trade=self.simulate()['trades'][0]
        self.assertEqual((trade['entry_time'],trade['exit_time'],trade['exit']),('10:15','10:15',100))
        # Hourly confirmation doesn't defer a protective stop to 11:15.
        with self.assertRaisesRegex(ValueError,'first completed confirmation'):
            momentum.MomentumConfig(start='2025-02-03',end='2025-02-04',confirmation_minutes=60,
                                    last_entry_time='10:00',acknowledge_limitations=True)

    def test_fee_accounting_and_reserved_capital(self):
        self.cfg.slippage_bps=10
        self.cfg.buy_cost_bps=15
        self.cfg.sell_cost_bps=20
        self.daily['B']=deepcopy(self.daily['A'])
        self.minutes['B']=deepcopy(self.minutes['A'])
        self.plan['2025-02-03'].append({**self.plan['2025-02-03'][0],'symbol':'B'})
        result=self.simulate()
        self.assertAlmostEqual(result['metrics']['final_equity'],self.cfg.capital+sum(t['pnl'] for t in result['trades']))
        self.assertLessEqual(sum(t['quantity']*t['entry']*(1+.0015) for t in result['trades']),self.cfg.capital)
        self.assertGreater(result['metrics']['modeled_fees'],0)
        self.assertEqual(result['metrics']['overnight_positions'],0)

    def test_missing_input_halts_and_late_entry_disallowed(self):
        bars=self.minutes['A']['2025-02-03']
        bars.pop()
        with self.assertRaisesRegex(ValueError,'Incomplete momentum inputs'):
            self.simulate()
        self.minutes['A']['2025-02-03']=session('2025-02-03')
        bars=self.minutes['A']['2025-02-03']
        bars[0].update(close=100.5,volume=200)
        next(b for b in bars if b['time']=='11:30').update(close=102,high=102)
        self.assertEqual(self.simulate()['trades'],[])

    def test_plan_ignores_entry_session_close_and_future_daily(self):
        rows=[]
        start=datetime(2024,11,1)
        for i in range(70):
            day=(start+timedelta(days=i)).date().isoformat()
            rows.append(dict(date=day,open=100,high=102,low=98,close=100,volume=10000))
        self.cfg.start=rows[60]['date'];self.cfg.end=rows[65]['date']
        self.cfg.min_turnover=0;self.cfg.min_atr_pct=0
        baseline=momentum.entry_plan({'A':rows},self.cfg)[0][str(self.cfg.start)]
        rows[60]['close']=1000000;rows[60]['volume']=99999999
        actual=momentum.entry_plan({'A':rows},self.cfg)[0][str(self.cfg.start)]
        self.assertEqual(baseline,actual)

    def test_chart_freezes_intraday_levels(self):
        t=self.simulate()['trades'][0]
        chart=momentum.trade_chart({'config':self.cfg.model_dump(mode='json')},t,self.minutes['A']['2025-02-03'])
        self.assertEqual(chart['bars'][0]['chart_values'],{})
        self.assertEqual(chart['bars'][2]['chart_values']['protective_stop'],100)
        self.assertEqual(chart['explanation']['signal']['timestamp'],t['signal_timestamp'])

    def test_vwap_filter_uses_only_signal_context(self):
        bars=self.minutes['A']['2025-02-03']
        bars[0].update(high=101,low=99,close=100.5,volume=100000)
        bars[1].update(high=102,low=101,close=102,volume=1)
        self.cfg.require_vwap=True
        self.cfg.min_relative_volume=0
        original=self.simulate()['trades'][0]
        bars[-1].update(high=99999,low=1,close=88888,volume=999999999)
        changed=self.simulate()['trades'][0]
        self.assertEqual(original['entry_timestamp'],changed['entry_timestamp'])
        self.assertEqual(original['signal_vwap'],changed['signal_vwap'])

    def test_breakout_buffer_can_block_marginal_entries(self):
        self.cfg.breakout_buffer_atr=.5
        self.assertEqual(self.simulate()['trades'],[])
        self.assertEqual(self.simulate()['diagnostics']['no_breakout'],1)

    def test_full_confirmation_range_rejects_retraced_breakouts_without_future_data(self):
        bars=self.minutes['A']['2025-02-03']
        self.cfg.confirmation_minutes=10
        self.cfg.min_close_strength=.7
        bars[0].update(high=110,low=99,close=100.5)
        # First post-range confirmation closes above 110, but retraced from 130.
        bars[1].update(open=100,high=130,low=100,close=111)
        for b in bars[2:]: b.update(open=100,high=101,low=99,close=100)
        self.assertEqual(self.simulate()['trades'],[])
        self.assertEqual(self.simulate()['diagnostics']['quality_rejected_signals'],1)
        q=momentum.confirmation_quality(bars,1,10,1,4)
        bars[-1].update(high=9999,low=1,close=9999)
        self.assertEqual(q,momentum.confirmation_quality(bars,1,10,1,4))

    def test_directional_body_and_short_close_strength(self):
        bars=self.minutes['A']['2025-02-03']
        bars[1].update(open=105,high=105,low=101,close=102)
        for b in bars[2:]: b.update(close=100)
        self.assertEqual(len(self.simulate()['trades']),1)
        self.cfg.min_confirmation_body_atr=.1
        self.assertEqual(self.simulate()['trades'],[])
        bars[0].update(open=100,high=101,low=99,close=99.5)
        bars[1].update(open=100,high=100,low=97,close=97.5)
        self.cfg.min_close_strength=.7
        trade=self.simulate()['trades'][0]
        self.assertEqual(trade['direction'],'short')
        self.assertAlmostEqual(trade['confirmation_quality']['close_strength'],2.5/3)
        self.assertGreater(trade['confirmation_quality']['body_atr'],.1)

    def test_vwap_rejects_wrong_side_confirmation(self):
        bars=self.minutes['A']['2025-02-03']
        bars[1].update(high=150,close=102,volume=1000000)
        for b in bars[2:]:
            b.update(close=100)
        self.assertEqual(len(self.simulate()['trades']),1)
        self.cfg.require_vwap=True
        result=self.simulate()
        self.assertEqual(result['trades'],[])
        self.assertEqual(result['diagnostics']['vwap_rejected_signals'],1)

    def test_breakeven_activates_next_bar_and_chart_follows_recorded_stop(self):
        self.cfg.breakeven_after_r=1
        bars=self.minutes['A']['2025-02-03']
        bars[2].update(high=105,low=101,close=104)
        bars[3].update(open=103,high=104,low=101,close=103)
        result=self.simulate();t=result['trades'][0]
        self.assertEqual(t['initial_stop'],100)
        self.assertEqual(t['exit'],102)
        self.assertEqual([x['stop'] for x in t['stop_trace']],[100,102])
        chart=momentum.trade_chart({'config':self.cfg.model_dump(mode='json')},t,bars)
        self.assertEqual(chart['bars'][2]['chart_values']['protective_stop'],100)
        self.assertEqual(chart['bars'][3]['chart_values']['protective_stop'],102)

    def test_diagnostics_reconcile_and_chronological_segments(self):
        result=self.simulate()
        d=result['diagnostics']
        self.assertAlmostEqual(d['long']['pnl']+d['short']['pnl'],sum(t['pnl'] for t in result['trades']))
        self.assertEqual(d['session_count'],1)
        result['curve'].append(dict(date='2025-02-04',equity=result['curve'][0]['equity']-100,drawdown_pct=1))
        evaluation=momentum.chronological_evaluation(result)
        self.assertEqual(len(evaluation['segments']),2)
        self.assertEqual(evaluation['segments'][1]['pnl'],0)


if __name__=='__main__':
    unittest.main()
