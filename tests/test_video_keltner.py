import unittest
from copy import deepcopy
from core.execution.upstox import equity_charges
from core.research.video_methods import aggregate_minutes,portfolio_replay
from core.research.video_keltner import indicators,setups,replay,settle
from tests.test_video_methods import bars


def fixture():
    history=[bars([100]*375) for _ in range(3)]
    for day,session in enumerate(history):
        for b in session:
            b['date']=f'2026-06-{25+day}';b['timestamp']-=(3-day)*86400000
            b.update(high=100.02,low=99.98)
    current=bars([100]*375)
    for b in current:b.update(high=100.02,low=99.98)
    for b in current[60:]:b.update(open=100.4,close=100.4,high=100.42,low=100.38)
    current[60]['open']=100;current[60]['low']=99.98
    for b in current[60:63]:b['volume']=50000
    return current,history


class KeltnerTest(unittest.TestCase):
    def test_indicator_known_values_and_signal_volume_exclusion(self):
        rows=aggregate_minutes(bars(list(range(100,160))),3)
        values=indicators(rows)
        self.assertAlmostEqual(values[14]['cmo'],100)
        rows=aggregate_minutes(bars([100]*66),3)
        rows[20]['volume']=90000
        self.assertEqual(indicators(rows)[20]['rvol'],3)
        rows[21]['volume']=1e9
        self.assertEqual(indicators(rows)[20]['rvol'],3)

    def test_nonempty_setup_and_prefix_causality_both_directions(self):
        current,history=fixture()
        def reflect(session):
            return [dict(b,open=200-b['open'],high=200-b['low'],low=200-b['high'],close=200-b['close']) for b in session]
        for direction in (1,-1):
            source=current if direction==1 else reflect(current)
            prior=history if direction==1 else [reflect(s) for s in history]
            full,series=setups(source,prior,direction)
            self.assertTrue(full)
            for n in (60,62,63,90,180,300):
                partial,_=setups(source[:n],prior,direction)
                self.assertEqual(partial,[s for s in full if s['signal_index']<n])
            self.assertEqual(full[0]['signal_index'],62)
            self.assertEqual(full[0]['available_at'],current[62]['timestamp']+60000)

    def test_market_entry_and_stop_first_on_ambiguous_candle(self):
        current,history=fixture();signals,series=setups(current,history);s=signals[0]
        current[63].update(low=99,high=103)
        t=replay(s,current,series,scaled=True)
        self.assertEqual(t['entry_index'],63)
        self.assertAlmostEqual(t['entry'],current[63]['open']*1.0002)
        self.assertEqual(t['reason'],'stop');self.assertEqual(len(t['exit_legs']),1)

    def test_partial_trailing_stop_uses_only_completed_candles(self):
        current,history=fixture();signals,series=setups(current,history);s=signals[0]
        entry=current[63]['open']*1.0002;target=entry+(entry-s['stop'])
        current[63]['high']=target+.1
        # The63-65 frame closes at66. Its new basis must not affect64/65.
        modified=deepcopy(series)
        modified[21]['basis']=entry-.01
        current[64]['low']=entry-.02
        current[65]['low']=entry-.02
        current[66]['low']=entry-.03
        t=replay(s,current,modified,scaled=True)
        self.assertEqual(t['exit_index'],66)
        self.assertEqual(len(t['exit_legs']),2)
        self.assertEqual(t['reason'],'trail')
        changed=deepcopy(modified)
        for v in changed[22:]:v['basis']=10000
        self.assertEqual(replay(s,current,changed,scaled=True),t)

    def test_partial_fees_odd_quantity_short_sides_and_cash_reconciliation(self):
        t=dict(date='2026-07-01',entry_at=100000,exit_at=300000,symbol='AAA',entry=100,stop=101,
               exit_raw=98.5,market_exit=True,direction=-1,volume=100000,reason='trail',ambiguity=False,
               exit_legs=[dict(raw=99,market=False,index=1),dict(raw=98,market=True,index=2)])
        v=settle(t,5)
        prices=(99,98*1.0002)
        expected=equity_charges(100,5,'sell',t['date'],intraday=True)['total']
        expected+=sum(equity_charges(p,q,'buy',t['date'],intraday=True)['total'] for p,q in zip(prices,(2,3)))
        self.assertAlmostEqual(v['fees'],expected)
        self.assertAlmostEqual(v['exit_raw'],98.4)
        self.assertAlmostEqual(v['net_pnl'],500-(prices[0]*2+prices[1]*3)-expected)
        ledger=portfolio_replay([t],settle=settle,planned_exit_parts=2)
        self.assertEqual(len(ledger),1)
        stressed=settle(ledger[0],ledger[0]['quantity'],5,1.5)
        self.assertLess(stressed['net_pnl'],ledger[0]['net_pnl'])

    def test_cost_guard_counts_market_entry_friction(self):
        t=dict(date='2026-07-01',entry_at=100000,exit_at=300000,symbol='AAA',entry=100,stop=98.5,
               exit_raw=102,market_exit=False,volume=100000,reason='target',ambiguity=False,
               exit_legs=[dict(raw=102,market=False,index=1)])
        self.assertEqual(len(portfolio_replay([t],max_friction_r=.25,settle=settle)),1)
        self.assertEqual(portfolio_replay([dict(t,entry_raw=99.5)],max_friction_r=.25,settle=settle),[])


if __name__=='__main__':unittest.main()
