import unittest
from datetime import date, timedelta
from unittest.mock import patch
from core.research.backtest import simulate
from core.research.config import BacktestConfig


class StrengthPriorityTests(unittest.TestCase):
    def test_stronger_completed_signal_wins_slot_and_future_price_does_not_rank(self):
        datasets={}
        for symbol, growth in [('A',.1),('Z',1)]:
            rows=[]
            for i in range(128):
                price=100+growth*i
                if i==127 and symbol=='A':
                    price=1000 # Entry-day future close cannot lift A's ranking.
                rows.append(dict(date=(date(2024,1,1)+timedelta(days=i)).isoformat(),
                                 open=100,high=max(price,101),low=99,close=price,volume=10000))
            datasets[symbol]=rows
        cfg=BacktestConfig(pattern='vcp',start='2024-05-07',end='2024-05-08',
                           acknowledge_limitations=True,max_positions=1,entry_mode='next_open',
                           candidate_rank='rs_126',min_rs_rating=70)
        with patch('core.research.backtest.signal',return_value=True):
            result=simulate(datasets,cfg)
        self.assertEqual([t['symbol'] for t in result['trades']],['Z'])

if __name__=='__main__':
    unittest.main()
