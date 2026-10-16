"""Print a predeclared historical investor comparison; write no reports or runs."""
import json
import random
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, data_quality, store
from core.research.config import BacktestConfig, Settings


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    baseline = store.read('runs/a1ac1ce102c1')
    settings = Settings(universe=baseline['universe'])
    # Declare periods, experiments and cost stress before observing outcomes.
    periods = [('2021-01-01', '2022-12-31'), ('2023-01-01', '2024-12-31')]
    trials = [
        ('Original alphabetical', {}, {}),
        ('RS126 ranking', {'candidate_rank': 'rs_126'}, {}),
        ('RS126 + actual contraction', {'candidate_rank': 'rs_126'}, {'max_contraction_ratio': 1.0}),
        ('RS126 + opening gap <=3%', {'candidate_rank': 'rs_126', 'max_open_gap_pct': 3}, {}),
        ('RS126 + breadth >=40%', {'candidate_rank': 'rs_126', 'skip_weak_markets': True}, {}),
        ('Blue Sky / RS126', {'pattern': 'blue_sky', 'candidate_rank': 'rs_126'}, None),
        ('RS126 / doubled costs', {'candidate_rank': 'rs_126', 'buy_cost_bps': 20,
                                  'sell_cost_bps': 20, 'slippage_bps': 20}, {}),
    ]
    print('PLAN ' + json.dumps(dict(periods=periods, trials=trials, priority_seeds=[0, 1, 2],
          common_warmup=200, notice='Historical checks on current constituents; other strategies previously used these periods. No point-in-time universe or total-return benchmark.'), ensure_ascii=False), flush=True)
    for start, end in periods:
        cfg = BacktestConfig(**{**baseline['config'], 'start': start, 'end': end,
                              'comparison_run_id': None, 'minimum_warmup_sessions': 200})
        universe, inputs, manifest, excluded = backtest.prepare(settings, cfg)
        # Future candles must not drive anomaly exclusions or simulation state.
        inputs = {s: [b for b in bs if b['date'] <= end] for s, bs in inputs.items()}
        quality = data_quality.audit(inputs, end=cfg.end)
        inputs = data_quality.exclude_anomalies(inputs, quality, lambda msg: print('QUALITY ' + msg, flush=True))
        malformed = [(s, b['date']) for s, bs in inputs.items() for b in bs
                     if start <= b['date'] <= end and not
                     (b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high'])]
        if malformed:
            raise ValueError(f'Invalid OHLC: {malformed[:5]}')
        print('COVERAGE ' + json.dumps(dict(start=start, end=end, stocks=len(inputs),
              exclusions_before_gap_audit=len(excluded), gaps_excluded=quality['excluded_symbols'],
              future_candles_retained=False)), flush=True)
        retained = {id(bs): bs for bs in inputs.values()}
        memo, original = {}, backtest.signal
        def cached(bs, i, config):
            if retained.get(id(bs)) is not bs:
                return original(bs, i, config)
            key = (id(bs), i, config.pattern,
                   config.investor_rules.model_dump_json() if config.investor_rules else '')
            if key not in memo:
                memo[key] = original(bs, i, config)
            return memo[key]
        def evaluate(name, datasets, config):
            r = backtest.simulate(datasets, config, sector_instruments=universe['instruments'])
            pnl = sum(t['pnl'] for t in r['trades'])
            assert abs(pnl - (r['metrics']['final_equity'] - config.capital)) < 0.1
            print('RESULT ' + json.dumps(dict(period=f'{start}/{end}', name=name, metrics=r['metrics']), ensure_ascii=False), flush=True)
        with patch.object(backtest, 'signal', side_effect=cached):
            for name, changes, rules in trials:
                values = {**cfg.model_dump(mode='json'), **changes,
                          'investor_rules': {**cfg.investor_rules.model_dump(), **rules} if rules is not None else None}
                evaluate(name, inputs, BacktestConfig(**values))
            for seed in [0, 1, 2]:
                order = sorted(inputs)
                random.Random(seed).shuffle(order)
                renamed = {f'{i:04d}_{s}': inputs[s] for i, s in enumerate(order)}
                evaluate(f'Fixed random priority seed {seed}', renamed, cfg)


if __name__ == '__main__':
    main()
