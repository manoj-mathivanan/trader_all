import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from core.research import options_history as history, options_strategy
from core.strategies.four_indicator import indicators


class OptionsDataTests(unittest.TestCase):
    def test_plus_rejection_distinct_from_expired_token(self):
        for code, status, message in [('UDAPI1149', 403, 'Plus'), ('UDAPI100050', 401, 'expired')]:
            transport = httpx.MockTransport(lambda req: httpx.Response(status,
                json={'status': 'error', 'errors': [{'errorCode': code}]}))
            with httpx.Client(transport=transport) as client:
                with self.assertRaisesRegex(history.ProviderError, message) as error:
                    history.request(client, 'private-test-token', '/v2/expired-instruments/expiries')
                self.assertNotIn('private-test-token', str(error.exception))

    def test_offset_conversion_oi_and_invalid_candles(self):
        start = end = date(2026, 10, 20)
        raw = [['2026-10-20T03:45:00Z', 100, 110, 90, 105, 200, 300]]
        bar = history.normalize_candles(raw, start, end)[0]
        self.assertEqual((bar['time'], bar['open_interest']), ('09:15', 300))
        variants = [raw + raw,
                    [['2026-10-20T09:15:00', 100, 110, 90, 105, 200]],
                    [['2026-10-19T09:15:00+05:30', 100, 110, 90, 105, 200]],
                    [['2026-10-20T09:15:00+05:30', 100, 99, 90, 105, 200]],
                    [['2026-10-20T09:15:00+05:30', 100, 110, 90, 105, 200, -1]]]
        for invalid in variants:
            with self.assertRaises(ValueError):
                history.normalize_candles(invalid, start, end)

    def test_historical_contract_identity_and_lot_size(self):
        contract = dict(instrument_key='NSE_FO|123|20-10-2026', expiry='2026-10-20',
                        underlying_key=history.UNDERLYING, instrument_type='CE', lot_size=65, strike_price=25000)
        self.assertEqual(history.validate_contracts([contract], '2026-10-20'), [contract])
        for changed in [dict(contract, lot_size=0), dict(contract, expiry='2026-10-27'),
                        dict(contract, underlying_key='OTHER'), dict(contract, strike_price=float('nan'))]:
            with self.assertRaises(ValueError):
                history.validate_contracts([changed], '2026-10-20')
        with self.assertRaises(ValueError):
            history.validate_contracts([contract, contract], '2026-10-20')

    def test_failed_access_stops_before_contract_download(self):
        calls = []
        def handler(req):
            calls.append(req.url.path)
            if '/expiries' in req.url.path:
                return httpx.Response(403, json={'status': 'error', 'errors': [{'errorCode': 'UDAPI1149'}]})
            return httpx.Response(200, json={'status': 'success', 'data': {'candles': []}})
        with tempfile.TemporaryDirectory() as tmp, httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(history.ProviderError):
                history.download_sample(client, 'private-test-token', start=date(2026, 10, 5),
                    end=date(2026, 10, 16), output=tmp)
            evidence = json.loads((Path(tmp)/'access.json').read_text())
            self.assertEqual(evidence['expired_options']['status'], 'unavailable')
            self.assertEqual(len(calls), 2)
            self.assertFalse((Path(tmp)/'manifest.json').exists())

    def test_sample_preserves_catalog_raw_oi_and_records_empty_contract(self):
        expiry = '2026-10-20'
        contracts = [dict(instrument_key=f'NSE_FO|{kind}|20-10-2026', expiry=expiry,
            underlying_key=history.UNDERLYING, instrument_type=kind, lot_size=65, strike_price=25000)
            for kind in ('CE', 'PE')]
        raw = [['2026-10-16T09:15:00+05:30', 25000, 25001, 24999, 25000, 0, 0]]
        def handler(req):
            path = req.url.path
            if path.endswith('/expiries'):
                data = [expiry]
            elif path.endswith('/option/contract'):
                data = contracts
            elif '/v3/' in path:
                data = {'candles': raw}
            else:
                self.assertIn('20-10-2026', path)
                data = {'candles': [] if '|PE|' in path else [
                    ['2026-10-16T09:15:00+05:30', 250, 255, 245, 251, 65, 130]]}
            return httpx.Response(200, json={'status': 'success', 'data': data})
        with tempfile.TemporaryDirectory() as tmp, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch.object(history.time, 'sleep'):
            result = history.download_sample(client, 'private-test-token', start=date(2026, 10, 5),
                end=date(2026, 10, 16), output=tmp, max_contracts=2)
            self.assertFalse(result['backtest_ready'])
            self.assertEqual(result['status'], 'sample_downloaded_with_warnings')
            self.assertEqual(len(result['failures']), 1)
            self.assertEqual(len(result['files']), 3)
            self.assertEqual(json.loads((Path(tmp)/'contracts.json').read_text()), contracts)
            evidence = next(x for x in result['files'] if x.get('instrument', {}).get('instrument_type') == 'CE')
            saved = json.loads((Path(tmp)/evidence['file']).read_text())
            self.assertEqual(saved['bars'][0]['open_interest'], 130)
            self.assertEqual(saved['raw_response']['data']['candles'][0][6], 130)
            from core.research.options_backtest import load_option_sample
            loaded, catalogs, expiries = load_option_sample(tmp)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(catalogs[expiry], contracts)
            self.assertEqual(expiries, [expiry])
            (Path(tmp)/evidence['file']).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                load_option_sample(tmp)


