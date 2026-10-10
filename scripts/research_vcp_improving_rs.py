"""Declared VCP / emerging-RS comparison using identical frozen Blue Sky inputs.

No parameter optimization, live portfolio changes or new market downloads.
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from bisect import bisect_left

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import backtest, fundamental_history, market_history, corporate_actions
from core.research.config import BacktestConfig
from core.research.relative_strength import StrengthHistory
from strategies.swing_patterns.patterns.signals import vcp_setup, vcp

VARIANTS = {
    'blue_sky': {},
    'blue_sky_rs126': {'min_rs_rating': 70},
    'vcp': {'pattern': 'vcp'},
    'vcp_rs126': {'pattern': 'vcp', 'min_rs_rating': 70},
    'vcp_rs63': {'pattern': 'vcp', 'min_short_rs_rating': 70},
    'vcp_rs63_improving': {'pattern': 'vcp', 'min_short_rs_rating': 70, 'min_rs_improvement': 10},
    'vcp_rs126_improving': {'pattern': 'vcp', 'rs_short_lookback': 126,
                            'min_short_rs_rating': 70, 'min_rs_improvement': 10},
}


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        keys = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', default='b4584ee01955')
    parser.add_argument('--output', default='artifacts/vcp_improving_rs')
    args = parser.parse_args()
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'data'
    original = json.loads((source / f'runs/{args.reference}.json').read_text(encoding='utf-8'))
    data_path = source / f'run_data/{args.reference}.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))
    if not all(market_history.digest(data[m['symbol']]) == m['sha256'] for m in original['manifest']):
        raise ValueError('Frozen input manifest mismatch')
    financial_path = source / f'run_fundamentals/{args.reference}.json'
    financial = json.loads(financial_path.read_text(encoding='utf-8'))
    if financial['sha256'] != original['fundamental_reference']['sha256']:
        raise ValueError('Frozen fundamental reference mismatch')
    scores = fundamental_history.Scores(financial)
    base = original['config']
    periods = {'full': (base['start'], base['end']),
               'calibration': ('2025-03-03', '2026-02-27'),
               'validation': ('2026-03-02', '2026-06-30'),
               'recent': ('2026-07-01', base['end'])}
    protocol = dict(reference=args.reference, variants=VARIANTS, periods=periods,
                    universe_count=len(data), price_file_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
                    financial_file_sha256=hashlib.sha256(financial_path.read_bytes()).hexdigest(),
                    source_files={str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [Path(__file__), ROOT/'core/research/backtest.py', ROOT/'core/research/config.py',
                                            ROOT/'core/research/relative_strength.py', ROOT/'core/execution/zerodha.py',
                                            ROOT/'strategies/swing_patterns/patterns/signals.py']},
                    notice='All periods previously inspected; current-member subset, not independent validation. No optimization.',
                    false_start_definition='Net losing trade exiting within 10 observed stock sessions after entry.',
                    matched_winner_definition='A candidate entry in the same stock within 60 stock sessions before or after a profitable baseline entry; proximity does not prove the same rally.')
    (out / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    results = {}
    ledger = []
    for name, changes in VARIANTS.items():
        results[name] = {}
        for label, (start, end) in periods.items():
            cfg = BacktestConfig(**{**base, **changes, 'name': name, 'start': start, 'end': end})
            result = backtest.simulate(data, cfg, fundamental_scores=scores, entry_warmup=cfg.minimum_warmup_sessions)
            if name == 'blue_sky' and label == 'full':
                if result['metrics'] != original['metrics'] or result['trades'] != original['trades']:
                    raise ValueError('Baseline replay differs from the saved run')
                protocol['baseline_replay_exact'] = True
            dates = {s: {b['date']: i for i, b in enumerate(rows)} for s, rows in data.items()}
            trades = result['trades']
            results[name][label] = dict(**result['metrics'],
                losing_trades=sum(t['pnl'] < 0 for t in trades),
                false_starts=sum(t['pnl'] < 0 and dates[t['symbol']][t['exit_date']]-dates[t['symbol']][t['entry_date']] <= 10 for t in trades),
                entry_filter_rejections=result['entry_filter_rejections'])
            (out / f'{name}_{label}.json').write_text(json.dumps(dict(config=cfg.model_dump(mode='json'), metrics=results[name][label], trades=trades, curve=result['curve']), indent=2), encoding='utf-8')
            ledger.extend(dict(variant=name, period=label, **t) for t in trades)
            (out / 'comparison.json').write_text(json.dumps(dict(protocol=protocol, results=results), indent=2), encoding='utf-8')
            print(name, label, round(result['metrics']['return_pct'], 2), 'DD', round(result['metrics']['max_drawdown_pct'], 2), 'trades', len(trades), flush=True)

    # Early watchlist is a diagnostic only: price still below the contraction pivot.
    cfg = BacktestConfig(**{**base, **VARIANTS['vcp_rs63_improving']})
    strength = StrengthHistory(data)
    setups, confirmed = [], []
    for symbol, rows in data.items():
        for i in range(max(cfg.minimum_warmup_sessions, backtest.required_warmup(cfg)), len(rows)):
            day = rows[i]['date']
            if not cfg.start.isoformat() <= day <= cfg.end.isoformat():
                continue
            adjusted = corporate_actions.adjusted_bars(rows, day)
            if not vcp_setup(adjusted, i, cfg) or not strength.passes(symbol, day, cfg):
                continue
            pivot = max(b['high'] for b in adjusted[i-cfg.vcp_window_days:i])
            if adjusted[i]['close'] <= pivot:
                setups.append(dict(symbol=symbol, date=day, close=adjusted[i]['close'], pivot=pivot, **strength.measure(symbol, day, cfg)))
            if vcp(adjusted, i, cfg):
                confirmed.append(dict(symbol=symbol, signal_date=day))
    write_csv(out / 'early_watchlist.csv', setups)
    write_csv(out / 'confirmed_signals.csv', confirmed)
    write_csv(out / 'trades.csv', ledger)
    winners = [t for t in original['trades'] if t['pnl'] > 0]
    matching = []
    for name in VARIANTS:
        entries = [t for t in ledger if t['variant'] == name and t['period'] == 'full']
        paired = []
        for winner in winners:
            idx = dates[winner['symbol']][winner['entry_date']]
            nearby = [t for t in entries if t['symbol'] == winner['symbol'] and abs(dates[t['symbol']][t['entry_date']]-idx) <= 60]
            chosen = min(nearby, key=lambda t: abs(dates[t['symbol']][t['entry_date']]-idx)) if nearby else None
            paired.append(dict(variant=name, symbol=winner['symbol'], baseline_entry=winner['entry_date'],
                               candidate_entry=chosen['entry_date'] if chosen else None,
                               lead_sessions=idx-dates[chosen['symbol']][chosen['entry_date']] if chosen else None))
        matching.extend(paired)
        results[name]['winner_capture'] = dict(baseline_winners=len(winners), missed=sum(t['candidate_entry'] is None for t in paired),
                                               earlier=sum(t['lead_sessions'] is not None and t['lead_sessions'] > 0 for t in paired))
    write_csv(out / 'winner_matching.csv', matching)
    protocol.update(early_watchlist_rows=len(setups), confirmed_signal_rows=len(confirmed))
    (out / 'comparison.json').write_text(json.dumps(dict(protocol=protocol, results=results), indent=2), encoding='utf-8')
    candidate, baseline = results['vcp_rs63_improving']['full'], results['blue_sky']['full']
    verdict = ('The candidate improves both full-period return and drawdown; independent validation is still required.'
               if candidate['return_pct'] > baseline['return_pct'] and candidate['max_drawdown_pct'] < baseline['max_drawdown_pct']
               else 'The candidate did not improve both full-period return and drawdown. These results do not support replacing Blue Sky.')
    lines = ['# VCP with improving relative strength', '', verdict, '',
             f"Frozen baseline {args.reference}: {len(data)} stocks, {base['start']} to {base['end']}. Baseline trades and metrics replay exactly.", '',
             'All variants retain fundamental ordering, next-open execution, five positions, ₹1 lakh capital, 8% stop, +15% close-based winner exit, breadth gate, Zerodha fees and 10 bps slippage per side. Only pattern and declared RS filters change. Thresholds were fixed before this comparison; no optimization.', '',
             '| Variant | Full net return | Max drawdown | Trades | False starts | Recent net return | Baseline winners missed | Earlier matched entries |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, result in results.items():
        a, b, c = result['full'], result['recent'], result['winner_capture']
        lines.append(f"| {name} | {a['return_pct']:.2f}% | {a['max_drawdown_pct']:.2f}% | {a['trade_count']} | {a['false_starts']} | {b['return_pct']:.2f}% | {c['missed']}/{c['baseline_winners']} | {c['earlier']} |")
    lines += ['', 'False starts: net losses closing within 10 observed stock sessions. Winner matching: same stock, closest candidate entry within ±60 sessions of each profitable baseline entry; this is a timing diagnostic, not proof of the same rally or profit capture.', '',
              f'{len(setups)} early watchlist stock-session rows and {len(confirmed)} confirmed VCP + RS63-improvement signals. Watchlist uses trend, liquidity, contraction and RS; it does not enforce portfolio slots, breadth, fundamental eligibility or earnings checks, and creates no orders.', '',
              'RS63-improving requires a 63-session return percentile ≥70 and a gain ≥10 percentile points from 20 stock sessions earlier. Historical ranks use eligible stocks on each historical date and action-adjusted prices available then. RS126-improving applies the same rule to 126-session returns.', '',
              'Calibration, validation and recent windows restart with cash and liquidate at their ends. Every period was previously inspected. Current constituents, exclusions, incomplete financial archives, daily-bar execution and unmodeled fill constraints limit conclusions. Earnings-event checks are not implemented. No paper or live portfolio settings were changed.']
    (out / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('REPORT', out / 'report.md', flush=True)


if __name__ == '__main__':
    main()
