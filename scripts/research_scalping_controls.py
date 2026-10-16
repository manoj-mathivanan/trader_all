"""Post-initial-study controls: matched scan cap and score cost sensitivity."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import scalping, store, momentum


def main():
    reference = '8e3ef5c8cd30'
    folder = store.DATA/'scalping_improvement_research'/reference
    summary = store.read('scalping_improvement_research/'+reference+'/summary')
    ref = store.read('runs/'+reference)
    cfg = scalping.ScalpingConfig(**ref['config'])
    daily = store.read('run_data/'+reference)
    if any(scalping.digest(daily.get(m['symbol'])) != m['sha256'] for m in ref['manifest']):
        raise ValueError('Daily hashes changed.')
    declarations = [
        ('turnover_top5_control', dict(liquid_universe_size=5)),
        ('score_zero_cost_diagnostic', dict(stock_selection='score', min_stock_score=60, liquid_universe_size=5,
                                          slippage_bps=0, buy_cost_bps=0, sell_cost_bps=0)),
        ('score_vwap_wider_stops_lower_cost', dict(stock_selection='score', min_stock_score=60, liquid_universe_size=5,
                                                 entry_filter='ema_vwap', min_stop_pct=0.4, max_stop_pct=1.0,
                                                 slippage_bps=2, buy_cost_bps=2, sell_cost_bps=2)),
        ('score_vwap_wider_stops_zero_cost', dict(stock_selection='score', min_stock_score=60, liquid_universe_size=5,
                                                entry_filter='ema_vwap', min_stop_pct=0.4, max_stop_pct=1.0,
                                                slippage_bps=0, buy_cost_bps=0, sell_cost_bps=0)),
    ]
    summary['followup_declarations'] = declarations
    summary['followup_notice'] = 'Follow-up controls declared after the initial ten results; exploratory, no untouched validation.'

    def save():
        with (folder/'summary.json').open('w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, allow_nan=False)

    save()
    baseline = scalping.frozen_sessions(cfg.model_copy(update={'comparison_run_id': reference}), ref)
    scored = store.read('scalping_improvement_research/'+reference+'/score_inputs')
    if scalping.digest(scored) != summary['score_input_sha256']:
        raise ValueError('Scored minute hashes changed.')
    plan = store.read('scalping_improvement_research/'+reference+'/score_selection')
    for name, updates in declarations:
        trial = scalping.ScalpingConfig(**{**cfg.model_dump(), **updates})
        score = name.startswith('score')
        selected = plan if score else {d: cs[:5] for d, cs in ref['selection_plan'].items()}
        print('Simulating', name, flush=True)
        report = scalping.simulate(daily, trial, scored if score else baseline, selected)
        evaluation = momentum.chronological_evaluation(report)
        summary['runs'].append(dict(name=name, config=trial.model_dump(mode='json'), metrics=report['metrics'],
                                    diagnostics=report['diagnostics'], evaluation=evaluation, followup=True))
        for t in report['trades']:
            t.pop('stop_trace', None)
        report.update(config=trial.model_dump(mode='json'), evaluation=evaluation)
        with (folder/(name+'.json')).open('w', encoding='utf-8') as f:
            json.dump(report, f, allow_nan=False)
        print(name, round(report['metrics']['return_pct'],4), report['metrics']['trade_count'], flush=True)
        save()


if __name__ == '__main__':
    main()
