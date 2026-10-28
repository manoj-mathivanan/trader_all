"""Upstox account reads and single-attempt order writes. Never retry a POST."""
import gzip
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

import httpx
from core.research import store, upstox


class BrokerError(ValueError):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class Broker:
    def __init__(self, *, transport=None):
        self.client = httpx.Client(timeout=15, follow_redirects=False, transport=transport,
                                  headers={'Authorization': 'Bearer ' + store.token(trading=True), 'Accept': 'application/json'})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def request(self, method, path, *, params=None, payload=None, algo_name=''):
        mutation = method != 'GET'
        host = 'https://api-hft.upstox.com' if mutation else 'https://api.upstox.com'
        try:
            response = self.client.request(method, host + path, params=params, json=payload,
                                           headers={'X-Algo-Name': algo_name} if algo_name else {})
        except httpx.RequestError:
            raise BrokerError('Upstox connection failed. Order outcome needs reconciliation.' if mutation else
                              'Upstox could not be reached.', uncertain=mutation) from None
        try:
            body = response.json()
        except (ValueError, TypeError):
            raise BrokerError('Upstox returned an unreadable response.', uncertain=mutation) from None
        if response.status_code != 200 or body.get('status') != 'success':
            # Provider messages can contain submitted data. Expose codes, never raw bodies or headers.
            codes = ', '.join(str(e.get('errorCode', e.get('error_code', '')))[:40]
                              for e in (body.get('errors') or []) if isinstance(e, dict))
            raise BrokerError(f'Upstox rejected the request (HTTP {response.status_code}; {codes or "provider error"}). '
                              'Check token, permissions, funds, static IP and algo setup.',
                              uncertain=mutation and (response.status_code >= 500 or response.status_code in (200, 408)))
        return body

    def get(self, path, **params):
        return self.request('GET', path, params=params)['data']

    def profile(self):
        return self.get('/v2/user/profile')

    def orders(self):
        return self.get('/v2/order/retrieve-all')

    def order(self, order_id):
        return self.get('/v2/order/details', order_id=order_id)

    def quotes(self, keys):
        result = {}
        keys = sorted(set(keys))
        for offset in range(0, len(keys), 100):
            rows = self.get('/v2/market-quote/quotes', instrument_key=','.join(keys[offset:offset + 100]))
            for row in rows.values():
                result[row['instrument_token']] = row
        return result

    def place(self, payload, algo_name):
        return self.request('POST', '/v3/order/place', payload=payload, algo_name=algo_name)['data']['order_ids']

    def cancel(self, order_id, algo_name):
        return self.request('DELETE', '/v3/order/cancel', params={'order_id': order_id}, algo_name=algo_name)

    def instruments(self):
        cached = store.read('live/instruments', {})
        if cached.get('day') == datetime.now(timezone.utc).date().isoformat():
            return cached['items']
        try:
            # Public instrument master: do not send the account's Authorization header.
            response = httpx.get(upstox.INSTRUMENTS, timeout=30)
            response.raise_for_status()
            raw = response.content
            rows = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
            items = {r['instrument_key']: r for r in rows
                     if r.get('segment') == 'NSE_EQ' and r.get('instrument_type') == 'EQ'}
            if not items:
                raise ValueError()
        except (httpx.HTTPError, ValueError, OSError, KeyError):
            raise BrokerError('Could not load current Upstox equity tick sizes. Orders are blocked.') from None
        store.write('live/instruments', {'day': datetime.now(timezone.utc).date().isoformat(), 'items': items})
        return items


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def quote_price(quote, now, *, fresh=True):
    price = positive(quote.get('last_price'))
    try:
        stamp = quote['timestamp']
        timestamp = (datetime.fromtimestamp(float(stamp) / 1000, timezone.utc)
                     if isinstance(stamp, (float, int)) or str(stamp).isdigit()
                     else datetime.fromisoformat(stamp.replace('Z', '+00:00')))
        age = (now - timestamp).total_seconds()
    except (KeyError, TypeError, ValueError, OverflowError):
        age = float('inf')
    return price if price and (not fresh or -5 <= age <= 60) else None


def limit_price(price, tick_paise, side, protection_bps):
    tick = Decimal(str(tick_paise)) / 100  # Upstox instrument master uses paise.
    if tick <= 0:
        raise ValueError('Invalid exchange tick size.')
    boundary = Decimal(str(price)) * (1 + Decimal(str(protection_bps)) / 10000 * (1 if side == 'BUY' else -1))
    # Round inside the protection boundary, never increase permitted slippage.
    rounding = ROUND_FLOOR if side == 'BUY' else ROUND_CEILING
    return float((boundary / tick).to_integral_value(rounding=rounding) * tick)
