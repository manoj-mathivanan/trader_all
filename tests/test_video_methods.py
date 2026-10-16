import unittest
from core.research.video_methods import (
    aggregate_minutes, confirmed_pivots, fvg_setups, portfolio_replay,
    replay_limit, settlement, sma_cross_orders,
)


def bars(prices):
    return [dict(date='2026-07-01',time=f'{9+(15+j)//60:02d}:{(15+j)%60:02d}',
                 timestamp=j*60000,open=p,close=p,high=p+.2,low=p-.2,volume=10000)
            for j,p in enumerate(prices)]


class VideoMethodsTest(unittest.TestCase):
    def test_pivot_confirmation_requires_right_wing(self):
        rows=bars([1,2,5,3,2,4])
        self.assertNotIn(2,confirmed_pivots(rows))
        self.assertEqual(confirmed_pivots(rows)[4]['high'],5.2)
        self.assertEqual(confirmed_pivots(rows[:4]),{})

    def test_aggregate_drops_incomplete_and_rejects_gaps(self):
        rows=bars([10]*31)
        result=aggregate_minutes(rows,15)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['available_at'],900000)
        rows[7]['timestamp']+=60000
        with self.assertRaises(ValueError):aggregate_minutes(rows,15)

    def test_no_formation_fill_and_buy_limit_never_worsens(self):
        rows=bars([100]*6)
        rows[0]['low']=90
        setup=dict(signal_index=0,entry=100,stop=99,expires=3,volume=10000)
        trade=replay_limit(setup,rows,hold_minutes=1)
        self.assertEqual(trade['entry_index'],1)
        self.assertEqual(settlement(trade,10,10)['entry'],100)

    def test_touch_does_not_fill_and_stop_wins_ambiguity(self):
        rows=bars([100]*6)
        setup=dict(signal_index=0,entry=100,stop=99,expires=3,volume=10000)
        for b in rows:b['low']=100
        self.assertIsNone(replay_limit(setup,rows))
        rows[1].update(low=98,high=105)
        trade=replay_limit(setup,rows)
        self.assertEqual(trade['reason'],'stop')
        self.assertTrue(trade['ambiguity'])

    def test_next_session_sma_orders_are_causal(self):
        rows=[dict(close=x) for x in [10,9,8,7,10,12,15,8,5,4]]
        orders=sma_cross_orders(rows,2,4)
        self.assertEqual(orders[6],'buy')
        self.assertEqual(orders[9],'sell')
        for size in range(5,len(rows)):
            prefix=sma_cross_orders(rows[:size],2,4)
            self.assertEqual(prefix,{k:v for k,v in orders.items() if k<size})

    def test_time_exit_does_not_use_later_candle_low(self):
        rows=bars([100]*6)
        rows[2].update(open=101,close=98,low=97,high=105)
        setup=dict(signal_index=0,entry=100,stop=99,expires=3,volume=10000)
        trade=replay_limit(setup,rows,hold_minutes=1)
        self.assertEqual((trade['reason'],trade['exit_raw']),('time',101))

    def test_stop_gap_and_cash_unavailable_until_exit_completed(self):
        rows=bars([100,100,98,98])
        trade=replay_limit(dict(signal_index=0,entry=100,stop=99,expires=3,volume=10000),rows)
        self.assertEqual(trade['exit_raw'],98)
        trade.update(symbol='AAA')
        # All other symbols compete for the same capital, independent of winners.
        competing=[dict(trade,symbol=s) for s in ('AAA','BBB','CCC','DDD')]
        ledger=portfolio_replay(competing,cash=10000)
        self.assertLessEqual(len(ledger),3)
        self.assertTrue(all(t['net_pnl']<0 for t in ledger))

    def test_portfolio_cash_cap_and_matched_cost_stress(self):
        base=dict(date='2026-07-01',entry_at=100000,exit_at=300000,entry=100,
                  exit_raw=103,market_exit=True,stop=99,volume=100000,reason='time',ambiguity=False)
        candidates=[dict(base,symbol=s) for s in ['AAA','BBB','CCC','DDD']]
        ledger=portfolio_replay(candidates,cash=100000)
        self.assertEqual(len(ledger),3)
        self.assertLessEqual(sum(t['entry']*t['quantity'] for t in ledger),100000)
        stressed=[settlement(t,t['quantity'],5,1.5) for t in ledger]
        self.assertEqual([t['quantity'] for t in ledger],[t['quantity'] for t in stressed])
        self.assertLess(sum(t['net_pnl'] for t in stressed),sum(t['net_pnl'] for t in ledger))

    def test_cost_guard_uses_planned_stop_not_future_profit(self):
        narrow=dict(date='2026-07-01',symbol='AAA',entry_at=100000,exit_at=300000,
                    entry=100,exit_raw=103,market_exit=True,stop=99.95,volume=100000,
                    reason='time',ambiguity=False)
        self.assertEqual(portfolio_replay([narrow],max_friction_r=.25),[])
        wide=dict(narrow,stop=99)
        self.assertEqual(len(portfolio_replay([wide],max_friction_r=.25)),1)
        self.assertEqual(len(portfolio_replay([dict(wide,exit_raw=90)],max_friction_r=.25)),1)

    def test_short_gap_execution_and_ledger_use_actual_fee_sides(self):
        from core.execution.zerodha import equity_charges
        rows=bars([100,100,102,102])
        setup=dict(signal_index=0,entry=100,stop=101,expires=3,volume=10000,direction=-1)
        trade=replay_limit(setup,rows)
        self.assertEqual(trade['exit_raw'],102)
        trade['symbol']='AAA'
        position=portfolio_replay([trade])[0]
        self.assertLess(position['net_pnl'],0)
        q=position['quantity']
        expected=equity_charges(100,q,'sell',trade['date'],intraday=True)['total']
        expected+=equity_charges(position['exit'],q,'buy',trade['date'],intraday=True)['total']
        self.assertAlmostEqual(position['fees'],expected)

    def test_fvg_results_do_not_change_with_future_prices(self):
        wave=[0,.2,.4,.2,0,-.2,-.4,-.2]
        history=[bars([100+(day*25+j//15)*.005+wave[(day*25+j//15)%8]
                       for j in range(375)]) for day in range(3)]
        for day,session in enumerate(history):
            for b in session:
                b['date']=f'2026-06-{25+day}'
                b['timestamp']-=(3-day)*86400000
        current=bars([102]*375)
        for b in current:b.update(high=b['close']+.02,low=b['close']-.02)
        prices=[102,102.2,102.4,102.2,102,101.8,102,102.1,101.9,101.7,101.5,101.7,102.3]
        for j,p in enumerate(prices,30):
            current[j].update(open=p-.01,close=p,high=p+.02,low=p-.02)
        current[42]['open']=102.29
        self.assertTrue(all(b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'] for b in current))
        all_setups=fvg_setups(current,history)
        self.assertTrue(all_setups, 'Causality fixture must exercise an actual FVG signal.')
        for size in (45,90,180,300):
            self.assertEqual(fvg_setups(current[:size],history),[s for s in all_setups if s['signal_index']<size])
        def reflect(session):
            return [dict(b,open=204-b['open'],close=204-b['close'],high=204-b['low'],low=204-b['high']) for b in session]
        bearish=reflect(current);prior=[reflect(s) for s in history]
        shorts=fvg_setups(bearish,prior,direction=-1)
        self.assertTrue(shorts)
        self.assertTrue(all(s['stop']>s['entry'] for s in shorts))
        for size in (45,90,180,300):
            self.assertEqual(fvg_setups(bearish[:size],prior,-1),[s for s in shorts if s['signal_index']<size])


if __name__=='__main__':unittest.main()
