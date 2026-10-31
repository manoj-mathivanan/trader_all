"""Encrypted owner credentials and dated Indian API observations for paper trading."""
from datetime import datetime, timezone
import hashlib
import threading
import time

from core.research import store, identity
from core.research.analyst_consensus import IndianAPIClient, consensus

_lock = threading.RLock()
_clients = {}


def owner():
    name = identity.username()
    if not name:
        raise ValueError('An account identity is required for analyst data.')
    return name


def save_key(value):
    if not value or not isinstance(value, str):
        raise ValueError('An Indian API key is required.')
    store.write('private/indian_api/'+owner(), {'encrypted':store.cipher().encrypt(value.strip().encode()).decode()})


def key():
    record = store.read('private/indian_api/'+owner(), {})
    if not record.get('encrypted'):
        raise ValueError('Indian API access is not configured for this account.')
    return store.cipher().decrypt(record['encrypted'].encode()).decode()


def history(symbol):
    return store.read('analyst_observations/'+owner()+'/'+symbol, [])


def remember(observation):
    symbol = observation['requested_symbol']
    name = 'analyst_observations/'+owner()+'/'+symbol
    with store.LOCK:
        rows = store.read(name, [])
        if not any(row['observed_at'] == observation['observed_at'] for row in rows):
            rows.append(observation)
            store.write(name, sorted(rows, key=lambda row:row['observed_at']))


def collect(item, log=lambda message:None):
    """Reuse today's snapshot across portfolios; failures block buys, never exits."""
    name = owner()
    with _lock:
        today = datetime.now(timezone.utc).date().isoformat()
        existing = [row for row in history(item['symbol']) if row.get('expected_isin') == item['isin']]
        if existing and existing[-1]['observed_at'][:10] == today:
            return existing[-1]
        failure_key = 'analyst_failures/'+name+'/'+item['symbol']
        if store.read(failure_key, {}).get('day') == today:
            return None
        try:
            secret = key()
            fingerprint = hashlib.sha256(secret.encode()).hexdigest()
            cached = _clients.get(name)
            if not cached or cached[0] != fingerprint:
                if cached:cached[1].close()
                cached = (fingerprint,IndianAPIClient(secret))
                _clients[name] = cached
            # Persistent pacing also covers process restarts and other local workers.
            with store.LOCK:
                next_time = store.read('analyst_rate_limit/'+name, {}).get('next_request_epoch', 0)
                time.sleep(max(0,next_time-time.time()))
                failure = None
                try:observation = cached[1].stock(item['symbol'])
                except Exception as exc:failure = exc
                store.write('analyst_rate_limit/'+name, {'next_request_epoch':time.time()+1.05})
            if failure:raise ValueError('Indian API observation unavailable.') from None
            payload = observation['payload']
            if not isinstance(payload,dict):payload={}
            profile = payload.get('companyProfile') or {}
            observation.update(requested_symbol=item['symbol'], expected_isin=item['isin'],
                               provider_isin=profile.get('isInId'), provider_symbol=profile.get('exchangeCodeNse'),
                               identity_verified=profile.get('isInId') == item['isin'])
            observation['payload'] = {k:payload.get(k) for k in ('companyName','companyProfile','analystView','recosBar')}
            try:observation['normalized'] = consensus(observation['payload'])
            except (ValueError,TypeError,KeyError):observation['normalized']={'status':'invalid'}
            remember(observation)
            return observation
        except Exception:
            store.write(failure_key, {'day':today,'at':store.now(),'status':'unavailable'})
            log('Indian API unavailable for '+item['symbol']+'; new buys require a prior valid snapshot. Exits remain active.')
            return None


def at_open(symbol, day):
    from datetime import time as day_time
    from zoneinfo import ZoneInfo
    opening = datetime.combine(datetime.fromisoformat(day).date(),day_time(9,15),ZoneInfo('Asia/Kolkata'))
    rows = [row for row in history(symbol) if datetime.fromisoformat(row['observed_at']) <= opening]
    return max(rows,key=lambda row:row['observed_at']) if rows else None
