import unittest
from datetime import date
from scripts.pull_nifty_minute_history import audit_session, expected_calendar, expected_times


class NiftyMinuteAuditTests(unittest.TestCase):
    def test_regular_session_excludes_close_timestamp(self):
        times = expected_times('2024-10-01')
        self.assertEqual((len(times), times[0], times[-1]), (375, '09:15', '15:29'))

    def test_missing_duplicate_and_after_hours_are_disclosed(self):
        bars = [dict(time=t) for t in expected_times('2024-10-01') if t != '09:42']
        bars.extend([dict(time='09:15'), dict(time='15:59')])
        result = audit_session('2024-10-01', bars)
        self.assertEqual(result['missing_minutes'], ['09:42'])
        self.assertEqual(result['extra_minutes'], ['15:59'])
        self.assertEqual(result['duplicate_minutes'], 1)

    def test_missing_session_lists_all_missing_minutes(self):
        self.assertEqual(len(audit_session('2024-10-01', [])['missing_minutes']), 375)

    def test_muhurat_uses_declared_session(self):
        self.assertEqual(expected_times('2024-11-01')[0], '18:00')
        self.assertEqual(len(expected_times('2024-11-01')), 60)
        self.assertEqual(expected_times('2025-10-21')[0], '13:45')

    def test_calendar_includes_budget_weekends_and_excludes_election_holidays(self):
        for day in ('2025-02-01', '2026-02-01', '2024-11-01'):
            d = date.fromisoformat(day)
            self.assertEqual(expected_calendar(d, d), [day])
        for day in ('2024-11-20', '2026-01-15', '2026-10-02'):
            d = date.fromisoformat(day)
            self.assertEqual(expected_calendar(d, d), [])

    def test_unreviewed_calendar_range_rejected(self):
        with self.assertRaises(ValueError):
            expected_calendar(date(2024, 1, 1), date(2026, 11, 2))


if __name__ == '__main__':
    unittest.main()
