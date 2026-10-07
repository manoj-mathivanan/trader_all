"""Validated five-minute Upstox history, cached separately from daily history."""
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx
from core.research import store, upstox

IST = timezone(timedelta(hours=5, minutes=30))
SPECIAL_SESSIONS = {
    '2025-10-21': {'open': '13:45', 'close': '14:45',
                   'source': 'https://nsearchives.nseindia.com/content/circulars/CMTR70319.pdf'},
}


def normalize(raw, day):
    result, seen = [], set()
    for row in raw:
        if len(row) < 6:
            raise ValueError('Malformed five-minute candle.')
        instant = datetime.fromisoformat(row[0])
        if instant.tzinfo is None:
            raise ValueError('Intraday candle requires an explicit timezone.')
        instant = instant.astimezone(IST)
        if instant.date().isoformat()!=day or instant.minute%5 or instant.second:
            raise ValueError('Intraday candle is outside its requested session or five-minute boundary.')
        timestamp = int(instant.timestamp()*1000)
        if timestamp in seen:
            raise ValueError('Duplicate intraday candle.')
        seen.add(timestamp)
        o,h,l,c,v = map(float,row[1:6])
        if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c) or l>h:
            raise ValueError('Invalid intraday OHLCV candle.')
        result.append(dict(date=day,time=instant.strftime('%H:%M'),timestamp=timestamp,
                           open=o,high=h,low=l,close=c,volume=v))
    return sorted(result,key=lambda x:x['timestamp'])


def cache_key(isin, day):
    return f'intraday/5m/{isin}/{day}'


def fetch(item, day, token):
    key = cache_key(item['isin'],day)
    cached = store.read(key)
    if cached:
        raw = [[datetime.fromtimestamp(b['timestamp']/1000,IST).isoformat(),b['open'],b['high'],b['low'],b['close'],b['volume']] for b in cached['bars']]
        return normalize(raw,day)
    url = f"https://api.upstox.com/v3/historical-candle/{quote(item['key'],safe='')}/minutes/5/{day}/{day}"
    with httpx.Client(timeout=30) as client:
        payload = upstox.get(client,url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'}).json()
    if payload.get('status')!='success':
        raise ValueError('Upstox did not return successful intraday data.')
    bars = normalize(payload.get('data',{}).get('candles',[]),day)
    if not bars:
        raise ValueError(f"No five-minute candles for {item['symbol']} on {day}.")
    store.write(key,dict(instrument=item,interval_minutes=5,source='Upstox historical V3',fetched_at=store.now(),bars=bars))
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


def trading_bars(bars, cutoff):
    """Require complete regular-session bars through the exact cutoff; never invent prices."""
    by_time = {b['time']:b for b in bars}
    hour,minute = map(int,cutoff.split(':'))
    end = hour*60+minute
    times = [f'{x//60:02d}:{x%60:02d}' for x in range(9*60+15,end+1,5)]
    if any(t not in by_time for t in times):
        raise ValueError(f'Incomplete regular-session candles through {cutoff} IST.')
    return [by_time[t] for t in times]
