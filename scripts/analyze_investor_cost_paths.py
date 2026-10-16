"""Investigate why small costs can change a capacity-limited trade path."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, store
from core.research.config import BacktestConfig


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    baseline = store.read('runs/a1ac1ce102c1')
    datasets = store.read('run_data/a1ac1ce102c1')
    retained = {id(bs): bs for bs in datasets.values()}
    memo, original = {}, backtest.signal
    def cached(bars, i, cfg):
        if retained.get(id(bars)) is not bars:
            return original(bars, i, cfg)
        key = (id(bars), i)
        if key not in memo:
            memo[key] = original(bars, i, cfg)
        return memo[key]
    outcomes = []
    output = Path('artifacts/investor_baseline/deep_analysis/cost_paths.json')
    with patch.object(backtest, 'signal', side_effect=cached):
        for name, fee, slip in [('Zero costs', 0, 0), ('Fees only', 10, 0), ('Slippage only', 0, 10), ('Half costs', 5, 5)]:
            cfg = BacktestConfig(**{**baseline['config'], 'buy_cost_bps': fee, 'sell_cost_bps': fee, 'slippage_bps': slip})
            result = backtest.simulate(datasets, cfg)
            row = dict(name=name, fee_bps_per_side=fee, slippage_bps_per_side=slip, metrics=result['metrics'], trades=result['trades'])
            outcomes.append(row)
            output.write_text(json.dumps(dict(outcomes=outcomes), indent=2), encoding='utf-8')
            print(f"{name}: {result['metrics']['return_pct']:.2f}% / {len(result['trades'])} trades", flush=True)
    baseline_keys = {(t['symbol'], t['entry_date']): t for t in baseline['trades']}
    zero_keys = {(t['symbol'], t['entry_date']): t for t in outcomes[0]['trades']}
    common = set(baseline_keys) & set(zero_keys)
    changed = [dict(symbol=k[0], entry_date=k[1], baseline=baseline_keys[k], zero_cost=zero_keys[k]) for k in common
               if baseline_keys[k]['exit_date'] != zero_keys[k]['exit_date'] or baseline_keys[k]['reason'] != zero_keys[k]['reason']]
    changed.sort(key=lambda r: min(r['baseline']['exit_date'], r['zero_cost']['exit_date']))
    detail = dict(common_entries=len(common), baseline_only_entries=[baseline_keys[k] for k in sorted(set(baseline_keys) - common)],
                  zero_only_entries=[zero_keys[k] for k in sorted(set(zero_keys) - common)], changed_exit_paths=changed)
    output.write_text(json.dumps(dict(outcomes=outcomes, path_comparison=detail), indent=2), encoding='utf-8')
    print('Shared entries:', len(common), 'changed exits:', len(changed), flush=True)
    print('First altered exit:', json.dumps(changed[:1]), flush=True)


if __name__ == '__main__':
    main()
