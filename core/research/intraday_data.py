"""Validated five-minute Upstox history, cached separately from daily history."""
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx
from core.research import store, upstox

IST = timezone(timedelta(hours=5, minutes=30))
SPECIAL_SESSIONS = {
    '2024-11-01': {'open': '18:00', 'close': '19:00',
                   'source': 'https://nsearchives.nseindia.com/content/circulars/CMTR64628.pdf'},
    '2025-10-21': {'open': '13:45', 'close': '14:45',
                   'source': 'https://nsearchives.nseindia.com/content/circulars/CMTR70319.pdf'},
}


def normalize(raw, day, interval_minutes=5):
    if interval_minutes not in (1, 5):
        raise ValueError('Supported minute intervals are 1 and 5.')
    result, seen = [], set()
    for row in raw:
        if len(row) < 6:
            raise ValueError('Malformed five-minute candle.')
        instant = datetime.fromisoformat(row[0])
        if instant.tzinfo is None:
            raise ValueError('Intraday candle requires an explicit timezone.')
        instant = instant.astimezone(IST)
        if instant.date().isoformat()!=day or instant.minute%interval_minutes or instant.second or instant.microsecond:
            raise ValueError('Intraday candle is outside its requested session or five-minute boundary.')
        timestamp = int(instant.timestamp()*1000)
        if timestamp in seen:
            raise ValueError('Duplicate intraday candle.')
        seen.add(timestamp)
        o,h,l,c,v = map(float,row[1:6])
        if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c) or l>h:
            raise ValueError('Invalid intraday OHLCV candle.')
        result.append(dict(date=day,time=f'{instant.hour:02d}:{instant.minute:02d}',timestamp=timestamp,
                           open=o,high=h,low=l,close=c,volume=v))
    return sorted(result,key=lambda x:x['timestamp'])


def cache_key(isin, day, interval_minutes=5):
    return f'intraday/{interval_minutes}m/{isin}/{day}'


def cached_bars(record, day, interval_minutes=5):
    raw = [[datetime.fromtimestamp(b['timestamp']/1000, IST).isoformat(),
            b['open'], b['high'], b['low'], b['close'], b['volume']] for b in record['bars']]
    return normalize(raw, day, interval_minutes)


def fetch(item, day, token, interval_minutes=5):
    key = cache_key(item['isin'],day,interval_minutes)
    cached = store.read(key)
    if cached:
        return cached_bars(cached, day, interval_minutes)
    url = f"https://api.upstox.com/v3/historical-candle/{quote(item['key'],safe='')}/minutes/{interval_minutes}/{day}/{day}"
    with httpx.Client(timeout=30) as client:
        payload = upstox.get(client,url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'}).json()
    if payload.get('status')!='success':
        raise ValueError('Upstox did not return successful intraday data.')
    bars = normalize(payload.get('data',{}).get('candles',[]),day,interval_minutes)
    if not bars:
        raise ValueError(f"No five-minute candles for {item['symbol']} on {day}.")
    store.write(key,dict(instrument=item,interval_minutes=interval_minutes,source='Upstox historical V3',fetched_at=store.now(),bars=bars))
    return bars


def load_sessions(plan, universe, log):
    """Fetch only eligible signal dates; cached sessions need no new authentication."""
    instruments = {x['symbol']:x for x in universe['instruments']}
    requests = {(x['symbol'],day) for day,candidates in plan.items() for x in candidates}
    sessions = {}
    missing = [(symbol,day) for symbol,day in sorted(requests)
               if not store.read(cache_key(instruments[symbol]['isin'],day))]
    token = store.token() if missing else None
    log(f'Intraday input: {len(requests)} stock-sessions; {len(missing)} require five-minute downloads.')
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(fetch,instruments[symbol],day,token):(symbol,day) for symbol,day in requests}
        for count,future in enumerate(as_completed(pending),1):
            symbol,day = pending[future]
            try:
                sessions.setdefault(symbol,{})[day] = future.result()
            except ValueError as exc:
                raise ValueError(f'Intraday history unavailable for {symbol} on {day}: {exc}') from None
            if count%100==0 or count==len(requests):
                log(f'Five-minute sessions ready: {count}/{len(requests)}.')
    return sessions


