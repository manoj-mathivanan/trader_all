"""Audit investor losses and run declared diagnostics on frozen inputs only."""
import csv
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, corporate_actions, investor_breakouts, market_history, store
from core.research.config import BacktestConfig

BASELINE = 'a1ac1ce102c1'
COMPARISON = 'd1c26298219b'
OUT = Path('artifacts/investor_baseline/deep_analysis')


def groups(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[key(row)].append(row)
    return {k: dict(trades=len(v), pnl=sum(r['pnl'] for r in v),
                    mean_r=statistics.mean(r['r'] for r in v),
                    wins=sum(r['pnl'] > 1e-6 for r in v),
                    mean_held_sessions=statistics.mean(r['held_sessions'] for r in v)) for k, v in sorted(result.items())}


def describe(report, datasets):
    sectors = {i['symbol']: i.get('sector', 'Unknown') for i in report['universe_snapshot']['instruments']}
    cfg = BacktestConfig(**report['config'])
    rows = []
    for index, t in enumerate(report['trades']):
        bars = datasets[t['symbol']]
        by_day = {b['date']: i for i, b in enumerate(bars)}
        first, last = by_day[t['entry_date']], by_day[t['exit_date']]
        signal_bars = corporate_actions.adjusted_bars(bars, bars[first - 1]['date'])
        measurement = investor_breakouts.setup(signal_bars[:first], cfg.investor_rules) if cfg.investor_rules else None
        # Exclude the exit day's whole candle: its high/low can occur after the exit.
        path = corporate_actions.adjusted_bars(bars, t['entry_date'])[first:last]
        pnl = t['pnl']
        prior = signal_bars[:first]
        breakout_lookback = cfg.investor_rules.resistance_sessions if cfg.investor_rules else min(cfg.blue_sky_lookback_days, first - 1)
        level = max(b['high'] for b in prior[-breakout_lookback - 1:-1])
        old50 = sum(b['close'] for b in prior[-55:-5]) / 50
        ma50 = sum(b['close'] for b in prior[-50:]) / 50
        ma100 = sum(b['close'] for b in prior[-100:]) / 100
        ma20 = sum(b['close'] for b in prior[-20:]) / 20
        broad = []
        for stock_bars in datasets.values():
            idx = next((i for i in range(len(stock_bars) - 1, -1, -1) if stock_bars[i]['date'] == prior[-1]['date']), None)
            if idx is not None and idx >= 199:
                history = corporate_actions.adjusted_bars(stock_bars, prior[-1]['date'])
                broad.append(history[idx]['close'] > sum(b['close'] for b in history[idx - 199:idx + 1]) / 200)
        row = dict(t, trade_index=index, sector=sectors[t['symbol']], held_sessions=last - first + 1,
                   signal_date=prior[-1]['date'], signal_close=prior[-1]['close'], pivot=level,
                   opening_gap_pct=(bars[first]['open'] / prior[-1]['close'] - 1) * 100,
                   open_below_pivot=bars[first]['open'] < level,
                   strict_trend=prior[-1]['close'] >= ma20 >= ma50 >= ma100 and ma50 > old50,
                   breadth_pct=sum(broad) / len(broad) * 100 if broad else None,
                   signal_above_sma50_pct=(prior[-1]['close'] / ma50 - 1) * 100,
                   outcome='win' if pnl > 1e-6 else 'loss' if pnl < -1e-6 else 'flat',
                   pre_exit_mfe_pct=max([(b['high'] / t['entry'] - 1) * 100 for b in path], default=None),
                   pre_exit_mae_pct=min([(b['low'] / t['entry'] - 1) * 100 for b in path], default=None),
                   best_pre_exit_close_pct=max([(b['close'] / t['entry'] - 1) * 100 for b in path], default=None),
                   close_below_pivot_first_5=any(b['close'] < level for b in path[:5]),
                   reached_8pct_close=any(b['close'] >= t['entry'] * 1.08 for b in path),
                   reached_8pct_high=any(b['high'] >= t['entry'] * 1.08 for b in path))
        if measurement:
            row.update(volume_ratio=measurement['volume_ratio'], contraction_ratio=measurement['contraction_ratio'],
                       average_turnover=measurement['average_turnover'], extension_pct=measurement['distance_pct'])
        rows.append(row)
    tolerance = 1e-6
    wins, losses, flats = ([r for r in rows if r['pnl'] > tolerance], [r for r in rows if r['pnl'] < -tolerance],
                           [r for r in rows if abs(r['pnl']) <= tolerance])
    peak = report['curve'][0]
    worst = None
    for point in report['curve']:
        if point['equity'] > peak['equity']:
            peak = point
        dd = 100 * (peak['equity'] - point['equity']) / peak['equity']
        if worst is None or dd > worst['pct']:
            worst = dict(pct=dd, peak=peak, trough=point)
    monthly = {}
    previous = cfg.capital
    for point in report['curve']:
        monthly[point['date'][:7]] = point['equity']
    for month, equity in list(monthly.items()):
        monthly[month] = dict(return_pct=(equity / previous - 1) * 100, end_equity=equity)
        previous = equity
    equity_at = {p['date']: p['equity'] for p in report['curve']}
    exposures = defaultdict(float)
    for t in rows:
        bs = datasets[t['symbol']]
        for b in bs:
            if t['entry_date'] <= b['date'] < t['exit_date']:
                exposures[b['date']] += t['quantity'] * b['close']
    return dict(metrics=report['metrics'], tolerance_adjusted_counts=dict(wins=len(wins), losses=len(losses), flats=len(flats)),
                mean_win_r=statistics.mean(r['r'] for r in wins) if wins else None,
                mean_loss_r=statistics.mean(r['r'] for r in losses) if losses else None,
                gross_profit=sum(r['pnl'] for r in wins), gross_loss=sum(r['pnl'] for r in losses),
                fixed_ledger_before_modeled_costs_return_pct=report['metrics']['return_pct'] +
                    (report['metrics']['modeled_fees'] + report['metrics']['modeled_slippage']) / cfg.capital * 100,
                drawdown=worst, monthly=monthly, trades=rows,
                by_exit=groups(rows, lambda r: r['reason']), by_sector=groups(rows, lambda r: r['sector']),
                by_entry_month=groups(rows, lambda r: r['entry_date'][:7]),
                by_gap=groups(rows, lambda r: '<0%' if r['opening_gap_pct'] < 0 else '0–3%' if r['opening_gap_pct'] <= 3 else '>3%'),
                by_volume=groups([r for r in rows if 'volume_ratio' in r], lambda r: '<1.5×' if r['volume_ratio'] < 1.5 else '≥1.5×'),
                by_contraction=groups([r for r in rows if 'contraction_ratio' in r], lambda r: '≤0.8' if r['contraction_ratio'] <= .8 else '>0.8'),
                by_breadth=groups(rows, lambda r: '<40%' if (r['breadth_pct'] or 0) < 40 else '≥40%'),
                by_strict_trend=groups(rows, lambda r: str(r['strict_trend'])),
                by_open_below_pivot=groups(rows, lambda r: str(r['open_below_pivot'])),
                first_5_sessions=groups(rows, lambda r: 'exit ≤5 sessions' if r['held_sessions'] <= 5 else 'exit >5 sessions'),
                reentries={s: n for s, n in Counter(r['symbol'] for r in rows).items() if n > 1},
                intraday_8pct_without_close=groups([r for r in rows if r['reached_8pct_high'] and not r['reached_8pct_close']], lambda r: r['outcome']),
                early_pivot_failure=groups(rows, lambda r: str(r['close_below_pivot_first_5'])),
                mean_end_of_session_exposure_pct=statistics.mean(exposures.get(day, 0) / equity * 100 for day, equity in equity_at.items()))


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help='Reuse completed trials in this saved analysis.')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    reports = [store.read('runs/' + run_id) for run_id in (BASELINE, COMPARISON)]
    base, compare = reports
    datasets = store.read('run_data/' + BASELINE)
    assert base['manifest'] == compare['manifest']
    assert set(base['excluded']) == set(compare['excluded'])
    expected = {r['symbol']: r['sha256'] for r in base['manifest']}
    assert set(datasets) == set(expected)
    for symbol, bars in datasets.items():
        assert market_history.digest(bars) == expected[symbol], symbol + ' frozen hash changed'
    snapshot = store.read('run_data/' + COMPARISON)
    assert all(market_history.digest(snapshot[s]) == expected[s] for s in datasets)
    del snapshot
    cfg = BacktestConfig(**base['config'])
    analysis = dict(baseline_id=BASELINE, comparison_id=COMPARISON, audit=dict(frozen_hashes_match=True,
                    same_manifest=True, same_exclusions=True, included_stocks=len(datasets),
                    excluded_stocks=len(base['excluded']), exclusions_are_whole_stock_and_may_use_later_window_events=True,
                    out_of_sample=False), sensitivity=[])
    if args.resume:
        analysis = json.loads((OUT / 'analysis.json').read_text(encoding='utf-8'))
        assert analysis['baseline_id'] == BASELINE and analysis['comparison_id'] == COMPARISON
    else:
        for r in reports:
            print('Attribution: ' + r['config']['name'], flush=True)
            analysis[r['config']['pattern']] = describe(r, datasets)
    malformed = []
    for symbol, bars in datasets.items():
        for b in bars:
            if str(cfg.start) <= b['date'] <= str(cfg.end) and not (b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']):
                malformed.append(dict(symbol=symbol, date=b['date']))
    analysis['audit']['invalid_ohlc_in_test_window'] = malformed
    print('Attribution saved; running declared sensitivities.', flush=True)
    (OUT / 'analysis.json').write_text(json.dumps(analysis, indent=2), encoding='utf-8')
    trials = [
        ('Baseline replay', {}, {}),
        ('Zero costs (diagnostic only)', dict(buy_cost_bps=0, sell_cost_bps=0, slippage_bps=0), {}),
        ('Strict 20/50/100 trend', {}, dict(strict_trend=True)),
        ('Breakout volume ≥1.5×', {}, dict(min_breakout_volume_ratio=1.5)),
        ('Range contraction ≤0.8', {}, dict(max_contraction_ratio=.8)),
        ('Turnover ≥₹5 crore', {}, dict(min_turnover_rupees=50_000_000)),
        ('Opening gap ≤3%', dict(max_open_gap_pct=3), {}),
        ('Open above pivot', dict(require_open_above_pivot=True), {}),
        ('Protect at +4% (0.5R)', dict(breakeven_r=.5), {}),
        ('Protect at +16% (2R)', dict(breakeven_r=2), {}),
        ('Exit first-five-session pivot failure', dict(failed_breakout_sessions=5), {}),
        ('Market breadth ≥40%', dict(skip_weak_markets=True), {}),
        ('RS126 signal priority', dict(candidate_rank='rs_126'), {}),
    ]
    # Cache only exact references to retained frozen stock lists. Adjusted copies
    # fall back to the production predicate; ephemeral object IDs are never cached.
    retained = {id(bars): bars for bars in datasets.values()}
    memo = {}
    original = backtest.signal
    def cached_signal(bars, i, configuration):
        if configuration.pattern != 'investor_early_breakout' or retained.get(id(bars)) is not bars:
            return original(bars, i, configuration)
        key = (id(bars), i, configuration.investor_rules.model_dump_json())
        if key not in memo:
            memo[key] = original(bars, i, configuration)
        return memo[key]
    with patch.object(backtest, 'signal', side_effect=cached_signal):
        for name, changes, rule_changes in trials:
            saved = next((r for r in analysis['sensitivity'] if r['name'] == name), None)
            if saved:
                assert saved['config_changes'] == changes and saved['rule_changes'] == rule_changes
                print('Completed earlier: ' + name, flush=True)
                continue
            values = {**cfg.model_dump(mode='json'), **changes,
                      'investor_rules': {**cfg.investor_rules.model_dump(), **rule_changes}}
            experiment = BacktestConfig(**values)
            result = backtest.simulate(datasets, experiment, sector_instruments=base['universe_snapshot']['instruments'])
            if name == 'Baseline replay':
                assert result['trades'] == base['trades'], 'Replay trade ledger differs'
                assert result['curve'] == base['curve'], 'Replay equity differs'
                analysis['audit']['baseline_replay_identical'] = True
            curve = result['curve']
            middle = next(p for p in reversed(curve) if p['date'] < '2026-04-01')['equity']
            row = dict(name=name, config_changes=changes, rule_changes=rule_changes,
                       metrics=result['metrics'],
                       trade_ledger=result['trades'],
                       earlier_period_return_pct=(middle / cfg.capital - 1) * 100,
                       later_period_return_pct=(curve[-1]['equity'] / middle - 1) * 100)
            analysis['sensitivity'].append(row)
            (OUT / 'analysis.json').write_text(json.dumps(analysis, indent=2), encoding='utf-8')
            print(f"{name}: {result['metrics']['return_pct']:.2f}% / DD {result['metrics']['max_drawdown_pct']:.2f}% / {result['metrics']['trade_count']} trades", flush=True)
    details = analysis['investor_early_breakout']['trades']
    with (OUT / 'trade_diagnostics.csv').open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=sorted({k for r in details for k in r}))
        writer.writeheader()
        writer.writerows(details)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from datetime import date
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout='constrained')
    for r, color in zip(reports, ('#b45353', '#347d6b')):
        dates = [date.fromisoformat(p['date']) for p in r['curve']]
        axes[0, 0].plot(dates, [p['equity'] / cfg.capital * 100 - 100 for p in r['curve']], label=r['config']['pattern'], color=color)
        axes[0, 1].plot(dates, [-p['drawdown_pct'] for p in r['curve']], color=color)
    axes[0, 0].set(title='Portfolio return after modeled costs', ylabel='Return (%)')
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].set(title='Drawdown from running peak', ylabel='Drawdown (%)')
    data = analysis['investor_early_breakout']
    exits = data['by_exit']
    axes[1, 0].barh(list(exits), [x['pnl'] / 1000 for x in exits.values()], color='#b45353')
    axes[1, 0].set(title='Investor realized P&L by exit', xlabel='P&L (₹ thousands)')
    trials = analysis['sensitivity']
    axes[1, 1].barh([t['name'] for t in trials], [t['metrics']['return_pct'] for t in trials], color=['#347d6b' if t['metrics']['return_pct'] >= 0 else '#b45353' for t in trials])
    axes[1, 1].axvline(0, color='#555', linewidth=.8)
    axes[1, 1].set(title='Declared one-change diagnostics\nSame inspected sample', xlabel='Return (%)')
    axes[1, 1].tick_params(axis='y', labelsize=7)
    for ax in axes.flat:
        ax.grid(axis='x', alpha=.15)
    fig.suptitle('Investor technical baseline: 1 Oct 2025–9 Oct 2026 · 672 frozen stocks\nExploratory sample; news and financial assessments excluded', fontsize=12)
    fig.savefig(OUT / 'diagnostics.png', dpi=160)
    print(str(OUT.resolve()), flush=True)


if __name__ == '__main__':
    main()
