"""Archive Nifty index or ETF minute history and audit PostgreSQL coverage."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import intraday_data as intraday, options_history as provider, postgres_store as pg, store

INSTRUMENT = dict(isin='NIFTY50', symbol='NIFTY50', key=provider.UNDERLYING,
                  name='Nifty 50 index', exchange='NSE_INDEX')
CALENDAR_SOURCES = [
    'https://archives.nseindia.com/content/circulars/CMTR59722.pdf',
    'https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf',
    'https://www.nseindia.com/resources/exchange-communication-holidays?apiversion=v2',
    'https://www.niftyindices.com/Press_Release/ind_prs24012025_3.pdf',
    'https://nsearchives.nseindia.com/content/circulars/CMPT72389.pdf',
]
# Reviewed NSE equity calendar for the bounded October 2024–November 2026 pull.
HOLIDAYS = set('''2024-10-02 2024-11-01 2024-11-15 2024-11-20 2024-12-25
2025-02-26 2025-03-14 2025-03-31 2025-04-10 2025-04-14 2025-04-18
2025-05-01 2025-08-15 2025-08-27 2025-10-02 2025-10-21 2025-10-22
2025-11-05 2025-12-25 2026-01-15 2026-01-26 2026-03-03 2026-03-26
2026-03-31 2026-04-03 2026-04-14 2026-05-01 2026-05-28 2026-06-26
2026-09-14 2026-10-02 2026-10-20 2026-11-10 2026-11-24 2026-12-25'''.split())
EXTRA_SESSIONS = {'2025-02-01', '2026-02-01', '2024-11-01', '2025-10-21'}


def expected_calendar(start, end):
    if start < date(2024, 10, 1) or end > date(2026, 11, 3):
        raise ValueError('Extend the reviewed exchange calendar before using dates outside this range.')
    days = []
    while start <= end:
        day = str(start)
        if (start.weekday() < 5 and day not in HOLIDAYS) or day in EXTRA_SESSIONS:
            days.append(day)
        start += timedelta(days=1)
    return days


def expected_times(day):
    special = intraday.SPECIAL_SESSIONS.get(day, {})
    segments = special.get('segments', [(special.get('open', '09:15'), special.get('close', '15:30'))])
    result = []
    for first, last in segments:
        a, b = [int(t[:2])*60+int(t[3:]) for t in (first, last)]
        result.extend(f'{m//60:02d}:{m%60:02d}' for m in range(a, b))
    return result


def audit_session(day, bars):
    expected = set(expected_times(day))
    observed = [b['time'] for b in bars]
    return dict(date=day, bars=len(bars), expected_bars=len(expected),
                missing_minutes=sorted(expected-set(observed)),
                extra_minutes=sorted(set(observed)-expected),
                duplicate_minutes=len(observed)-len(set(observed)))


def persisted_sessions(start, end, isin='NIFTY50'):
    rows = pg.connection().execute(
        'SELECT s.session,s.bars,c.content,d.sha256,s.source_sha256 '
        'FROM trader.intraday_sessions s JOIN trader.documents d '
        'ON d.namespace=s.namespace AND d.name=s.document_name '
        'JOIN trader.contents c ON c.sha256=d.sha256 '
        'WHERE s.namespace=%s AND s.isin=%s AND s.interval_minutes=1 '
        'AND s.session BETWEEN %s AND %s ORDER BY s.session',
        (pg.namespace(), isin, str(start), str(end))).fetchall()
    records = {}
    for day, bars, content, digest, source_digest in rows:
        record = json.loads(pg.unpack(content, digest))
        if source_digest != digest or record['bars'] != bars:
            raise ValueError(f'Database projection mismatch: {day}')
        records[day] = record
    return records


def pull(start, end, output, instrument=None):
    instrument = instrument or INSTRUMENT
    isin = instrument['isin']
    encoded_key = quote(instrument['key'], safe='')
    symbol = instrument['symbol'].lower()
    if not store.database_enabled():
        raise ValueError('This ingestion requires PostgreSQL storage.')
    if end >= datetime.now(intraday.IST).date():
        raise ValueError('Use completed sessions ending before today.')
    expected = expected_calendar(start, end)
    prefix = f'market_archives/{symbol}_1m/{start}_{end}'
    token = store.token()
    raw_daily = []
    with pg.mutex(f'{symbol}-minute-history', timeout=0), httpx.Client(timeout=60) as client:
        existing_records = persisted_sessions(start, end, isin)
        cursor = start
        while cursor <= end:
            last = min(end, cursor+timedelta(days=27))
            key = f'{prefix}/minutes_{cursor}_{last}'
            archive = store.read(key)
            if archive is None:
                payload = provider.request(client, token,
                    f'/v3/historical-candle/{encoded_key}/minutes/1/{last}/{cursor}')
                # Validate the entire response before persisting any session.
                provider.normalize_candles(payload['data']['candles'], cursor, last)
                archive = dict(source='Upstox historical V3', instrument=instrument,
                               start=str(cursor), end=str(last), fetched_at=store.now(), raw_response=payload)
                with pg.transaction():
                    store.write(key, archive)
            grouped = defaultdict(list)
            rows = archive['raw_response']['data']['candles']
            provider.normalize_candles(rows, cursor, last)
            for row in rows:
                day = datetime.fromisoformat(row[0]).astimezone(intraday.IST).date().isoformat()
                grouped[day].append(row)
            for day, raw in sorted(grouped.items()):
                bars = intraday.normalize(raw, day, 1)
                allowed_times = set(expected_times(day))
                excluded = [b for b in bars if b['time'] not in allowed_times]
                bars = [b for b in bars if b['time'] in allowed_times]
                record = dict(instrument=instrument, interval_minutes=1,
                              source='Upstox historical V3', fetched_at=archive['fetched_at'],
                              raw_archive_key=key, excluded_out_of_session_bars=excluded, bars=bars)
                cache_key = intraday.cache_key(isin, day, 1)
                previous = existing_records.get(day)
                if (previous is None or previous.get('bars') != bars or
                        previous.get('excluded_out_of_session_bars', []) != excluded):
                    with pg.transaction():
                        store.write(cache_key, record)
                existing_records[day] = record
            print(f'{cursor}..{last}: {len(rows)} candles, {len(grouped)} sessions stored', flush=True)
            cursor = last+timedelta(days=1)
        # A bounded single-session retry distinguishes batch omissions from provider gaps.
        retries = []
        for day in expected:
            cache = intraday.cache_key(isin, day, 1)
            record = existing_records.get(day, {'bars': []})
            check = audit_session(day, record['bars'])
            if not check['missing_minutes']:
                continue
            payload = provider.request(client, token,
                f'/v3/historical-candle/{encoded_key}/minutes/1/{day}/{day}')
            bars = intraday.normalize(payload['data']['candles'], day, 1)
            allowed_times = set(expected_times(day))
            excluded = [b for b in bars if b['time'] not in allowed_times]
            bars = [b for b in bars if b['time'] in allowed_times]
            key = f'{prefix}/retry_{day}'
            with pg.transaction():
                store.write(key, dict(fetched_at=store.now(), raw_response=payload))
                if len(bars) >= len(record['bars']):
                    store.write(cache, dict(instrument=instrument, interval_minutes=1,
                        source='Upstox historical V3', fetched_at=store.now(), raw_archive_key=key,
                        excluded_out_of_session_bars=excluded, bars=bars))
            alternate = provider.request(client, token,
                f'/v2/historical-candle/{encoded_key}/1minute/{day}/{day}')
            alternate_bars = intraday.normalize(alternate['data']['candles'], day, 1)
            with pg.transaction():
                store.write(f'{prefix}/v2_probe_{day}', dict(fetched_at=store.now(), raw_response=alternate))
            retries.append(dict(date=day, before=len(record['bars']), returned=len(bars),
                                v2_audit=audit_session(day, alternate_bars)))
            print(f'Retried {day}: {len(record["bars"])} -> {len(bars)} candles', flush=True)
        cursor = start
        while cursor <= end:
            last = min(end, cursor+timedelta(days=364))
            key = f'{prefix}/daily_{cursor}_{last}'
            archive = store.read(key)
            if archive is None:
                payload = provider.request(client, token,
                    f'/v3/historical-candle/{encoded_key}/days/1/{last}/{cursor}')
                archive = dict(fetched_at=store.now(), raw_response=payload)
                with pg.transaction():
                    store.write(key, archive)
            raw_daily.extend(archive['raw_response']['data']['candles'])
            cursor = last+timedelta(days=1)
        daily = provider.normalize_candles(raw_daily, start, end)
        daily_days = {b['date'] for b in daily}
        del existing_records
        sessions, checksum, excluded_counts = {}, hashlib.sha256(), {}
        for day, record in persisted_sessions(start, end, isin).items():
            # Read compressed canonical documents independently of the SQL projection.
            bars = record['bars']
            validated = intraday.cached_bars(record, day, 1)
            if validated != bars:
                raise ValueError(f'Database candle normalization mismatch: {day}')
            sessions[day] = bars
            if record.get('excluded_out_of_session_bars'):
                excluded_counts[day] = len(record['excluded_out_of_session_bars'])
            checksum.update(pg.pack(dict(date=day, bars=bars)))
        audits = [audit_session(d, sessions.get(d, [])) for d in expected]
        issues = [r for r in audits if r['missing_minutes'] or r['extra_minutes'] or r['duplicate_minutes']]
        unexpected = sorted(set(sessions)-set(expected))
        missing_daily = sorted(set(expected)-daily_days)
        extra_daily = sorted(daily_days-set(expected))
        ready = not (issues or unexpected or missing_daily or extra_daily)
        report = dict(status='verified_complete' if ready else 'coverage_gaps',
            backtest_ready=ready, instrument=instrument, interval_minutes=1, timezone='Asia/Kolkata',
            requested_start=str(start), requested_end=str(end), namespace=pg.namespace(),
            audited_at=store.now(), expected_sessions=len(expected), stored_sessions=len(sessions),
            complete_sessions=len(expected)-len(issues), total_candles=sum(map(len,sessions.values())),
            eligible_sessions=[r['date'] for r in audits if not (
                r['missing_minutes'] or r['extra_minutes'] or r['duplicate_minutes'])],
            excluded_incomplete_sessions=[r['date'] for r in issues],
            backtest_policy='Use eligible_sessions only; fail or skip explicitly on incomplete sessions. Never fill missing prices.',
            first_session=min(sessions,default=None), last_session=max(sessions,default=None),
            missing_sessions=sorted(set(expected)-set(sessions)), unexpected_sessions=unexpected,
            daily_missing_sessions=missing_daily, daily_unexpected_sessions=extra_daily,
            session_issues=issues, session_audit=audits, candle_sha256=checksum.hexdigest(),
            single_session_retries=retries, excluded_out_of_session_candles=excluded_counts,
            calendar_sources=CALENDAR_SOURCES,
            special_sessions={d:intraday.SPECIAL_SESSIONS.get(d, {'open':'09:15','close':'15:30'})
                              for d in expected if d in EXTRA_SESSIONS},
            storage_key=f'intraday/1m/{isin}/YYYY-MM-DD', raw_archive_prefix=prefix,
            limitations=[('Index volume is not traded volume; do not use it as stock/futures volume.'
                          if instrument['exchange']=='NSE_INDEX' else
                          'ETF traded prices can differ from NAV and from scaled index values.'),
                        'Coverage checks do not independently certify vendor price accuracy.',
                        'Daily OHLC can differ from minute aggregation; retained as separate observations.'])
        with pg.transaction():
            store.write(f'{prefix}/verification', report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ('session_audit','eligible_sessions')}), flush=True)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2024,10,1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2026,11,2))
    parser.add_argument('--output', type=Path, default=Path('/tmp/nifty50-minute-verification.json'))
    args = parser.parse_args()
    report = pull(args.start, args.end, args.output)
    sys.exit(0 if report['backtest_ready'] else 2)
