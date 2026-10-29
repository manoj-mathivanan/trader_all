import unittest
try:
    import numpy as np
except ImportError:
    np = None

from core.strategies.four_indicator import indicators
from scripts.research_four_indicator_5m import fast_values, simulate


@unittest.skipIf(np is None, 'Optional NumPy research runtime unavailable')
class FiveMinuteResearchTests(unittest.TestCase):
    def test_future_prices_cannot_change_completed_indicators(self):
        rows=np.array([[i*300000,100+i%9,102+i%9,99+i%9,101+i%9,1000] for i in range(200)])
        original=fast_values(rows,2.5)
        changed=rows.copy()
        changed[100:,1:5]*=2
        future=fast_values(changed,2.5)
        for a,b in zip(original,future):
            np.testing.assert_allclose(a[:100],b[:100],equal_nan=True)

    def test_fast_indicators_match_shared_rules(self):
        rng = np.random.default_rng(301)
        close = 100+np.cumsum(rng.normal(0,.8,2000))
        rows = np.array([[i*300000,c,c+1,c-1,c,1000] for i,c in enumerate(close)])
        bars = [dict(open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in rows]
        expected = indicators(bars,bollinger_multiplier=2.5)
        rsi, st, up, band = fast_values(rows,2.5)
        for i,value in enumerate(expected):
            self.assertEqual(bool(up[i]),value['uptrend'])
            for actual,key in ((rsi[i],'rsi'),(st[i],'supertrend'),(band[i],'upper_band')):
                if value[key] is None: self.assertTrue(np.isnan(actual))
                else: self.assertAlmostEqual(actual,value[key],places=10)
            if i>=20:
                self.assertEqual(bool(up[i] and close[i]>st[i] and rsi[i]>65 and close[i]>band[i]),
                    value['uptrend'] and close[i]>value['supertrend'] and value['rsi']>65 and close[i]>value['upper_band'])

    def test_sizing_costs_rank_and_next_open_exit(self):
        o=np.array([[100.,100.],[101.,110.],[102.,120.]])
        c=o+1
        entries=np.array([[True,True],[True,True],[False,False]])
        exits=np.array([[False,False],[False,True],[False,False]])
        cfg=dict(capital=10000,max_positions=1,slippage_bps=10,buy_cost_bps=10,sell_cost_bps=10)
        result=simulate(o,c,entries,exits,np.array([[1.,2.],[1.,2.],[1.,2.]]),np.array([1,2,3]),['A','B'],cfg)
        first=result['trades'][0]
        self.assertEqual(first['symbol'],'B')
        self.assertEqual(first['entry_timestamp'],1)
        self.assertEqual(first['exit_timestamp'],2)
        self.assertAlmostEqual(first['entry'],100.1)
        self.assertAlmostEqual(first['exit'],109.89)
        self.assertEqual(result['trades'][1]['symbol'],'A')
        self.assertEqual(result['trades'][1]['entry_timestamp'],2)
        self.assertAlmostEqual(result['metrics']['final_equity'],10000+sum(t['pnl'] for t in result['trades']))


if __name__ == '__main__':
    unittest.main()
