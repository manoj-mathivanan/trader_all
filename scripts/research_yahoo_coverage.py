"""Read-only Yahoo coverage experiment; writes only the requested report directory.

Run in an isolated environment with yfinance installed. No Trader storage imports.
"""
import argparse
import contextlib
import importlib.metadata
import io
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SAMPLE = {
    'RELIANCE.NS': 'large diversified company',
    'TCS.NS': 'large IT company',
    'HDFCBANK.NS': 'bank',
    'BAJFINANCE.NS': 'NBFC',
    'SUNPHARMA.NS': 'pharmaceutical company',
    'SKYGOLD.NS': 'smaller company',
    'VIKRAMSOLR.NS': 'recent listing',
    'VALIANT.BO': 'BSE-only smaller company',
    'RELIANCE.BO': 'cross-exchange control',
    'AAPL': 'US access control',
}


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if hasattr(value, 'item'):
        return clean(value.item())
    return value


def table(frame):
    if frame is None:
        return {'rows': 0, 'columns': [], 'records': {}}
    return {'rows': len(frame), 'columns': [str(c) for c in frame.columns],
            'records': clean(frame.to_dict(orient='index'))}


def worker(symbol, out):
    import yfinance as yf
    yf.set_tz_cache_location(str(out / 'yahoo_cache'))
    ticker = yf.Ticker(symbol)
    report = {'symbol': symbol, 'role': SAMPLE.get(symbol), 'endpoints': {}}
    target = out / (symbol.replace('.', '_') + '.json')

    def save():
        target.write_text(json.dumps(clean(report), indent=2, allow_nan=False), encoding='utf-8')

    operations = {
        'history': lambda: table(ticker.history(period='1mo', auto_adjust=False, actions=True, timeout=15)),
        'quarterly_income': lambda: table(ticker.get_income_stmt(freq='quarterly')),
        'annual_income': lambda: table(ticker.get_income_stmt(freq='yearly')),
        'balance_sheet': lambda: table(ticker.get_balance_sheet(freq='yearly')),
        'cashflow': lambda: table(ticker.get_cash_flow(freq='yearly')),
        'calendar': ticker.get_calendar,
        'earnings_dates': lambda: table(ticker.get_earnings_dates(limit=4)),
        'news': lambda: ticker.get_news(count=10),
        'filings': ticker.get_sec_filings,
    }
    save()
    for name, operation in operations.items():
        started = time.monotonic()
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured), contextlib.redirect_stdout(captured):
            try:
                value = operation()
                empty = value is None or value == {} or value == [] or (isinstance(value, dict) and value.get('rows') == 0)
                entry = {'status': 'empty' if empty else 'returned', 'data': clean(value)}
            except Exception as exc:
                entry = {'status': 'error', 'error_type': type(exc).__name__, 'message': str(exc)[:700]}
        entry['seconds'] = round(time.monotonic() - started, 2)
        entry['diagnostics'] = captured.getvalue()[-1500:]
        report['endpoints'][name] = entry
        save()
        print(symbol, name, entry['status'], flush=True)
        time.sleep(1)
    return report


