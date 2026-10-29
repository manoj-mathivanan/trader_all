import unittest
import os
from datetime import date, timedelta
from unittest.mock import Mock, patch

from core.research import market_data as market, intraday_data
from scripts.refresh_market_history import expected_sessions, require_server_schedule


class MinuteHistoryTests(unittest.TestCase):
    def test_automatic_refresh_rejects_local_environment_before_accessing_data(self):
        with patch.dict(os.environ,{'TRADER_ENV':'local'}), \
             patch('scripts.refresh_market_history.store.database_enabled',return_value=True):
            with self.assertRaisesRegex(ValueError,'server-only'):
                require_server_schedule()

    def test_automatic_refresh_requires_production_database_storage(self):
        with patch.dict(os.environ,{'TRADER_ENV':'production'}), \
             patch('scripts.refresh_market_history.store.database_enabled',return_value=False):
            with self.assertRaisesRegex(ValueError,'server-only'):
                require_server_schedule()
        with patch.dict(os.environ,{'TRADER_ENV':'production'}), \
             patch('scripts.refresh_market_history.store.database_enabled',return_value=True):
            require_server_schedule()

    def test_split_special_session_does_not_invent_candles_during_break(self):
        day = '2024-03-02'
        times = list(range(555,600,5))+list(range(690,750,5))
        raw = [[f'{day}T{t//60:02d}:{t%60:02d}:00+05:30',100,101,99,100,1] for t in times]
        bars = intraday_data.normalize(raw,day)
        self.assertTrue(market.complete_minutes({'bars':bars},day))
        self.assertFalse(market.complete_minutes({'bars':bars[:-1]},day))

    def test_provider_chunks_cover_long_gap_without_crossing_complete_session(self):
        start = date(2026,1,1)
        sessions = [str(start+timedelta(days=i)) for i in range(90)]
        missing = set(sessions)-{'2026-02-02'}
        ranges = list(market.minute_ranges(sessions,missing))
        covered = set()
        for a,b in ranges:
            self.assertLessEqual((b-a).days,27)
            covered.update(str(a+timedelta(days=i)) for i in range((b-a).days+1))
        self.assertEqual(covered,missing)

    def test_calendar_exposes_daily_gap_and_does_not_expect_prelisting_days(self):
        expected, missing = expected_sessions([{'date':'2026-10-26'},{'date':'2026-10-28'}],
            ['2026-10-23','2026-10-26','2026-10-27','2026-10-28'],date(2022,1,1),date(2026,10,28))
        self.assertEqual(expected,['2026-10-26','2026-10-27','2026-10-28'])
        self.assertEqual(missing,['2026-10-27'])

    def test_provider_omission_is_reported_as_missing_after_download(self):
        with patch.object(market.store,'read',return_value=None), \
             patch.object(market,'download_minutes',return_value={'bars':75,'sessions':1,'first':'2026-10-26','last':'2026-10-26'}), \
             patch.object(market.time,'sleep'):
            result = market.save_minutes(Mock(),{'isin':'TEST'},'synthetic',date(2026,10,26),date(2026,10,27),
                sessions=['2026-10-26','2026-10-27'])
        self.assertEqual(result['missing_sessions'],['2026-10-26','2026-10-27'])


if __name__=='__main__':
    unittest.main()
