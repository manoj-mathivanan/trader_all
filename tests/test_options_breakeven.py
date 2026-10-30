import unittest
from core.research import options_backtest as bt
from tests.test_options_backtest import event, prices, catalog, stamp


class BreakevenTests(unittest.TestCase):
    def run_case(self, closes, opens=None):
        audit=dict(events=[event('10:00',call=True),event('10:06',exit_call=True)],excluded_sessions=[])
        bars={'call':prices({'09:59':250,**closes})}
        for clock,value in (opens or {}).items():
            bars['call'][stamp(clock)]['open']=value
        return bt.replay(audit,bars,{'2026-10-20':[catalog()]},['2026-10-20'],
            bt.ReplayConfig(breakeven_activation_fraction=.2,slippage_bps=10))

    def test_activation_is_latched_and_fee_adjusted_exit_fills_next_open(self):
        result=self.run_case({'10:00':250,'10:01':301,'10:02':270,'10:03':251,'10:04':240,'10:06':300})
        t=result['trades'][0]
        self.assertEqual(t['protection_activation_timestamp'],stamp('10:02'))
        self.assertEqual(t['exit_timestamp'],stamp('10:04'))
        self.assertEqual(t['reason'],'fee_breakeven_completed_minute')
        self.assertAlmostEqual(t['exit'],240*.999)
        self.assertLess(t['pnl'],0)  # Next-open gap can lose despite the breakeven label.

    def test_no_activation_from_future_open_or_premium_below_threshold(self):
        result=self.run_case({'10:00':250,'10:01':299,'10:02':240,'10:03':240,'10:04':240,'10:05':240,'10:06':280},
            {'10:02':400})
        t=result['trades'][0]
        self.assertEqual(t['exit_timestamp'],stamp('10:06'))
        self.assertNotIn('protection_activation_timestamp',t)

    def test_missing_monitoring_data_does_not_fabricate_protection(self):
        result=self.run_case({'10:00':250,'10:02':301,'10:06':280})
        self.assertIsNone(result['diagnostic_summary'])
        self.assertIsNotNone(result['unresolved_position'])

    def test_entry_minute_activation_never_uses_its_close_for_entry_fill(self):
        result=self.run_case({'10:00':301,'10:01':250,'10:02':240,'10:06':280},{'10:00':250})
        t=result['trades'][0]
        self.assertAlmostEqual(t['entry'],250*1.001)
        self.assertEqual(t['protection_activation_timestamp'],stamp('10:01'))
        self.assertEqual(t['exit_timestamp'],stamp('10:02'))

    def test_invalid_activation(self):
        for value in (0,-.2,float('inf'),float('nan')):
            with self.assertRaises(ValueError):
                bt.ReplayConfig(breakeven_activation_fraction=value)

    def test_activation_does_not_carry_into_next_position(self):
        audit=dict(events=[event('10:00',call=True),event('10:03'),event('10:06',call=True),
                           event('10:12',exit_call=True)],excluded_sessions=[])
        values={'09:59':250,**{f'10:{minute:02d}':250 for minute in range(13)}}
        bars={'call':prices(values)}
        bars['call'][stamp('10:00')]['close']=301
        result=bt.replay(audit,bars,{'2026-10-20':[catalog()]},['2026-10-20'],
            bt.ReplayConfig(breakeven_activation_fraction=.2,slippage_bps=10))
        self.assertEqual(len(result['trades']),2)
        self.assertEqual(result['trades'][0]['reason'],'fee_breakeven_completed_minute')
        self.assertNotIn('protection_activation_timestamp',result['trades'][1])
        self.assertEqual(result['trades'][1]['exit_timestamp'],stamp('10:12'))

    def test_pairing_distinguishes_cut_winners_from_changed_entries(self):
        from scripts.research_options_breakeven import paired_outcomes
        original=dict(key='a',entry_timestamp=0,exit_timestamp=100,pnl=100,reason='original')
        changed=dict(original,exit_timestamp=50,pnl=-20,reason='fee_breakeven_completed_minute')
        later=dict(key='b',entry_timestamp=70,exit_timestamp=100,pnl=50,reason='original')
        result=paired_outcomes(dict(trades=[original]),dict(trades=[changed,later]))
        self.assertEqual(result['original_winners_cut_short'],1)
        self.assertEqual(result['original_losers_improved'],0)
        self.assertEqual(result['new_entries_after_exit_changes'],1)
        self.assertEqual(result['total_same_entry_protection_delta'],-120)
