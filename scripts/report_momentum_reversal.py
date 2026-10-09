"""Compare recorded follow/reverse momentum runs with identical frozen inputs."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from core.research import store


def report(control_id, reverse_id):
    control, reverse = [store.read('runs/' + key) for key in (control_id, reverse_id)]
    if not control or not reverse:
        raise ValueError('Both completed reports are required.')
    if control['config'].get('execution_mode', 'follow') != 'follow' or reverse['config']['execution_mode'] != 'reverse':
        raise ValueError('Supply a follow control followed by a reversed run.')
    ignored = {'name', 'comparison_run_id', 'execution_mode'}
    configs = [{k: v for k, v in r['config'].items() if k not in ignored} for r in (control, reverse)]
    if configs[0] != configs[1] or control['manifest'] != reverse['manifest'] or control['intraday_source']['sha256'] != reverse['intraday_source']['sha256']:
        raise ValueError('Configs or frozen input hashes differ; comparison halted.')
    if control['selections'] != reverse['selections']:
        raise ValueError('Daily stock selections differ; comparison halted.')
    capital = control['metrics']['initial_capital']
    summary = {'control_id': control_id, 'reverse_id': reverse_id, 'config': configs[0],
               'control': control['metrics'], 'reverse': reverse['metrics'],
               'same_frozen_inputs': True, 'yearly': []}
    entries = [{(t['symbol'], t['signal_timestamp'], t['entry_timestamp']) for t in r['trades']} for r in (control, reverse)]
    summary['entry_overlap'] = {'matched': len(entries[0] & entries[1]),
                              'control_only': len(entries[0] - entries[1]),
                              'reverse_only': len(entries[1] - entries[0])}
    for year in sorted({r['date'][:4] for r in control['curve']}):
        row = {'year': year}
        for label, run in [('control', control), ('reverse', reverse)]:
            prior = [p for p in run['curve'] if p['date'][:4] < year]
            points = [p for p in run['curve'] if p['date'][:4] == year]
            start = prior[-1]['equity'] if prior else capital
            row[label] = {'return_pct': (points[-1]['equity'] / start - 1) * 100,
                          'pnl': points[-1]['equity'] - start,
                          'trades': sum(t['entry_date'][:4] == year for t in run['trades'])}
        summary['yearly'].append(row)
    output = Path(__file__).resolve().parents[1]
    artifacts = output / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    (artifacts / 'momentum_reversal_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    fig, ax = plt.subplots(figsize=(12, 5.5), layout='constrained')
    for label, run, color in [('Original momentum', control, '#b64d42'), ('Reversed momentum', reverse, '#246c9d')]:
        dates = [datetime.fromisoformat(run['config']['start']), *[datetime.fromisoformat(p['date']) for p in run['curve']]]
        ax.plot(dates, [capital / 100000, *[p['equity'] / 100000 for p in run['curve']]], label=label, color=color, linewidth=1.6)
    ax.axhline(capital / 100000, color='#777777', linestyle='--', linewidth=.8)
    ax.set(title='Original vs reversed intraday momentum — after modeled costs', ylabel='Portfolio equity (INR lakh)')
    ax.grid(alpha=.18)
    ax.legend()
    fig.savefig(artifacts / 'momentum_reversal_equity.png', dpi=170)
    plt.close(fig)
    def metric(key, precision=2):
        return ['—' if r['metrics'][key] is None else f"{r['metrics'][key]:,.{precision}f}" for r in (control, reverse)]
    lines = ['# Reversed intraday momentum experiment', '',
             f"Original net return **{control['metrics']['return_pct']:+.3f}%**; reversed net return **{reverse['metrics']['return_pct']:+.3f}%**. Difference: {reverse['metrics']['return_pct'] - control['metrics']['return_pct']:+.3f} percentage points. These are reduced-universe, modeled-cost results.", '',
             f"Requested window: **{control['config']['start']}–{control['config']['end']}**. Observed sessions: {len(control['curve'])}, {control['curve'][0]['date']}–{control['curve'][-1]['date']}.", '',
             'Original signals, opening-volume ranking and next-bar entry timing are preserved. Reverse execution shorts buy signals and buys sell signals. Protective stops/targets use the actual position direction. Fees and adverse slippage are recalculated; this is not a sign flip of old P&L.', '',
             f"Universe: current {control['universe']}; {len(control['manifest'])} eligible daily symbols. Explicit event exclusions: {', '.join(control['config']['exclude_symbols']) or 'None'}. The unfiltered attempt failed its price-gap audit (job `77fdb4d0c2a5`); these four exclusions apply to both runs before liquidity ranking. Another {len(control['excluded']) - len(control['config']['exclude_symbols'])} symbols lacked eligible daily inputs. This reduced-universe result does not establish the full-universe result.", '',
             f"Control `{control_id}`; reverse `{reverse_id}`. Daily manifests, minute snapshot hashes, costs and all configuration fields except name/execution mode/reference are identical.", '',
             'Regular-opening candle exclusions: ' + ', '.join(control['config'].get('exclude_stock_sessions', [])) + '. Both runs skip these stock-sessions and any candidate whose opening-volume history uses them; the rest of each stock’s history remains eligible.', '',
             f"Matched entries: {summary['entry_overlap']['matched']}; control-only: {summary['entry_overlap']['control_only']}; reverse-only: {summary['entry_overlap']['reverse_only']}.", '',
             '| Measure | Original | Reversed |', '|---|---:|---:|']
    for label, key, precision in [('Starting capital (INR)', 'initial_capital', 2), ('Final equity (INR)', 'final_equity', 2), ('Net return (%)', 'return_pct', 3), ('Maximum session-end drawdown (%)', 'max_drawdown_pct', 3), ('Trades', 'trade_count', 0), ('Win rate (%)', 'win_rate', 2), ('Profit factor', 'profit_factor', 3), ('Expectancy (R)', 'expectancy_r', 3), ('Modeled fees (INR)', 'modeled_fees', 2), ('Modeled slippage (INR)', 'modeled_slippage', 2)]:
        a, b = metric(key, precision)
        lines.append(f'| {label} | {a} | {b} |')
    lines.extend(['', '| Calendar portion | Original return | Reversed return | Original / reversed trades |', '|---|---:|---:|---:|'])
    for row in summary['yearly']:
        a, b = row['control'], row['reverse']
        lines.append(f"| {row['year']} | {a['return_pct']:+.3f}% | {b['return_pct']:+.3f}% | {a['trades']} / {b['trades']} |")
    lines.extend(['', '![Matched equity curves](artifacts/momentum_reversal_equity.png)', '',
                  f"Cost attribution on actual trades: P&L with modeled fees/slippage added back is INR {control['diagnostics']['pnl_before_modeled_cost_impact']:,.2f} for the original and INR {reverse['diagnostics']['pnl_before_modeled_cost_impact']:,.2f} for the reversed strategy. This adds costs back to recorded fills, not a separate zero-cost backtest; costs also influence sizing and stops.", '',
                  'Parameters: five-minute opening range/confirmation; relative opening volume ≥1.5; top 50 prior-turnover stocks; up to five positions; 0.25% risk; 0.5 ATR stop; no profit target; last entry 11:30; square-off 15:00 IST. Starting capital INR 1,000,000. Slippage 10 bps each side; buy and sell charges 10 bps each.', '',
                  'Special sessions are omitted from normal-clock momentum eligibility, including any candidate whose 14-session opening-volume context contains one. Added 1 November 2024 Muhurat timing from [NSE circular CMTR64628](https://nsearchives.nseindia.com/content/circulars/CMTR64628.pdf); the existing 21 October 2025 special-session policy also applies. These days remain in the equity calendar with zero trading activity where ineligible.', '',
                  'Exploratory results: current constituents and retrospective exclusions introduce bias; corporate-action checks remain incomplete. Costs are assumptions, short eligibility/circuits/participation are unverified, and drawdown is measured at session ends. The entire historical window is exploratory. Defaults and live/paper behavior remain unchanged.', '',
                  'Reproduce the report: `.venv/Scripts/python.exe scripts/report_momentum_reversal.py ' + control_id + ' ' + reverse_id + '`.', ''])
    (output / 'MOMENTUM_REVERSE_RESEARCH.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('control_id')
    parser.add_argument('reverse_id')
    args = parser.parse_args()
    report(args.control_id, args.reverse_id)
