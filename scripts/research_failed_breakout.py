"""Four predeclared failure-reversal trials on the baseline's frozen liquid-stock pool."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import failed_breakout as strategy, scalping, store, momentum, provenance

TRIALS = [('range15_original_costs', {}),
          ('range15_lower_cost_sensitivity', dict(slippage_bps=2,buy_cost_bps=2,sell_cost_bps=2)),
          ('range15_zero_cost_diagnostic', dict(slippage_bps=0,buy_cost_bps=0,sell_cost_bps=0)),
          ('range30_original_costs', dict(opening_minutes=30,first_entry_time='09:45'))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='8e3ef5c8cd30')
    args=parser.parse_args()
    root='failed_breakout_research/'+args.reference
    if store.read(root+'/summary'):
        raise ValueError('Research output already exists; preserve it and choose another reference or archive explicitly.')
    ref=store.read('runs/'+args.reference)
    cfg=strategy.FailedBreakoutConfig(start=ref['config']['start'],end=ref['config']['end'],acknowledge_limitations=True)
    summary=dict(reference=args.reference,created_at=store.now(),status='running',declarations=TRIALS,
                 baseline_config=cfg.model_dump(mode='json'),provenance=provenance.capture(),runs=[],failures=[],
                 notice='Research only. All dates already inspected; no untouched validation. Prior turnover top 20 pool, '
                        'then top 3 by completed opening activity. Relative volume uses the frozen 3 prior opening sessions, '
                        'not 20 days. One trade per stock/day. Midpoint target; original fees/slippage or separately labeled sensitivities.')
    store.write(root+'/summary',summary)
    print('Verifying frozen daily and one-minute inputs.',flush=True)
    try:
        daily=store.read('run_data/'+args.reference)
        if any(scalping.digest(daily.get(m['symbol']))!=m['sha256'] for m in ref['manifest']):
            raise ValueError('Daily hashes changed.')
        sessions=scalping.frozen_sessions(scalping.ScalpingConfig(**{**ref['config'],'comparison_run_id':args.reference}),ref)
        summary['input_sha256']=ref['intraday_source']['sha256']
        for name,changes in TRIALS:
            print('Selecting and simulating',name,flush=True)
            trial=strategy.FailedBreakoutConfig(**{**cfg.model_dump(),**changes})
            try:
                plan=strategy.select(ref['selection_plan'],sessions,trial)
                report=strategy.simulate(daily,trial,sessions,plan)
                report['evaluation']=momentum.chronological_evaluation(report)
                report['reference']=args.reference
                for t in report['trades']: t.pop('stop_trace',None)
                store.write(root+'/'+name,report)
                summary['runs'].append(dict(name=name,config=trial.model_dump(mode='json'),metrics=report['metrics'],
                    diagnostics=report['diagnostics'],evaluation=report['evaluation'],
                    selected_stock_sessions=sum(map(len,plan.values())),empty_sessions=sum(not cs for cs in plan.values()),
                    traded_symbols=len({t['symbol'] for t in report['trades']})))
                print(name,round(report['metrics']['return_pct'],4),report['metrics']['trade_count'],flush=True)
            except Exception as exc:
                summary['failures'].append(dict(name=name,error=str(exc)))
                print('FAILED',name,str(exc),flush=True)
            store.write(root+'/summary',summary)
    except Exception as exc:
        summary['failures'].append(dict(stage='input verification',error=str(exc)))
    summary.update(status='completed_with_failures' if summary['failures'] else 'completed',completed_at=store.now())
    store.write(root+'/summary',summary)
    print('Saved',store.DATA/(root+'/summary.json'),flush=True)


if __name__=='__main__': main()
