"""Completed current-day candles, separate from Upstox's historical endpoint."""
from datetime import datetime, timedelta
from urllib.parse import quote

from core.research import intraday_data, store, upstox


def completed_day(now=None):
    now = (now or datetime.now(intraday_data.IST)).astimezone(intraday_data.IST)
    day = now.date().isoformat()
    hours = intraday_data.SPECIAL_SESSIONS.get(day)
    if now.weekday() >= 5 and not hours:
        return None
    closing = (hours or {}).get('close', '15:30')
    cutoff = datetime.fromisoformat(day + 'T' + closing).replace(tzinfo=intraday_data.IST) + timedelta(minutes=30)
    return now.date() if now >= cutoff else None


def daily(client, item, token, day, *, now=None):
    """Return a provisional daily aggregate only for a complete, closed session."""
    if completed_day(now) != day:
        raise ValueError('Current-session data requires a completed session and close buffer.')
    key = intraday_data.cache_key(item['isin'], str(day))
    cached = store.read(key, {})
    if cached.get('source') == 'Upstox current session V3' and cached.get('complete_session'):
        bars = intraday_data.cached_bars(cached, str(day))
    else:
        url = f"https://api.upstox.com/v3/historical-candle/intraday/{quote(item['key'], safe='')}/minutes/5"
        payload = upstox.get(client, url, headers={'Authorization': 'Bearer '+token, 'Accept': 'application/json'}).json()
        if payload.get('status') != 'success':
            raise ValueError('Upstox did not return successful current-session candles.')
        bars = intraday_data.normalize(payload.get('data', {}).get('candles', []), str(day))
    if not bars:
        return None  # No observed current session; never invent a holiday candle.
    hours = intraday_data.SPECIAL_SESSIONS.get(str(day), {'open': '09:15', 'close': '15:30'})
    expected = set()
    for opening, closing in hours.get('segments', [(hours['open'], hours['close'])]):
        first, last = (int(t[:2])*60+int(t[3:]) for t in (opening, closing))
        expected.update(f'{m//60:02d}:{m%60:02d}' for m in range(first, last, 5))
    bars = [b for b in bars if b['time'] in expected]
    if {b['time'] for b in bars} != expected:
        raise ValueError(f"{item['symbol']}: incomplete current session; provisional daily candle not saved.")
    if not cached.get('complete_session') or cached.get('source') != 'Upstox current session V3':
        store.write(key, dict(instrument=item, interval_minutes=5, source='Upstox current session V3',
                              complete_session=True, fetched_at=store.now(), bars=bars))
    return dict(date=str(day), timestamp=int(datetime.fromisoformat(str(day)+'T00:00:00+05:30').timestamp()*1000),
                open=bars[0]['open'], high=max(b['high'] for b in bars), low=min(b['low'] for b in bars),
                close=bars[-1]['close'], volume=sum(b['volume'] for b in bars))
