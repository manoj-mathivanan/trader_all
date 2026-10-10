"""Reproducible, frozen-input swing research; no live portfolio writes.

Selection uses March 2025-February 2026 calibration and March-June 2026
validation. July-October is a previously inspected audit, never claimed OOS.
"""
import argparse
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import backtest, fundamental_history, market_history
from core.research.config import BacktestConfig

PERIODS = [('calibration', '2025-03-03', '2026-02-27'),
           ('validation', '2026-03-02', '2026-06-30')]
SCREEN_KEYS = ('pattern', 'base_days', 'max_depth_pct', 'volume_multiple',
               'sma_days', 'min_turnover', 'require_long_trend',
               'require_rising_long_trend', 'vcp_window_days', 'vcp_volume_multiple',
               'blue_sky_lookback_days', 'multiyear_base_days',
               'multiyear_max_depth_pct', 'ipo_max_age_days')


def initialize(reference):
    global DATA, BASE, SCORES
    report = json.loads((ROOT / f'data/runs/{reference}.json').read_text())
    DATA = json.loads((ROOT / f'data/run_data/{reference}.json').read_text())
    if not all(market_history.digest(DATA[m['symbol']]) == m['sha256'] for m in report['manifest']):
        raise ValueError('Frozen price hash mismatch.')
    financial = json.loads((ROOT / f'data/run_fundamentals/{reference}.json').read_text())
    if financial['sha256'] != report['fundamental_reference']['sha256']:
        raise ValueError('Frozen financial hash mismatch.')
    SCORES = fundamental_history.Scores(financial)
    BASE = {**report['config'], 'fee_model': 'zerodha_equity', 'buy_cost_bps': 0, 'sell_cost_bps': 0}
    original = backtest.signal
    identities = {id(rows) for rows in DATA.values()}
    cache = {}

    def cached(rows, i, cfg):
        # Never memoize temporary corporate-action-adjusted lists by recycled id.
        if id(rows) not in identities:
            return original(rows, i, cfg)
        key = (id(rows), i, tuple(getattr(cfg, k) for k in SCREEN_KEYS))
        if key not in cache:
            cache[key] = original(rows, i, cfg)
        return cache[key]
    backtest.signal = cached


def compact(result):
    trades = result['trades']
    profits = sorted((t['pnl'] for t in trades if t['pnl'] > 0), reverse=True)
    capital = result['metrics']['initial_capital']
    return {**result['metrics'], 'without_best_trade_pct':
            (sum(t['pnl'] for t in trades) - (profits[0] if profits else 0)) / capital * 100,
            'top_three_profit': sum(profits[:3]), 'rejections': result['entry_filter_rejections']}


def evaluate(item):
    name, changes = item
    values = {**BASE, **changes, 'name': name}
    row = dict(name=name, changes=changes, periods={})
    for label, start, end in PERIODS:
        cfg = BacktestConfig(**{**values, 'start': start, 'end': end})
        row['periods'][label] = compact(backtest.simulate(DATA, cfg, fundamental_scores=SCORES,
                                           entry_warmup=cfg.minimum_warmup_sessions))
    a, b = (row['periods'][p[0]] for p in PERIODS)
    # Predetermined lower-DD score. Profit without the best trade discourages
    # single-winner dependence; minimum trades excludes very sparse screens.
    row['eligible'] = a['trade_count'] >= 15 and b['trade_count'] >= 8
    row['score'] = (min(a['return_pct'], 50) + 2 * min(b['return_pct'], 35)
                    - a['max_drawdown_pct'] - 2 * b['max_drawdown_pct']
                    + .25 * (a['without_best_trade_pct'] + b['without_best_trade_pct']))
    return row


