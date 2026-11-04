import unittest
from unittest.mock import patch, MagicMock
from dashboard.api import intraday


class IntradayCalculatorTests(unittest.TestCase):
    def setUp(self):
        self.member = {'cached': False, 'fetched_at': '2026-11-04', 'instruments': [
            {'symbol': 'TEST', 'name': 'Test stock', 'isin': 'INE123'}]}

    def test_stocks_use_nifty_membership_and_catalog(self):
        with patch.object(intraday, 'membership', return_value=self.member), patch.object(intraday.store, 'read', return_value={
            'INE123': {'close': 123, 'last': '2026-11-03'}, 'OTHER': {'close': 999}}):
            result = intraday.stocks()
        self.assertEqual(len(result['stocks']), 1)
        self.assertEqual(result['stocks'][0]['price'], 123)

    def test_quote_unavailable_uses_dated_close(self):
        with patch.object(intraday, 'membership', return_value=self.member), patch.object(intraday.store, 'token', side_effect=ValueError('Missing')), patch.object(intraday.store, 'read', return_value={'INE123': {'close': 123, 'last': '2026-11-03'}}):
            self.assertEqual(intraday.price('TEST'), {'price': 123, 'as_of': '2026-11-03', 'source': 'Saved daily close (quote unavailable)'})

    def test_missing_price_and_nonmember_are_rejected(self):
        with patch.object(intraday, 'membership', return_value=self.member), patch.object(intraday.store, 'token', side_effect=ValueError('Missing')), patch.object(intraday.store, 'read', return_value={}):
            for symbol in ['TEST', 'OTHER']:
                with self.assertRaises(ValueError):
                    intraday.price(symbol)

    def test_observed_quote(self):
        response = MagicMock()
        response.json.return_value = {'data': {'NSE_EQ:TEST': {'instrument_token': 'NSE_EQ|INE123', 'last_price': 125, 'timestamp': '2026-11-04T10:00:00+05:30'}}}
        with patch.object(intraday, 'membership', return_value=self.member), patch.object(intraday.store, 'token', return_value='test-token'), patch.object(intraday.httpx, 'Client') as client:
            client.return_value.__enter__.return_value.get.return_value = response
            self.assertEqual(intraday.price('TEST')['price'], 125)


if __name__ == '__main__':
    unittest.main()
