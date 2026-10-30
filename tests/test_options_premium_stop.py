import unittest
from core.research import options_backtest as bt
from tests.test_options_backtest import event, prices, catalog, stamp


class PremiumStopTests(unittest.TestCase):
    def run_case(self, bars):
        audit=dict(events=[event('10:00',call=True),event('10:03',exit_call=True)],excluded_sessions=[])
        return bt.replay(audit,{'call':prices(bars)},{'2026-10-20':[catalog()]},['2026-10-20'],
                         bt.ReplayConfig(premium_stop_fraction=.2))

    def test_stop_uses_completed_close_then_next_open_with_gap_loss(self):
        result=self.run_case({'09:59':250,'10:00':250,'10:01':200,'10:02':180,'10:03':300})
        trade=result['trades'][0]
        self.assertEqual(trade['exit_timestamp'],stamp('10:02'))
        self.assertEqual(trade['exit'],180)
        self.assertEqual(trade['reason'],'premium_stop_completed_minute')

    def test_missing_monitoring_minute_suppresses_result(self):
        result=self.run_case({'09:59':250,'10:00':250,'10:02':180,'10:03':300})
        self.assertIsNone(result['diagnostic_summary'])
        self.assertIsNotNone(result['unresolved_position'])

    def test_entry_minute_can_trigger_exit_only_at_following_open(self):
        audit=dict(events=[event('10:00',call=True)],excluded_sessions=[])
        bars={'call':prices({'09:59':250,'10:00':250,'10:01':190})}
        bars['call'][stamp('10:00')]['close']=190
        result=bt.replay(audit,bars,{'2026-10-20':[catalog()]},['2026-10-20'],bt.ReplayConfig(premium_stop_fraction=.2))
        self.assertEqual(result['trades'][0]['entry'],250)
        self.assertEqual(result['trades'][0]['exit_timestamp'],stamp('10:01'))

    def test_invalid_stop_rejected(self):
        for value in (0,1,-.2,float('nan')):
            with self.assertRaises(ValueError):
                bt.ReplayConfig(premium_stop_fraction=value)