def summarize(report, baseline):
    ep = report['endpoints']
    row = {'symbol': report['symbol'], 'endpoints': {k: v['status'] for k, v in ep.items()}}
    hist = ep.get('history', {}).get('data') or {}
    records = hist.get('records', {})
    row['price_rows'] = len(records)
    if records:
        row['latest_price_date'] = max(records)[:10]
    # Never compare a BSE close with an NSE candle merely because names match.
    local = baseline.get(report['symbol'].split('.')[0], {}) if report['symbol'].endswith('.NS') else {}
    localbars = {b['date'][:10]: b for b in (local.get('bars') or {}).get('bars', [])}
    comparisons = []
    for stamp, bar in records.items():
        previous = localbars.get(stamp[:10])
        if previous and previous.get('close'):
            comparisons.append({'date': stamp[:10], 'yahoo_close': bar['Close'], 'upstox_close': previous['close'],
                                'difference_pct': (bar['Close'] / previous['close'] - 1) * 100})
    row['matched_prices'] = comparisons
    for name in ('quarterly_income', 'annual_income', 'balance_sheet', 'cashflow'):
        data = ep.get(name, {}).get('data') or {}
        row[name + '_periods'] = data.get('columns', [])
        row[name + '_metrics'] = data.get('rows', 0)
        row[name + '_nonempty_periods'] = [c for c in data.get('columns', [])
            if any(values.get(c) is not None for values in data.get('records', {}).values())]
    snapshot = (local.get('fundamentals') or {}).get('snapshot') or {}
    period = snapshot.get('period_end')
    quarter = ep.get('quarterly_income', {}).get('data') or {}
    comparisons = []
    for calculation in snapshot.get('calculations', []):
        candidates = {'revenue_growth_pct': ['TotalRevenue', 'OperatingRevenue'],
                      'profit_growth_pct': ['NetIncome', 'NetIncomeIncludingNoncontrollingInterests']}.get(calculation['key'], [])
        if not candidates:
            continue
        for metric in candidates:
            values = quarter.get('records', {}).get(metric, {})
            for column, value in values.items():
                if column[:10] == period and value is not None:
                    official = float(calculation['current'])
                    comparisons.append({'metric': metric, 'period': period, 'yahoo_value': value,
                        'official_value': official, 'official_key': calculation['key'],
                        'difference_pct': (value / official - 1) * 100 if official else None})
    row['financial_diagnostics'] = comparisons
    row['financial_comparison_notice'] = 'Candidate field comparisons only: Yahoo accounting basis and revenue/PAT definitions must be reconciled before treating differences as errors.'
    news = ep.get('news', {}).get('data') or []
    row['news_count'] = len(news) if isinstance(news, list) else None
    row['calendar_earnings_dates'] = (ep.get('calendar', {}).get('data') or {}).get('Earnings Date', [])
    return row


def search_probe(output):
    """Check company-name discovery as well as exchange-suffixed ticker search."""
    import yfinance as yf
    result = {}
    for query in ('RELIANCE.NS', 'TCS.NS', 'VIKRAMSOLR.NS', 'AAPL',
                  'Reliance Industries', 'Tata Consultancy Services', 'HDFC Bank', 'Vikram Solar'):
        try:
            found = yf.Search(query, news_count=5, max_results=2, timeout=15)
            result[query] = {'news': found.news, 'quotes': found.quotes}
        except Exception as exc:
            result[query] = {'error_type': type(exc).__name__, 'message': str(exc)[:700]}
        (output / 'search_probe.json').write_text(json.dumps(clean(result), indent=2, allow_nan=False), encoding='utf-8')
        print(query, 'news', len(result[query].get('news', [])), flush=True)
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--symbols', nargs='+', default=list(SAMPLE))
    parser.add_argument('--worker')
    parser.add_argument('--timeout', type=int, default=150)
    parser.add_argument('--search-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.search_only:
        search_probe(args.output)
        return
    if args.worker:
        worker(args.worker, args.output)
        return
    baseline = json.loads(args.baseline.read_text(encoding='utf-8-sig')) if args.baseline else {}
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'yfinance_version': importlib.metadata.version('yfinance'),
              'method': 'Sequential symbols and endpoints; unadjusted closes; bounded subprocess per symbol; no application data writes.',
              'limitations': ['Small convenience sample, not a universe-wide or uptime audit.',
                              'A returned response is not verification of factual accuracy or news relevance.',
                              'SEC filings endpoint is tested only as an available library feature, not assumed to cover NSE/BSE.',
                              'Financial statement periods are not publication dates or revision history.'], 'results': []}
    for symbol in args.symbols:
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--output', str(args.output.resolve()), '--worker', symbol],
                           timeout=args.timeout, check=True)
            completed = True
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            completed = False
        path = args.output / (symbol.replace('.', '_') + '.json')
        item = json.loads(path.read_text()) if path.exists() else {'symbol': symbol, 'endpoints': {}}
        row = summarize(item, baseline)
        row['completed'] = completed
        report['results'].append(row)
        report['updated_at'] = datetime.now(timezone.utc).isoformat()
        (args.output / 'report.json').write_text(json.dumps(clean(report), indent=2, allow_nan=False), encoding='utf-8')
    print('Saved', str(args.output / 'report.json'), 'for', len(report['results']), 'symbols.')


if __name__ == '__main__':
    main()
