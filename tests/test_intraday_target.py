import json
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
from core.research.intraday_data import normalize
from core.research.intraday_target import simulate
from scripts.pull_nifty_minute_history import expected_times


def session(day, changes=None):
    rows = [[f'{day}T{t}:00+05:30', 100, 100, 100, 100, 1000] for t in expected_times(day)]
    for row in rows:
        if row[0][11:16] in (changes or {}):
            row[1:5] = changes[row[0][11:16]]
    return {'bars': normalize(rows, day, 1)}


class TargetBacktestTests(unittest.TestCase):
    def test_point_two_target_exits_before_point_five(self):
        d = '2024-11-04'
        data = {d: session(d, {'09:31': [100, 100.25, 100, 100],
                              '10:00': [100, 100.6, 100, 100]})}
        small = simulate(data, [d], target_pct=.2)
        original = simulate(data, [d])
        self.assertEqual(small['days'][0]['exit_time'], '09:31')
        self.assertEqual(small['days'][0]['exit_price'], 100.2)
        self.assertAlmostEqual(small['days'][0]['gross_pnl'], 5000)
        self.assertEqual(original['days'][0]['exit_time'], '10:00')
        self.assertEqual(small['target_pct'], .2)
        self.assertEqual(small['id'], 'hdfcbank-0930-target02-2y')
        for target in (0, -1, 100, float('nan')):
            with self.assertRaises(ValueError):
                simulate(data, [d], target_pct=target)

    def test_short_target_uses_low_and_taxes_the_correct_legs(self):
        d = '2024-11-04'
        r = simulate({d: session(d, {'09:29': [100, 100, 98, 100],
                                     '09:32': [100, 100, 99, 100]})}, [d], direction='short')
        trade = r['days'][0]
        self.assertEqual(trade['exit_time'], '09:32')
        self.assertEqual(trade['exit_price'], 99.5)
        self.assertEqual(trade['gross_pnl'], 12500)
        self.assertEqual(trade['fees']['stt'], 2500000*.00025)
        self.assertEqual(trade['fees']['stamp'], 2487500*.00003)
        self.assertEqual(r['success_days'], 1)
        self.assertAlmostEqual(r['final_capital'], 500000+r['final_pnl'])

    def test_short_failure_ignores_low_after_manual_exit(self):
        d = '2024-11-04'
        r = simulate({d: session(d, {'15:15': [101, 102, 98, 100]})}, [d], direction='short')
        trade = r['days'][0]
        self.assertEqual(trade['outcome'], 'failure')
        self.assertEqual(trade['exit_price'], 101)
        self.assertEqual(trade['gross_pnl'], -25000)

    def test_first_target_and_compounding_after_costs(self):
        dates = ['2024-11-04', '2024-11-05']
        data = {d: session(d, {'09:29': [100, 110, 100, 100],
                             '09:31': [100, 101, 100, 100]}) for d in dates}
        r = simulate(data, dates)
        a, b = r['days']
        self.assertEqual(a['exit_time'], '09:31')
        self.assertAlmostEqual(a['exit_price'], 100.5)
        self.assertEqual(a['quantity'], 25000)
        # Independent round-trip fee calculation at the capped brokerage rate.
        buy, sell = 2500000, 2512500
        turnover = buy + sell
        expected = 40 + sell*.00025 + turnover*.0000307 + turnover*.000001 + buy*.00003
        expected += .18*(40+turnover*.0000307+turnover*.000001)
        self.assertAlmostEqual(a['charges'], expected)
        self.assertEqual(b['quantity'], int(a['closing_capital']*5//100))
        self.assertAlmostEqual(r['final_capital'], 500000+r['final_pnl'])

    def test_failure_can_be_profitable_and_late_high_is_ignored(self):
        d = '2024-11-04'
        r = simulate({d: session(d, {'15:15': [100.2, 102, 100, 101],
                                     '15:16': [100, 102, 100, 100]})}, [d])
        trade = r['days'][0]
        self.assertEqual(trade['outcome'], 'failure')
        self.assertEqual(trade['exit_price'], 100.2)
        self.assertGreater(trade['net_pnl'], 0)

    def test_missing_data_rejected_and_special_session_skipped(self):
        d = '2024-11-04'
        bad = session(d)
        bad['bars'].pop(20)
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            simulate({d: bad}, [d])
        with self.assertRaisesRegex(ValueError, 'Missing session'):
            simulate({}, [d])
        d = '2025-10-21'
        r = simulate({d: session(d)}, [d])
        self.assertEqual(len(r['skipped']), 1)
        self.assertEqual(r['final_capital'], 500000)

    def test_saved_report_reconciles_and_shared_page_serves_same_data(self):
        for name in ('hdfcbank-target', 'hdfcbank-short-target', 'hdfcbank-target02'):
            with self.subTest(report=name):
                self.check_saved_report(name)

    def check_saved_report(self, name):
        from dashboard.shared import create_app
        path = Path(__file__).resolve().parents[1]/f'dashboard/reports/{name}.json'
        r = json.loads(path.read_text())
        self.assertEqual(r['success_days']+r['failure_days'], len(r['days']))
        self.assertEqual(len(r['days'])+len(r['skipped']), r['expected_sessions'])
        self.assertAlmostEqual(sum(d['net_pnl'] for d in r['days']), r['final_pnl'])
        for i, d in enumerate(r['days']):
            self.assertAlmostEqual(sum(d['fees'].values()), d['charges'])
            self.assertAlmostEqual(d['opening_capital']+d['net_pnl'], d['closing_capital'])
            if i:
                self.assertEqual(d['opening_capital'], r['days'][i-1]['closing_capital'])
        with TestClient(create_app()) as client:
            self.assertEqual(client.get('/api/intraday/backtests/'+name).json(), r)
            self.assertEqual(client.get('/api/intraday/backtests/unknown').status_code, 404)


if __name__ == '__main__':
    unittest.main()
