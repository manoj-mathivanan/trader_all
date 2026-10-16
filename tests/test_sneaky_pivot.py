from datetime import datetime, timedelta

import unittest

from core.research import intraday_data
from core.research.sneaky_pivot import (
    OpeningPivotRules, earlier_session_support, level_long_setups,
    opening_long_setup, replay_long_setup,
    reprice_diagnostic_trade,
)


def session(day, rows):
    start = datetime.fromisoformat(day+'T09:15:00').replace(tzinfo=intraday_data.IST)
    return [dict(date=day, time=(start+timedelta(minutes=5*i)).strftime('%H:%M'),
                 timestamp=int((start+timedelta(minutes=5*i)).timestamp()*1000),
                 open=o, high=h, low=l, close=c, volume=1000)
            for i,(o,h,l,c) in enumerate(rows)]


def inputs():
    prior = session('2026-10-08', [(103,110,100,104)]*75)
    current = session('2026-10-09', [
        (104,104.5,102,102.5), (102.5,103,100,101), (101,101.5,100.2,100.4),
        (100.4,101,100.1,100.7), (100.7,102,100.2,101.5), (101.5,103,101.2,102.8),
    ])
    return prior,current


class OpeningPivotTests(unittest.TestCase):
    def test_known_only_when_confirmation_finishes(self):
        prior,current=inputs()
        self.assertEqual(opening_long_setup(prior,current[:5],10),(None,'confirmation_unfinished'))
        setup,reason=opening_long_setup(prior,current,10)
        self.assertEqual(reason,'setup_ready')
        self.assertEqual(datetime.fromtimestamp(setup['available_at']/1000,intraday_data.IST).strftime('%H:%M'),'09:45')
        self.assertEqual(setup['confirmation_high'],103)
        self.assertEqual(setup['stop_reference_low'],100)
        self.assertEqual(setup['target_level'],110)


    def test_future_bars_cannot_change_setup(self):
        prior,current=inputs()
        future=session('2026-10-09',[(104,104.5,102,102.5)]*7)[6:]
        future[0].update(open=500,high=1000,low=1,close=2)
        self.assertEqual(opening_long_setup(prior,current,10),opening_long_setup(prior,current+future,10))


    def test_missing_opening_bar_is_not_compressed(self):
        prior,current=inputs()
        later=session('2026-10-09',[(104,104.5,102,102.5)]*7)[6:]
        with self.assertRaisesRegex(ValueError,'contiguous'):
            opening_long_setup(prior,current[:2]+current[3:]+later,10)


    def test_prior_session_requires_full_coverage(self):
        prior,current=inputs()
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            opening_long_setup(prior[:-1],current,10)

    def test_stop_reference_stays_below_support_when_wicks_stop_short(self):
        prior,current=inputs()
        near=[dict(b) for b in current]
        for b in near: b['low']=max(b['low'],100.1)
        setup,reason=opening_long_setup(prior,near,10)
        self.assertEqual(reason,'setup_ready')
        self.assertEqual(setup['stop_reference_low'],100)


    def test_repeated_support_and_reclaim_are_required(self):
        prior,current=inputs()
        away=[dict(b) for b in current]
        for b in away[3:]: b['low']=max(b['low'],101)
        self.assertEqual(opening_long_setup(prior,away,10)[1],'confirmation_low_away_from_support')
        red=[dict(b) for b in current]
        red[5]['close']=100.3
        self.assertEqual(opening_long_setup(prior,red,10)[1],'confirmation_not_bullish')


    def test_invalid_atr_or_session_order_fail(self):
        prior,current=inputs()
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): opening_long_setup(prior,current,value)
        with self.assertRaisesRegex(ValueError,'precede'):
            opening_long_setup(current,prior,10)
        with self.assertRaises(ValueError): OpeningPivotRules(level_tolerance_atr=0)


    def test_special_session_excluded(self):
        prior,current=inputs()
        special=[dict(b,date='2025-10-21') for b in prior]
        self.assertEqual(opening_long_setup(special,current,10),(None,'special_session'))


