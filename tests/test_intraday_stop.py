import unittest
from pydantic import ValidationError
from core.research.intraday_target import simulate, stop_activation
from core.research.intraday_runs import TargetRequest
from tests.test_intraday_target import session


class DelayedStopTests(unittest.TestCase):
    day='2024-11-04'

    def run_trade(self, changes, direction='long', **config):
        return simulate({self.day:session(self.day,changes)},[self.day],direction=direction,
                        target_pct=.5,stop_loss_enabled=True,stop_loss_pct=.2,
                        stop_loss_delay_minutes=config.pop('delay',10),**config)

    def test_adverse_price_before_activation_is_ignored(self):
        for side,early,target in [('long',[100,100,98,100],[100,101,100,100]),
                                  ('short',[100,102,100,100],[100,100,99,100])]:
            with self.subTest(side=side):
                result=self.run_trade({'09:31':early,'09:45':target},side)
                self.assertEqual(result['days'][0]['exit_reason'],'Target reached')
                self.assertEqual(result['days'][0]['exit_time'],'09:45')
                self.assertEqual(result['stop_loss_days'],0)

    def test_active_stop_exits_before_a_later_target_for_both_sides(self):
        for side,breach,target,price in [('long',[100,100,99.7,100],[100,101,100,100],99.8),
                                        ('short',[100,100.3,100,100],[100,100,99,100],100.2)]:
            with self.subTest(side=side):
                result=self.run_trade({'09:40':breach,'09:45':target},side)
                trade=result['days'][0]
                self.assertEqual(trade['exit_reason'],'Stop loss')
                self.assertEqual(trade['exit_time'],'09:40')
                self.assertAlmostEqual(trade['exit_price'],price)
                self.assertEqual(trade['stop_active_from'],'09:40')
                self.assertEqual(trade['outcome'],'failure')
                self.assertEqual(result['stop_loss_days'],1)
                self.assertAlmostEqual(trade['gross_pnl'],-5000)
                self.assertLess(trade['net_pnl'],trade['gross_pnl'])
                sell_price=trade['entry_price'] if side=='short' else price
                buy_price=price if side=='short' else trade['entry_price']
                self.assertAlmostEqual(trade['fees']['stt'],sell_price*trade['quantity']*.00025)
                self.assertAlmostEqual(trade['fees']['stamp'],buy_price*trade['quantity']*.00003)

    def test_gap_through_stop_uses_actual_open_instead_of_stop_price(self):
        for side,bar,expected in [('long',[99,101,98,99],99),('short',[101,102,99,101],101)]:
            with self.subTest(side=side):
                trade=self.run_trade({'09:40':bar},side)['days'][0]
                self.assertEqual(trade['exit_price'],expected)
                self.assertAlmostEqual(trade['gross_pnl'],-25000)
                self.assertFalse(trade['ambiguous_exit'])

    def test_unknown_same_minute_order_is_stop_first_but_target_open_is_known(self):
        for side in ('long','short'):
            with self.subTest(side=side):
                result=self.run_trade({'09:40':[100,101,99,100]},side)
                self.assertEqual(result['days'][0]['exit_reason'],'Stop loss')
                self.assertTrue(result['days'][0]['ambiguous_exit'])
                self.assertEqual(result['ambiguous_days'],1)
                favorable=[101,102,98,100] if side=='long' else [99,102,98,100]
                trade=self.run_trade({'09:40':favorable},side)['days'][0]
                self.assertEqual(trade['exit_reason'],'Target reached')
                self.assertFalse(trade['ambiguous_exit'])

    def test_zero_delay_and_session_cutoff(self):
        trade=self.run_trade({'09:30':[100,100,99.7,100]},delay=0)['days'][0]
        self.assertEqual(trade['exit_time'],'09:30')
        self.assertEqual(trade['exit_reason'],'Stop loss')
        trade=self.run_trade({'15:15':[100,110,90,100]},entry_time='15:14',delay=0)['days'][0]
        self.assertEqual(trade['exit_time'],'15:15')
        self.assertEqual(trade['exit_price'],100)
        self.assertEqual(trade['exit_reason'],'Session exit')

    def test_checkbox_off_preserves_target_only_financial_results(self):
        records={self.day:session(self.day,{'09:40':[100,100,99,100],'09:45':[100,101,100,100]})}
        original=simulate(records,[self.day])
        disabled=simulate(records,[self.day],stop_loss_enabled=False,stop_loss_pct=.9,stop_loss_delay_minutes=0)
        for field in ('final_capital','final_pnl','total_charges','total_gross_pnl','success_days','failure_days'):
            self.assertEqual(original[field],disabled[field])
        self.assertEqual(original['days'],disabled['days'])

    def test_invalid_delays_percentages_and_activation_after_exit_are_rejected(self):
        self.assertEqual(stop_activation('09:30',True,30,.2),'10:00')
        self.assertEqual(stop_activation('15:14',True,0,.2),'15:14')
        for change in ({'stop_loss_delay_minutes':-1},{'stop_loss_delay_minutes':1.5},
                       {'stop_loss_delay_minutes':360},{'stop_loss_pct':0},{'stop_loss_pct':100},
                       {'stop_loss_pct':float('nan')},{'entry_time':'15:00','stop_loss_delay_minutes':15}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                TargetRequest(**{'stock':'RELIANCE','target_pct':.2,'stop_loss_enabled':True,**change})
        self.assertFalse(TargetRequest(stock='RELIANCE',target_pct=.2).stop_loss_enabled)
        self.assertFalse(TargetRequest(stock='RELIANCE',target_pct=.2,entry_time='15:14').stop_loss_enabled)


if __name__=='__main__':
    unittest.main()
