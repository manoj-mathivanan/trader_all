"""Daily OHLCV refresh and resumable five-minute coverage audit/backfill."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import intraday_data, jobs, market_data as market, store
import httpx

PROVIDER_START = date(2022, 1, 1)
STATE = 'market_five_minute_backfill'


def require_server_schedule():
    if os.environ.get('TRADER_ENV') != 'production' or not store.database_enabled():
        raise ValueError('Scheduled market refresh is server-only. Run manually without --scheduled when explicitly requested locally.')


def cached_sessions(item, start, end):
    if store.database_enabled():
        from core.research import postgres_store as pg
        rows = pg.connection().execute(
            'SELECT session,bars FROM trader.intraday_sessions WHERE namespace=%s '
            'AND isin=%s AND interval_minutes=5 AND session BETWEEN %s AND %s',
            (pg.namespace(),item['isin'],str(start),str(end))).fetchall()
        return {day: {'bars':bars} for day,bars in rows}
    prefix = f"intraday/5m/{item['isin']}/"
    return {key.rsplit('/',1)[1]:store.read(key) for key in store.keys(prefix)
            if str(start) <= key.rsplit('/',1)[1] <= str(end)}


def expected_sessions(daily, calendar, start, end):
    """No prelisting expectation; expose missing daily observations separately."""
    days = sorted({b['date'] for b in daily if b['date'] <= str(end)})
    if not days:
        return [], []
    first = max(str(start),days[0])
    expected = sorted({d for d in calendar if first <= d <= str(end)} |
                      {d for d in days if first <= d <= str(end)})
    return expected, sorted(set(expected)-set(days))


def coverage(item, daily, calendar, start, end):
    expected, daily_missing = expected_sessions(daily,calendar,start,end)
    cached = cached_sessions(item,start,end)
    missing = [d for d in expected if not market.complete_minutes(cached.get(d),d)]
    return dict(symbol=item['symbol'],isin=item['isin'],expected_sessions=len(expected),
                complete_sessions=len(expected)-len(missing),missing_sessions=missing,
                missing_daily_sessions=daily_missing,first_expected=expected[0] if expected else None,
                last_expected=expected[-1] if expected else None)


def backfill(log, *, start=PROVIDER_START, audit_only=False):
    start = max(start,PROVIDER_START)
    token = store.token()
    with httpx.Client(timeout=40) as client:
        end = market.last_traded_day(client,token)
        # Independent exchange calendar prevents a missing daily stock candle hiding a gap.
        calendar_bars = market.upstox.fetch_range(client,market.BENCHMARK,token,start,end)
        calendar = [b['date'] for b in calendar_bars]
        if not calendar or calendar[-1] != str(end):
            raise ValueError('Completed-session calendar unavailable for the backfill.')
        universe = store.read('universes/niftytotalmarket',{}).get('instruments',[])
        if not universe:
            raise ValueError('Refresh the full stock universe first.')
        report = dict(start=str(start),end=str(end),started_at=store.now(),status='running',
                      audit_only=audit_only,total_symbols=len(universe),processed_symbols=0,
                      expected_sessions=0,complete_sessions=0,missing_sessions=0,
                      downloaded_bars=0,stocks=[],failures=[])
        state_key = STATE+'_audit' if audit_only else STATE
        store.write(state_key,report)
        for item in universe:
            daily = store.read('bars/'+item['isin'],{}).get('bars',[])
            before = coverage(item,daily,calendar,start,end)
            failed = []
            if not audit_only:
                expected, _ = expected_sessions(daily,calendar,start,end)
                ranges = list(market.minute_ranges(expected,set(before['missing_sessions'])))
                for first,last in reversed(ranges):
                    try:
                        got = market.download_minutes(client,item,token,first,last)
                        report['downloaded_bars'] += got['bars']
                    except Exception as exc:
                        message = market.error_detail(exc)
                        if '401/403' in message:
                            report.update(status='failed',message=message,updated_at=store.now())
                            store.write(state_key,report)
                            raise ValueError(message) from None
                        failed.append(dict(start=str(first),end=str(last),message=message))
                    time.sleep(.15)
            after = before if audit_only else coverage(item,daily,calendar,start,end)
            after['missing_before'] = len(before['missing_sessions'])
            after['download_failures'] = failed
            if not daily:
                after['error'] = 'No daily history: listing boundary cannot be verified.'
            stock_key = state_key+'/stocks/'+item['isin']
            store.write(stock_key,after)
            report['stocks'].append({k:after[k] for k in ('symbol','isin','expected_sessions','complete_sessions','missing_before')})
            report['stocks'][-1].update(missing_sessions=len(after['missing_sessions']),detail_key=stock_key)
            report['processed_symbols'] += 1
            report['expected_sessions'] += after['expected_sessions']
            report['complete_sessions'] += after['complete_sessions']
            report['missing_sessions'] += len(after['missing_sessions'])
            if failed or after.get('error'):
                report['failures'].append(item['symbol'])
            report['updated_at'] = store.now()
            store.write(state_key,report)
            log(f"{report['processed_symbols']}/{len(universe)} {item['symbol']}: "
                f"{after['complete_sessions']}/{after['expected_sessions']} complete; "
                f"{len(after['missing_sessions'])} missing/incomplete (was {after['missing_before']}).")
        report['partial'] = bool(report['missing_sessions'] or report['failures'])
        report['status'] = 'warning' if report['partial'] else 'success'
        report['completed_at'] = store.now()
        store.write(state_key,report)
        return {k:report[k] for k in ('start','end','status','total_symbols','processed_symbols',
            'expected_sessions','complete_sessions','missing_sessions','downloaded_bars','partial','completed_at')} | {'report_key':state_key}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backfill',action='store_true')
    parser.add_argument('--audit-only',action='store_true')
    parser.add_argument('--scheduled',action='store_true',help='Require the production server environment.')
    parser.add_argument('--start',type=date.fromisoformat,default=PROVIDER_START)
    args = parser.parse_args()
    if args.scheduled:
        try:
            require_server_schedule()
        except ValueError as exc:
            parser.error(str(exc))
    def execute(log,job_id):
        # jobs.submit already claims the global job slot transactionally. Reuse its
        # connection so the small production DB retains connection headroom.
        if not args.audit_only:
            market.fetch(log,job_id,include_fundamentals=False)
        if args.backfill or args.audit_only:
            result = backfill(log,start=args.start,audit_only=args.audit_only)
            if args.backfill:
                # Long backfills can cross the market close. Catch up once more
                # before releasing the global job slot to the regular scheduler.
                latest = market.fetch(log,job_id,include_fundamentals=False)
                result['latest_refresh_end'] = latest['end']
                result['partial'] = result['partial'] or latest['partial']
            return result
        return store.read('market_fetch')
    job = jobs.submit('Five-minute history backfill' if args.backfill else
                      'Five-minute coverage audit' if args.audit_only else 'Daily market history refresh',
                      execute,dict(start=str(args.start),backfill=args.backfill,audit_only=args.audit_only))
    print(json.dumps({'job_id':job['id']}),flush=True)
    jobs.POOL.shutdown(wait=True)
    result = next(j for j in store.read('jobs',[]) if j['id']==job['id'])
    print(json.dumps({k:result.get(k) for k in ('id','status','updated_at')}),flush=True)
    if result['status']=='failed':
        print(result['logs'][-1]['message'],flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