class ExtendedPivotTests(unittest.TestCase):
    def test_historical_proxy_is_recent_and_never_future(self):
        rows=[dict(date='2026-10-06',low=98),dict(date='2026-10-07',low=99),
              dict(date='2026-10-08',low=100)]
        level=earlier_session_support(rows,100,prior_day='2026-10-08')
        self.assertEqual((level['price'],level['source_date']),(99,'2026-10-07'))
        with self.assertRaises(ValueError):
            earlier_session_support(rows+[dict(date='2026-10-09',low=97)],100,prior_day='2026-10-08')

    def test_third_confirmation_needs_all_nine_constituents(self):
        prior,current=inputs()
        for b in current[3:]:
            b.update(open=100.8,high=101,low=100.1,close=100.5)
        third=session('2026-10-09',[(100.5,102,100.1,101.8)]*9)[6:9]
        self.assertEqual(level_long_setups(prior,current+third[:2],10)[0],[])
        setups,_=level_long_setups(prior,current+third,10)
        self.assertEqual(len(setups),1)
        self.assertEqual(setups[0]['entry_window_start'],'10:00')
        self.assertEqual(setups[0]['entry_window_end_exclusive'],'10:15')
        self.assertEqual(setups[0]['confirmation_candle'],3)
        self.assertEqual(level_long_setups(prior,current+third,10,max_confirmation_candle=2)[0],[])

    def test_failed_support_does_not_rearm_lower(self):
        prior,current=inputs()
        current[3]['low']=99.5
        third=session('2026-10-09',[(100.5,102,100.1,101.8)]*9)[6:9]
        self.assertEqual(level_long_setups(prior,current+third,10)[0],[])

    def test_extra_level_has_distinct_provenance(self):
        prior,current=inputs()
        shifted=[dict(b,**{k:b[k]-2 for k in ('open','high','low','close')}) for b in current]
        self.assertEqual(level_long_setups(prior,shifted,10)[0],[])
        level=dict(price=98,source_date='2026-10-07',kind='earlier_session_low_proxy')
        setups,_=level_long_setups(prior,shifted,10,extra_support=level)
        self.assertEqual(setups[0]['support_source_date'],'2026-10-07')
        with self.assertRaises(ValueError):
            level_long_setups(prior,shifted,10,extra_support=dict(level,source_date='2026-10-09'))


class ReplayTests(unittest.TestCase):
    def fixture(self):
        prior,opening=inputs()
        bars=session('2026-10-09',[(103.5,104,102,103.5)]*75)
        bars[:6]=opening
        for b in bars: b['volume']=100000
        bars[6].update(open=102.8,high=104,low=102,close=103.5)
        bars[7].update(open=103.5,high=111,low=103,close=110)
        setup,_=opening_long_setup(prior,bars,10)
        return setup,bars

    def test_fees_adverse_slippage_and_risk_sizing(self):
        setup,bars=self.fixture()
        trade,reason=replay_long_setup(setup,bars)
        self.assertEqual(reason,'diagnostic_trade')
        self.assertEqual(trade['entry_time'],'09:45')
        self.assertEqual(trade['exit_reason'],'target')
        self.assertGreater(trade['fees'],0)
        self.assertGreater(trade['raw_slippage'],0)
        self.assertLessEqual(trade['modeled_stop_loss'],1000)
        self.assertLessEqual(trade['quantity'],1000)
        self.assertAlmostEqual(trade['net_pnl'],(trade['exit']-trade['entry'])*trade['quantity']-trade['fees'])

    def test_same_bar_ambiguity_is_counted_and_stop_first(self):
        setup,bars=self.fixture()
        bars[6].update(high=111,low=99)
        trade,_=replay_long_setup(setup,bars)
        self.assertEqual(trade['exit_reason'],'stop')
        self.assertTrue(trade['ambiguous_entry'])
        self.assertTrue(trade['ambiguous_exit'])
        self.assertLess(trade['net_pnl'],0)

    def test_later_stop_gap_uses_actual_open(self):
        setup,bars=self.fixture()
        bars[7].update(open=95,high=96,low=94,close=95)
        trade,_=replay_long_setup(setup,bars)
        self.assertEqual(trade['exit_reason'],'stop')
        self.assertAlmostEqual(trade['exit'],95*(1-2/10000))
        self.assertGreater(-trade['net_pnl'],1000)  # Gaps can exceed the risk budget.

    def test_expiry_and_pre_entry_invalidation(self):
        setup,bars=self.fixture()
        for b in bars[6:9]: b.update(open=102,high=103,low=101,close=102)
        self.assertEqual(replay_long_setup(setup,bars),(None,'entry_window_expired'))
        bars[6]['low']=99
        self.assertEqual(replay_long_setup(setup,bars),(None,'support_failed_before_cross'))

    def test_cutoff_uses_open_without_future_high_low(self):
        setup,bars=self.fixture()
        for b in bars[7:]: b.update(open=104,high=105,low=102,close=104)
        trade,_=replay_long_setup(setup,bars)
        self.assertEqual(trade['exit_reason'],'cutoff_open')
        bars[69].update(high=1000,low=1,close=500)
        self.assertEqual(replay_long_setup(setup,bars)[0],trade)

    def test_target_consumed_by_opening_gap_cancels(self):
        setup,bars=self.fixture()
        bars[6].update(open=111,high=112,low=110,close=111)
        self.assertEqual(replay_long_setup(setup,bars),(None,'gap_consumed_target'))

    def test_cost_stress_preserves_sample_and_deteriorates_same_trade(self):
        setup,bars=self.fixture()
        trade,_=replay_long_setup(setup,bars)
        same=reprice_diagnostic_trade(trade,slippage_bps=2)
        self.assertEqual(same,trade)
        stressed=reprice_diagnostic_trade(trade,slippage_bps=10,fee_multiplier=1.5)
        for key in ('date','entry_time','exit_time','quantity','raw_entry','raw_exit','initial_price_risk'):
            self.assertEqual(stressed[key],trade[key])
        self.assertLess(stressed['net_pnl'],trade['net_pnl'])
        self.assertGreater(stressed['modeled_stop_loss'],trade['modeled_stop_loss'])
