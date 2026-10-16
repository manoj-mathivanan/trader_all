"""Perturb only simultaneous-signal priority; retain prices, rules and costs."""
import json
import random
import statistics
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, store
from core.research.config import BacktestConfig


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    report = store.read('runs/a1ac1ce102c1')
    inputs = store.read('run_data/a1ac1ce102c1')
    cfg = BacktestConfig(**report['config'])
    retained = {id(bs): bs for bs in inputs.values()}
    memo, original = {}, backtest.signal
    def cached(bs, i, config):
        if retained.get(id(bs)) is not bs:
            return original(bs, i, config)
        key = (id(bs), i)
        if key not in memo:
            memo[key] = original(bs, i, config)
        return memo[key]
    trials = []
    output = Path('artifacts/investor_baseline/deep_analysis/priority.json')
    with patch.object(backtest, 'signal', side_effect=cached):
        for seed in range(10):
            order = sorted(inputs)
            random.Random(seed).shuffle(order)
            # Rename keys to impose one fixed stock priority for the whole window.
            # The daily signal sees the identical retained price list for each stock.
            renamed = {f'{i:04d}_{symbol}': inputs[symbol] for i, symbol in enumerate(order)}
            result = backtest.simulate(renamed, cfg)
            row = dict(seed=seed, metrics=result['metrics'])
            trials.append(row)
            output.write_text(json.dumps(dict(trials=trials), indent=2), encoding='utf-8')
            print(f"Priority seed {seed}: {result['metrics']['return_pct']:.2f}% / DD {result['metrics']['max_drawdown_pct']:.2f}%", flush=True)
    returns = [t['metrics']['return_pct'] for t in trials]
    summary = dict(trials=trials, minimum=min(returns), maximum=max(returns), mean=statistics.mean(returns),
                   median=statistics.median(returns), positive_runs=sum(r > 0 for r in returns),
                   notice='Ten predeclared fixed priority permutations on the already inspected sample. This tests sensitivity to tie-breaking, not an alternative deployable strategy, confidence interval, or out-of-sample validation.')
    output.write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