def load_ranges(plan, universe, log, interval_minutes=5):
    """Reuse session cache; batch missing history into <=28-day provider requests."""
    instruments = {x['symbol']: x for x in universe['instruments']}
    requests = {(x['symbol'], day) for day, candidates in plan.items() for x in candidates}
    sessions, missing = {}, {}
    for count, (symbol, day) in enumerate(sorted(requests), 1):
        record = store.read(cache_key(instruments[symbol]['isin'], day, interval_minutes))
        if record and record.get('bars'):
            sessions.setdefault(symbol, {})[day] = cached_bars(record, day, interval_minutes)
        else:
            missing.setdefault(symbol, []).append(day)
        if count % 5000 == 0:
            log(f'Minute cache checked: {count}/{len(requests)} stock-sessions.')
    log(f'{interval_minutes}-minute input: {len(requests)} stock-sessions; {sum(map(len, missing.values()))} missing; others reused.')
    token = store.token() if missing else None
    chunks = []
    for symbol, days in missing.items():
        while days:
            first = datetime.fromisoformat(days[0]).date()
            selected = [d for d in days if datetime.fromisoformat(d).date() <= first + timedelta(days=27)]
            chunks.append((symbol, selected))
            days = days[len(selected):]

    def download(symbol, days):
        item = instruments[symbol]
        url = f"https://api.upstox.com/v3/historical-candle/{quote(item['key'],safe='')}/minutes/{interval_minutes}/{days[-1]}/{days[0]}"
        with httpx.Client(timeout=30) as client:
            payload = upstox.get(client, url, headers={'Authorization':'Bearer '+token,'Accept':'application/json'}).json()
        if payload.get('status') != 'success':
            raise ValueError('Upstox did not return successful intraday history.')
        grouped = {}
        for row in payload.get('data', {}).get('candles', []):
            if len(row) < 6:
                raise ValueError('Malformed intraday history.')
            instant = datetime.fromisoformat(row[0])
            if instant.tzinfo is None:
                raise ValueError('Intraday candle requires an explicit timezone.')
            day = instant.astimezone(IST).date().isoformat()
            if not days[0] <= day <= days[-1]:
                raise ValueError('Provider returned candles outside the requested interval.')
            grouped.setdefault(day, []).append(row)
        result = {}
        for day in days:
            bars = normalize(grouped.get(day, []), day, interval_minutes)
            if not bars:
                raise ValueError(f"No five-minute candles for {symbol} on {day}.")
            store.write(cache_key(item['isin'], day, interval_minutes), dict(instrument=item, interval_minutes=interval_minutes,
                        source='Upstox historical V3', fetched_at=store.now(), bars=bars))
            result[day] = bars
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(download, symbol, days): symbol for symbol, days in chunks}
        for count, future in enumerate(as_completed(pending), 1):
            symbol = pending[future]
            sessions.setdefault(symbol, {}).update(future.result())
            if count % 10 == 0 or count == len(chunks):
                log(f'Momentum minute batches ready: {count}/{len(chunks)}.')
    return sessions


def trading_bars(bars, cutoff, interval_minutes=5):
    """Require complete regular-session bars through the exact cutoff; never invent prices."""
    by_time = {b['time']:b for b in bars}
    hour,minute = map(int,cutoff.split(':'))
    end = hour*60+minute
    times = [f'{x//60:02d}:{x%60:02d}' for x in range(9*60+15,end+1,interval_minutes)]
    if any(t not in by_time for t in times):
        raise ValueError(f'Incomplete regular-session candles through {cutoff} IST.')
    return [by_time[t] for t in times]