def candidates():
    rows = [('original_zerodha', {})]
    for exit_mode in ('take_8', 'take_15', 'trail_pct', 'trail_50d', 'trail_30w'):
        rows.append((exit_mode, {'winner_exit': exit_mode}))
    anchor = dict(winner_exit='trail_50d')
    axes = [('volume', 'volume_multiple', [1.25, 1.5, 2]),
            ('gap', 'max_open_gap_pct', [2, 3, 5]),
            ('risk', 'risk_pct', [.75, 1, 1.25]),
            ('stop', 'stop_pct', [6, 7, 10]),
            ('rs', 'min_rs_rating', [60, 70, 80]),
            ('extension', 'max_extension_pct', [20, 30, 40]),
            ('stall', 'stalled_exit_sessions', [5, 10, 15, 20]),
            ('failure', 'failed_breakout_sessions', [2, 3, 5]),
            ('cooldown', 'reentry_cooldown_sessions', [5, 10, 20]),
            ('be', 'breakeven_r', [.5, .75, 1.25])]
    for label, key, values in axes:
        rows.extend((f'trail50_{label}_{value}', {**anchor, key: value}) for value in values)
    rows.extend([
        ('trail50_rising200', {**anchor, 'require_rising_long_trend': True}),
        ('trail50_open_pivot', {**anchor, 'require_open_above_pivot': True}),
        ('trail50_breadth_off', {**anchor, 'skip_weak_markets': False}),
        ('trail50_market_half', {**anchor, 'skip_weak_markets': False, 'market_risk_scale': .5}),
        ('trail50_breadth_rising20', {**anchor, 'market_breadth_trend_sessions': 20}),
        ('trail50_rs_priority', {**anchor, 'candidate_rank': 'rs_126'}),
        ('trail50_vcp', {**anchor, 'pattern': 'vcp'}),
        ('trail50_multiyear', {**anchor, 'pattern': 'multiyear'})])
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', default='89e14eff54a3')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    target = ROOT / 'artifacts/swing_refinement_search.json'
    target.parent.mkdir(exist_ok=True)
    output = dict(reference=args.reference, selection_periods=PERIODS,
                  notice='Frozen current-member sample; final audit dates already inspected. Selection is exploratory.', trials=[])
    output['source_files']={str(p.relative_to(ROOT)).replace('\\','/'):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in [
        ROOT/'core/research/backtest.py', ROOT/'core/research/config.py',
        ROOT/'core/execution/zerodha.py', ROOT/'core/risk/position_sizer.py',
        ROOT/'strategies/swing_patterns/patterns/signals.py',Path(__file__).resolve()]}
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                             initargs=(args.reference,)) as pool:
        work = {pool.submit(evaluate, item): item[0] for item in candidates()}
        for future in as_completed(work):
            row = future.result()
            output['trials'].append(row)
            target.write_text(json.dumps(output, indent=2))
            print(row['name'], round(row['score'], 2), row['eligible'],
                  [round(x['return_pct'], 2) for x in row['periods'].values()], flush=True)
        leaders = sorted((r for r in output['trials'] if r['eligible']), key=lambda r:r['score'], reverse=True)[:4]
        # Small, declared combination stage: stronger single adjustments with
        # gap protection and reduced risk. No final-audit outcomes influence it.
        combinations = []
        seen = {json.dumps(r['changes'], sort_keys=True) for r in output['trials']}
        for leader in leaders:
            for suffix, additions in [('gap3', {'max_open_gap_pct':3}),
                                      ('risk1_gap3', {'risk_pct':1, 'max_open_gap_pct':3}),
                                      ('risk1_gap3_stall10', {'risk_pct':1, 'max_open_gap_pct':3, 'stalled_exit_sessions':10})]:
                changes = {**leader['changes'], **additions}
                key = json.dumps(changes, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    combinations.append((leader['name']+'_'+suffix, changes))
        for row in pool.map(evaluate, combinations):
            output['trials'].append(row)
            target.write_text(json.dumps(output, indent=2))
            print(row['name'], round(row['score'],2), row['eligible'],
                  [round(x['return_pct'],2) for x in row['periods'].values()], flush=True)
    ranked = sorted((r for r in output['trials'] if r['eligible']), key=lambda r:r['score'], reverse=True)
    output['selection'] = ranked[0] if ranked else None
    output['ranking'] = [r['name'] for r in ranked]
    target.write_text(json.dumps(output, indent=2))
    print('SELECTED', output['selection'], flush=True)


if __name__ == '__main__':
    main()
