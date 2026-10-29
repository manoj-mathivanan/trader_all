"""Identify the worst saved candle result, then reverse its whole entry cohort."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import candle_reversal as engine,candle_rejection,intraday_data,store
from scripts import research_candle_rejection as first
from scripts.research_candle_passive import verify_control


SPEC=dict(version=1,scope='The 99 realistic-cost candle-family results in this conversation; excludes zero-cost diagnostics and unrelated project strategies.',
    identification='Lowest saved 2025 net portfolio return across rejection, continuation, context and passive studies. Also report lowest return at common 5bps costs.',
    cohort='Freeze every executed entry in the overall worst run, including original winners and losers. All replay scenarios attempt these same stock/date/entry-open events. Independent sizing/capital/position limits may reject events; record every decision.',
    reverse='Original long becomes short. Original target becomes protective stop; original stop becomes profit target. Evaluate exits afresh from the frozen candles, not original recorded exit timestamps. Reward/risk is roughly 0.5:1, not the original 2:1.',
    risk='Retain original risk sizing, fees, daily collateral, position/trade limits and maximum stop distance. Reject reversed entries whose target is no longer profitable after entry slippage. Gaps and ambiguous bars follow conservative original execution rules.',
    costs=[0,2,5,10],zero='Zero scenario has neither fees nor monetary slippage. Other scenarios use full dated Upstox fees and adverse bps on both entry and exit.',
    controls='Follow-mode replay on exactly the same frozen entry events and original barriers. Require the 10bps control to reproduce source metrics/trade identities within original floating-point tolerances.',
    candidate_gate=first.SPEC['candidate_gate'],
    outcome_bias='Worst-model selection uses all 2025 outcomes and is explicitly retrospective. Individual loss labels must not influence entry decisions. A profitable reversal would remain exploratory.',
    validation='Do not load or run the reserved 2026 period in this reversal diagnostic. No orders or live/paper settings changed.')


def identify(root):
    rows=[]
    for name in ('candle_rejection_20261029','candle_continuation_20261029','candle_context_20261029'):
        directory=root/name
        for row in json.loads((directory/'summary.json').read_text())['runs']:
            rows.append(dict(row,source=str(directory/(row['key']+'.json'))))
    directory=root/'candle_passive_20261029_v2'
    for row in json.loads((directory/'summary.json').read_text())['runs']:
        rows.append(dict(key=f"passive_{row['slippage_bps']}bps",slippage_bps=row['slippage_bps'],
                         source=str(directory/f"passive_{row['slippage_bps']}bps.json"),**row['passive']))
    return dict(ranked=sorted(rows,key=lambda r:(r['return_pct'],r['source'])),
                worst=min(rows,key=lambda r:(r['return_pct'],r['source'])),
                worst_5bps=min((r for r in rows if r['slippage_bps']==5),key=lambda r:(r['return_pct'],r['source'])))


def verify(result,source):
    events=engine.entry_events(source)
    if abs(result['metrics']['final_equity']-result['metrics']['initial_capital']-sum(t['pnl'] for t in result['trades']))>1e-6:
        raise ValueError('Reversal accounting mismatch.')
    if len(result['entry_decisions'])!=len(source['trades']):
        raise ValueError('Not every source entry was attempted and recorded.')
    for t in result['trades']:
        event=events[t['date']][t['symbol']][t['entry_index']]
        if t['entry_timestamp']!=event['source_entry_timestamp'] or t['entry_timestamp']<t['signal_timestamp']+300000:
            raise ValueError('Reverse entered at a different or noncausal time.')
        if t['exit_timestamp']<t['entry_timestamp'] or t['exit_time']>'15:00':
            raise ValueError('Reverse exit timing failed.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=store.ROOT/'artifacts'/'candle_reversal_20261029')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    identification=identify(store.ROOT/'artifacts')
    worst=identification['worst']
    source_path=Path(worst['source'])
    source=json.loads(source_path.read_text())
    spec={**SPEC,'selected_key':worst['key'],'selected_source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest()}
    spec_path=output/'specification.json'
    if spec_path.exists() and json.loads(spec_path.read_text())['spec']!=spec:
        raise ValueError('Frozen reversal specification/source changed.')
    if not spec_path.exists():
        first.save(spec_path,dict(declared_at=datetime.now(intraday_data.IST).isoformat(),spec=spec,spec_sha256=first.digest(spec)))
    paths=[Path(__file__),Path(engine.__file__),Path(candle_rejection.__file__),Path(first.__file__),
           store.ROOT/'scripts/research_candle_passive.py',store.ROOT/'core/research/intraday_costs.py']
    manifest={str(p.relative_to(store.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest_path=output/'code_manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text())!=manifest:
        raise ValueError('Frozen reversal code changed; preserve outputs.')
    first.save(manifest_path,manifest)
    first.save(output/'identification.json',identification)
    first.save(output/'entry_events.json',engine.entry_events(source))
    print(f"Worst: {worst['key']} {worst['return_pct']:+.3f}% / {source['metrics']['trade_count']} entries. Reversal rules frozen.",flush=True)
    inputs,audit=first.load_inputs(store.ROOT/'artifacts'/'candle_rejection_20261029','research',first.SPEC['research'])
    worst_trade=min(source['trades'],key=lambda t:t['pnl'])
    example_index=source['trades'].index(worst_trade)
    summary=dict(spec_sha256=first.digest(spec),input_sha256=audit['input_sha256'],worst=worst,
                 worst_5bps=identification['worst_5bps'],runs=[],validation_status='not loaded or simulated',
                 example_source_trade=worst_trade,example_source_trade_index=example_index)
    reverses={}
    for slip in SPEC['costs']:
        fees=0 if slip==0 else 1
        control=engine.simulate(inputs,source,'follow',slip,fee_multiplier=fees)
        verify(control,source)
        if slip==10:
            verify_control(source,control)
        reverse=engine.simulate(inputs,source,'reverse',slip,fee_multiplier=fees)
        verify(reverse,source)
        reverses[slip]=reverse
        first.save(output/f'follow_{slip}bps.json',control)
        first.save(output/f'reverse_{slip}bps.json',reverse)
        summary['runs'].append(dict(slippage_bps=slip,fees_enabled=bool(fees),follow=control['metrics'],reverse=reverse['metrics'],
                                    diagnostics=reverse['diagnostics'],
                                    example_reverse_trades=[t for t in reverse['trades'] if t['source_trade_index']==example_index],
                                    example_reverse_decisions=[d for d in reverse['entry_decisions'] if d['source_trade_index']==example_index]))
        first.save(output/'summary.json',summary)
        print(f"{slip}bps: follow {control['metrics']['return_pct']:+.3f}% / reverse {reverse['metrics']['return_pct']:+.3f}% / {reverse['metrics']['trade_count']} reversed fills",flush=True)
    summary['gate']=first.eligible(reverses[5],reverses[10])
    summary['decision']='Reversal passes research gates but remains retrospective; validation not opened.' if summary['gate']['passed'] else 'Reversal fails research gates; no candidate advanced.'
    summary['source_control_reproduced']=True
    first.save(output/'summary.json',summary)
    lines=['WORST CANDLE RESULT AND REVERSED ENTRIES — 29 OCTOBER 2026 (IST)','',
           f"Worst of {len(identification['ranked'])} realistic-cost candle-family runs: {worst['key']} / {worst['return_pct']:+.3f}%.",
           f"Worst at 5bps common costs: {identification['worst_5bps']['key']} / {identification['worst_5bps']['return_pct']:+.3f}%.",
           'Worst source is the level-reaction long baseline, not the wick-filtered rejection strategy.',
           'All 1,894 original entry events are attempted, including original winners; future P&L and exit times are not used to choose or close reverse trades.',
           'Original target becomes short stop; original stop becomes short target. Positions are resized independently; source times remain fixed, but capital/risk/position checks can reject entries.',
           '', 'Scenario / Follow control return / Reverse return / Reverse trades / Reverse PF']
    for row in summary['runs']:
        lines.append(f"{row['slippage_bps']}bps {'with fees' if row['fees_enabled'] else 'no fees'} / {row['follow']['return_pct']:+.3f}% / {row['reverse']['return_pct']:+.3f}% / {row['reverse']['trade_count']} / {row['reverse']['profit_factor']}")
    lines+=['',summary['decision'],
            'Follow control at 10bps reproduced the original source ledger; remaining follow controls are replays on this same fixed source-10bps entry cohort, not the original independently selected scenario cohorts.',
            'Costs remain payable in either direction. Swapped barriers produce roughly 0.5:1 reward/risk, and both directions use stop-first ambiguous-bar handling.',
            'Selection of the worst full-year outcome is retrospective. This does not establish out-of-sample edge.',
            '', 'WORST INDIVIDUAL SOURCE TRADE (illustration only; not used to select entries)',
            f"{worst_trade['symbol']} {worst_trade['date']} {worst_trade['entry_time']} IST: original net Rs {worst_trade['pnl']:+,.2f}."]
    for row in summary['runs']:
        if row['example_reverse_trades']:
            t=row['example_reverse_trades'][0]
            lines.append(f"Reverse {row['slippage_bps']}bps: {t['entry_time']} short {t['quantity']} shares, exit {t['exit_time']}, net Rs {t['pnl']:+,.2f} ({t['reason']}).")
        else:
            lines.append(f"Reverse {row['slippage_bps']}bps: example was not filled; decision={row['example_reverse_decisions']}.")
    lines+=['','No reserved 2026 validation candles loaded or simulated. No broker orders, paper changes or database writes.']
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(summary['decision'],flush=True)


if __name__=='__main__':
    main()
