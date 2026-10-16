"""Console-only winner audit and annual comparisons; no strategy or report writes."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, corporate_actions, data_quality, market_history, store
from core.research.config import BacktestConfig


def emit(kind, value):
    print(kind + ' ' + json.dumps(value, ensure_ascii=False), flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    base = store.read('runs/a1ac1ce102c1')
    universe = store.read('universes/' + base['universe'])
    reference = market_history.evidence(snapshot=True)
    records = {}
    for item in universe['instruments']:
        r = store.read('bars/' + item['isin'])
        if r:
            bs, history = market_history.prepare(item, r, reference=reference, fingerprint=False)
            if bs:
                records[item['symbol']] = (bs, r['requested_start'], r['requested_end'], history)
    benchmark = store.read('sector/prices/benchmark')['bars']
    periods = [('2021-01-01', '2022-12-31'), ('2023-01-01', '2024-12-31')]
    years = [(f'{y}-01-01', f'{y}-12-31') for y in range(2021, 2026)] + [('2026-01-01', '2026-10-09')]
    emit('PLAN', dict(audit_periods=periods, annual_periods=years, ranking='rs_126',
         costs_bps_per_side=dict(fees=10, slippage=10), warmup=200,
         annual_accounts_reset=True, no_parameter_selection=True))

    def inputs_for(start, end):
        inputs = {s: [b for b in bs if b['date'] <= end] for s, (bs, rs, re, _) in records.items()
                  if rs <= start and re >= end and sum(b['date'] < start for b in bs) >= 200}
        inputs = {s: bs for s, bs in inputs.items() if any(start <= b['date'] <= end for b in bs)}
        quality = data_quality.audit(inputs, end=end)
        inputs = data_quality.exclude_anomalies(inputs, quality)
        emit('COVERAGE', dict(start=start, end=end, stocks=len(inputs), exclusions=quality['excluded_symbols']))
        return inputs

    def config(start, end, pattern):
        return BacktestConfig(**{**base['config'], 'start': start, 'end': end, 'pattern': pattern,
              'candidate_rank': 'rs_126', 'minimum_warmup_sessions': 200, 'comparison_run_id': None,
              'investor_rules': base['config']['investor_rules'] if pattern == 'investor_early_breakout' else None})

    def run(inputs, cfg):
        result = backtest.simulate(inputs, cfg, sector_instruments=universe['instruments'])
        assert abs(sum(t['pnl'] for t in result['trades']) - result['metrics']['final_equity'] + cfg.capital) < .1
        return result

    for start, end in periods:
        inputs = inputs_for(start, end)
        result = run(inputs, config(start, end, 'blue_sky'))
        expected = {'2021-01-01': 1451793.31, '2023-01-01': 2617677.9}[start]
        assert abs(result['metrics']['final_equity'] - expected) < .01, 'Older Blue Sky replay changed'
        trades = sorted(result['trades'], key=lambda t: t['pnl'], reverse=True)
        winners = [t for t in trades if t['pnl'] > 1e-6]
        total = sum(t['pnl'] for t in trades)
        emit('CONCENTRATION', dict(period=start[:4] + '-' + end[:4], metrics=result['metrics'],
             gross_winner_pnl=sum(t['pnl'] for t in winners),
             top1_pnl=sum(t['pnl'] for t in trades[:1]), top3_pnl=sum(t['pnl'] for t in trades[:3]),
             top5_pnl=sum(t['pnl'] for t in trades[:5]),
             fixed_ledger_return_without_top1=100*(total-sum(t['pnl'] for t in trades[:1]))/1e6,
             fixed_ledger_return_without_top3=100*(total-sum(t['pnl'] for t in trades[:3]))/1e6,
             fixed_ledger_return_without_top5=100*(total-sum(t['pnl'] for t in trades[:5]))/1e6,
             actions=result['corporate_actions']))
        for t in trades[:5]:
            bs = inputs[t['symbol']]
            i = next(i for i, b in enumerate(bs) if b['date'] == t['entry_date'])
            j = next(i for i, b in enumerate(bs) if b['date'] == t['exit_date'])
            path = bs[i:j+1]
            prior = corporate_actions.adjusted_bars(bs, bs[i-1]['date'])
            pairs = list(zip(bs[max(0, i-1):j], bs[i:j+1]))
            gaps = sorted([dict(date=b['date'], gap_pct=100*(b['open']/a['close']-1),
                                close_change_pct=100*(b['close']/a['close']-1)) for a,b in pairs],
                          key=lambda r: abs(r['close_change_pct']), reverse=True)
            invalid = [b['date'] for b in path if not (b['low'] <= min(b['open'],b['close']) <= max(b['open'],b['close']) <= b['high'])]
            dates = [b['date'] for b in bs]
            calendar_dates = {b['date'] for b in benchmark if t['entry_date'] <= b['date'] <= t['exit_date']}
            emit('WINNER', dict(period=start[:4]+'-'+end[:4], trade=t,
                 price_return_pct=100*(t['exit']/t['entry']-1), sessions=j-i+1,
                 signal_date=bs[i-1]['date'], signal_close=prior[i-1]['close'],
                 prior_high=max(b['high'] for b in prior[max(0,i-5001):i-1]),
                 cached_history_start=bs[0]['date'],
                 entry_open=bs[i]['open'], exit_ohlc=bs[j],
                 entry_quantity_pct_daily_volume=100*t['quantity']/bs[i]['volume'] if bs[i]['volume'] else None,
                 exit_quantity_pct_daily_volume=100*t['quantity']/bs[j]['volume'] if bs[j]['volume'] else None,
                 largest_daily_changes=gaps[:3], invalid_ohlc=invalid,
                 duplicate_dates=len(dates)!=len(set(dates)),
                 missing_benchmark_sessions=sorted(calendar_dates-set(b['date'] for b in path)),
                 history_evidence=records[t['symbol']][3]))

    if '--audit-only' in sys.argv:
        return
    for start, end in years:
        inputs = inputs_for(start, end)
        rows = []
        for pattern in ['investor_early_breakout', 'blue_sky']:
            result = run(inputs, config(start, end, pattern))
            rows.append(dict(pattern=pattern, metrics=result['metrics']))
        prior = [b for b in benchmark if b['date'] < start][-1]
        path = [b for b in benchmark if start <= b['date'] <= end]
        peak, dd = prior['close'], 0
        for b in path:
            peak = max(peak,b['close'])
            dd = max(dd,100*(1-b['close']/peak))
        emit('ANNUAL', dict(start=start, end=end, stocks=len(inputs), strategies=rows,
             benchmark_price_return_pct=100*(path[-1]['close']/prior['close']-1),
             benchmark_drawdown_pct=dd, benchmark_last_date=path[-1]['date']))


if __name__ == '__main__':
    main()
