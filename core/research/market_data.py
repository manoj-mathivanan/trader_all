"""Rolling market downloads shared by swing, momentum and intraday research."""
from datetime import date, datetime, timedelta
from urllib.parse import quote
import time
import httpx
from core.research import store, upstox, intraday_data, fundamentals
from core.research.config import Settings

BENCHMARK = {'key': 'NSE_INDEX|Nifty 50', 'isin': 'NIFTY50', 'symbol': 'NIFTY50'}


def windows(last):
    # Same calendar date in the previous year, including leap-day handling.
    try:
        start = last.replace(year=last.year - 1)
    except ValueError:
        start = last.replace(year=last.year - 1, day=28)
    return {'daily_start': str(start), 'minute_start': str(last - timedelta(days=9)), 'end': str(last)}


def last_traded_day(client, token, now=None):
    now = (now or datetime.now(intraday_data.IST)).astimezone(intraday_data.IST)
    # Never ingest an unfinished session. Historical availability can lag the close.
    cutoff = now.date() if (now.hour, now.minute) >= (16, 0) else now.date() - timedelta(days=1)
    candles = upstox.fetch_range(client, BENCHMARK, token, cutoff - timedelta(days=30), cutoff)
    if not candles:
        raise ValueError('Cannot determine the last completed trading day from Nifty 50 history. Retry later.')
    return date.fromisoformat(candles[-1]['date'])


def missing_ranges(sessions, missing):
    """Batch adjacent missing trading sessions without crossing a cached session."""
    ranges = []
    active = False
    for day in sorted(sessions):
        if day not in missing:
            active = False
            continue
        if ranges and active:
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
        active = True
    return [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in ranges]


def save_daily(client, item, token, start, end, *, sessions=None):
    record = store.read('bars/' + item['isin'], {})
    existing = record.get('bars', [])
    ranges = []
    if not existing:
        ranges = [(start, end)]
    else:
        first, last = (date.fromisoformat(existing[i]['date']) for i in (0, -1))
        # A previously checked pre-listing range is not a hole in trading history.
        if start < first and record.get('requested_start', str(first)) > str(start):
            ranges.append((start, min(end, first - timedelta(days=1))))
        if sessions is None:
            if end > last:
                ranges.append((max(start, last + timedelta(days=1)), end))
        else:
            eligible = [d for d in sessions if max(str(start), str(first)) <= d <= str(end)]
            missing = set(eligible) - {b['date'] for b in existing}
            ranges.extend(missing_ranges(eligible, missing))
    additions = []
    for range_start, range_end in ranges:
        if range_start > range_end:
            continue
        downloaded = upstox.fetch_range(client, item, token, range_start, range_end)
        if not downloaded:
            raise ValueError('No daily candles returned for the missing range.')
        additions.extend(downloaded)
        time.sleep(.15)
    if not additions and existing:
        # Paper coverage metadata can advance without rewriting all stored candles.
        if record.get('requested_end', '') < str(end):
            store.write('bars/' + item['isin'], {**record, 'requested_end': str(end)})
        return 0
    merged = upstox.merge_candles(existing, additions)
    # Validate both downloaded and retained candles before the atomic replacement.
    merged = upstox.validate_candles(
        [[b['date']+'T00:00:00+05:30', b['open'], b['high'], b['low'], b['close'], b['volume']] for b in merged],
        date.fromisoformat(merged[0]['date']), date.fromisoformat(merged[-1]['date']))
    store.write('bars/' + item['isin'], {**record, 'instrument': item, 'bars': merged,
        'source': 'upstox_v3', 'fetched_at': store.now(), 'adjustments': 'unverified',
        'requested_start': min(record.get('requested_start', str(start)), str(start)),
        'requested_end': max(record.get('requested_end', str(end)), str(end)),
        'verified_repairs': store.read('provider_overrides/' + item['isin'], {}).get('repairs', [])})
    with store.LOCK:
        catalog = store.read('bar_catalog', {})
        catalog[item['isin']] = {'count': len(merged), 'first': merged[0]['date'], 'last': merged[-1]['date'],
            'close': merged[-1]['close'], 'change': (merged[-1]['close']/merged[-2]['close']-1)*100 if len(merged)>1 else None}
        store.write('bar_catalog', catalog)
    return len(additions)