class OptionsSignalTests(unittest.TestCase):
    def bars(self):
        start = datetime(2026, 10, 20, 9, 15, tzinfo=history.IST)
        return [dict(date='2026-10-20', timestamp=int((start+timedelta(minutes=3*i)).timestamp()*1000),
            close=100+i*.2, open=100+i*.2, high=101+i*.2, low=99+i*.2) for i in range(120)]

    def test_default_bands_unchanged_and_22_period_warmup(self):
        bars = self.bars()
        default = indicators(bars)
        explicit = indicators(bars, bollinger_period=20)
        self.assertEqual(default, explicit)
        values = indicators(bars, bollinger_period=22)
        self.assertIsNone(values[20]['upper_band'])
        self.assertIsNotNone(values[21]['lower_band'])
        self.assertEqual(default[-1]['supertrend'], values[-1]['supertrend'])

    def test_future_changes_cannot_change_past_signals(self):
        bars = self.bars()
        prior = {'2026-10-20': dict(high=105, low=95, close=100)}
        prefix = options_strategy.signals(bars[:105], prior)
        extended = copy.deepcopy(bars)
        for bar in extended[105:]:
            bar.update(close=500, high=501, low=499)
        self.assertEqual(prefix, options_strategy.signals(extended, prior)[:105])
        self.assertTrue(all(not x['ready'] for x in prefix[:99]))

    def test_both_directions_require_all_four_checks(self):
        values = [dict(uptrend=True, supertrend=90, rsi=75, upper_band=110, lower_band=80)]*120
        bars = self.bars()
        prior = {'2026-10-20': dict(high=105, low=95, close=100)}
        with patch.object(options_strategy, 'indicators', return_value=values):
            self.assertTrue(options_strategy.signals(bars, prior)[-1]['call'])
        values = [dict(uptrend=False, supertrend=140, rsi=25, upper_band=150, lower_band=130)]*120
        prior = {'2026-10-20': dict(high=150, low=130, close=140)}
        with patch.object(options_strategy, 'indicators', return_value=values):
            result = options_strategy.signals(bars, prior)[-1]
            self.assertTrue(result['put'])
            self.assertFalse(result['call'])
            self.assertTrue(result['exit_call'])
            self.assertFalse(options_strategy.signals(bars, {})[-1]['ready'])


if __name__ == '__main__':
    unittest.main()
