"""Independent per-stock accounts to separate signal quality from shared slots.

R distributions are diagnostic. They are not a deployable portfolio or return.
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import backtest, corporate_actions, investor_breakouts, store
from core.research.config import BacktestConfig


def summarize(trades):
    wins = [t for t in trades if t['pnl'] > 1e-6]
    losses = [t for t in trades if t['pnl'] < -1e-6]
    return dict(trades=len(trades), wins=len(wins), losses=len(losses), flats=len(trades) - len(wins) - len(losses),
                mean_r=statistics.mean(t['r'] for t in trades) if trades else None,
                median_r=statistics.median(t['r'] for t in trades) if trades else None,
                mean_win_r=statistics.mean(t['r'] for t in wins) if wins else None,
                mean_loss_r=statistics.mean(t['r'] for t in losses) if losses else None)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    inputs = store.read('run_data/a1ac1ce102c1')
    report = store.read('runs/a1ac1ce102c1')
    result = dict(notice='Each stock has an independent ₹10 lakh hypothetical account, with one position at a time. Averaged trade R removes shared cash/slot allocation; it is not a portfolio return. Repeated entries are correlated and delisted/historical membership limitations remain.', strategies={})
    for pattern in ('investor_early_breakout', 'blue_sky'):
        values = {**report['config'], 'pattern': pattern, 'max_positions': 1}
        if pattern == 'blue_sky':
            values['investor_rules'] = None
        cfg = BacktestConfig(**values)
        rows, errors = [], []
        for count, (symbol, bars) in enumerate(sorted(inputs.items()), 1):
            try:
                simulation = backtest.simulate({symbol: bars}, cfg)
            except ValueError as error:
                errors.append(dict(symbol=symbol, reason=str(error)))
                continue
            for trade in simulation['trades']:
                row = dict(trade)
                if cfg.investor_rules:
                    idx = next(i for i, b in enumerate(bars) if b['date'] == trade['entry_date']) - 1
                    signal_bars = corporate_actions.adjusted_bars(bars, bars[idx]['date'])
                    value = investor_breakouts.setup(signal_bars[:idx + 1], cfg.investor_rules)
                    assert value and value['stage'] == 'early_breakout'
                    row.update(volume_ratio=value['volume_ratio'], contraction_ratio=value['contraction_ratio'],
                               extension_sma50_pct=(value['close'] / value['ma50'] - 1) * 100)
                rows.append(row)
            if count % 100 == 0:
                print(f'{pattern}: {count}/{len(inputs)} stocks, {len(rows)} independent trades', flush=True)
        cohorts = {}
        if pattern == 'investor_early_breakout':
            for name, predicate in (
                    ('range contracting (<1)', lambda r: r['contraction_ratio'] < 1),
                    ('range not contracting (>=1)', lambda r: r['contraction_ratio'] >= 1),
                    ('volume <1.5', lambda r: r['volume_ratio'] < 1.5),
                    ('volume >=1.5', lambda r: r['volume_ratio'] >= 1.5),
                    ('SMA50 extension <=20%', lambda r: r['extension_sma50_pct'] <= 20),
                    ('SMA50 extension >20%', lambda r: r['extension_sma50_pct'] > 20)):
                cohorts[name] = summarize([r for r in rows if predicate(r)])
        result['strategies'][pattern] = dict(summary=summarize(rows), cohorts=cohorts, excluded_errors=errors, trades=rows)
        Path('artifacts/investor_baseline/deep_analysis/independent_signals.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(pattern, json.dumps(result['strategies'][pattern]['summary']), flush=True)


if __name__ == '__main__':
    main()
