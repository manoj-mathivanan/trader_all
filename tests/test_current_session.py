import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from core.research import current_session as current, market_data as market, store, intraday_data


DAY = date(2026, 10, 29)
AFTER = datetime(2026, 10, 29, 17, tzinfo=intraday_data.IST)


def raw(day='2026-10-29', times=None):
    return [[f'{day}T{m//60:02d}:{m%60:02d}:00+05:30', 100, 103, 99, 102, 10]
            for m in (times if times is not None else range(555, 930, 5))]


class CurrentSessionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        p = patch.object(store, 'DATA', Path(directory.name))
        p.start()
        self.addCleanup(p.stop)
        self.item = dict(symbol='TEST', isin='TEST', key='NSE_EQ|TEST')

    def response(self, rows):
        response = Mock()
        response.json.return_value = dict(status='success', data=dict(candles=rows))
        return response

    def test_after_close_uses_current_endpoint_and_full_coverage_before_advancing_calendar(self):
        with patch.object(market.upstox, 'fetch_range', return_value=[{'date':'2026-10-28'}]), \
             patch.object(current.upstox, 'get', return_value=self.response(raw())) as get:
            self.assertEqual(market.last_traded_day(Mock(), 'token', AFTER), DAY)
        self.assertIn('/intraday/', get.call_args.args[1])
        self.assertIn('/minutes/5', get.call_args.args[1])

    def test_no_intraday_request_before_close_buffer_or_for_weekend(self):
        for moment in [AFTER.replace(hour=15,minute=45), AFTER.replace(day=31)]:
            with self.subTest(moment=moment), patch.object(market.upstox,'fetch_range',return_value=[{'date':'2026-10-28'}]), \
                 patch.object(current.upstox,'get') as get:
                self.assertEqual(market.last_traded_day(Mock(),'token',moment),date(2026,10,28))
                get.assert_not_called()

    def test_holiday_does_not_invent_today_and_incomplete_session_is_rejected(self):
        for rows in [[], raw()[:-1]]:
            with patch.object(current.upstox,'get',return_value=self.response(rows)):
                if rows:
                    with self.assertRaisesRegex(ValueError,'incomplete'):
                        current.daily(Mock(),self.item,'token',DAY,now=AFTER)
                else:
                    self.assertIsNone(current.daily(Mock(),self.item,'token',DAY,now=AFTER))
        self.assertIsNone(store.read(intraday_data.cache_key('TEST',str(DAY))))

    def test_special_split_session_requires_only_its_declared_trading_segments(self):
        day='2024-03-02'
        rows=raw(day,list(range(555,600,5))+list(range(690,750,5)))
        moment=datetime(2024,3,2,17,tzinfo=intraday_data.IST)
        with patch.object(current.upstox,'get',return_value=self.response(rows)):
            bar=current.daily(Mock(),self.item,'token',date(2024,3,2),now=moment)
        self.assertEqual(bar['volume'],210)

    def test_daily_aggregate_is_labeled_reused_and_replaced_by_published_candle(self):
        yesterday=dict(date='2026-10-28',open=100,high=103,low=99,close=101,volume=700)
        store.write('bars/TEST',dict(bars=[yesterday],requested_start='2025-10-29',requested_end='2026-10-28'))
        with patch.object(current,'completed_day',return_value=DAY), \
             patch.object(market.upstox,'fetch_range',return_value=[]), \
             patch.object(current.upstox,'get',return_value=self.response(raw())) as get, \
             patch.object(market.time,'sleep'):
            market.save_daily(Mock(),self.item,'token',date(2025,10,29),DAY,sessions=['2026-10-28',str(DAY)])
            saved=store.read('bars/TEST')
            self.assertTrue(saved['provisional_daily'][str(DAY)]['provisional'])
            self.assertEqual(saved['bars'][-1]['volume'],750)
            self.assertEqual(saved['bars'][-1]['close'],102)
            market.save_daily(Mock(),self.item,'token',date(2025,10,29),DAY,sessions=['2026-10-28',str(DAY)])
            self.assertEqual(get.call_count,1)
            published=dict(saved['bars'][-1],close=101.5,volume=760)
        with patch.object(current,'completed_day',return_value=date(2026,10,30)), \
             patch.object(market.upstox,'fetch_range',return_value=[published]) as fetch, \
             patch.object(market.time,'sleep'):
            market.save_daily(Mock(),self.item,'token',date(2025,10,29),DAY,sessions=['2026-10-28',str(DAY)])
        self.assertEqual(fetch.call_args.args[-2:],(DAY,DAY))
        saved=store.read('bars/TEST')
        self.assertEqual(saved['provisional_daily'],{})
        self.assertEqual(saved['bars'][-1]['close'],101.5)
        self.assertEqual(saved['bars'][0]['close'],101)

    def test_five_minute_download_uses_current_endpoint_for_today(self):
        with patch.object(current,'completed_day',return_value=DAY), \
             patch.object(current.upstox,'get',return_value=self.response(raw())), \
             patch.object(market,'download_minutes') as historical:
            detail=market.save_minutes(Mock(),self.item,'token',DAY,DAY,sessions=[str(DAY)])
        historical.assert_not_called()
        self.assertEqual(detail['bars'],75)
        self.assertEqual(detail['missing_sessions'],[])

    def test_wrong_date_response_and_malformed_candle_cannot_advance_calendar(self):
        for rows in [raw('2026-10-28'), [['2026-10-29T09:15:00+05:30',100,0,99,102,10]]]:
            with patch.object(market.upstox,'fetch_range',return_value=[{'date':'2026-10-28'}]), \
                 patch.object(current.upstox,'get',return_value=self.response(rows)):
                with self.assertRaises(ValueError):
                    market.last_traded_day(Mock(),'token',AFTER)

    def test_full_refresh_advances_benchmark_stocks_and_minutes_and_reports_provisional(self):
        yesterday=dict(date='2026-10-28',open=100,high=103,low=99,close=101,volume=700)
        for isin in ['TEST','NIFTY50']:
            store.write('bars/'+isin,dict(bars=[yesterday],requested_start='2025-10-29',requested_end='2026-10-28'))
        with patch.object(current,'completed_day',return_value=DAY), \
             patch.object(market.store,'token',return_value='token'), \
             patch.object(market.upstox,'fetch_range',side_effect=lambda *a:[dict(yesterday)] if a[-2]<DAY else []), \
             patch.object(current.upstox,'get',return_value=self.response(raw())), \
             patch.object(market.upstox,'refresh_universe',return_value={'instruments':[self.item]}), \
             patch.object(market.data_quality,'audit_cached_universe',return_value={'warnings':[],'excluded_symbols':[]}), \
             patch.object(market.time,'sleep'):
            result=market.fetch(Mock(),include_fundamentals=False)
        self.assertEqual(result['end'],str(DAY))
        self.assertEqual(store.read('bars/NIFTY50')['bars'][-1]['date'],str(DAY))
        self.assertEqual(store.read('bars/TEST')['bars'][-1]['date'],str(DAY))
        self.assertEqual(result['provisional_daily_symbols'],['TEST'])
        self.assertTrue(result['partial'])
        self.assertFalse(result['current_session_unverified'])


if __name__ == '__main__':
    unittest.main()