def complete_minutes(record, day):
    if not record or not record.get('bars'):
        return False
    try:
        bars = intraday_data.cached_bars(record, day)
        hours = intraday_data.SPECIAL_SESSIONS.get(day, {'open': '09:15', 'close': '15:30'})
        opening, closing = (sum(int(x) * factor for x, factor in zip(hours[k].split(':'), (60, 1)))
                            for k in ('open', 'close'))
        expected = {f'{t//60:02d}:{t%60:02d}' for t in range(opening, closing, 5)}
        return expected <= {b['time'] for b in bars}
    except (ValueError, KeyError, TypeError):
        return False


def save_minutes(client, item, token, start, end, *, sessions=None):
    if sessions is None:
        # The stock's daily candles identify observed sessions, including special sessions.
        sessions = [b['date'] for b in store.read('bars/' + item['isin'], {}).get('bars', [])]
        if not sessions:
            return download_minutes(client, item, token, start, end)
    sessions = sorted({d for d in sessions if str(start) <= d <= str(end)})
    missing = {d for d in sessions if not complete_minutes(store.read(intraday_data.cache_key(item['isin'], d)), d)}
    detail = {'bars': 0, 'sessions': 0, 'reused_sessions': len(sessions) - len(missing)}
    for range_start, range_end in missing_ranges(sessions, missing):
        downloaded = download_minutes(client, item, token, range_start, range_end)
        detail['bars'] += downloaded['bars']
        detail['sessions'] += downloaded['sessions']
        detail.setdefault('first', downloaded['first'])
        detail['last'] = downloaded['last']
        time.sleep(.15)
    return detail


def download_minutes(client, item, token, start, end):
    url = f"https://api.upstox.com/v3/historical-candle/{quote(item['key'],safe='')}/minutes/5/{end}/{start}"
    payload = upstox.get(client, url, headers={'Authorization': 'Bearer '+token, 'Accept': 'application/json'}).json()
    if payload.get('status') != 'success':
        raise ValueError('Upstox did not return successful five-minute history.')
    grouped = {}
    for row in payload.get('data', {}).get('candles', []):
        if len(row) < 6:
            raise ValueError('Malformed five-minute candle.')
        instant = datetime.fromisoformat(row[0])
        if instant.tzinfo is None:
            raise ValueError('Intraday candle requires an explicit timezone.')
        day = instant.astimezone(intraday_data.IST).date().isoformat()
        if not str(start) <= day <= str(end):
            raise ValueError('Five-minute candle outside the requested window.')
        grouped.setdefault(day, []).append(row)
    if not grouped:
        raise ValueError('No five-minute candles returned for the rolling ten days.')
    # Validate the full response before saving any session. Never delete other days.
    sessions = {day: intraday_data.normalize(rows, day) for day, rows in grouped.items()}
    for day, bars in sessions.items():
        key = intraday_data.cache_key(item['isin'], day)
        old = store.read(key, {})
        merged = {b['timestamp']: b for b in old.get('bars', [])}
        merged.update({b['timestamp']: b for b in bars})
        raw = [[datetime.fromtimestamp(b['timestamp']/1000, intraday_data.IST).isoformat(),
                b['open'], b['high'], b['low'], b['close'], b['volume']] for b in merged.values()]
        store.write(key, {'instrument': item, 'interval_minutes': 5, 'source': 'Upstox historical V3',
                        'fetched_at': store.now(), 'bars': intraday_data.normalize(raw, day)})
    return {'bars': sum(map(len, sessions.values())), 'sessions': len(sessions),
            'first': min(sessions), 'last': max(sessions)}


