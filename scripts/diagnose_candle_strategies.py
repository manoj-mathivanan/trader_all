"""Fixed-sample fidelity audit, exact cost attribution and zero-cost replays.

Only verified 2025 artifacts are read. Existing sources, results and reserved
validation inputs are not changed. Patching fee boundaries is process-local.
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import candle_rejection as rejection, candle_continuation as continuation
from core.research.candle_rejection import Rules
from core.research import intraday_data, store
from scripts import research_candle_rejection as first, research_candle_continuation as second


SPEC=dict(version=1, research=first.SPEC['research'],validation='Do not load or simulate any validation data.',
    prior_knowledge='All 66 realistic-cost scenarios already inspected and negative; this is diagnosis, not independent validation.',
    scenarios='22 zero-fee, zero-slippage full replays: 3 rejection rules x 2 directions; 4 continuation rules x 2 directions x 2 windows.',
    zero_cost='Process-local fee overrides at both engines and shared sizing boundary; slippage=0. Keep original stops/targets/holding rules and universe. Retest penetration remains 5bps, distinct from monetary slippage. Capital, sizing, entries and paths may change; this is not adding fees back to an old ledger.',
    ledger_attribution='Separately, on each frozen 5bps ledger, reconcile gross raw-price P&L = net P&L + actual modeled fees + actual modeled slippage. This is descriptive attribution at fixed trades/quantities, not a zero-cost rerun.',
    samples='For full-window level/rejection/confirmation/weak_pullback/gap_retest, each direction: one net winner and loser, picked by minimum SHA256(variant|direction|symbol|date|entry_timestamp), plus one expired retest per direction picked by the same rule using submission timestamp. Up to 22 cases, selected before new diagnostics. No handpicked replacements.',
    markouts='For every modeled raw opportunity meeting the original stop-distance bounds, irrespective of portfolio capacity, measure sign-adjusted close returns at 1,3,6,12 bars from entry. Retest opportunities use declared delay/expiry and 5bps penetration. MFE/MAE exclude entry bar for all setups. Ignore stops/targets in this separate path diagnostic; do not treat as tradable performance.',
    stops='On frozen executed trades, measure how often stop exits subsequently have positive raw-entry-relative close at the 12-bar horizon. This descriptive recovery statistic does not justify widening or removing stops.',
    fidelity='Compare declared numerical rules against timestamped transcript passages; source videos/chart drawings are unavailable in transcripts.',
    decision='No tuning or automatic candidate promotion. If a setup loses even without fees/slippage, stop that implementation. Any positive zero-cost result still requires realistically executable positive performance before validation.',
)


FIDELITY=[
    dict(topic='Level selection',time='38:40-39:27;44:08-44:46',
         transcript='The relevant support/resistance level is primary; a buying-pressure candle at resistance is not a buy.',
         implemented='First study uses previous-day and first-15-minute extremes. Continuation/premium-inspired study has no independently defined support/resistance or higher-timeframe trend gate.',
         assessment='Material approximation. Losing continuation results do not validate or refute discretionary level-conditioned trading.'),
    dict(topic='Weak candles',time='19:20-20:38;32:43-32:49',
         transcript='Discusses a weak same-colour buyer after a strong buyer, wick-dependent exceptions, and weak counter-direction sellers elsewhere.',
         implemented='Weak-pullback model requires opposite-colour/doji candles with body <=1/3 impulse and no wick beyond 50% of impulse body.',
         assessment='Only one interpretation of several examples; the same-colour weak-buyer continuation and wick exceptions were not tested.'),
    dict(topic='Retest timing',time='24:01-24:46',
         transcript='At a next-candle directional opening jump, place the order immediately at the previous candle close.',
         implemented='Wait an entire five-minute candle before the order can fill; expire after the next three bars.',
         assessment='Material execution approximation already declared. Diagnose first-bar retests; cannot call the delayed version a faithful reproduction.'),
    dict(topic='Candle direction/context',time='16:02-16:15;36:23-36:57',
         transcript='Specifically discusses option-premium charts and ITM option purchases, while saying the reading can also apply to spot.',
         implemented='Long/short cash-equity adaptations; no option contract/premium/expiry/IV data.',
         assessment='Different instrument; results establish nothing about option profitability.'),
    dict(topic='Morning session',time='39:02-40:52',
         transcript='Wait until 09:30, focus on early trades and optionally a later session; discussion gives varying time boundaries.',
         implemented='09:30-10:15 entry-only window versus 09:30-14:00. Exits may remain active after entry cutoff.',
         assessment='Partial match; not an exact two-trades-total session cap, 10:15 forced liquidation or separate afternoon test.'),
    dict(topic='Stops and exits',time='26:46-28:08;31:05-31:24',
         transcript='Some examples wait without the usual stop; the interviewer challenges tail loss. Targets also refer to prior chart levels.',
         implemented='Always-active structural stop, fixed 2R target and 60-minute cap.',
         assessment='Intentional risk/exit adaptation. Neither fixed 2R nor 60 minutes is established as the speaker\'s full rule.'),
    dict(topic='Order management',time='Video Eb3tyXLZEeA 06:32-07:03',
         transcript='Cancel remaining target/stop orders after manually closing a position.',
         implemented='Research positions close once, pending retests have terminal states, no broker integration in this study.',
         assessment='Research lifecycle modeled; live order protection/cancellation is not validated.'),
]


def key(row):
    stamp=row.get('entry_timestamp',row.get('submitted_timestamp'))
    return hashlib.sha256(f"{row['variant']}|{row['direction']}|{row['symbol']}|{row['date']}|{stamp}".encode()).hexdigest()


def attribution(result):
    trades=result['trades']
    raw=sum((1 if t['direction']=='long' else -1)*(t['raw_exit']-t['raw_entry'])*t['quantity'] for t in trades)
    net=sum(t['pnl'] for t in trades)
    fees=sum(t['fees'] for t in trades)
    slip=sum(t['slippage'] for t in trades)
    if abs(raw-net-fees-slip)>1e-6:
        raise ValueError('Raw-price attribution does not reconcile.')
    return dict(trade_count=len(trades), net_pnl=net,raw_price_pnl=raw,fees=fees,slippage=slip,
                raw_price_return_pct=raw/result['metrics']['initial_capital']*100,
                fees_pct=fees/result['metrics']['initial_capital']*100,
                slippage_pct=slip/result['metrics']['initial_capital']*100,
                exit_reasons=dict(Counter(t['reason'] for t in trades)),
                median_holding_minutes=median((t['exit_timestamp']-t['entry_timestamp'])/60000 for t in trades) if trades else None)


def zero_replay(inputs,family,variant,sign,rules):
    """Do not mutate engine files or input snapshots for the diagnostic."""
    original_fill=continuation.limit_fill
    def fill_with_fixed_penetration(order,bar,index,direction,ignored_slip,policy):
        return original_fill(order,bar,index,direction,.0005,policy)
    def no_fee(*args,**kwargs):
        return 0.0
    with patch.object(rejection,'upstox_cash_fees',no_fee), patch.object(continuation,'upstox_cash_fees',no_fee), patch.object(continuation,'limit_fill',fill_with_fixed_penetration):
        engine=rejection if family=='rejection' else continuation
        result=engine.simulate(inputs['sessions'],inputs['plan'],variant,sign,0,rules)
    if result['metrics'].get('fees',result['metrics'].get('modeled_fees',0)) != 0 or result['metrics'].get('slippage',0) != 0:
        raise ValueError('Zero-cost diagnostic retained costs.')
    return result


def trade_index(trade,bars):
    return next(i for i,b in enumerate(bars) if b['timestamp']==trade['entry_timestamp'])


def paths_for_trade(trade,bars,sign):
    j=trade_index(trade,bars)
    horizon=min(j+11, next(i for i,b in enumerate(bars) if b['time']=='15:00'))
    future=bars[j+1:horizon+1]
    risk=sign*(trade['entry']-trade['stop'])
    mfe=max([0]+[sign*(b['high' if sign==1 else 'low']-trade['raw_entry']) for b in future])
    mae=max([0]+[-sign*(b['low' if sign==1 else 'high']-trade['raw_entry']) for b in future])
    return dict(horizon_index=horizon, mfe_r=mfe/risk,mae_r=mae/risk,
                horizon_return_bps=sign*(bars[horizon]['close']/trade['raw_entry']-1)*10000,
                horizon_after_exit=bars[horizon]['timestamp']>trade['exit_timestamp'])


def path_summary(result,sessions,sign):
    rows=[dict(t,**paths_for_trade(t,sessions[t['symbol']][t['date']],sign)) for t in result['trades']]
    stopped=[t for t in rows if t['reason'] in ('stop','gap_stop') and t['horizon_after_exit']]
    return dict(trades=len(rows),mean_post_entry_mfe_r=mean(t['mfe_r'] for t in rows) if rows else None,
                mean_post_entry_mae_r=mean(t['mae_r'] for t in rows) if rows else None,
                reached_1r_pct=mean(t['mfe_r']>=1 for t in rows)*100 if rows else None,
                reached_2r_pct=mean(t['mfe_r']>=2 for t in rows)*100 if rows else None,
                eligible_stopped_trades=len(stopped),
                stopped_then_positive_horizon_pct=mean(t['horizon_return_bps']>0 for t in stopped)*100 if stopped else None)


def opportunity_markouts(inputs,family,variant,sign,rules):
    rows=[]
    first_bar_touches=first_bar_penetrations=submissions=0
    for day,selected in sorted(inputs['plan'].items()):
        for context in selected:
            bars=inputs['sessions'][context['symbol']][day]
            opportunities=(rejection.signals(bars,context,variant,sign,rules) if family=='rejection'
                           else continuation.orders(bars,context,variant,sign,rules))
            for j,setup in opportunities.items():
                stop=setup['extreme']-sign*rules.stop_buffer_atr*setup['atr']
                entry=bars[j]['open']
                start=j
                limit=setup.get('kind')=='limit'
                if family=='rejection' and sign*(entry-setup['level'])<=0:
                    continue
                if limit:
                    submissions+=1
                    extreme=bars[j]['low' if sign==1 else 'high']
                    first_bar_touches+=sign*(extreme-setup['limit'])<=0
                    first_bar_penetrations+=sign*(extreme-setup['limit'])<=-setup['limit']*.0005
                    fills=[k for k in range(j+1,min(j+4,len(bars)))
                           if continuation.limit_fill(setup,bars[k],k,sign,.0005,rules)]
                    if not fills:
                        continue
                    start,entry=fills[0],setup['limit']
                width=sign*(entry-stop)
                if width<=0 or not rules.min_stop_fraction<=width/entry<=rules.max_stop_fraction:
                    continue
                row=dict(symbol=context['symbol'],date=day,entry_index=start,entry=entry)
                for horizon in (1,3,6,12):
                    end=start+horizon-1
                    if end<len(bars) and bars[end]['time']<='15:00':
                        row[str(horizon)]=sign*(bars[end]['close']/entry-1)*10000
                rows.append(row)
    summary={}
    for horizon in ('1','3','6','12'):
        values=[r[horizon] for r in rows if horizon in r]
        summary[horizon]=dict(count=len(values),mean_bps=mean(values) if values else None,
                               median_bps=median(values) if values else None,
                               positive_pct=mean(v>0 for v in values)*100 if values else None)
    return dict(opportunities=len(rows),horizons=summary,retest_submissions=submissions,
                gap_bar_touch_count=first_bar_touches,gap_bar_penetration_count=first_bar_penetrations,
                gap_bar_penetration_pct=first_bar_penetrations/submissions*100 if submissions else None)


def select_samples(records):
    samples=[]
    for variant in ('level','rejection','confirmation','weak_pullback','gap_retest'):
        for direction in ('long','short'):
            record=next(r for r in records if r['variant']==variant and r['direction']==direction and r['window']=='full')
            for bucket in ('winner','loser'):
                candidates=[dict(t,variant=variant,direction=direction) for t in record['result']['trades']
                            if (t['pnl']>0 if bucket=='winner' else t['pnl']<0)]
                if candidates:
                    samples.append(dict(min(candidates,key=key),bucket=bucket))
            if variant=='gap_retest':
                candidates=[dict(o,variant=variant,direction=direction) for o in record['result']['order_ledger'] if o['status']=='expired']
                if candidates:
                    samples.append(dict(min(candidates,key=key),bucket='unfilled'))
    return samples


def sample_audit(sample,inputs):
    sign=1 if sample['direction']=='long' else -1
    bars=inputs['sessions'][sample['symbol']][sample['date']]
    context=next(c for c in inputs['plan'][sample['date']] if c['symbol']==sample['symbol'])
    is_first=sample['variant'] in ('level','rejection','confirmation')
    signals=(rejection.signals(bars,context,sample['variant'],sign) if is_first
             else continuation.orders(bars,context,sample['variant'],sign))
    j=(trade_index(sample,bars) if is_first else sample['submitted_index'])
    setup=signals.get(j)
    checks=dict(regenerated_signal=setup is not None)
    if setup is not None:
        expected_stop=setup['extreme']-sign*Rules().stop_buffer_atr*setup['atr']
        checks['structural_stop_matches']=abs(expected_stop-sample['stop'])<1e-8
        checks['signal_complete_at_decision']=bars[setup['signal_index']]['timestamp']+300000 <= bars[j]['timestamp']
    if sample['bucket']=='unfilled':
        eligible=range(sample['active_index'],min(sample['expires_index']+1,len(bars)))
        checks['no_eligible_fill']=not any(continuation.limit_fill(sample,bars[k],k,sign,.0005,Rules()) for k in eligible)
    else:
        checks['entry_after_completed_signal']=sample['entry_timestamp']>=sample['signal_timestamp']+300000
        checks['net_pnl_reconciles']=abs(sample['pnl']-(sign*(sample['exit']-sample['entry'])*sample['quantity']-sample['fees']))<1e-7
        checks['same_day_exit']=sample['exit_time']<='15:00'
    return dict(sample,checks=checks,all_checks_pass=all(checks.values()))


def chart_samples(output,samples,inputs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    paths=[]
    for page in range((len(samples)+5)//6):
        fig,axes=plt.subplots(3,2,figsize=(17,12))
        for ax,sample in zip(axes.flat,samples[page*6:page*6+6]):
            bars=inputs['sessions'][sample['symbol']][sample['date']]
            decision=sample.get('submitted_index',next((i for i,b in enumerate(bars) if b['timestamp']==sample.get('entry_timestamp')),-1))
            signal=next(i for i,b in enumerate(bars) if b['timestamp']==sample['signal_timestamp'])
            left=max(0,signal-5)
            right=min(75,decision+18)
            for i in range(left,right):
                b=bars[i]
                color='#087f5b' if b['close']>=b['open'] else '#c92a2a'
                ax.vlines(i,b['low'],b['high'],color=color,linewidth=1)
                ax.add_patch(Rectangle((i-.3,min(b['open'],b['close'])),.6,max(abs(b['close']-b['open']),b['close']*.00002),facecolor=color,edgecolor=color))
            ax.axvline(signal+.5,color='#555',linestyle=':',label='signal completed')
            ax.axhline(sample['stop'],color='#c92a2a',linestyle='--',linewidth=.9,label='stop')
            ax.axhline(sample['target'],color='#087f5b',linestyle='--',linewidth=.9,label='target')
            price=sample.get('limit',sample['entry'])
            ax.axhline(price,color='#1864ab',linestyle='--',linewidth=.9,label='entry/limit')
            if sample['bucket']!='unfilled':
                j=trade_index(sample,bars)
                ax.scatter(j,sample['entry'],color='#1864ab',marker='^',s=65,zorder=5)
                exit_j=next(i for i,b in enumerate(bars) if b['timestamp']==sample['exit_timestamp'])
                ax.scatter(exit_j,sample['exit'],color='black',marker='x',s=45,zorder=5)
                detail=f"{sample['reason']} / net Rs {sample['pnl']:+,.0f}"
            else:
                ax.axvspan(sample['active_index'],sample['expires_index']+.5,color='#1864ab',alpha=.08)
                detail='expired; blue band = eligible order bars'
            ticks=list(range(left,right,3))
            ax.set_xticks(ticks,[bars[i]['time'] for i in ticks],fontsize=8)
            ax.set_title(f"{sample['variant']} {sample['direction']} {sample['bucket']}\n{sample['symbol']} {sample['date']} | {detail}",fontsize=10)
            ax.tick_params(axis='y',labelsize=8)
            ax.grid(alpha=.15)
        for ax in list(axes.flat)[len(samples[page*6:page*6+6]):]:
            ax.axis('off')
        fig.suptitle('Fixed hash-selected audit samples | 2025 data | five-minute candles',fontsize=14)
        fig.tight_layout(rect=(0,0,1,.97))
        path=output/f'sample_charts_{page+1}.png'
        fig.savefig(path,dpi=115)
        plt.close(fig)
        paths.append(str(path))
    return paths


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=store.ROOT/'artifacts'/'candle_diagnostics_20261029')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    path=output/'specification.json'
    if path.exists() and json.loads(path.read_text())['spec']!=SPEC:
        raise ValueError('Diagnostic specification changed; use a new output.')
    if not path.exists():
        first.save(path,dict(declared_at=datetime.now(intraday_data.IST).isoformat(),spec=SPEC,spec_sha256=first.digest(SPEC)))
    sources=[Path(__file__),Path(rejection.__file__),Path(continuation.__file__),Path(first.__file__),Path(second.__file__),store.ROOT/'core/research/intraday_costs.py']
    hashes={str(p.relative_to(store.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    manifest=output/'code_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text())!=hashes:
        raise ValueError('Diagnostic code changed; preserve previous output.')
    first.save(manifest,hashes)
    records=[]
    for family,directory in [('rejection','candle_rejection_20261029'),('continuation','candle_continuation_20261029')]:
        root=store.ROOT/'artifacts'/directory
        summary=json.loads((root/'summary.json').read_text())
        for row in summary['runs']:
            if row['slippage_bps']!=5:
                continue
            records.append(dict(family=family,variant=row['variant'],direction=row['direction'],window=row.get('window','full'),
                                source=str(root/(row['key']+'.json')),result=json.loads((root/(row['key']+'.json')).read_text())))
    samples=select_samples(records)
    first.save(output/'sample_selection.json',samples)
    first.save(output/'source_results.json',{r['source']:hashlib.sha256(Path(r['source']).read_bytes()).hexdigest() for r in records})
    print(f'Diagnostic specification frozen; selected {len(samples)} audit cases before new outcomes.',flush=True)
    inputs,audit=first.load_inputs(store.ROOT/'artifacts'/'candle_rejection_20261029','research',SPEC['research'])
    sampled=[sample_audit(s,inputs) for s in samples]
    if not all(s['all_checks_pass'] for s in sampled):
        first.save(output/'sample_checks.json',sampled)
        raise ValueError('Sample fidelity implementation check failed; see sample_checks.json.')
    first.save(output/'sample_checks.json',sampled)
    first.save(output/'transcript_fidelity.json',FIDELITY)
    rows=[]
    for record in records:
        sign=1 if record['direction']=='long' else -1
        rules=Rules() if record['window']=='full' else replace(Rules(),last_entry='10:15')
        identity={k:record[k] for k in ('family','variant','direction','window')}
        name='_'.join(identity.values())
        result=zero_replay(inputs,record['family'],record['variant'],sign,rules)
        first.save(output/(name+'_zero_cost.json'),result)
        attr=attribution(record['result'])
        markouts=opportunity_markouts(inputs,record['family'],record['variant'],sign,rules)
        row=dict(**identity,source=record['source'],realistic_metrics=record['result']['metrics'],
                 fixed_ledger_attribution=attr,zero_cost_metrics=result['metrics'],
                 zero_cost_result_sha256=first.digest(result),trade_path=path_summary(record['result'],inputs['sessions'],sign),
                 opportunity_markouts=markouts)
        rows.append(row)
        first.save(output/'summary.json',dict(spec_sha256=first.digest(SPEC),input_sha256=audit['input_sha256'],runs=rows))
        print(f"{name}: real {row['realistic_metrics']['return_pct']:+.3f}% / fixed-ledger gross {attr['raw_price_return_pct']:+.3f}% / zero-cost replay {result['metrics']['return_pct']:+.3f}%",flush=True)
    charts=chart_samples(output,sampled,inputs)
    summary=dict(spec_sha256=first.digest(SPEC),input_sha256=audit['input_sha256'],runs=rows,sample_count=len(sampled),
                 sample_checks_passed=True,charts=charts,fidelity=FIDELITY,validation_status='not loaded or simulated')
    first.save(output/'summary.json',summary)
    lines=['CANDLE STRATEGY DIAGNOSTICS — 29 OCTOBER 2026 (IST)','',
           'No strategy or validation period was promoted. These are diagnostics on previously inspected 2025 data.',
           'Fixed-ledger gross attribution and independent zero-cost replays answer different questions.',
           'Retest trade-through threshold stays at 5bps even in zero-cost replays.',
           '', 'Family / Entry rule / Direction / Window / Realistic net % / Fixed-ledger raw % / Independent zero-cost % / Zero-cost trades']
    for row in rows:
        lines.append(f"{row['family']} / {row['variant']} / {row['direction']} / {row['window']} / {row['realistic_metrics']['return_pct']:+.3f} / {row['fixed_ledger_attribution']['raw_price_return_pct']:+.3f} / {row['zero_cost_metrics']['return_pct']:+.3f} / {row['zero_cost_metrics']['trade_count']}")
    lines+=['','TRANSCRIPT FIDELITY']
    for finding in FIDELITY:
        lines.extend(['',finding['topic']+' — '+finding['time'],finding['transcript'],finding['implemented'],finding['assessment']])
    lines+=['',f'FIXED-SAMPLE CHECKS: {len(sampled)} cases; all numerical rule/timing checks passed.',
            'Manual visual review of contact sheets remains required; algorithmic checks do not establish discretionary chart fidelity.',
            '', 'Unconditioned forward markouts ignore portfolio filters and stops; they are not tradable performance.',
            'Stop-recovery statistics and favorable/adverse excursions are descriptive, not evidence to remove stops or choose new thresholds.',
            'Reserved 2026 validation candles were not loaded or simulated. No database writes, source strategy changes or broker orders.']
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Saved: '+str(output),flush=True)


if __name__=='__main__':
    main()
