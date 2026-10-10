import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from core.research import market_data as market, store, intraday_data


def candle(day, close=100):
    return {'date': day, 'open': close, 'high': close+2, 'low': close-2, 'close': close, 'volume': 100}


class MarketFetchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for target, value in [('DATA', Path(directory.name)), ('token', lambda: 'synthetic-token')]:
            patched = patch.object(store, target, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.item = {'symbol': 'TEST', 'isin': 'TESTISIN', 'key': 'synthetic'}

    def test_windows_calendar_year_and_ten_inclusive_days(self):
        self.assertEqual(market.windows(date(2026, 10, 7)),
                         {'daily_start': '2025-10-07', 'minute_start': '2026-09-28', 'end': '2026-10-07'})
        self.assertEqual(market.windows(date(2024, 2, 29))['daily_start'], '2023-02-28')

    def test_settings_schema_and_save_offer_only_universe_preserving_internal_ranges(self):
        from fastapi.testclient import TestClient
        from dashboard.api.main import app
        store.write('settings', {'universe':'nifty500', 'start':'2019-01-01','end':'2026-10-08'})
        with TestClient(app) as client:
            bootstrap = client.get('/api/bootstrap').json()
            self.assertEqual(set(bootstrap['settings_schema']['properties']), {'universe'})
            self.assertEqual(bootstrap['settings']['universe'], 'niftytotalmarket')
            self.assertEqual(bootstrap['settings_schema']['properties']['universe']['const'], 'niftytotalmarket')
            response = client.put('/api/settings', json={'universe':'niftytotalmarket'}, headers={'X-Trader-Request':'local-ui'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(store.read('settings'), {'universe':'niftytotalmarket','start':'2019-01-01','end':'2026-10-08'})
            self.assertEqual(client.put('/api/settings', json={'universe':'nifty50','start':'2020-01-01'},
                                       headers={'X-Trader-Request':'local-ui'}).status_code, 422)

    def test_current_settings_upgrade_preserves_frozen_universes_and_portfolios(self):
        from core.research.config import Settings, DataPreferences, current_settings
        legacy = {'universe': 'nifty500', 'start': '2019-01-01', 'end': '2026-10-08'}
        frozen = {'universe': 'nifty500', 'instruments': [{'symbol': 'OLD', 'isin': 'EXISTING'}]}
        portfolio = {'universe_snapshot': frozen, 'ledger': {'cash': 123}}
        store.write('settings', legacy)
        store.write('universes/nifty500', frozen)
        store.write('runs/legacy', {'universe': 'nifty500', 'universe_snapshot': frozen})
        store.write('portfolios/swing_patterns', portfolio)
        self.assertEqual(Settings().universe, 'niftytotalmarket')
        self.assertEqual(DataPreferences().universe, 'niftytotalmarket')
        self.assertEqual(current_settings().universe, 'niftytotalmarket')
        self.assertEqual(store.read('settings'), {**legacy, 'universe': 'niftytotalmarket'})
        self.assertEqual(store.read('universes/nifty500'), frozen)
        self.assertEqual(store.read('runs/legacy')['universe_snapshot'], frozen)
        self.assertEqual(store.read('portfolios/swing_patterns'), portfolio)
        self.assertEqual(Settings(universe='nifty500').universe, 'nifty500')
        self.assertEqual(current_settings('legacy').universe, 'nifty500')
        self.assertEqual(current_settings().universe, 'niftytotalmarket')

    def test_latest_provider_session_excludes_unfinished_today(self):
        with patch.object(market.upstox, 'fetch_range', return_value=[candle('2026-10-06')]) as fetch:
            last = market.last_traded_day(Mock(), 'synthetic', datetime(2026, 10, 8, 12, tzinfo=intraday_data.IST))
        self.assertEqual(last, date(2026, 10, 6))
        self.assertEqual(fetch.call_args.args[-1], date(2026, 10, 7))

    def test_no_benchmark_data_fails_before_stock_downloads(self):
        with patch.object(market.upstox, 'fetch_range', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'last completed trading day'):
                market.last_traded_day(Mock(), 'synthetic')

    def test_daily_refresh_fills_holes_without_redownloading_cached_dates(self):
        store.write('bars/TESTISIN', {'bars': [candle('2020-01-01'), candle('2026-10-07', 99)],
                                    'requested_start': '2019-01-01', 'requested_end': '2026-10-07'})
        with patch.object(market.upstox, 'fetch_range', return_value=[candle('2026-10-06')]) as fetch:
            market.save_daily(Mock(), self.item, 'synthetic', date(2025, 10, 7), date(2026, 10, 7),
                              sessions=['2026-10-06', '2026-10-07'])
        self.assertEqual(fetch.call_args.args[-2:], (date(2026,10,6), date(2026,10,6)))
        saved = store.read('bars/TESTISIN')
        self.assertEqual(len(saved['bars']), 3)
        self.assertEqual(saved['bars'][0]['date'], '2020-01-01')
        self.assertEqual(saved['bars'][-1]['close'], 99)
        self.assertEqual(saved['requested_start'], '2019-01-01')

    def test_daily_repeat_refresh_makes_no_request_or_candle_write(self):
        original = {'bars': [candle('2026-10-06'), candle('2026-10-07')],
                    'requested_start': '2025-10-07', 'requested_end': '2026-10-07'}
        store.write('bars/TESTISIN', original)
        with patch.object(market.upstox, 'fetch_range') as fetch, patch.object(store, 'write') as write:
            count = market.save_daily(Mock(), self.item, 'synthetic', date(2025,10,7), date(2026,10,7),
                                      sessions=['2026-10-06', '2026-10-07'])
        self.assertEqual(count, 0)
        fetch.assert_not_called()
        write.assert_not_called()

    def test_daily_new_session_fetches_only_new_day(self):
        store.write('bars/TESTISIN', {'bars': [candle('2026-10-07')],
                                    'requested_start': '2025-10-07', 'requested_end': '2026-10-07'})
        with patch.object(market.upstox, 'fetch_range', return_value=[candle('2026-10-08')]) as fetch:
            market.save_daily(Mock(), self.item, 'synthetic', date(2025,10,8), date(2026,10,8),
                              sessions=['2026-10-07', '2026-10-08'])
        self.assertEqual(fetch.call_args.args[-2:], (date(2026,10,8), date(2026,10,8)))

    def test_minutes_reuses_complete_sessions_and_fetches_incomplete_day(self):
        day = '2026-10-07'
        raw = [[f'{day}T{t//60:02d}:{t%60:02d}:00+05:30',100,102,98,100,10]
               for t in range(9*60+15,15*60+30,5)]
        store.write(intraday_data.cache_key('TESTISIN', day), {'bars': intraday_data.normalize(raw, day)})
        with patch.object(market, 'download_minutes', return_value={
                'bars': 75, 'sessions': 1, 'first':'2026-10-08', 'last':'2026-10-08'}) as download:
            result = market.save_minutes(Mock(), self.item, 'synthetic', date(2026,10,7),date(2026,10,8),
                                         sessions=[day, '2026-10-08'])
        self.assertEqual(result['reused_sessions'], 1)
        self.assertEqual(download.call_args.args[-2:], (date(2026,10,8),date(2026,10,8)))
        with patch.object(market, 'download_minutes') as download:
            result = market.save_minutes(Mock(), self.item, 'synthetic',date(2026,10,7),date(2026,10,7),sessions=[day])
        self.assertEqual(result['bars'], 0)
        download.assert_not_called()
        store.write(intraday_data.cache_key('TESTISIN',day), {'bars': intraday_data.normalize(raw[:-1],day)})
        self.assertFalse(market.complete_minutes(store.read(intraday_data.cache_key('TESTISIN',day)),day))

    def test_missing_ranges_does_not_cross_cached_session(self):
        self.assertEqual(market.missing_ranges(['2026-10-05','2026-10-06','2026-10-07','2026-10-08'],
                                              {'2026-10-05','2026-10-07','2026-10-08'}),
                         [(date(2026,10,5),date(2026,10,5)),(date(2026,10,7),date(2026,10,8))])

    def test_second_full_refresh_downloads_no_stock_candles(self):
        day = '2026-10-07'
        response = Mock()
        response.json.return_value = {'status':'success', 'data':{'candles':[
            [f'{day}T{t//60:02d}:{t%60:02d}:00+05:30',100,102,98,100,10]
            for t in range(9*60+15,15*60+30,5)]}}
        with patch.object(market, 'last_traded_day', return_value=date(2026,10,7)), \
             patch.object(market.upstox, 'refresh_universe', return_value={'instruments':[self.item]}), \
             patch.object(market.upstox, 'fetch_range', return_value=[candle(day)]) as daily, \
             patch.object(market.upstox, 'get', return_value=response) as minute, \
             patch.object(market.fundamentals, 'pull', return_value={'counts':{}}), \
             patch.object(market.time, 'sleep'):
            first = market.fetch(lambda _:None, 'first')
            self.assertEqual(first['daily_bars'], 1)
            self.assertEqual(first['minute_bars'], 75)
            daily.reset_mock()
            minute.reset_mock()
            second = market.fetch(lambda _:None, 'second')
        self.assertEqual(second['daily_bars'], 0)
        self.assertEqual(second['minute_bars'], 0)
        self.assertEqual(second['stocks'][0]['minute']['reused_sessions'], 1)
        daily.assert_called_once()  # Shared benchmark session calendar only.
        self.assertEqual(daily.call_args.args[1], market.BENCHMARK)
        minute.assert_not_called()

    def test_special_session_is_complete_with_its_shorter_hours(self):
        day = '2025-10-21'
        raw = [[f'{day}T{t//60:02d}:{t%60:02d}:00+05:30',100,102,98,100,10]
               for t in range(13*60+45,14*60+45,5)]
        self.assertTrue(market.complete_minutes({'bars':intraday_data.normalize(raw,day)},day))

    def test_five_minute_refresh_merges_session_and_keeps_older_days(self):
        old_day = intraday_data.cache_key('TESTISIN', '2020-01-01')
        store.write(old_day, {'bars': [candle('2020-01-01')]})
        key = intraday_data.cache_key('TESTISIN', '2026-10-07')
        prior = intraday_data.normalize([['2026-10-07T09:15:00+05:30',100,102,98,100,10]], '2026-10-07')
        store.write(key, {'bars': prior})
        response = Mock()
        response.json.return_value = {'status': 'success', 'data': {'candles': [
            ['2026-10-07T09:20:00+05:30',101,103,99,101,20]]}}
        with patch.object(market.upstox, 'get', return_value=response):
            market.save_minutes(Mock(), self.item, 'synthetic', date(2026,9,28), date(2026,10,7))
        self.assertEqual([b['time'] for b in store.read(key)['bars']], ['09:15','09:20'])
        self.assertEqual(store.read(old_day)['bars'][0]['date'], '2020-01-01')

    def test_malformed_minute_response_leaves_existing_sessions_untouched(self):
        key = intraday_data.cache_key('TESTISIN', '2026-10-07')
        store.write(key, {'bars': []})
        response = Mock()
        response.json.return_value = {'status':'success','data':{'candles':[
            ['2026-10-07T09:15:00+05:30',100,102,98,100,10],
            ['2026-10-07T09:20:00+05:30',100,0,98,100,10]]}}
        with patch.object(market.upstox, 'get', return_value=response):
            with self.assertRaises(ValueError):
                market.save_minutes(Mock(), self.item, 'synthetic', date(2026,9,28), date(2026,10,7))
        self.assertEqual(store.read(key), {'bars': []})

    def test_all_750_stocks_and_both_intervals_attempted_after_auth_and_unexpected_errors(self):
        universe = {'instruments': [dict(self.item, symbol=f'S{i}', isin=f'I{i}') for i in range(750)]}
        daily = Mock(side_effect=[ValueError('Upstox rejected token (401/403).'), RuntimeError('secret-header')]+[1]*748)
        minute = Mock(return_value={'bars': 75, 'sessions': 1, 'first':'2026-10-07','last':'2026-10-07'})
        with patch.object(market, 'last_traded_day', return_value=date(2026,10,7)), \
             patch.object(market.upstox, 'fetch_range', return_value=[candle('2026-10-07')]), \
             patch.object(market.upstox, 'refresh_universe', return_value=universe) as refresh, \
             patch.object(market, 'save_daily', daily), patch.object(market, 'save_minutes', minute), \
             patch.object(market.time, 'sleep'), patch.object(market.fundamentals, 'pull', return_value={'counts':{}}) as fundamental_pull, patch.object(store, 'write'):
            result = market.fetch(lambda _: None, 'test-job')
        self.assertEqual(refresh.call_args.args[0].universe, 'niftytotalmarket')
        self.assertEqual(daily.call_count, 750)
        self.assertEqual(minute.call_count, 750)
        self.assertEqual(len(fundamental_pull.call_args.args[0]),750)
        self.assertEqual(result['daily_symbols'], 748)
        self.assertEqual(result['minute_symbols'], 750)
        self.assertTrue(result['partial'])
        self.assertNotIn('secret-header', str(result))


if __name__ == '__main__':
    unittest.main()
