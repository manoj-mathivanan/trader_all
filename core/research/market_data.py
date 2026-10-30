"""Rolling market downloads shared by swing, momentum and intraday research."""
from datetime import date, datetime, timedelta
from urllib.parse import quote
import time
import httpx
from core.research import store, upstox, intraday_data, fundamentals, data_quality, current_session
from core.research.config import Settings

BENCHMARK = {'key': 'NSE_INDEX|Nifty 50', 'isin': 'NIFTY50', 'symbol': 'NIFTY50'}


def retained_completed_benchmark(candles, cutoff):
    """Keep a verified completed session while daily publication is still pending."""
    record = store.read('bars/NIFTY50', {})
    retained = [b for b in record.get('bars', []) if b['date'] <= str(cutoff)
                and b['date'] in record.get('provisional_daily', {})
                and complete_minutes(store.read(intraday_data.cache_key('NIFTY50', b['date'])), b['date'])]
    # Published history wins when it has arrived.
    return upstox.merge_candles(retained, candles)


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
    candles = retained_completed_benchmark(candles, cutoff)
    current = current_session.completed_day(now)
    if current and (not candles or candles[-1]['date'] < str(current)):
        observed = current_session.daily(client, BENCHMARK, token, current, now=now)
        if observed:
            return current
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


def minute_ranges(sessions, missing):
    """Five-minute API requests allow at most one month; use <=28 days."""
    for first, last in missing_ranges(sessions, missing):
        while first <= last:
            end = min(last, first + timedelta(days=27))
            yield first, end
            first = end + timedelta(days=1)


def save_daily(client, item, token, start, end, *, sessions=None, allow_empty_prefix=False,
               unavailable_ranges=None):
    record = store.read('bars/' + item['isin'], {})
    existing = record.get('bars', [])
    provisional = dict(record.get('provisional_daily', {}))
    current = current_session.completed_day()
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
    # Always revisit aggregates, even when the normal cache has no missing dates.
    for day in provisional:
        target = date.fromisoformat(day)
        if target <= end and not any(a <= target <= b for a,b in ranges):
            ranges.append((target, target))
    additions = []
    checked_empty_prefix = False
    for range_start, range_end in ranges:
        if range_start > range_end:
            continue
        downloaded = list(upstox.fetch_range(client, item, token, range_start, range_end))
        published = {b['date'] for b in downloaded}
        for day in published:
            provisional.pop(day, None)
        if current and range_start <= current <= range_end and str(current) not in published:
            aggregate = current_session.daily(client, item, token, current)
            if aggregate:
                downloaded.append(aggregate)
                provisional[str(current)] = dict(source='Upstox current session V3; complete five-minute aggregation',
                    provisional=True, close_basis='Final regular-session five-minute close; not published daily close')
        if not downloaded:
            if allow_empty_prefix and existing and range_end < date.fromisoformat(existing[0]['date']):
                checked_empty_prefix = True
                continue
            if range_start == range_end and str(range_start) in provisional:
                continue  # Published candle still unavailable; retain the marked aggregate.
            if unavailable_ranges is not None and existing:
                unavailable_ranges.append({'start': str(range_start), 'end': str(range_end)})
                continue
            raise ValueError('No daily candles returned for the missing range.')
        additions.extend(downloaded)
        time.sleep(.15)
    if sessions is not None:
        available = {b['date'] for b in existing+additions}
        first_available = min(available) if available else str(start)
        missing = {d for d in sessions if max(str(start), first_available) <= d <= str(end)} - available
        if missing:
            if unavailable_ranges is None:
                raise ValueError('Missing daily candles on observed exchange sessions: '+', '.join(sorted(missing)))
            # Backfill callers collect explicit holes and still retain valid
            # downloads. Normal market refresh remains strict about completeness.
            for first, last in missing_ranges(sorted(sessions), missing):
                hole = {'start': str(first), 'end': str(last)}
                if hole not in unavailable_ranges:
                    unavailable_ranges.append(hole)
    if not additions and existing:
        # Paper coverage metadata can advance without rewriting all stored candles.
        if checked_empty_prefix or record.get('requested_end', '') < str(end):
            updated = {**record, 'requested_end': max(record.get('requested_end', ''), str(end))}
            if checked_empty_prefix:
                updated['requested_start'] = min(record.get('requested_start', str(start)), str(start))
            store.write('bars/' + item['isin'], updated)
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
        'verified_repairs': store.read('provider_overrides/' + item['isin'], {}).get('repairs', []),
        'provisional_daily': provisional})
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
        expected = set()
        for opening, closing in hours.get('segments', [(hours['open'],hours['close'])]):
            first, last = (sum(int(x)*factor for x,factor in zip(value.split(':'),(60,1)))
                           for value in (opening,closing))
            expected.update(f'{t//60:02d}:{t%60:02d}' for t in range(first,last,5))
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
    current = current_session.completed_day()
    if current and str(current) in missing:
        aggregate = current_session.daily(client, item, token, current)
        if not aggregate:
            raise ValueError('No current-session candles returned for an observed exchange session.')
        missing.remove(str(current))
        detail['bars'] += len(store.read(intraday_data.cache_key(item['isin'], str(current)))['bars'])
        detail['sessions'] += 1
    for range_start, range_end in minute_ranges(sessions, missing):
        downloaded = download_minutes(client, item, token, range_start, range_end)
        detail['bars'] += downloaded['bars']
        detail['sessions'] += downloaded['sessions']
        detail.setdefault('first', downloaded['first'])
        detail['last'] = downloaded['last']
        time.sleep(.15)
    detail['missing_sessions'] = sorted(d for d in missing if not complete_minutes(
        store.read(intraday_data.cache_key(item['isin'], d)), d))
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
        raise ValueError('No five-minute candles returned for the requested range.')
    # Validate the full response before saving any session. Never delete other days.
    sessions = {day: intraday_data.normalize(rows, day) for day, rows in grouped.items()}
    with store.LOCK:
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


