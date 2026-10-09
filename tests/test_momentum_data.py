import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from core.research import intraday_data, store
from tests.test_momentum import session


class MomentumDataTests(unittest.TestCase):
    def test_cached_sessions_need_no_token(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), patch.object(store,'token') as token:
            store.write(intraday_data.cache_key('ISIN','2025-02-03'), {'bars':session('2025-02-03')})
            data=intraday_data.load_ranges({'2025-02-03':[{'symbol':'A'}]}, {'instruments':[{'symbol':'A','isin':'ISIN','key':'KEY'}]}, lambda m:None)
            self.assertEqual(len(data['A']['2025-02-03']),70)
            token.assert_not_called()

    def test_batches_merge_missing_sessions_and_validate_provider(self):
        rows=[]
        for day in ('2025-02-03','2025-02-04'):
            for b in session(day):
                rows.append([f"{day}T{b['time']}:00+05:30",b['open'],b['high'],b['low'],b['close'],b['volume']])
        response=Mock()
        response.json.return_value={'status':'success','data':{'candles':rows}}
        universe={'instruments':[{'symbol':'A','isin':'ISIN','key':'NSE_EQ|ISIN'}]}
        plan={d:[{'symbol':'A'}] for d in ('2025-02-03','2025-02-04')}
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), patch.object(store,'token',return_value='private-token'), patch.object(intraday_data.upstox,'get',return_value=response) as get:
            result=intraday_data.load_ranges(plan,universe,lambda m:None)
            self.assertEqual(set(result['A']),set(plan))
            self.assertEqual(get.call_count,1)
            self.assertIn('/minutes/5/2025-02-04/2025-02-03',get.call_args.args[1])
            self.assertNotIn('private-token',store.read(intraday_data.cache_key('ISIN','2025-02-03')).__repr__())
            intraday_data.load_ranges(plan,universe,lambda m:None)
            self.assertEqual(get.call_count,1)

    def test_missing_requested_session_fails_without_fabrication(self):
        response=Mock()
        response.json.return_value={'status':'success','data':{'candles':[]}}
        with tempfile.TemporaryDirectory() as folder, patch.object(store,'DATA',Path(folder)), patch.object(store,'token',return_value='token'), patch.object(intraday_data.upstox,'get',return_value=response):
            with self.assertRaisesRegex(ValueError,'No five-minute candles'):
                intraday_data.load_ranges({'2025-02-03':[{'symbol':'A'}]}, {'instruments':[{'symbol':'A','isin':'ISIN','key':'KEY'}]},lambda m:None)
            self.assertIsNone(store.read(intraday_data.cache_key('ISIN','2025-02-03')))
