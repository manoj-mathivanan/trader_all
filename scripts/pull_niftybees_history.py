"""Resolve the tradable ETF, archive its minute history, and compare with Nifty."""
import argparse
from datetime import date
import gzip
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from core.research import postgres_store as pg, store, upstox
from scripts.pull_nifty_minute_history import pull, persisted_sessions


def resolve_instrument():
    with httpx.Client(timeout=60) as client:
        response = client.get(upstox.INSTRUMENTS)
        response.raise_for_status()
    rows = json.loads(gzip.decompress(response.content))
    matches = [r for r in rows if r.get('trading_symbol') == 'NIFTYBEES'
               and r.get('segment') == 'NSE_EQ']
    if len(matches) != 1:
        raise ValueError('Expected one official NSE NIFTYBEES instrument.')
    row = matches[0]
    with pg.transaction():
        store.write('market_archives/niftybees_instrument', dict(
            source=upstox.INSTRUMENTS, fetched_at=store.now(), provider_record=row))
    return dict(isin=row['isin'], symbol=row['trading_symbol'], key=row['instrument_key'],
                name=row['name'], exchange=row['segment'])


def compare(start, end, instrument, output):
    etf = persisted_sessions(start, end, instrument['isin'])
    index = persisted_sessions(start, end)
    ratios, etf_returns, index_returns, examples = [], [], [], []
    matched = 0
    same_price = True
    days = sorted(set(etf) & set(index))
    sample_days = {days[0], days[len(days)//2], days[-1]} if days else set()
    for day in days:
        eb = {b['timestamp']: b for b in etf[day]['bars']}
        ib = {b['timestamp']: b for b in index[day]['bars']}
        previous = None
        common = sorted(set(eb) & set(ib))
        for stamp in common:
            e, i = eb[stamp], ib[stamp]
            matched += 1
            same_price = same_price and e['close'] == i['close']
            ratios.append(i['close']/e['close'])
            if previous is not None and stamp-previous == 60000:
                etf_returns.append(e['close']/eb[previous]['close']-1)
                index_returns.append(i['close']/ib[previous]['close']-1)
            previous = stamp
        if day in sample_days and common:
            stamp = common[-1]
            examples.append(dict(date=day, time=eb[stamp]['time'],
                                 niftybees_close=eb[stamp]['close'], nifty50_close=ib[stamp]['close'],
                                 index_to_etf_ratio=ib[stamp]['close']/eb[stamp]['close']))
    if not ratios:
        raise ValueError('No common index/ETF candles to compare.')
    tracking = [abs(e-i)*10000 for e,i in zip(etf_returns,index_returns)]
    report = dict(instrument=instrument, compared_with='NSE_INDEX|Nifty 50',
        start=str(start), end=str(end), compared_at=store.now(), matched_minute_candles=matched,
        matched_sessions=len(days), same_price=same_price,
        index_to_etf_price_ratio=dict(min=min(ratios), median=statistics.median(ratios), max=max(ratios)),
        consecutive_within_session_return_pairs=len(etf_returns),
        one_minute_return_correlation=statistics.correlation(etf_returns,index_returns)
            if len(etf_returns)>1 and statistics.pstdev(etf_returns)>0 and statistics.pstdev(index_returns)>0 else None,
        absolute_one_minute_return_difference_bps=dict(median=statistics.median(tracking),max=max(tracking))
            if tracking else None,
        examples=examples,
        interpretation='Use actual ETF OHLC and traded volume for fills and indicators; index prices are separate signal inputs.',
        limitations=['Candle comparison does not measure bid/ask spreads or executable fills.',
                     'Close-to-close price returns exclude distributions and are not total returns.',
                     'Correlation is descriptive, not a validation of any strategy.'])
    key=f'market_archives/niftybees_1m/{start}_{end}/index_comparison'
    with pg.transaction():
        store.write(key,report)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',type=date.fromisoformat,default=date(2024,10,1))
    p.add_argument('--end',type=date.fromisoformat,default=date(2026,11,2))
    p.add_argument('--output',type=Path,default=Path('/tmp/niftybees-history'))
    args=p.parse_args()
    instrument=resolve_instrument()
    print(json.dumps(instrument),flush=True)
    coverage=pull(args.start,args.end,args.output/'verification.json',instrument=instrument)
    compare(args.start,args.end,instrument,args.output/'index-comparison.json')
    sys.exit(0 if coverage['backtest_ready'] else 2)
