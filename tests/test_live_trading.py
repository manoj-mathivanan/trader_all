import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from core.execution.upstox_live import Broker, BrokerError, limit_price, quote_price
from core.portfolio import live
from core.research import store


KEY = 'NSE_EQ|INE000A01001'
ITEM = {'key': KEY, 'isin': 'INE000A01001', 'symbol': 'EXAMPLE', 'name': 'Example'}
NOW = datetime(2026, 10, 16, 9, 20, tzinfo=live.IST)


class Exchange:
    def __init__(self):
        self.calls = []
        self.book = []
        self.positions = []
        self.holdings = []
        self.price = 100
        self.quote_time = NOW.isoformat()
        self.user = 'ACCOUNT1'
        self.status = 'NORMAL_OPEN'
        self.fail_post = None
        self.fail_read = None

    def handler(self, request):
        self.calls.append(request)
        path = request.url.path
        if self.fail_read and request.method == 'GET':
            return httpx.Response(401, json={'status': 'error', 'errors': [{'errorCode': 'UDAPI100050'}]})
        if request.method == 'POST':
            if self.fail_post == 'timeout':
                raise httpx.ReadTimeout('contains-private-token', request=request)
            if self.fail_post == '500':
                return httpx.Response(500, json={'status': 'error', 'errors': None})
            if self.fail_post == '400':
                return httpx.Response(400, json={'status': 'error', 'errors': [{'errorCode': 'TEST', 'message': 'test-private-token'}]})
            payload = json.loads(request.content)
            row = {**payload, 'instrument_token': payload['instrument_token'], 'order_id': str(len(self.book) + 1),
                   'status': 'open', 'filled_quantity': 0, 'average_price': 0,
                   'pending_quantity': payload['quantity'], 'trading_symbol': 'EXAMPLE'}
            self.book.append(row)
            return httpx.Response(200, json={'status': 'success', 'data': {'order_ids': [row['order_id']]}})
        if request.method == 'DELETE':
            self.book[0]['status'] = 'cancelled'
            return httpx.Response(200, json={'status': 'success', 'data': {'order_id': self.book[0]['order_id']}})
        if path == '/v2/user/profile':
            data = {'user_id': self.user, 'user_name': 'Test', 'is_active': True}
        elif path == '/v2/portfolio/long-term-holdings':
            data = self.holdings
        elif path == '/v2/portfolio/short-term-positions':
            data = self.positions
        elif path == '/v2/order/retrieve-all':
            data = self.book
        elif path == '/v2/order/details':
            data = next(r for r in self.book if r['order_id'] == request.url.params['order_id'])
        elif path == '/v2/order/trades/get-trades-for-day':
            data = []
        elif path == '/v2/user/get-funds-and-margin':
            data = {'equity': {'available_margin': 100000}}
        elif path == '/v2/market-quote/quotes':
            data = {KEY: {'instrument_token': KEY, 'last_price': self.price, 'timestamp': self.quote_time,
                          'ohlc': {'close': 100}}}
        elif path == '/v2/market/status/NSE':
            data = {'status': self.status}
        elif '/historical-candle/' in path:
            data = {'candles': [['2026-10-15T00:00:00+05:30', 100, 101, 99, 100, 1000]]}
        elif path == '/v2/charges/historical-trades':
            data = [{'trade_date': '2026-10-15', 'symbol': 'EXAMPLE', 'quantity': 1, 'price': 100}]
        else:
            raise AssertionError('Unexpected API: ' + str(request.url))
        return httpx.Response(200, json={'status': 'success', 'data': data})


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for context in (patch.object(store, 'DATA', Path(self.temp.name)),
                        patch.dict(os.environ, {'TRADER_STORAGE': 'json'}),
                        patch.object(store, 'token', return_value='test-private-token'),
                        patch.object(live, 'clock', return_value=NOW)):
            context.start()
            self.addCleanup(context.stop)
        live._stop.clear()
        self.exchange = Exchange()
        self.broker = Broker(transport=httpx.MockTransport(self.exchange.handler))
        self.addCleanup(self.broker.client.close)
        self.master = patch.object(Broker, 'instruments', return_value={KEY: {'tick_size': 5, 'lot_size': 1}})
        self.master.start()
        self.addCleanup(self.master.stop)
        self.plan = {'signal_day': '2026-10-15', 'matches': [{**ITEM, 'signal_day': '2026-10-15', 'close': 100, 'score': 80}], 'excluded': []}
        self.signal_patch = patch.object(live, 'candidates', return_value=copy.deepcopy(self.plan))
        self.signal_patch.start()
        self.addCleanup(self.signal_patch.stop)
        store.write('live/config', live.LiveConfig().model_dump(mode='json'))
        store.write('live/connection', live.Connection(expected_user_id='ACCOUNT1', static_ip_confirmed=True,
                                                       delivery_sell_authorized=True, algo_name='my-algo').model_dump())

    def cycle(self, **kw):
        return live.cycle(self.broker, execute=True, now=NOW, **kw)

    def mutations(self):
        return [r for r in self.exchange.calls if r.method != 'GET']

    def fill_buy(self, quantity=None):
        order = self.exchange.book[0]
        filled = quantity if quantity is not None else order['quantity']
        order.update(filled_quantity=filled, average_price=100, pending_quantity=order['quantity'] - filled,
                     status='complete' if filled == order['quantity'] else 'open')
        self.exchange.positions = [{'instrument_token': KEY, 'product': 'D', 'quantity': filled,
                                    'day_buy_quantity': filled, 'day_sell_quantity': 0, 'average_price': 100}]

    def test_preview_reads_only_and_no_activation_on_import(self):
        result = live.cycle(self.broker, now=NOW)
        self.assertEqual(result['signal_day'], '2026-10-15')
        self.assertEqual(self.mutations(), [])
        self.assertFalse(live.public_state()['running'])

    def test_order_contract_limits_tag_header_and_durable_intent(self):
        original = self.broker.place
        def inspect(payload, algo):
            saved = live.ledger()['orders'][0]
            self.assertEqual(saved['status'], 'submitting')
            self.assertEqual(saved['tag'], payload['tag'])
            return original(payload, algo)
        with patch.object(self.broker, 'place', side_effect=inspect):
            self.cycle()
        request = self.mutations()[0]
        payload = json.loads(request.content)
        self.assertEqual(request.url.host, 'api-hft.upstox.com')
        self.assertEqual(request.url.path, '/v3/order/place')
        self.assertEqual(request.headers['X-Algo-Name'], 'my-algo')
        self.assertEqual(payload['order_type'], 'LIMIT')
        self.assertEqual(payload['product'], 'D')
        self.assertFalse(payload['is_amo'])
        self.assertFalse(payload['slice'])
        self.assertLessEqual(payload['quantity'] * payload['price'], 6250)  # 0.5% risk / 8% stop
        self.assertEqual(live.ledger()['orders'][0]['status'], 'submitted')
        self.assertNotIn('test-private-token', json.dumps(live.public_state()))

    def test_pending_and_repeated_signal_do_not_duplicate_buys(self):
        self.cycle()
        self.cycle()
        self.fill_buy()
        self.cycle()
        self.cycle()
        self.assertEqual(len(self.mutations()), 1)

    def test_partial_fills_are_applied_once_then_cumulative_completion(self):
        self.cycle()
        self.fill_buy(5)
        self.cycle()
        self.cycle()
        self.assertEqual(live.ledger()['positions'][KEY]['quantity'], 5)
        self.fill_buy()
        self.cycle()
        self.assertEqual(live.ledger()['positions'][KEY]['quantity'], self.exchange.book[0]['quantity'])

    def test_pause_blocks_entries_but_target_still_exits_and_books_realized_fills(self):
        self.cycle()
        self.fill_buy()
        self.cycle()
        store.write('live/control', {'paused': True})
        cfg = live.LiveConfig(winner_exit='take_8')
        live.save_config(cfg)
        self.exchange.price = 110
        self.cycle()
        self.assertEqual(len(self.mutations()), 2)
        sell = self.exchange.book[1]
        self.assertEqual(sell['transaction_type'], 'SELL')
        qty = sell['quantity']
        sell.update(status='complete', filled_quantity=qty, average_price=110, pending_quantity=0)
        self.exchange.positions[0].update(day_sell_quantity=qty, quantity=0)
        self.cycle()
        self.assertFalse(live.ledger()['positions'])
        self.assertAlmostEqual(live.ledger()['realized_pnl'], qty * 10)

    def test_pause_without_positions_places_no_orders(self):
        store.write('live/control', {'paused': True})
        self.cycle()
        self.assertEqual(self.mutations(), [])

    def test_config_changes_apply_to_existing_stops(self):
        self.cycle()
        self.fill_buy()
        self.cycle()
        live.save_config(live.LiveConfig(stop_pct=2))
        self.exchange.price = 97
        self.cycle()
        self.assertEqual(self.exchange.book[-1]['transaction_type'], 'SELL')
        self.assertEqual(live.ledger()['positions'][KEY]['stop_price'], 98)

    def test_stale_quote_prevents_entry_and_held_exit(self):
        self.exchange.quote_time = (NOW - timedelta(minutes=2)).isoformat()
        self.cycle()
        self.assertEqual(self.mutations(), [])
        self.exchange.quote_time = NOW.isoformat()
        self.cycle()
        self.fill_buy()
        self.exchange.quote_time = (NOW - timedelta(minutes=2)).isoformat()
        with self.assertRaisesRegex(ValueError, 'fresh quote'):
            self.cycle()
        self.assertEqual(len(self.mutations()), 1)

    def test_holiday_and_outside_window_do_not_submit(self):
        self.exchange.status = 'NORMAL_CLOSE'
        self.cycle()
        self.assertEqual(self.mutations(), [])
        self.exchange.status = 'NORMAL_OPEN'
        live.cycle(self.broker, execute=True, now=NOW.replace(hour=16))
        self.assertEqual(self.mutations(), [])

    def test_account_mismatch_and_incomplete_connection_block(self):
        self.exchange.user = 'WRONG'
        with self.assertRaisesRegex(ValueError, 'account differs'):
            self.cycle()
        self.exchange.user = 'ACCOUNT1'
        store.write('live/connection', live.Connection(expected_user_id='ACCOUNT1').model_dump())
        with self.assertRaisesRegex(ValueError, 'static IP'):
            self.cycle()
        self.assertEqual(self.mutations(), [])

    def test_timeout_and_500_never_retry_post_and_unknown_blocks_next_cycle(self):
        for failure in ('timeout', '500'):
            store.write('live/ledger', {'account_id': None, 'positions': {}, 'orders': [], 'realized_pnl': 0, 'daily_baselines': {}})
            self.exchange.fail_post = failure
            count = len(self.mutations())
            with self.assertRaises(BrokerError):
                self.cycle()
            self.assertEqual(live.ledger()['orders'][0]['status'], 'unknown')
            with self.assertRaisesRegex(ValueError, 'unknown'):
                self.cycle()
            self.assertEqual(len(self.mutations()), count + 1)
            self.assertNotIn('test-private-token', json.dumps(live.public_state()))

    def test_explicit_rejection_is_retained_and_not_retried_same_signal(self):
        self.exchange.fail_post = '400'
        with self.assertRaises(BrokerError):
            self.cycle()
        self.assertEqual(live.ledger()['orders'][0]['status'], 'rejected')
        self.cycle()
        self.assertEqual(len(self.mutations()), 1)

    def test_crash_after_broker_accept_recovers_by_tag(self):
        self.cycle()
        state = live.ledger()
        state['orders'][0].update(status='submitting', order_ids=[])
        store.write('live/ledger', state)
        self.fill_buy(5)
        self.cycle()
        self.assertEqual(live.ledger()['positions'][KEY]['quantity'], 5)
        self.assertEqual(len(self.mutations()), 1)

    def test_open_order_ttl_cancels_before_new_order(self):
        self.cycle()
        state = live.ledger()
        state['orders'][0]['created_at'] = (NOW - timedelta(minutes=2)).isoformat()
        store.write('live/ledger', state)
        self.cycle()
        self.assertEqual(self.mutations()[-1].method, 'DELETE')
        self.assertEqual(self.mutations()[-1].url.path, '/v3/order/cancel')

    def test_settings_change_cancels_unfilled_order_before_another_request(self):
        self.cycle()
        live.save_config(live.LiveConfig(risk_pct=1))
        self.cycle()
        self.assertEqual(self.mutations()[-1].method, 'DELETE')
        self.assertEqual(len(self.mutations()), 2)

    def test_expired_order_detail_is_unknown_and_historical_fill_can_be_reconciled(self):
        self.cycle()
        original = live.ledger()['orders'][0]
        self.exchange.book = []
        with patch.object(self.broker, 'order', side_effect=BrokerError('No longer available')):
            with self.assertRaisesRegex(ValueError, 'history'):
                self.cycle()
        self.assertEqual(live.ledger()['orders'][0]['status'], 'unknown')
        with patch.object(live, 'Broker', return_value=self.broker):
            result = live.resolve_unknown(original['id'], '1', False,
                                          {'status': 'complete', 'filled_quantity': original['quantity'], 'average_price': 100})
        self.assertEqual(result['ledger']['positions'][KEY]['quantity'], original['quantity'])
        self.assertEqual(result['ledger']['orders'][0]['status'], 'complete')
        self.assertEqual(len(self.mutations()), 1)

    def test_quote_that_expires_during_instrument_lookup_cannot_be_submitted(self):
        def slow_lookup():
            live.clock.return_value = NOW + timedelta(minutes=2)
            return {KEY: {'tick_size': 5, 'lot_size': 1}}
        with patch.object(self.broker, 'instruments', side_effect=slow_lookup):
            with self.assertRaisesRegex(ValueError, 'stale before submission'):
                self.cycle()
        self.assertFalse(live.ledger()['orders'])
        self.assertFalse(self.mutations())

    def test_external_holdings_and_orders_are_not_adopted(self):
        self.exchange.holdings = [{'instrument_token': KEY, 'quantity': 10, 'average_price': 90}]
        self.cycle()
        self.assertEqual(self.mutations(), [])
        self.assertFalse(live.ledger()['positions'])
        self.exchange.holdings = []
        self.exchange.book = [{'order_id': 'manual', 'instrument_token': KEY, 'transaction_type': 'BUY', 'price': 100,
                               'pending_quantity': 1, 'status': 'open', 'quantity': 1}]
        self.cycle()
        self.assertEqual(self.mutations(), [])

    def test_manual_sell_or_quantity_disagreement_blocks_automatic_exit(self):
        self.cycle()
        self.fill_buy()
        self.cycle()
        self.exchange.positions[0]['day_buy_quantity'] = 0
        self.exchange.price = 90
        with self.assertRaisesRegex(ValueError, 'quantity is below'):
            self.cycle()
        self.assertEqual(len(self.mutations()), 1)

    def test_daily_loss_gate_blocks_additional_entries(self):
        store.write('live/ledger', {'account_id': 'ACCOUNT1', 'orders': [], 'positions': {}, 'realized_pnl': -3000,
                                    'daily_baselines': {'2026-10-16': 0}})
        self.cycle()
        self.assertEqual(self.mutations(), [])

    def test_config_cannot_reduce_capital_below_committed_exposure(self):
        self.cycle()
        with self.assertRaisesRegex(ValueError, 'capital cannot'):
            live.save_config(live.LiveConfig(capital=1000))

    def test_insufficient_funds_and_daily_cap_block_entries(self):
        live.save_config(live.LiveConfig(max_daily_buy_value=100))
        # At a protected 100.50 buy limit even one share exceeds the daily cap.
        self.cycle()
        self.assertEqual(self.mutations(), [])

    def test_history_dates_and_pagination_contract(self):
        result = live.history(date(2026, 10, 1), date(2026, 10, 15), 2, broker=self.broker)
        req = self.exchange.calls[-1]
        self.assertEqual(req.url.params['page_number'], '2')
        self.assertEqual(req.url.params['page_size'], '100')
        self.assertEqual(result['page'], 2)
        self.assertFalse(result['has_more'])
        with self.assertRaises(ValueError):
            live.history(date(2026, 10, 15), date(2026, 10, 1), broker=self.broker)

    def test_holdings_pnl_uses_current_quote_and_does_not_add_t1_twice(self):
        self.exchange.holdings = [{'instrument_token': KEY, 'quantity': 10, 't1_quantity': 5,
                                   'average_price': 90, 'last_price': 1}]
        account = live.refresh_account(self.broker, now=NOW)
        self.assertEqual(account['holdings'][0]['current_unrealized_pnl'], 100)
        self.assertEqual(live.account_quantity(account, KEY), 10)

    def test_provider_auth_failure_contains_no_secret(self):
        self.exchange.fail_read = True
        with self.assertRaises(BrokerError) as error:
            self.cycle()
        self.assertNotIn('test-private-token', str(error.exception))
        self.assertEqual(self.mutations(), [])

    def test_price_tick_rounding_and_invalid_stale_or_future_prices(self):
        self.assertEqual(limit_price(100, 5, 'BUY', 50), 100.5)
        self.assertEqual(limit_price(100.01, 5, 'SELL', 50), 99.55)
        for value in (float('nan'), float('inf'), -1, 0):
            self.assertIsNone(quote_price({'last_price': value, 'timestamp': NOW.isoformat()}, NOW))
        self.assertIsNone(quote_price({'last_price': 100, 'timestamp': (NOW + timedelta(minutes=1)).isoformat()}, NOW))

    def test_new_configuration_validates_unknown_fields_and_nonfinite_values(self):
        for value in ({'capital': float('nan')}, {'max_positions': 0}, {'filters': {'min_rs_rating': 50}}):
            with self.assertRaises(ValueError):
                live.LiveConfig(**value)

    def test_real_candidate_engine_uses_only_latest_completed_session_and_fundamentals(self):
        self.signal_patch.stop()
        store.write('universes/niftytotalmarket', {'instruments': [ITEM]})
        bars = [{'date': (date(2026, 10, 15) - timedelta(days=60 - i)).isoformat(),
                 'open': 99, 'high': 101, 'low': 98, 'close': 100, 'volume': 1000000} for i in range(61)]
        bars[-1].update(open=100, high=111, close=110, volume=2000000)
        bars.append({'date': '2026-10-16', 'open': 900, 'high': 1000, 'low': 900, 'close': 999, 'volume': 9999999})
        store.write('bars/' + ITEM['isin'], {'bars': bars})
        cfg = live.LiveConfig(filters={'pattern': 'breakout'})
        with patch.object(live, 'current_settings', return_value=type('Settings', (), {'universe': 'niftytotalmarket'})()), \
             patch.object(live.fundamentals, 'buy_check', return_value={'buy_allowed': True, 'score': 80}):
            result = live.candidates(self.broker, cfg, NOW)
            self.assertEqual(result['matches'][0]['close'], 110)
            self.assertEqual(result['signal_day'], '2026-10-15')
        bars.pop(-2)
        store.write('bars/' + ITEM['isin'], {'bars': bars})
        with patch.object(live, 'current_settings', return_value=type('Settings', (), {'universe': 'niftytotalmarket'})()):
            result = live.candidates(self.broker, cfg, NOW)
            self.assertFalse(result['matches'])
            self.assertIn('Missing latest', result['excluded'][0]['reason'])

    def test_api_origin_validation_live_acknowledgment_and_config_update(self):
        from dashboard.api import main
        with patch.object(main, 'USER', ''), TestClient(main.app) as client:
            self.assertEqual(client.post('/api/live/start', json={'acknowledge_real_orders': True}).status_code, 403)
            response = client.post('/api/live/start', headers={'X-Trader-Request': 'local-ui'}, json={})
            self.assertEqual(response.status_code, 400)
            response = client.put('/api/live/config', headers={'X-Trader-Request': 'local-ui'},
                                  json=live.LiveConfig(risk_pct=1).model_dump(mode='json'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['config']['risk_pct'], 1)
            self.assertFalse(response.json()['running'])
            with patch.object(main, 'PUBLIC_ORIGIN', 'https://example.test'):
                self.assertEqual(client.get('/api/live').status_code, 403)
            with patch.object(main, 'USER', 'admin'), patch.object(main, 'PASSWORD', 'test-password'):
                self.assertEqual(client.get('/api/live').status_code, 401)
                self.assertEqual(client.get('/api/live', auth=('admin', 'test-password')).status_code, 200)


if __name__ == '__main__':
    unittest.main()