def fetch(log, job_id=None, *, include_fundamentals=True):
    token = store.token()
    with httpx.Client(timeout=40) as client:
        window = windows(last_traded_day(client, token))
        previous = store.read('market_fetch', {})
        if previous.get('end'):
            # A downtime longer than ten days must not strand the intervening sessions.
            window['minute_start'] = min(window['minute_start'], previous['end'])
            if not previous.get('completed_at') or any(f.get('interval') == 'minute' for f in previous.get('failures', [])):
                window['minute_start'] = min(window['minute_start'], previous.get('minute_start', previous['end']))
        start, minute_start, end = (date.fromisoformat(window[k]) for k in ('daily_start', 'minute_start', 'end'))
        benchmark = upstox.fetch_range(client, BENCHMARK, token, start, end)
        benchmark = retained_completed_benchmark(benchmark, end)
        current = current_session.completed_day()
        if current == end and (not benchmark or benchmark[-1]['date'] != str(end)):
            aggregate = current_session.daily(client, BENCHMARK, token, end)
            if aggregate:
                benchmark = upstox.merge_candles(benchmark, [aggregate])
        if current == end or store.read('bars/NIFTY50', {}).get('provisional_daily'):
            # Persist the observed benchmark date so all readers see today's session.
            save_daily(client, BENCHMARK, token, start, end, sessions=[b['date'] for b in benchmark])
        if not benchmark or benchmark[-1]['date'] != str(end):
            raise ValueError('Completed trading-session calendar is unavailable. Retry later.')
        sessions = [b['date'] for b in benchmark]
        log(f"Incremental fetch: daily {start} → {end}; five-minute {minute_start} → {end}. Complete cached sessions are reused.")
        # Independent of research/paper selection: always the complete current 750-stock universe.
        universe = upstox.refresh_universe(Settings(universe='niftytotalmarket', start=start, end=end), log)
        result = {'job_id': job_id, 'universe': 'niftytotalmarket', **window, 'started_at': store.now(),
                  'total_symbols': len(universe['instruments']), 'daily_symbols': 0, 'minute_symbols': 0,
                  'daily_bars': 0, 'minute_bars': 0, 'failures': [], 'stocks': []}
        result['provisional_daily_symbols'] = []
        result['current_session_unverified'] = bool(current and end < current)
        if result['current_session_unverified']:
            log(f'Current-date coverage unverified: no completed benchmark session returned for {current}; latest observed session is {end}. A holiday or unavailable data must not be reported as current coverage.')
        if current == end:
            log(f'Current completed session {end}: using the current-day endpoint where published daily history is unavailable. Aggregates are provisional and will be reconciled.')
        store.write('market_fetch', result)
        for index, item in enumerate(universe['instruments'], 1):
            stock = {'symbol': item['symbol'], 'isin': item['isin']}
            for interval in ('daily', 'minute'):
                try:
                    if interval == 'daily':
                        detail = {'bars': save_daily(client, item, token, start, end, sessions=sessions)}
                        provisional = store.read('bars/'+item['isin'], {}).get('provisional_daily', {})
                        if provisional:
                            detail['provisional_dates'] = sorted(provisional)
                            result['provisional_daily_symbols'].append(item['symbol'])
                    else:
                        observed = [b['date'] for b in store.read('bars/' + item['isin'], {}).get('bars', [])]
                        detail = save_minutes(client, item, token, minute_start, end,
                                              sessions=observed or sessions)
                    stock[interval] = {'status': 'success', **detail}
                    if detail.get('missing_sessions'):
                        stock[interval]['status'] = 'warning'
                        result['failures'].append({'symbol': item['symbol'], 'interval': interval,
                            'message': 'Missing or incomplete five-minute sessions after refresh.',
                            'sessions': detail['missing_sessions']})
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
        log('Market candles saved. Auditing retained daily history for unresolved price gaps.')
        result['data_quality'] = data_quality.audit_cached_universe(
            Settings(universe='niftytotalmarket'), universe=universe, end=end)
        for warning in result['data_quality']['warnings']:
            log(warning)
        store.write('market_fetch', result)
        result['fundamentals'] = {'status': 'not_requested'}
        if include_fundamentals:
            log('Checking quarterly fundamentals for the same stock universe.')
            try:
                result['fundamentals'] = fundamentals.pull(universe['instruments'], log, job_id, retry_failed=True)
            except Exception as exc:
                result['fundamentals'] = {'status':'failed', 'message':error_detail(exc)}
                log('Fundamentals stage failed; saved market candles retained.')
        if result['provisional_daily_symbols']:
            log(f"Provisional daily candles: {len(result['provisional_daily_symbols'])} stocks. Complete session aggregates use the final minute-bar close; published daily candles will replace them on refresh.")
        result['partial'] = bool(result['current_session_unverified'] or result['provisional_daily_symbols'] or result['failures'] or result['data_quality']['excluded_symbols'] or result['fundamentals'].get('partial') or
                                 result['fundamentals'].get('status') == 'failed')
        result['completed_at'] = store.now()
        store.write('market_fetch', result)
        fundamentals_note = 'Quarterly fundamentals checked; inspect the fundamentals result for coverage and failures.' if include_fundamentals else 'Fundamentals were not requested.'
        log(f"Finished all {result['total_symbols']} stocks: daily {result['daily_symbols']}, five-minute {result['minute_symbols']}; {len(result['failures'])} candle failures. {fundamentals_note} Older history retained.")
        from core.portfolio import refresh_followup
        followups = refresh_followup.run(log, job_id, result)
        if followups:
            result['paper_cycles'] = followups
            result['partial'] = result['partial'] or any(p['status'] == 'failed' for p in followups)
            store.write('market_fetch', result)
        return result
