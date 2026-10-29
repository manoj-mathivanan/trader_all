"""One fixed, causal support/resistance context ablation; research artifacts only."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import candle_level_context as strategy, candle_continuation, candle_rejection, intraday_data, store
from scripts import research_candle_rejection as first, research_candle_continuation as second
from scripts.research_candle_passive import verify_control


SPEC=dict(version=1,research=first.SPEC['research'],validation=first.SPEC['validation'],prospective=first.SPEC['prospective'],
    hypothesis='Known levels plus independently observed intraday structure may distinguish meaningful candle patterns from geometry alone.',
    prior_knowledge='Earlier 2025 outcomes and diagnostics were inspected. This is an exploratory fixed specification, not a faithful reproduction or independent proof of the videos.',
    levels='Prior-day high/low known at session open; opening-range high/low known at 09:30; same-day 15m pivots with two completed bars on both sides. A pivot exists only after its second right-side bar closes. Do not use future session candles to make levels available sooner.',
    availability='All levels must be known at the START of the rejection candle, or at the START of the impulse for weak pullbacks. Opening range cannot validate its own 09:25-09:30 candle.',
    invalidation='A support permanently expires for the day after a completed 15m close below it by more than 0.05 prior daily ATR; resistance symmetrically above. No retrospective role flips. A level must remain active at signal start.',
    touch='Signal candle for rejection; impulse/pullback candles before resumption for continuation. Candle range must overlap level +/-0.05 prior daily ATR. Signal close and next open must be on the reclaimed side. Choose nearest touched level to signal close; source-name tie-break.',
    trend='At pattern start, last two completed 15m candles must have strictly higher highs AND lows for longs, or lower highs AND lows for shorts. No trend from the current unfinished candle or the pattern outcome itself.',
    room='For context variants, nearest active opposing level ahead of the unslipped next open must be at least 2x structural risk from that open. If no active opposing level is known, permit but record unknown room. Stops/targets are not moved to fit levels.',
    variants=list(strategy.VARIANTS),baselines=strategy.BASELINES,
    descriptions=dict(geometry_control='Every qualifying wick/close-location rejection candle, no level gate.',
                      known_level='Same geometry plus causal known-level touch/reclaim.',
                      level_context='Known-level rejection plus prior trend and opposing-level room.',
                      weak_control='Exact original strong impulse / weak pullback / resumption.',
                      weak_context='Original weak pullback plus the same known-level/trend/room requirements.'),
    directions=['long','short'],slippage_bps=[2,5,10],window='Original 09:30-14:00 entry window only; 30 total research runs, no threshold sweep or morning selection.',
    unchanged='Original audited frozen 2025 inputs, stock selection, fees, market fills, sizing, 2R targets, structural stop buffer, holding cap, collateral and trade limits.',
    context_scope='Same-day context only; missing warmup makes trend unavailable and excludes a signal. Prior-day high/low use already verified daily price units. No extra candle downloads.',
    candidate_gate={**first.SPEC['candidate_gate'],
                    'additional':'Candidate known_level, level_context or weak_context must beat its declared same-direction 5bps baseline in net return. Select highest 5bps net return among all passing candidates before evaluating validation. No retuning.'},
    validation_gate=first.SPEC['validation_gate'],
    limitations=first.SPEC['limitations']+[
        'The speaker does not provide these exact level, pivot, trend or room definitions; all remain explicit numerical adaptations.',
        'Context ablations alter trade timing and sample size; lower total loss alone is not proof of improved edge.',
        'No known opposing level is not proof that resistance/support is absent.',
        'Trend requires sufficient same-day completed bars, so context signals generally start later.'],
)


def verify(result):
    trades=result['trades']
    if abs(result['metrics']['final_equity']-result['metrics']['initial_capital']-sum(t['pnl'] for t in trades))>1e-6:
        raise ValueError('Context ledger does not reconcile.')
    for t in trades:
        if not t['entry_timestamp']>=t['signal_timestamp']+300000 or t['exit_timestamp']<t['entry_timestamp'] or t['exit_time']>'15:00':
            raise ValueError('Context timing/exit invariant failed.')
        if 'context_level_known_index' in t and t['context_level_known_index']>t['context_anchor_index']:
            raise ValueError('Future level used before its availability.')
    if result['order_ledger']:
        raise ValueError('Unexpected limit order in market-only context study.')


def render_report(output,summary):
    lines=['KNOWN-LEVEL AND TREND CONTEXT STUDY — 29 OCTOBER 2026 (IST)','',summary['decision'],
           '', '30 prespecified research runs: five rules x two directions x three cost assumptions.',
           'Frozen audited 2025 inputs only; each standalone portfolio starts at Rs 1,000,000.',
           '', 'NET RESULTS AT 5 BPS PER SIDE PLUS FULL DATED FEES',
           'Rule / Direction / Return / Trades / Profit factor / Observed-close drawdown']
    for row in summary['runs']:
        if row['slippage_bps']==5:
            pf=f"{row['profit_factor']:.3f}" if row['profit_factor'] is not None else 'undefined'
            lines.append(f"{row['variant']} / {row['direction']} / {row['return_pct']:+.3f}% / {row['trade_count']} / {pf} / {row['max_observed_close_drawdown_pct']:.3f}%")
    lines+=['', 'MATCHED BASELINE DIFFERENCES AT 5 BPS']
    for row in summary.get('comparisons',[]):
        lines.append(f"{row['variant']} {row['direction']} vs {row['baseline']}: {row['return_difference_pct_points']:+.3f} percentage points; candidate gate {'PASS' if row['passed'] else 'FAIL'}")
    lines+=['', 'Validation status: '+summary['validation_status'],'', 'RULES',SPEC['levels'],SPEC['availability'],SPEC['invalidation'],SPEC['trend'],SPEC['room'],
            '', 'LIMITATIONS',*SPEC['limitations'],
            '', 'All ledgers passed accounting, entry availability, same-day exit and level-birth checks. Original weak-pullback controls reproduced before interpretation.']
    if 'validation_runs' in summary:
        lines+=['','VALIDATION RESULTS']
        for row in summary['validation_runs']:
            lines.append(f"{row['variant']} {row['direction']} {row['slippage_bps']}bps: {row['return_pct']:+.3f}% / {row['trade_count']} trades")
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=store.ROOT/'artifacts'/'candle_context_20261029')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    spec_path=output/'specification.json'
    if spec_path.exists() and json.loads(spec_path.read_text())['spec']!=SPEC:
        raise ValueError('Context specification changed; use a new output.')
    if not spec_path.exists():
        first.save(spec_path,dict(declared_at=datetime.now(intraday_data.IST).isoformat(),spec=SPEC,spec_sha256=first.digest(SPEC)))
    paths=[Path(__file__),Path(strategy.__file__),Path(candle_continuation.__file__),Path(candle_rejection.__file__),Path(first.__file__),
           Path(second.__file__),store.ROOT/'scripts/research_candle_passive.py',store.ROOT/'core/research/intraday_costs.py']
    code={str(p.relative_to(store.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest=output/'code_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text())!=code:
        raise ValueError('Frozen context code changed; preserve output and use a new directory.')
    first.save(manifest,code)
    print('Context specification frozen before new outcomes.',flush=True)
    inputs,audit=first.load_inputs(store.ROOT/'artifacts'/'candle_rejection_20261029','research',SPEC['research'])
    print('Building causal level/context snapshots...',flush=True)
    states=strategy.build_states(inputs)
    summary=dict(spec_sha256=first.digest(SPEC),input_sha256=audit['input_sha256'],runs=[],candidate_checks={},comparisons=[],
                 validation_status='not evaluated; pending research gates',limitations=SPEC['limitations'])
    results={}
    for variant in SPEC['variants']:
        for direction in SPEC['directions']:
            sign=1 if direction=='long' else -1
            for slip in SPEC['slippage_bps']:
                key=f'{variant}_{direction}_{slip}bps'
                result=strategy.simulate(inputs,variant,sign,slip,states)
                verify(result)
                if variant=='weak_control':
                    original=json.loads((store.ROOT/'artifacts/candle_continuation_20261029'/f'full_weak_pullback_{direction}_{slip}bps.json').read_text())
                    verify_control(original,result)
                sources=Counter(t.get('context_level_name','ungated').split('_')[0] for t in result['trades'])
                first.save(output/(key+'.json'),result)
                results[key]=result
                summary['runs'].append(dict(key=key,variant=variant,direction=direction,slippage_bps=slip,**result['metrics'],
                                            context_sources=dict(sources),no_opposing_level_trades=sum(t.get('context_trend',False) and t.get('opposing_room_r') is None for t in result['trades'])))
                first.save(output/'summary.json',summary)
                print(f"{key}: {result['metrics']['return_pct']:+.3f}% / {result['metrics']['trade_count']} trades",flush=True)
    candidates=[]
    for variant,baseline in strategy.BASELINES.items():
        for direction in SPEC['directions']:
            key=f'{variant}_{direction}_5bps'
            result=results[key]
            control=results[f'{baseline}_{direction}_5bps']
            gate=first.eligible(result,results[f'{variant}_{direction}_10bps'])
            gate['checks']['beats_baseline_return']=result['metrics']['return_pct']>control['metrics']['return_pct']
            gate['passed']=all(gate['checks'].values())
            summary['candidate_checks'][key]=gate
            summary['comparisons'].append(dict(variant=variant,direction=direction,baseline=baseline,
                return_difference_pct_points=result['metrics']['return_pct']-control['metrics']['return_pct'],passed=gate['passed']))
            if gate['passed']:
                candidates.append((result['metrics']['return_pct'],variant,direction))
    if not candidates:
        summary.update(validation_status='not opened: no context candidate passed the prespecified research gates',
                       decision='No context candidate advances to validation, paper trading or live trading.')
    else:
        _,variant,direction=max(candidates)
        summary['selected_candidate']=dict(variant=variant,direction=direction)
        summary['validation_status']='candidate choice frozen before opening validation'
        first.save(output/'summary.json',summary)
        data,vaudit=first.load_inputs(output,'validation',SPEC['validation'])
        summary['validation_input_sha256']=vaudit['input_sha256']
        validation_states=strategy.build_states(data)
        summary['validation_runs']=[]
        chosen=[]
        for trial in (strategy.BASELINES[variant],variant):
            for slip in (5,10):
                result=strategy.simulate(data,trial,1 if direction=='long' else -1,slip,validation_states)
                verify(result)
                first.save(output/f'validation_{trial}_{direction}_{slip}bps.json',result)
                summary['validation_runs'].append(dict(variant=trial,direction=direction,slippage_bps=slip,**result['metrics']))
                if trial==variant:
                    chosen.append(result['metrics'])
        passed=all(r['return_pct']>0 and r['max_observed_close_drawdown_pct']<=15 for r in chosen) and (chosen[0]['profit_factor'] or 0)>1
        summary.update(validation_status='passed' if passed else 'failed',
                       decision='Context candidate qualifies for a separate forward paper implementation; no trading enabled.' if passed else 'Context candidate failed validation; no trading enabled.')
    first.save(output/'summary.json',summary)
    render_report(output,summary)
    print(summary['decision'],flush=True)
    print('Saved: '+str(output),flush=True)


if __name__=='__main__':
    main()
