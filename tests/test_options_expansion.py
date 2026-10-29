from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from core.research import options_backtest as bt, options_history as history, options_costs


class ExpansionTests(unittest.TestCase):
    def test_complete_catalog_expiry_ranges_compression_and_resume(self):
        observed = []
        def handler(req):
            path = req.url.path
            observed.append(path)
            if path.endswith('/expiries'):
                data = ['2026-10-06', '2026-10-13']
            elif path.endswith('/option/contract'):
                expiry = req.url.params['expiry_date']
                data = [dict(instrument_key=expiry, expiry=expiry, underlying_key=history.UNDERLYING,
                             instrument_type='CE', strike_price=22500, lot_size=65)]
            else:
                day = '2026-10-06' if '2026-10-06' in path else '2026-10-07'
                data = dict(candles=[[day+'T09:15:00+05:30', 250, 260, 240, 255, 65, 130]])
            return httpx.Response(200, json=dict(status='success', data=data))
        underlying = (dict(start='2026-10-06', end='2026-10-07'),
                      [dict(date='2026-10-06'), dict(date='2026-10-07')], [])
        with tempfile.TemporaryDirectory() as tmp, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch.object(bt, 'load_underlying', return_value=underlying), patch.object(history.time, 'sleep'):
            args = dict(start=date(2026,10,6), end=date(2026,10,7), output=tmp, log=lambda _:None)
            result = history.download_research(client, 'secret', **args)
            self.assertEqual(result['status'], 'research_downloaded')
            self.assertEqual(result['expected_contracts'], 2)
            self.assertTrue(all(r['file'].endswith('.json.gz') for r in result['files']))
            bars, catalogs, expiries = bt.load_option_sample(tmp)
            self.assertEqual(len(bars), 2)
            self.assertEqual(len(catalogs), 2)
            self.assertEqual(len(expiries), 2)
            before = sum('/historical-candle/' in path for path in observed)
            history.download_research(client, 'secret', **args)
            self.assertEqual(before, sum('/historical-candle/' in path for path in observed))
            # Corrupted archives are re-downloaded, never silently reused.
            (Path(tmp)/result['files'][0]['file']).write_bytes(b'bad')
            history.download_research(client, 'secret', **args)
            self.assertEqual(before+1, sum('/historical-candle/' in path for path in observed))


class FeeTests(unittest.TestCase):
    def test_plus_fee_components_and_stt_boundary(self):
        buy = options_costs.fees(250,65,'buy','2026-10-05')
        sell = options_costs.fees(250,65,'sell','2026-10-05')
        self.assertEqual(buy['brokerage'], 30)
        self.assertEqual(buy['stt'], 0)
        self.assertAlmostEqual(buy['stamp'], .4875)
        self.assertAlmostEqual(sell['stt'], 24.375)
        self.assertEqual(sell['stamp'], 0)
        self.assertAlmostEqual(buy['total'], sum(v for k,v in buy.items() if k!='total'))
        before = options_costs.fees(250,65,'sell','2026-03-31')
        after = options_costs.fees(250,65,'sell','2026-04-01')
        self.assertAlmostEqual(after['total']-before['total'], 8.125)


if __name__ == '__main__':
    unittest.main()
