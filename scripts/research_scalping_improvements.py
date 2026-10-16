"""Declared matched scalping trials; persist inputs, failures, and all results."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import scalping, store, intraday_data, momentum


TRIALS = [
    ('baseline', {}),
    ('baseline_zero_cost_diagnostic', dict(slippage_bps=0, buy_cost_bps=0, sell_cost_bps=0)),
    ('baseline_lower_cost_sensitivity', dict(slippage_bps=2, buy_cost_bps=2, sell_cost_bps=2)),
    ('score_top5_min60', dict(stock_selection='score', min_stock_score=60, liquid_universe_size=5)),
    ('score_vwap', dict(entry_filter='ema_vwap')),
    ('score_wider_stops', dict(min_stop_pct=0.4, max_stop_pct=1.0)),
    ('score_longer_hold', dict(max_holding_minutes=30)),
    ('score_morning', dict(last_entry_time='11:00')),
    ('score_one_trade', dict(max_trades_per_symbol=1)),
    ('score_vwap_wider_stops', dict(entry_filter='ema_vwap', min_stop_pct=0.4, max_stop_pct=1.0)),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8e3ef5c8cd30')
    args = parser.parse_args()
    ref = store.read('runs/'+args.reference)
    cfg = scalping.ScalpingConfig(**ref['config'])
    daily = store.read('run_data/'+args.reference)
    if not daily or any(scalping.digest(daily.get(m['symbol'])) != m['sha256'] for m in ref['manifest']):
        raise ValueError('Reference daily input hashes changed.')
    score_cfg = scalping.ScalpingConfig(**{**cfg.model_dump(), **TRIALS[3][1]})
    output = store.DATA/'scalping_improvement_research'/args.reference
    output.mkdir(parents=True, exist_ok=True)
    summary = dict(reference=args.reference, created_at=store.now(), status='running',
                   definitions=TRIALS, baseline_config=ref['config'], runs=[], failures=[],
                   notice='All dates were already inspected. Earlier/later diagnostics are not untouched validation. '
                          'Score ranks the full frozen eligible universe, not just the old top 20. '
                          'Score weights and thresholds are exploratory. Lower costs are sensitivity assumptions, not verified execution.')

    def checkpoint():
        with (output/'summary.json').open('w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, allow_nan=False)

    checkpoint()
    print('Preparing full-universe prior-daily score selection.', flush=True)
    score_plan, requests = scalping.entry_plan(daily, score_cfg)
    summary['score_selection'] = dict(sessions=len(score_plan), selected_stock_sessions=sum(map(len, score_plan.values())),
                                    symbols=len({c['symbol'] for cs in score_plan.values() for c in cs}),
                                    empty_sessions=sum(not cs for cs in score_plan.values()))
    with (output/'score_selection.json').open('w', encoding='utf-8') as f:
        json.dump(score_plan, f, allow_nan=False)
    checkpoint()
    try:
        score_sessions = intraday_data.load_ranges(requests, ref['universe_snapshot'],
                                                   lambda msg: print(msg, flush=True), 1)
        summary['score_input_sha256'] = scalping.digest(score_sessions)
        with (output/'score_inputs.json').open('w', encoding='utf-8') as f:
            json.dump(score_sessions, f, allow_nan=False)
    except Exception as exc:
        summary['failures'].append(dict(stage='score inputs', error=str(exc)))
        summary['status'] = 'failed'
        checkpoint()
        raise
    checkpoint()
    print('Loading verified baseline frozen minutes.', flush=True)
    baseline_sessions = scalping.frozen_sessions(cfg.model_copy(update={'comparison_run_id': args.reference}), ref)
    for name, updates in TRIALS:
        print('Simulating', name, flush=True)
        is_score = name.startswith('score')
        trial = scalping.ScalpingConfig(**{**(score_cfg if is_score else cfg).model_dump(), **updates})
        try:
            report = scalping.simulate(daily, trial, score_sessions if is_score else baseline_sessions,
                                      score_plan if is_score else ref['selection_plan'])
            evaluation = momentum.chronological_evaluation(report)
            if name == 'baseline':
                for key in ('trade_count', 'final_equity', 'modeled_fees', 'modeled_slippage'):
                    if abs(report['metrics'][key]-ref['metrics'][key]) > 1e-5:
                        raise ValueError('Baseline reproduction mismatch: '+key)
            record = dict(name=name, config=trial.model_dump(mode='json'), metrics=report['metrics'],
                          diagnostics=report['diagnostics'], evaluation=evaluation)
            summary['runs'].append(record)
            for trade in report['trades']:
                trade.pop('stop_trace', None)
            report.update(config=record['config'], evaluation=evaluation)
            with (output/(name+'.json')).open('w', encoding='utf-8') as f:
                json.dump(report, f, allow_nan=False)
            print(name, 'return', round(report['metrics']['return_pct'], 4), 'trades', report['metrics']['trade_count'], flush=True)
        except Exception as exc:
            summary['failures'].append(dict(name=name, error=str(exc)))
            print(name, 'FAILED', str(exc), flush=True)
        checkpoint()
    summary['status'] = 'completed_with_failures' if summary['failures'] else 'completed'
    summary['completed_at'] = store.now()
    checkpoint()
    print('Saved', output/'summary.json', flush=True)


if __name__ == '__main__':
    main()
