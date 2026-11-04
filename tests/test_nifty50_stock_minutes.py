from contextlib import nullcontext
from datetime import date,datetime
import unittest
from unittest.mock import patch
from core.research.intraday_data import IST
from scripts.backfill_nifty50_stock_minutes import valid_session,ranges,ingest_response,stock_times
from scripts.pull_nifty_minute_history import expected_times


def session(day):
    return {'bars':[dict(date=day,time=t,
        timestamp=int(datetime.fromisoformat(day+'T'+t).replace(tzinfo=IST).timestamp()*1000),
        open=100.0,high=101.0,low=99.0,close=100.0,volume=1.0) for t in expected_times(day)]}


class StockMinuteBackfillTests(unittest.TestCase):
    def test_official_preopen_is_instrument_and_date_specific(self):
        for isin,day in [('INE154A01025','2025-01-06'),('INE030A01027','2025-12-05'),
                         ('INE155A01022','2025-10-14')]:
            times=stock_times(day,isin)
            self.assertEqual((len(times),times[0],times[-1]),(330,'10:00','15:29'))
            record=session(day)
            record['bars']=[b for b in record['bars'] if b['time'] in set(times)]
            self.assertTrue(valid_session(day,record,isin))
            record['bars']=record['bars'][1:]
            self.assertFalse(valid_session(day,record,isin))
            self.assertEqual(len(stock_times(day,'OTHER_STOCK')),375)

    def test_validate_actual_timestamps_and_prices_not_only_count(self):
        good=session('2026-11-03')
        self.assertTrue(valid_session('2026-11-03',good))
        good['bars'][1]=good['bars'][0]
        self.assertFalse(valid_session('2026-11-03',good))
        bad=session('2026-11-03')
        bad['bars'][0]['low']=200
        self.assertFalse(valid_session('2026-11-03',bad))

    def test_request_only_needed_windows_and_include_end(self):
        result=list(ranges(date(2024,10,1),date(2024,11,3),{'2024-11-01'}))
        self.assertEqual(result,[(date(2024,10,29),date(2024,11,3))])
        self.assertEqual(list(ranges(date(2024,10,1),date(2024,11,3),set())),[])

    def test_quarantine_invalid_provider_day_and_preserve_complete_cached_day(self):
        item=dict(isin='TEST',symbol='TEST')
        day='2026-11-03'
        existing={day:session(day)}
        with patch('scripts.backfill_nifty50_stock_minutes.pg.transaction',side_effect=lambda:nullcontext()), \
             patch('scripts.backfill_nifty50_stock_minutes.store.write') as write:
            result=ingest_response(item,'archive',day,day,
                {'data':{'candles':[[day+'T09:15:00+05:30',100,101,99,100,1]]}},existing,'3')
            self.assertEqual(result,[])
            self.assertEqual(len(existing[day]['bars']),375)
            self.assertEqual(write.call_count,1)  # Raw evidence only; complete cache retained.
            result=ingest_response(item,'archive',day,day,
                {'data':{'candles':[[day+'T09:15:00+05:30',100,101,200,100,1]]}},existing,'3')
            self.assertEqual(result[0]['date'],day)
            self.assertEqual(len(existing[day]['bars']),375)


if __name__=='__main__':unittest.main()
