"""Resumable current-Nifty-50 stock minute backfill with persisted coverage audits."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta
import gc
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import intraday_data as intraday, options_history as provider, postgres_store as pg, store, upstox
from scripts.pull_nifty_minute_history import expected_calendar, expected_times, audit_session, persisted_sessions

SPECIAL_PREOPEN = {
    ('INE154A01025','2025-01-06'): dict(open='10:00', close='15:30',
        source='https://nsearchives.nseindia.com/content/circulars/CMTR65845.pdf'),
    ('INE030A01027','2025-12-05'): dict(open='10:00', close='15:30',
        source='https://nsearchives.nseindia.com/content/circulars/CMTR71508.pdf'),
    ('INE155A01022','2025-10-14'): dict(open='10:00', close='15:30',
        source='https://nsearchives.nseindia.com/content/circulars/CMTR70614.pdf'),
}


def stock_times(day, isin):
    special = SPECIAL_PREOPEN.get((isin,day))
    return [t for t in expected_times(day) if not special or special['open'] <= t < special['close']]


def stock_audit(day, bars, isin):
    times=set(stock_times(day,isin))
    observed=[b['time'] for b in bars]
    return dict(date=day,bars=len(bars),expected_bars=len(times),
        missing_minutes=sorted(times-set(observed)),extra_minutes=sorted(set(observed)-times),
        duplicate_minutes=len(observed)-len(set(observed)))


def valid_session(day, record, isin=None):
    if not record or not record.get('bars'):
        return False
    try:
        bars = intraday.cached_bars(record, day, 1)
        if bars != record['bars']:
            return False
        audit = stock_audit(day, bars, isin or record.get('instrument',{}).get('isin'))
        return not (audit['missing_minutes'] or audit['extra_minutes'] or audit['duplicate_minutes'])
    except (ValueError, KeyError, TypeError, OverflowError):
        return False


def ranges(start, end, needed):
    while start <= end:
        last = min(end, start+timedelta(days=27))
        if any(str(start) <= d <= str(last) for d in needed):
            yield start, last
        start = last+timedelta(days=1)


def snapshot(prefix):
    saved = store.read(prefix+'/universe')
    if saved:
        return saved
    with httpx.Client(timeout=60, follow_redirects=True, headers={'User-Agent':'Mozilla/5.0'}) as client:
        response = upstox.get(client, upstox.UNIVERSES['nifty50'])
        rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        raw = upstox.get(client, upstox.INSTRUMENTS).content
        master = json.loads(gzip.decompress(raw) if raw[:2]==b'\x1f\x8b' else raw)
    items, excluded = upstox.match_constituents(rows, master)
    if len(items) != 50 or excluded:
        raise ValueError('Expected exactly 50 matched tradable constituents.')
    saved = dict(fetched_at=store.now(), membership='current_snapshot', source=upstox.UNIVERSES['nifty50'],
                 csv=response.text, csv_sha256=hashlib.sha256(response.content).hexdigest(),
                 instruments=[dict(i, exchange='NSE_EQ') for i in items])
    with pg.transaction():
        store.write(prefix+'/universe', saved)
    return saved


def fetch(item, token, first, last, unit='minutes', version=3):
    interval = f'{unit}/1' if version==3 else '1minute'
    with httpx.Client(timeout=60) as client:
        return provider.request(client, token,
            f'/v{version}/historical-candle/{quote(item["key"],safe="")}/{interval}/{last}/{first}')


def ingest_response(item, prefix, first, last, payload, existing, label):
    key = f'{prefix}/responses/{item["isin"]}/{label}_{first}_{last}'
    fetched_at = store.now()
    with pg.transaction():
        store.write(key, dict(instrument=item, first=str(first), last=str(last),
                             fetched_at=fetched_at, raw_response=payload))
    grouped, invalid = defaultdict(list), []
    for row in payload.get('data', {}).get('candles', []):
        if not isinstance(row,list) or len(row)<6:
            raise ValueError('Malformed provider candle; raw response archived.')
        instant = datetime.fromisoformat(row[0])
        if instant.tzinfo is None:
            raise ValueError('Provider candle has no timezone.')
        day = str(instant.astimezone(intraday.IST).date())
        if not str(first) <= day <= str(last):
            raise ValueError('Provider returned an out-of-range candle.')
        grouped[day].append(row)
    for day, raw in sorted(grouped.items()):
        try:
            bars = intraday.normalize(raw,day,1)
        except (ValueError, TypeError, OverflowError) as exc:
            invalid.append(dict(date=day, reason=str(exc)))
            continue
        times = set(stock_times(day,item['isin']))
        excluded = [b for b in bars if b['time'] not in times]
        bars = [b for b in bars if b['time'] in times]
        old = existing.get(day)
        # Preserve a complete cached observation, and never replace a better partial one.
        if valid_session(day,old,item['isin']) or (old and len(old.get('bars',[])) > len(bars)):
            continue
        record = dict(instrument=item, interval_minutes=1, source=f'Upstox historical V{label}',
                      fetched_at=fetched_at, raw_archive_key=key,
                      excluded_out_of_session_bars=excluded, bars=bars)
        with pg.transaction():
            store.write(intraday.cache_key(item['isin'],day,1),record)
        existing[day] = record
    return invalid


def audit_stock(item, start, end, expected, prefix):
    existing = persisted_sessions(start,end,item['isin'])
    audits, checksum, excluded = [], hashlib.sha256(), {}
    for day in expected:
        record = existing.get(day, {'bars':[]})
        bars = record['bars']
        check = stock_audit(day,bars,item['isin'])
        try:
            if bars and intraday.cached_bars(record,day,1) != bars:
                check['validation_error'] = 'Stored fields disagree with timestamp normalization.'
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            check['validation_error'] = str(exc)
        audits.append(check)
        checksum.update(pg.pack(dict(date=day,bars=bars)))
        if record.get('excluded_out_of_session_bars'):
            excluded[day] = len(record['excluded_out_of_session_bars'])
    issues = [a for a in audits if a['missing_minutes'] or a['extra_minutes'] or
              a['duplicate_minutes'] or a.get('validation_error')]
    eligible = [a['date'] for a in audits if a not in issues]
    unexpected = sorted(set(existing)-set(expected))
    report = dict(instrument=item, requested_start=str(start), requested_end=str(end),
        audited_at=store.now(), expected_sessions=len(expected), stored_sessions=len(existing),
        complete_sessions=len(eligible), eligible_sessions=eligible,
        missing_sessions=[a['date'] for a in audits if not a['bars']],
        missing_minutes=sum(len(a['missing_minutes']) for a in audits),
        session_issues=issues, unexpected_sessions=unexpected,
        total_candles=sum(len(r['bars']) for r in existing.values()),
        expected_candles=sum(a['expected_bars'] for a in audits),
        excluded_out_of_session_candles=excluded, candle_sha256=checksum.hexdigest(),
        instrument_session_rules={d:rule for (isin,d),rule in SPECIAL_PREOPEN.items()
                                  if isin==item['isin'] and str(start)<=d<=str(end)},
        backtest_ready=not (issues or unexpected),
        storage_key=f'intraday/1m/{item["isin"]}/YYYY-MM-DD')
    with pg.transaction():
        store.write(f'{prefix}/stocks/{item["isin"]}/verification',report)
    return report


def apply_session_rules(item,prefix,start,end):
    for (isin,day),rule in SPECIAL_PREOPEN.items():
        if isin!=item['isin'] or not str(start)<=day<=str(end):
            continue
        key=intraday.cache_key(isin,day,1)
        record=store.read(key)
        if not record:
            continue
        times=set(stock_times(day,isin))
        excluded=[b for b in record['bars'] if b['time'] not in times]
        if not excluded:
            continue
        with pg.transaction():
            archive=f'{prefix}/preopen_exclusions/{isin}/{day}'
            if store.read(archive) is None:
                store.write(archive,dict(original_record=record,rule=rule,archived_at=store.now()))
            updated=dict(record,bars=[b for b in record['bars'] if b['time'] in times],
                excluded_out_of_session_bars=record.get('excluded_out_of_session_bars',[])+excluded,
                instrument_session_rule=rule)
            store.write(key,updated)


def finalize(start,end,output):
    """Repeat persisted audits using official instrument-specific trading sessions."""
    prefix=f'market_archives/nifty50_stocks_1m/{start}_{end}'
    expected=expected_calendar(start,end)
    output.mkdir(parents=True,exist_ok=True)
    with pg.mutex('nifty50-stock-minute-backfill',timeout=0):
        original=store.read(prefix+'/verification')
        if not original or original['status']=='running':
            raise ValueError('Complete the ingestion before final verification.')
        summary={k:v for k,v in original.items() if k not in ('reports','failures')}
        summary.update(status='verifying_session_rules',reports=[],failures=[])
        with pg.transaction():
            if store.read(prefix+'/initial_regular_clock_audit') is None:
                store.write(prefix+'/initial_regular_clock_audit',original)
        universe=snapshot(prefix)
        for number,item in enumerate(universe['instruments'],1):
            apply_session_rules(item,prefix,start,end)
            old=store.read(f'{prefix}/stocks/{item["isin"]}/verification',{})
            report=audit_stock(item,start,end,expected,prefix)
            report.update({k:old[k] for k in ('provider_invalid_sessions','single_day_retries') if k in old})
            with pg.transaction():
                store.write(f'{prefix}/stocks/{item["isin"]}/verification',report)
            summary['reports'].append(report)
            print(f'Final audit {number}/50 {item["symbol"]}: {report["complete_sessions"]}/{len(expected)} sessions',flush=True)
            gc.collect()
        summary.update(stocks_verified_complete=sum(r['backtest_ready'] for r in summary['reports']),
            total_candles=sum(r['total_candles'] for r in summary['reports']),
            expected_candles=sum(r['expected_candles'] for r in summary['reports']),
            missing_minutes=sum(r['missing_minutes'] for r in summary['reports']),
            session_rule_sources=[r['source'] for r in SPECIAL_PREOPEN.values()],
            updated_at=store.now(),completed_at=store.now())
        summary['status']='verified_complete' if summary['stocks_verified_complete']==50 else 'coverage_gaps'
        summary['backtest_ready']=summary['status']=='verified_complete'
        with pg.transaction():
            store.write(prefix+'/verification',summary)
        (output/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='reports'}),flush=True)
        return summary


def run(start,end,output):
    if not store.database_enabled() or end >= datetime.now(intraday.IST).date():
        raise ValueError('Use PostgreSQL and completed sessions ending before today.')
    expected = expected_calendar(start,end)
    prefix = f'market_archives/nifty50_stocks_1m/{start}_{end}'
    output.mkdir(parents=True,exist_ok=True)
    token = store.token()
    with pg.mutex('nifty50-stock-minute-backfill',timeout=0):
        universe = snapshot(prefix)
        summary = dict(status='running',requested_start=str(start),requested_end=str(end),
            namespace=pg.namespace(),universe_key=prefix+'/universe',
            membership='current_snapshot',expected_stocks=50,expected_sessions_per_stock=len(expected),
            reports=[],failures=[],started_at=store.now(),report_prefix=prefix,
            limitations=['Current constituents are not historical index membership.',
                        'No missing prices are filled; backtests must use each stock eligibility list.',
                        'Provider history may be adjusted for corporate actions; historical tradeability needs separate modelling.',
                        'Minute OHLC does not include bid/ask spreads or certify executable fills.'])
        def checkpoint():
            summary['updated_at']=store.now()
            with pg.transaction():
                store.write(prefix+'/verification',summary)
            (output/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        checkpoint()
        for number,item in enumerate(universe['instruments'],1):
            print(f'{number}/50 {item["symbol"]}: checking retained candles',flush=True)
            try:
                apply_session_rules(item,prefix,start,end)
                existing = persisted_sessions(start,end,item['isin'])
                needed = {d for d in expected if not valid_session(d,existing.get(d),item['isin'])}
                tasks = list(ranges(start,end,needed))
                print(f'{item["symbol"]}: {len(needed)} sessions need ingestion, {len(tasks)} batches',flush=True)
                invalid, retries = [], []
                with ThreadPoolExecutor(max_workers=3) as pool:
                    for offset in range(0,len(tasks),3):
                        group=tasks[offset:offset+3]
                        futures=[pool.submit(fetch,item,token,a,b) for a,b in group]
                        for (a,b),future in zip(group,futures):
                            invalid.extend(ingest_response(item,prefix,a,b,future.result(),existing,'3'))
                        print(f'{item["symbol"]}: batches {min(offset+3,len(tasks))}/{len(tasks)} committed',flush=True)
                gaps=[d for d in expected if not valid_session(d,existing.get(d),item['isin'])]
                for day in gaps:
                    before=len(existing.get(day,{}).get('bars',[]))
                    for version in (3,2):
                        payload=fetch(item,token,date.fromisoformat(day),date.fromisoformat(day),version=version)
                        invalid.extend(ingest_response(item,prefix,day,day,payload,existing,str(version)+'_retry'))
                        if valid_session(day,existing.get(day),item['isin']):
                            break
                    retries.append(dict(date=day,before=before,after=len(existing.get(day,{}).get('bars',[]))))
                del existing
                gc.collect()
                report=audit_stock(item,start,end,expected,prefix)
                report['provider_invalid_sessions']=invalid
                report['single_day_retries']=retries
                with pg.transaction():
                    store.write(f'{prefix}/stocks/{item["isin"]}/verification',report)
                summary['reports'].append(report)
                print(f'{item["symbol"]}: VERIFIED {report["complete_sessions"]}/{len(expected)} sessions; '
                      f'{report["missing_minutes"]} missing minutes',flush=True)
            except Exception as exc:
                # Request helper sanitizes provider errors; never print HTTP headers or credentials.
                failure=dict(symbol=item['symbol'],isin=item['isin'],error=str(exc))
                summary['failures'].append(failure)
                print(f'{item["symbol"]}: FAILED {type(exc).__name__}: {exc}',flush=True)
            checkpoint()
            gc.collect()
        summary['stocks_verified_complete']=sum(r['backtest_ready'] for r in summary['reports'])
        summary['total_candles']=sum(r['total_candles'] for r in summary['reports'])
        summary['missing_minutes']=sum(r['missing_minutes'] for r in summary['reports'])
        summary['status']='verified_complete' if summary['stocks_verified_complete']==50 else 'coverage_gaps'
        summary['backtest_ready']=summary['status']=='verified_complete'
        summary['completed_at']=store.now()
        checkpoint()
        print(json.dumps({k:v for k,v in summary.items() if k!='reports'}),flush=True)
        return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',type=date.fromisoformat,default=date(2024,10,1))
    p.add_argument('--end',type=date.fromisoformat,default=date(2026,11,3))
    p.add_argument('--output',type=Path,default=Path('/tmp/nifty50-stock-minutes'))
    p.add_argument('--audit-only',action='store_true')
    args=p.parse_args()
    result=(finalize if args.audit_only else run)(args.start,args.end,args.output)
    sys.exit(0 if result['status']=='verified_complete' else 2)