def error_detail(exc):
    # Provider/validation ValueErrors are safe; unexpected exception text may contain headers.
    return str(exc) if isinstance(exc, ValueError) else f'Unexpected {type(exc).__name__}; existing valid data retained.'


def fetch(log, job_id=None):
    token = store.token()
    with httpx.Client(timeout=40) as client:
        window = windows(last_traded_day(client, token))
        start, minute_start, end = (date.fromisoformat(window[k]) for k in ('daily_start', 'minute_start', 'end'))
        benchmark = upstox.fetch_range(client, BENCHMARK, token, start, end)
        if not benchmark or benchmark[-1]['date'] != str(end):
            raise ValueError('Completed trading-session calendar is unavailable. Retry later.')
        sessions = [b['date'] for b in benchmark]
        log(f"Incremental fetch: daily {start} → {end}; five-minute {minute_start} → {end}. Complete cached sessions are reused.")
        # Independent of research/paper selection: always the complete current 750-stock universe.
        universe = upstox.refresh_universe(Settings(universe='niftytotalmarket', start=start, end=end), log)
        result = {'job_id': job_id, 'universe': 'niftytotalmarket', **window, 'started_at': store.now(),
                  'total_symbols': len(universe['instruments']), 'daily_symbols': 0, 'minute_symbols': 0,
                  'daily_bars': 0, 'minute_bars': 0, 'failures': [], 'stocks': []}
        store.write('market_fetch', result)
        for index, item in enumerate(universe['instruments'], 1):
            stock = {'symbol': item['symbol'], 'isin': item['isin']}
            for interval in ('daily', 'minute'):
                try:
                    if interval == 'daily':
                        detail = {'bars': save_daily(client, item, token, start, end, sessions=sessions)}
                    else:
                        observed = [b['date'] for b in store.read('bars/' + item['isin'], {}).get('bars', [])]
                        detail = save_minutes(client, item, token, minute_start, end,
                                              sessions=observed or sessions)
                    stock[interval] = {'status': 'success', **detail}
                    result[interval+'_symbols'] += 1
                    result[interval+'_bars'] += detail['bars']
                except Exception as exc:
                    message = error_detail(exc)
                    stock[interval] = {'status': 'failed', 'message': message}
                    result['failures'].append({'symbol': item['symbol'], 'interval': interval, 'message': message})
                    log(f"{item['symbol']} {interval}: {message} Continuing with remaining downloads.")
            result['stocks'].append(stock)
            result['partial'] = bool(result['failures'])
            store.write('market_fetch', result)
            log(f"{index}/{result['total_symbols']} · {item['symbol']}: daily {stock['daily']['status']}, five-minute {stock['minute']['status']}; "
                f"downloaded {stock['daily'].get('bars', 0)} daily / {stock['minute'].get('bars', 0)} five-minute bars, "
                f"reused {stock['minute'].get('reused_sessions', 0)} complete minute sessions.")
        log('Market candles saved. Checking quarterly fundamentals for the same stock universe.')
        try:
            result['fundamentals'] = fundamentals.pull(universe['instruments'], log, job_id, retry_failed=True)
        except Exception as exc:
            result['fundamentals'] = {'status':'failed', 'message':error_detail(exc)}
            log('Fundamentals stage failed; saved market candles retained.')
        result['partial'] = bool(result['failures'] or result['fundamentals'].get('partial') or
                                 result['fundamentals'].get('status') == 'failed')
        result['completed_at'] = store.now()
        store.write('market_fetch', result)
        log(f"Finished all {result['total_symbols']} stocks: daily {result['daily_symbols']}, five-minute {result['minute_symbols']}; {len(result['failures'])} candle failures. Quarterly fundamentals checked; inspect the fundamentals result for coverage and failures. Older history retained.")
        return result
