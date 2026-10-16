"""Compare investor technical breakouts with Blue Sky on frozen daily inputs."""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, store
from core.research.config import BacktestConfig, current_settings
from core.research.investor_rules import Rules


def save_comparison(run_ids, output):
    reports = [store.read('runs/' + run_id) for run_id in run_ids]
    baseline, comparison = reports
    if comparison['comparison']['run_id'] != baseline['id'] or comparison['manifest'] != baseline['manifest'] or set(comparison['excluded']) != set(baseline['excluded']):
        raise ValueError('Comparison changed the eligible stocks or frozen input manifest.')
    keys = ('start', 'end', 'capital', 'entry_mode', 'candidate_rank', 'max_positions', 'risk_pct', 'stop_pct',
            'winner_exit', 'breakeven_r', 'max_hold_days', 'fee_model', 'buy_cost_bps', 'sell_cost_bps',
            'slippage_bps', 'minimum_warmup_sessions')
    shared = {k: baseline['config'][k] for k in keys}
    if shared != {k: comparison['config'][k] for k in keys}:
        raise ValueError('Comparison changed portfolio or execution assumptions.')
    summary = dict(start=shared['start'], end=shared['end'], assumptions=shared,
                   investor_rules=baseline['config']['investor_rules'],
                   runs=[dict(run_id=r['id'], name=r['config']['name'], metrics=r['metrics'],
                              included_symbols=len(r['manifest']), excluded_symbols=r['excluded']) for r in reports],
                   notice='One exploratory sample with current-constituent bias. Technical rules only; news and financial assessments excluded. The 10 bps cost assumptions per side and slippage are illustrative. This is not out-of-sample validation.')
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output', default='artifacts/investor_baseline/comparison.json')
    args = parser.parse_args()
    rules = Rules(**store.read('investor/rules', store.read('investor/scan', {}).get('rules', {})))
    shared = dict(start=args.start, end=args.end, capital=1000000, entry_mode='next_open',
                  candidate_rank='alphabetical', max_positions=5, risk_pct=1.5, stop_pct=8,
                  winner_exit='trail_50d', breakeven_r=1, max_hold_days=120,
                  fee_model='custom_bps', buy_cost_bps=10, sell_cost_bps=10, slippage_bps=10,
                  minimum_warmup_sessions=100, acknowledge_limitations=True)
    run_ids = []
    reference = None
    for pattern, name in (('investor_early_breakout', 'Investor early breakout · technical baseline'),
                          ('blue_sky', 'Blue Sky · matched investor baseline')):
        run_id = uuid4().hex[:12]
        cfg = BacktestConfig(**shared, pattern=pattern, name=name, comparison_run_id=reference,
                             investor_rules=rules if not reference else None)
        print(f'{name}: {run_id}', flush=True)
        backtest.run(current_settings(reference), cfg, lambda message: print(message, flush=True), run_id)
        run_ids.append(run_id)
        if not reference:
            reference = run_id
    output = save_comparison(run_ids, args.output)
    print(str(output), flush=True)


if __name__ == '__main__':
    main()
