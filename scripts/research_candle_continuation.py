"""Frozen continuation/retest comparisons on the existing audited equity snapshot."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import candle_continuation as engine
from core.research.candle_rejection import Rules
from core.research import candle_rejection, intraday_data, store
from scripts import research_candle_rejection as parent


SPEC = dict(
    version=1, sources=['Eb3tyXLZEeA', 'EMsbckJq3gE'],
    interpretation='Numerical adaptations of supplied Tamil transcripts; chart drawings and discretionary level judgments not reconstructed.',
    prior_outcome_knowledge='2025 rejection study losses were already inspected; these are newly declared hypotheses, not independent validation of the videos.',
    inputs='Reuse exact checksum-verified 2025 audited snapshot from the rejection study; same stock selection, exclusions and prior daily ATR.',
    research=parent.SPEC['research'], validation=parent.SPEC['validation'], prospective=parent.SPEC['prospective'],
    variants=list(engine.VARIANTS), baselines=engine.BASELINES, directions=['long','short'], slippage_bps=[2,5,10],
    windows=dict(full=dict(first_entry='09:30',last_entry='14:00'), morning=dict(first_entry='09:30',last_entry='10:15')),
    strong_impulse='Directional body >=70% of candle range and >=0.1 preceding daily ATR; only completed candles from 09:25 onward.',
    impulse_control='Enter next open after a strong impulse.',
    weak_pullback='After strong impulse, require 1 or 2 opposite-colour/doji candles. Each body <=1/3 impulse body and no wick retraces beyond impulse body midpoint. Then a directional body >=50% of its own range closes beyond both impulse close and all pullback highs/lows; resumption may not breach impulse midpoint. Enter next open. Otherwise expire.',
    common_stop='Impulse extreme plus 0.05 prior daily ATR buffer in both a setup and its family baseline; stop always active.',
    gap_definition='Next intraday candle opens in impulse direction by >=max(0.02 prior daily ATR,0.05% previous close). No overnight-gap trades. Decision uses this open only.',
    gap_market_control='Enter at the detected gap open with adverse market slippage.',
    gap_retest='At gap open, submit limit at previous candle close. Conservative one-bar activation delay; eligible on the next 3 bars only, within entry window. Quantity and collateral fixed/reserved at submission. No favorable price improvement even at opening gap-through fills; never assume cancellation before such a fill.',
    limit_execution='Intrabar fill requires penetration beyond limit by the scenario bps; an opening crossing also fills. Fill price is the limit, never worse. Exit slippage applies. Intrabar entry-bar targets are not credited because their ordering is unknown; protective stops still execute, stop first. At-open fills can take subsequent same-bar targets.',
    rules=asdict(Rules()),
    execution='Same fees, risk sizing, 2R targets, 60-minute holding cap, 15:00 exit, five reserved/active slots, two fills per stock/day, no leverage or reuse of filled daily collateral as parent study.',
    ordering='Prior-turnover rank at submission; pending orders reserve cash and slots. Entries precede intrabar exits. Expired unfilled reservations release capital.',
    candidate_gate={**parent.SPEC['candidate_gate'], 'beats_same_direction_baseline_return': True,
                    'selection':'Apply original absolute gates plus higher 5bps return than own baseline, on each same entry window. Select highest 5bps return across passing setup/direction/window candidates; no parameter tuning.'},
    validation_gate=parent.SPEC['validation_gate'],
    limitations=parent.SPEC['limitations']+[
        'Both full and morning windows are prespecified comparisons; selection across eight candidates increases research selection bias.',
        'Gap/retest execution differs from the discretionary video: one-bar order delay and strict penetration are deliberate conservative assumptions.',
        'Five-minute equity candles cannot validate one-minute scalping, options premiums, IV, OI/PCR or ITM contract selection.',
        'The speaker gives incomplete/inconsistent numerical pullback examples; one-third body and 50% retracement are declared adaptations.'],
)


def rules_for(window):
    return replace(Rules(), **SPEC['windows'][window])


def verify(result):
    m, trades = result['metrics'], result['trades']
    if abs(m['final_equity']-m['initial_capital']-sum(t['pnl'] for t in trades)) > 1e-6:
        raise ValueError('Ledger does not reconcile.')
    for t in trades:
        if not (t['entry_timestamp'] >= t['signal_timestamp']+300000
                and t['exit_timestamp'] >= t['entry_timestamp'] and t['exit_time'] <= '15:00'):
            raise ValueError('Noncausal or overnight trade.')
        if t['kind']=='limit' and t['entry_timestamp'] < t['submitted_timestamp']+300000:
            raise ValueError('Limit activated before declared delay.')
    for day in {t['date'] for t in trades}:
        previous = [p['equity'] for p in result['curve'] if p['date'] < day]
        capital = previous[-1] if previous else m['initial_capital']
        if sum(t['entry']*t['quantity']+t['entry_fee'] for t in trades if t['date']==day) > capital+1e-6:
            raise ValueError('Daily filled capital was reused.')
    statuses = [o['status'] for o in result['order_ledger']]
    if len(statuses) != result['diagnostics'].get('limit_orders_submitted',0):
        raise ValueError('Limit orders have missing terminal states.')


def report(output, summary):
    lines=['CANDLE CONTINUATION / RETEST STUDY — 29 OCTOBER 2026 (IST)',
           '', summary['decision'], '',
           'Four entry rules x two directions x two entry windows x three slippage scenarios = 48 research runs.',
           'Each portfolio independently starts with Rs 1,000,000; returns cannot be added.',
           'Research: calendar 2025; same audited 12,387 stock-sessions and current-membership selection as first study.',
           '', 'NET RESULTS AT 5 BPS, PLUS DATED UPSTOX CASH-EQUITY FEES',
           'Window / Trial / Direction / Return / Trades / PF / Drawdown']
    for r in summary['runs']:
        if r['slippage_bps']==5:
            pf=f"{r['profit_factor']:.3f}" if r['profit_factor'] is not None else 'undefined'
            lines.append(f"{r['window']:7} {r['variant']:19} {r['direction']:5} {r['return_pct']:+.3f}% / {r['trade_count']} / {pf} / {r['max_observed_close_drawdown_pct']:.2f}%")
    lines+=['', 'FAMILY COMPARISONS AT 5 BPS',
            'Higher net return and higher expectancy versus baseline are separate descriptive outcomes. Fewer trades may reduce loss without establishing an edge.']
    lines.extend(f"{r['window']} {r['variant']} {r['direction']}: return difference {r['return_difference_pct_points']:+.3f} percentage points; net candidate {r['candidate_return_pct']:+.3f}%; research gate {'PASS' if r['gate_passed'] else 'FAIL'}"
                 for r in summary['comparisons'])
    lines+=['', 'Validation status: '+summary['validation_status'],
            'Prospective window is recorded only; no automation or live/paper runner is enabled.',
            '', 'EXECUTION AND LIMITATIONS', SPEC['weak_pullback'], SPEC['gap_definition'], SPEC['gap_retest'], SPEC['limit_execution'],
            '', *SPEC['limitations'], '',
            'All saved ledgers passed accounting, entry timing, same-day exit, reservation and order terminal-state checks.',
            'Source code, specification, source-transcript checksums and exact input checksum references accompany this report.']
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-directory',type=Path,default=store.ROOT/'artifacts'/'candle_rejection_20261029')
    parser.add_argument('--output',type=Path,default=store.ROOT/'artifacts'/'candle_continuation_20261029')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    specification=output/'specification.json'
    if specification.exists():
        if json.loads(specification.read_text())['spec'] != SPEC:
            raise ValueError('Frozen specification changed; use a new output directory.')
    else:
        parent.save(specification,dict(declared_at=datetime.now(intraday_data.IST).isoformat(),spec=SPEC,spec_sha256=parent.digest(SPEC)))
    paths=[Path(__file__),Path(engine.__file__),Path(candle_rejection.__file__),Path(parent.__file__),
           store.ROOT/'core/research/intraday_costs.py']
    code={str(p.relative_to(store.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    code_path=output/'code_manifest.json'
    if code_path.exists() and json.loads(code_path.read_text()) != code:
        raise ValueError('Research code changed; retain this evidence and use a new output.')
    parent.save(code_path,code)
    transcripts={}
    for video in SPEC['sources']:
        path=Path.home()/'Downloads'/f'tactiq-free-transcript-{video}.txt'
        if path.exists():
            transcripts[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    parent.save(output/'transcript_sources.json',transcripts)
    print('New specification and code frozen before new strategy outcomes.',flush=True)
    inputs,audit=parent.load_inputs(args.input_directory,'research',SPEC['research'])
    parent.save(output/'input_reference.json',dict(path=str(args.input_directory.resolve()/'research_inputs.json.gz'),
                input_sha256=audit['input_sha256'],source_spec_sha256=parent.digest(parent.SPEC),
                valid_stock_sessions=audit['valid_stock_sessions'],selected_stock_sessions=audit['selected_stock_sessions']))
    summary=dict(spec_sha256=parent.digest(SPEC),input_sha256=audit['input_sha256'],runs=[],candidate_checks={},comparisons=[],
                 validation_status='not evaluated; pending research gates',prospective=SPEC['prospective'],limitations=SPEC['limitations'])
    results={}
    for window in SPEC['windows']:
        for variant in SPEC['variants']:
            for direction in SPEC['directions']:
                for slip in SPEC['slippage_bps']:
                    key=f'{window}_{variant}_{direction}_{slip}bps'
                    result=engine.simulate(inputs['sessions'],inputs['plan'],variant,1 if direction=='long' else -1,slip,rules_for(window))
                    verify(result)
                    parent.save(output/(key+'.json'),result)
                    results[key]=result
                    summary['runs'].append(dict(key=key,window=window,variant=variant,direction=direction,slippage_bps=slip,
                                                **result['metrics'],diagnostics=result['diagnostics']))
                    parent.save(output/'summary.json',summary)
                    print(f"{key}: {result['metrics']['return_pct']:+.3f}% / {result['metrics']['trade_count']} trades",flush=True)
    candidates=[]
    for window in SPEC['windows']:
        for variant,baseline in engine.BASELINES.items():
            for direction in SPEC['directions']:
                key=f'{window}_{variant}_{direction}_5bps'
                candidate=results[key]
                control=results[f'{window}_{baseline}_{direction}_5bps']
                gate=parent.eligible(candidate,results[f'{window}_{variant}_{direction}_10bps'])
                gate['checks']['beats_baseline_return']=candidate['metrics']['return_pct']>control['metrics']['return_pct']
                gate['passed']=all(gate['checks'].values())
                summary['candidate_checks'][key]=gate
                summary['comparisons'].append(dict(window=window,variant=variant,direction=direction,
                    candidate_return_pct=candidate['metrics']['return_pct'],baseline_return_pct=control['metrics']['return_pct'],
                    return_difference_pct_points=candidate['metrics']['return_pct']-control['metrics']['return_pct'],gate_passed=gate['passed']))
                if gate['passed']:
                    candidates.append((candidate['metrics']['return_pct'],window,variant,direction))
    if not candidates:
        summary.update(validation_status='not opened: no candidate passed all prespecified research gates',
                       decision='No candidate advanced to validation, paper trading or live trading.')
    else:
        _,window,variant,direction=max(candidates)
        summary['selected_candidate']=dict(window=window,variant=variant,direction=direction)
        summary['validation_status']='candidate selection frozen before validation'
        parent.save(output/'summary.json',summary)
        data,vaudit=parent.load_inputs(output,'validation',SPEC['validation'])
        summary['validation_input_sha256']=vaudit['input_sha256']
        summary['validation_runs']=[]
        metrics=[]
        for trial in (engine.BASELINES[variant],variant):
            for slip in (5,10):
                result=engine.simulate(data['sessions'],data['plan'],trial,1 if direction=='long' else -1,slip,rules_for(window))
                verify(result)
                parent.save(output/f'validation_{window}_{trial}_{direction}_{slip}bps.json',result)
                summary['validation_runs'].append(dict(window=window,variant=trial,direction=direction,slippage_bps=slip,**result['metrics']))
                if trial==variant:
                    metrics.append(result['metrics'])
        passed=all(m['return_pct']>0 and m['max_observed_close_drawdown_pct']<=15 for m in metrics) and (metrics[0]['profit_factor'] or 0)>1
        summary.update(validation_status='passed' if passed else 'failed',
                       decision='Candidate eligible for separate forward paper implementation. No trading enabled.' if passed else 'Validation failed; no candidate advanced.')
    parent.save(output/'summary.json',summary)
    report(output,summary)
    print(summary['decision'],flush=True)
    print('Saved: '+str(output),flush=True)


if __name__=='__main__':
    main()
