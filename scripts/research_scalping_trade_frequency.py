"""Exploratory fewer-entry/smaller-target trials on verified frozen score inputs."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import scalping, store, momentum

TRIALS = [
    ('fewer_entries', dict(last_entry_time='11:00', max_trades_per_symbol=1)),
    ('target_1R_10min', dict(last_entry_time='11:00', max_trades_per_symbol=1, target_r=1, max_holding_minutes=10)),
    ('target_075R_10min', dict(last_entry_time='11:00', max_trades_per_symbol=1, target_r=0.75, max_holding_minutes=10)),
    ('target_05R_5min', dict(last_entry_time='11:00', max_trades_per_symbol=1, target_r=0.5, max_holding_minutes=5)),
    ('target_1R_larger_distance', dict(last_entry_time='11:00', max_trades_per_symbol=1, target_r=1,
                                    max_holding_minutes=10, min_stop_pct=0.6)),
    ('strict_score_85_top3', dict(last_entry_time='11:00', max_trades_per_symbol=1, target_r=1,
                                max_holding_minutes=10, min_stock_score=85, liquid_universe_size=3, max_positions=1)),
    ('target_1R_lower_cost_sensitivity', dict(last_entry_time='11:00', max_trades_per_symbol=1, target_r=1,
                                           max_holding_minutes=10, slippage_bps=2, buy_cost_bps=2, sell_cost_bps=2)),
]


def main():
    key = 'scalping_improvement_research/8e3ef5c8cd30'
    source = store.read(key+'/summary')
    base = store.read(key+'/score_vwap_wider_stops')
    ref = store.read('runs/8e3ef5c8cd30')
    daily = store.read('run_data/8e3ef5c8cd30')
    if any(scalping.digest(daily.get(m['symbol'])) != m['sha256'] for m in ref['manifest']):
        raise ValueError('Daily input hashes changed.')
    summary = dict(created_at=store.now(), status='running', declarations=TRIALS, reference='8e3ef5c8cd30',
                   comparison=dict(name='Scored/VWAP/wider-stop reference', metrics=base['metrics']), runs=[], failures=[],
                   notice='Follow-up exploratory tests on already inspected dates. Target R is relative to stop distance, not capital. '
                          'Lower costs are hypothetical sensitivity assumptions, not verified broker execution.')
    store.write(key+'/frequency_summary', summary)
    print('Loading and verifying frozen score minutes.', flush=True)
    sessions = store.read(key+'/score_inputs')
    if scalping.digest(sessions) != source['score_input_sha256']:
        raise ValueError('Minute hashes changed.')
    selected = store.read(key+'/score_selection')
    for name, changes in TRIALS:
        cfg = scalping.ScalpingConfig(**{**base['config'], **changes})
        # Restriction of the exact prior-ranked plan preserves ranking and never needs unseen candles.
        plan = {d: [c for c in cs if c['stock_score']['total'] >= cfg.min_stock_score][:cfg.liquid_universe_size]
                for d, cs in selected.items()}
        print('Simulating', name, flush=True)
        try:
            result = scalping.simulate(daily, cfg, sessions, plan)
            evaluation = momentum.chronological_evaluation(result)
            row = dict(name=name, config=cfg.model_dump(mode='json'), metrics=result['metrics'],
                       diagnostics=result['diagnostics'], evaluation=evaluation)
            summary['runs'].append(row)
            for t in result['trades']:
                t.pop('stop_trace', None)
            result.update(config=row['config'], evaluation=evaluation)
            store.write(key+'/frequency_'+name, result)
            print(name, round(result['metrics']['return_pct'],4), result['metrics']['trade_count'], flush=True)
        except Exception as exc:
            summary['failures'].append(dict(name=name, error=str(exc)))
            print('FAILED', name, str(exc), flush=True)
        store.write(key+'/frequency_summary', summary)
    summary.update(status='completed_with_failures' if summary['failures'] else 'completed', completed_at=store.now())
    store.write(key+'/frequency_summary', summary)


if __name__ == '__main__':
    main()
