import unittest
from datetime import datetime,timezone,timedelta
try:
    import numpy as np
except ImportError:
    np=None

from core.strategies.four_indicator_intraday import completed_trend,pullback_signals
from core.execution.upstox import equity_charges
from scripts.research_four_indicator_5m import simulate


@unittest.skipIf(np is None,'Optional NumPy research runtime unavailable')
class EntryVariantTests(unittest.TestCase):
    def test_15m_close_is_not_available_early(self):
        rows=np.array([[i*300000,100,102,99,101,10] for i in range(75)],dtype=float)
        def evaluate(aggregate,multiplier):
            self.assertEqual(len(aggregate),25)
            self.assertEqual(aggregate[0,5],30)
            return np.zeros(25),np.full(25,100),np.ones(25,dtype=bool),np.zeros(25)
        result=completed_trend(rows,evaluate)
        self.assertFalse(result[0]);self.assertFalse(result[1]);self.assertTrue(result[2])

    def test_partial_15m_future_cannot_change_earlier_signals(self):
        rows=np.array([[i*300000,100,102,99,101,10] for i in range(150)],dtype=float)
        def evaluate(a,m):
            up=a[:,4]>100
            return np.zeros(len(a)),np.full(len(a),100),up,np.zeros(len(a))
        first=completed_trend(rows,evaluate)
        rows[5,4]=90
        second=completed_trend(rows,evaluate)
        np.testing.assert_array_equal(first[:5],second[:5])
        self.assertNotEqual(first[5],second[5])

    def pullback_fixture(self):
        rows=np.array([[i*300000,100,102,101,101,100] for i in range(150)],dtype=float)
        base=np.zeros(150,dtype=bool);base[20]=True
        rows[21]=[21*300000,101,102,100,101,100]
        rows[22]=[22*300000,101,104,101,103,100]
        return rows,base,np.full(150,70.),np.full(150,98.),np.ones(150,dtype=bool),np.full(150,99.)

    def test_setup_touch_and_later_resumption_are_distinct(self):
        args=self.pullback_fixture()
        result=pullback_signals(*args)
        self.assertFalse(result[20]);self.assertFalse(result[21]);self.assertTrue(result[22])
        self.assertEqual(np.flatnonzero(result).tolist(),[22])

    def test_setup_expires_and_does_not_cross_session(self):
        args=list(self.pullback_fixture());args[0][22,4]=101
        args[0][28]=[28*300000,101,104,101,103,100]
        self.assertFalse(pullback_signals(*args).any())
        args=list(self.pullback_fixture());args[1][:]=False;args[1][74]=True
        args[0][75]=[75*300000,101,102,100,101,100]
        args[0][76]=[76*300000,101,104,101,103,100]
        self.assertFalse(pullback_signals(*args).any())

    def test_daily_cap_resets_and_shared_fees_classify_overnight(self):
        zone=timezone(timedelta(hours=5,minutes=30))
        def stamp(day,time):return int(datetime.fromisoformat(day+'T'+time).replace(tzinfo=zone).timestamp()*1000)
        stamps=np.array([stamp('2026-01-02',t) for t in ('09:15','09:20','09:25','09:30')]+[stamp('2026-01-05',t) for t in ('09:15','09:20')])
        openings=np.full((6,1),100.)
        entries=np.array([[1],[0],[1],[0],[1],[0]],dtype=bool)
        exits=np.array([[0],[1],[0],[1],[0],[0]],dtype=bool)
        cfg=dict(capital=10000,max_positions=1,slippage_bps=0,one_entry_per_day=True)
        result=simulate(openings,openings,entries,exits,openings,stamps,['A'],cfg)
        self.assertEqual(len(result['trades']),2)
        self.assertEqual(result['trades'][1]['entry_timestamp'],int(stamps[4]))
        self.assertEqual(result['metrics']['daily_entry_limit_skips'],1)
        first=result['trades'][0]
        expected=sum(equity_charges(100,first['quantity'],side,'2026-01-02',intraday=True)['total'] for side in ('buy','sell'))
        self.assertAlmostEqual(first['fees'],expected)
        # Hold one position across the observed session boundary.
        entries[:]=False;entries[0]=True;exits[:]=False;exits[4]=True
        overnight=simulate(openings,openings,entries,exits,openings,stamps,['A'],cfg)['trades'][0]
        expected=equity_charges(100,overnight['quantity'],'buy','2026-01-02')['total']
        expected+=equity_charges(100,overnight['quantity'],'sell','2026-01-05')['total']
        self.assertAlmostEqual(overnight['fees'],expected)


if __name__=='__main__':unittest.main()
