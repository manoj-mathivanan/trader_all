from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.research import options_backtest as bt, options_history as history


def stamp(clock, day='2026-10-20'):
    return int(datetime.fromisoformat(day+'T'+clock+':00+05:30').timestamp()*1000)


def event(clock, **overrides):
    value = dict(timestamp=stamp(clock), date='2026-10-20', time=clock, ready=True,
                 call=False, put=False, exit_call=False, exit_put=False,
                 entry_window='09:30' <= clock < '15:00', underlying_close=25000)
    return dict(value, **overrides)


def catalog(kind='CE', key='call', strike=25000, lot=65, expiry='2026-10-20'):
    return dict(instrument_key=key, underlying_key=history.UNDERLYING, instrument_type=kind,
                lot_size=lot, strike_price=strike, expiry=expiry)


def prices(values):
    return {stamp(clock): dict(open=premium, close=premium, volume=65)
            for clock, premium in values.items()}


class ReplayTests(unittest.TestCase):
    def sample(self):
        audit = dict(events=[event('10:00', call=True), event('10:03', exit_call=True)], excluded_sessions=[])
        bars = {'call': prices({'09:59': 250, '10:00': 255, '10:03': 280})}
        catalogs = {'2026-10-20': [catalog()]}
        return audit, bars, catalogs, ['2026-10-20']

    def run_sample(self, config=None):
        return bt.replay(*self.sample(), config or bt.ReplayConfig())

    def test_next_minute_open_historical_lot_and_round_trip_costs(self):
        cfg = bt.ReplayConfig(brokerage_per_order=20, buy_charge_bps=2, sell_charge_bps=8, slippage_bps=10)
        report = self.run_sample(cfg)
        trade = report['trades'][0]
        self.assertEqual(trade['quantity'], 65)
        self.assertEqual(trade['selection_timestamp'], stamp('09:59'))
        self.assertEqual(trade['entry_timestamp'], stamp('10:00'))
        self.assertAlmostEqual(trade['entry'], 255*1.001)
        self.assertAlmostEqual(trade['exit'], 280*.999)
        from core.execution.upstox import charges
        expected = 65*(280*.999-255*1.001)-sum(charges(price,65,side,'2026-10-20',segment='options')['total'] for price,side in [(255*1.001,'buy'),(280*.999,'sell')])
        self.assertAlmostEqual(trade['pnl'], expected)
        self.assertAlmostEqual(report['performance_summary']['final_cash'], 100000+expected)
        self.assertFalse(report['costs_verified'])

    def test_future_premium_cannot_change_signal_time_selection(self):
        audit, bars, catalogs, expiries = self.sample()
        catalogs['2026-10-20'].append(catalog(key='other', strike=25100))
        bars['other'] = prices({'09:59': 260, '10:00': 250, '10:03': 1000})
        chosen, reason = bt.choose_contract(catalogs, bars, expiries, audit['events'][0], 'call', 'fixed_250')
        self.assertIsNone(reason)
        self.assertEqual(chosen['instrument_key'], 'call')
        bars['other'][stamp('10:00')]['close'] = 250
        self.assertEqual(bt.choose_contract(catalogs, bars, expiries, audit['events'][0], 'call', 'fixed_250')[0], chosen)

    def test_missing_candidate_prevents_premium_ranking(self):
        audit, bars, catalogs, expiries = self.sample()
        catalogs['2026-10-20'].append(catalog(key='missing', strike=25100))
        result = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig())
        self.assertEqual(result['trades'], [])
        self.assertIn('candidate-chain', result['skipped_entries'][0]['reason'])
        self.assertIsNone(result['performance_summary'])
        diagnostic = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig(chain_policy='observed_traded'))
        self.assertEqual(diagnostic['status'], 'diagnostic_replay_complete')
        self.assertIsNone(diagnostic['performance_summary'])
        self.assertEqual(diagnostic['diagnostic_summary']['completed_trades'], 1)
        self.assertEqual(diagnostic['selection_coverage'][0]['missing_candidate_minutes'], 1)

    def test_missing_nearest_expiry_never_substitutes_later_catalog(self):
        audit, bars, catalogs, expiries = self.sample()
        del catalogs['2026-10-20']
        catalogs['2026-10-27'] = [catalog(expiry='2026-10-27')]
        chosen, reason = bt.choose_contract(catalogs, bars, expiries+['2026-10-27'], audit['events'][0], 'call', 'fixed_250')
        self.assertIsNone(chosen)
        self.assertIn('Nearest expiry', reason)

    def test_missing_exit_keeps_unresolved_position_without_metrics(self):
        audit, bars, catalogs, expiries = self.sample()
        del bars['call'][stamp('10:03')]
        report = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig())
        self.assertEqual(report['trades'], [])
        self.assertIsNotNone(report['unresolved_position'])
        self.assertIsNone(report['performance_summary'])
        self.assertIn('Exact exit', report['errors'][0])

    def test_entry_gap_is_not_filled_at_a_nearby_price(self):
        audit, bars, catalogs, expiries = self.sample()
        del bars['call'][stamp('10:00')]
        report = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig())
        self.assertEqual(report['trades'], [])
        self.assertIn('Exact entry', report['skipped_entries'][0]['reason'])

    def test_scheduled_liquidation_and_insufficient_cash(self):
        audit, bars, catalogs, expiries = self.sample()
        audit['events'] = audit['events'][:1]
        bars['call'][stamp('15:20')] = dict(open=300, close=305, volume=65)
        report = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig())
        self.assertEqual(report['trades'][0]['reason'], 'scheduled_intraday_exit')
        self.assertEqual(report['trades'][0]['exit'], 300)
        report = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig(capital=1000))
        self.assertEqual(report['trades'], [])
        self.assertIn('Insufficient cash', report['skipped_entries'][0]['reason'])

    def test_put_and_premium_variants(self):
        audit, bars, catalogs, expiries = self.sample()
        audit['events'][0].update(call=False, put=True, underlying_close=20000)
        audit['events'][1].update(exit_call=False, exit_put=True)
        catalogs['2026-10-20'] = [catalog(kind='PE', key='a', strike=25000), catalog(kind='PE', key='b', strike=25100)]
        bars = {'a': prices({'09:59': 250, '10:00': 260, '10:03': 280}),
                'b': prices({'09:59': 200, '10:00': 210, '10:03': 220})}
        fixed = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig())
        dynamic = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig(premium_variant='underlying_1pct'))
        self.assertEqual(fixed['trades'][0]['key'], 'a')
        self.assertEqual(dynamic['trades'][0]['key'], 'b')

    def test_no_same_minute_reversal_and_bad_configs(self):
        audit, bars, catalogs, expiries = self.sample()
        audit['events'][1].update(put=True)
        result = bt.replay(audit, bars, catalogs, expiries, bt.ReplayConfig())
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['skipped_entries'], [])
        for fields in [dict(capital=float('nan')), dict(slippage_bps=10000), dict(timeframe=1), dict(buy_charge_bps=-1)]:
            with self.assertRaises(ValueError):
                bt.ReplayConfig(**fields)


