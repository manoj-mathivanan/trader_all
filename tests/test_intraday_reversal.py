import unittest
from pydantic import ValidationError
from core.research.intraday_target import simulate
from core.research.intraday_runs import TargetRequest
from tests.test_intraday_target import session


class ReversalTests(unittest.TestCase):
    day='2024-11-04'

    def run_case(self, changes, **config):
        return simulate({self.day:session(self.day,changes)},[self.day],entry_time='09:17',
                        target_pct=.2,stop_loss_enabled=True,stop_loss_pct=.5,
                        stop_loss_delay_minutes=10,reverse_once_on_stop=True,**config)

    def test_one_opposite_trade_doubles_target_and_uses_remaining_capital(self):
        r=self.run_case({'09:27':[100,100,99.4,100], '09:28':[100,100,100,100],
                         '09:29':[100,100,99.5,100]})
        first,second=r['trades']
        self.assertEqual(first['exit_time'],'09:27')
        self.assertEqual(second['entry_time'],'09:28')
        self.assertEqual(second['direction'],'short')
        self.assertEqual(second['target_pct'],.4)
        self.assertEqual(second['target_price'],99.6)
        self.assertAlmostEqual(second['stop_price'],100.5)
        self.assertEqual(second['stop_active_from'],'09:38')
        self.assertEqual(second['opening_capital'],first['closing_capital'])
        self.assertEqual(second['quantity'],int(first['closing_capital']*5//100))
        self.assertEqual(r['trade_count'],2)
        self.assertEqual(r['reversal_count'],1)
        # Winning the 0.4% reversal cannot erase the first 0.5% loss plus charges.
        self.assertEqual(second['outcome'],'success')
        self.assertEqual(r['success_days'],0)
        self.assertEqual(r['failure_days'],1)
        self.assertLess(r['days'][0]['net_pnl'],0)
        self.assertAlmostEqual(r['final_capital'],500000+sum(t['net_pnl'] for t in r['trades']))
        self.assertAlmostEqual(r['total_charges'],sum(t['charges'] for t in r['trades']))
        self.assertEqual(r['curve'][-1]['equity'],second['closing_capital'])

    def test_a_second_stop_does_not_create_a_third_trade(self):
        r=self.run_case({'09:27':[100,100,99.4,100],'09:38':[100,100.6,100,100]})
        self.assertEqual(len(r['trades']),2)
        self.assertEqual(r['stop_loss_exits'],2)
        self.assertEqual(r['stop_loss_days'],1)
        self.assertEqual(r['trades'][1]['exit_reason'],'Stop loss')

    def test_no_reversal_after_target_or_session_exit(self):
        for changes in ({'09:18':[100,100.3,100,100]},{}):
            with self.subTest(changes=changes):
                r=self.run_case(changes)
                self.assertEqual(len(r['trades']),1)
                self.assertEqual(r['reversal_count'],0)

    def test_reverse_of_short_is_buy_and_does_not_reuse_stop_minute(self):
        r=self.run_case({'09:27':[100,101,99,100],'09:28':[100,100,100,100],
                         '09:29':[100,100.5,100,100]},direction='short')
        self.assertEqual(r['trades'][1]['direction'],'long')
        self.assertEqual(r['trades'][1]['entry_time'],'09:28')
        self.assertEqual(r['trades'][1]['target_price'],100.4)

    def test_no_entry_at_cutoff_and_late_buffer_never_extends_session(self):
        r=self.run_case({'15:14':[100,100,99.4,100]})
        self.assertEqual(len(r['trades']),1)
        self.assertEqual(r['reversal_skipped_days'],1)
        r=self.run_case({'15:10':[100,100,99.4,100]})
        second=r['trades'][1]
        self.assertEqual(second['entry_time'],'15:11')
        self.assertEqual(second['stop_active_from'],'15:21')
        self.assertEqual(second['exit_time'],'15:15')

    def test_api_requires_stop_and_valid_doubled_target(self):
        for config in ({'target_pct':.2}, {'target_pct':50,'stop_loss_enabled':True}):
            with self.assertRaises(ValidationError):
                TargetRequest(stock='HDFCBANK',reverse_once_on_stop=True,**config)


if __name__=='__main__':
    unittest.main()