class SignalAuditTests(unittest.TestCase):
    def day(self, key):
        anchor = datetime.fromisoformat(key+'T09:15:00+05:30')
        bars = []
        for i in range(375):
            instant = anchor+timedelta(minutes=i)
            bars.append(dict(date=key, time=instant.strftime('%H:%M'), timestamp=int(instant.timestamp()*1000),
                open=100, high=101, low=99, close=100, volume=10))
        daily = dict(date=key, open=100, high=101, low=99, close=100)
        return bars, daily

    def test_anchor_and_last_signal_are_completed_bar_end_times(self):
        warmup, first = self.day('2026-10-19')
        bars, second = self.day('2026-10-20')
        for timeframe, count in [(3, 125), (5, 75)]:
            audit = bt.prepare_signals(warmup+bars, [first, second], start=date(2026, 10, 20), end=date(2026, 10, 20), timeframe=timeframe)
            self.assertEqual(len(audit['events']), count)
            self.assertEqual(audit['events'][0]['time'], '09:18' if timeframe == 3 else '09:20')
            self.assertEqual(audit['events'][-1]['time'], '15:30')
            if timeframe == 3:
                self.assertTrue(audit['events'][0]['ready'])

    def test_gap_excludes_whole_session_and_resets_warmup(self):
        one, d1 = self.day('2026-10-19')
        two, d2 = self.day('2026-10-20')
        three, d3 = self.day('2026-10-21')
        result = bt.prepare_signals(one+two[:-1]+three, [d1, d2, d3],
            start=date(2026, 10, 19), end=date(2026, 10, 21), timeframe=3)
        self.assertEqual(len(result['excluded_sessions']), 1)
        self.assertEqual(result['excluded_sessions'][0]['date'], d2['date'])
        third = [e for e in result['events'] if e['date'] == d3['date']]
        self.assertFalse(third[0]['ready'])
        self.assertTrue(third[99]['ready'])

    def test_daily_range_mismatch_and_special_sessions_excluded(self):
        bars, daily = self.day('2026-10-20')
        daily['high'] = 150
        result = bt.prepare_signals(bars, [daily], start=date(2026, 10, 20), end=date(2026, 10, 20))
        self.assertEqual(result['events'], [])
        self.assertIn('disagree', result['excluded_sessions'][0]['reason'])

    def test_checksum_and_directory_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'data.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                bt.read_evidence(tmp, dict(file='data.json', sha256='wrong'))
            with self.assertRaisesRegex(ValueError, 'direct file'):
                bt.read_evidence(tmp, dict(file='../outside.json', sha256='wrong'))

    def test_missing_option_archive_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'No option-candle sample'):
                bt.load_option_sample(tmp)


if __name__ == '__main__':
    unittest.main()
