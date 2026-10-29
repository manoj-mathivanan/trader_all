"""One declared passive-entry diagnostic, preserving all previous study artifacts."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import candle_continuation as engine, candle_rejection as source, intraday_data, store
from scripts import research_candle_rejection as first


SPEC=dict(version=2, research=first.SPEC['research'], validation='Not opened by this diagnostic.',
    hypothesis='Can a passive entry reduce cost drag enough to retain the short-rejection signal? Diagnostic selection used prior 2025 zero-cost results; no claim of independent confirmation.',
    selection='Only full-window short rejection, chosen because its diagnosed zero-cost return was +14.046%, while its 5bps realistic return was -23.568%. No other directions, windows, thresholds or setups searched.',
    control='Replay original market entry at next candle open; require trade identity/quantities to match exactly, metrics within 1e-7 and floating trade values within 1e-9 of original source at each slippage scenario. This tolerates only arithmetic associativity, not different fills.',
    limit='Submit sell limit at completed rejection-candle close, active from the next candle open for three bars inclusive, subject to original 14:00 entry cutoff. Stop remains rejection high + 0.05 daily ATR. Quantity and collateral reserved before fill.',
    eligibility='Same original signal and same next-open level-reclaim validation as market control. Signals occurring while an order/position occupies the symbol are skipped.',
    fills='Existing conservative limit engine: no favorable improvement, intrabar penetration by scenario bps, opening crossing may fill. Unknown-order entry-bar targets not credited; protective stops remain active. Opening gap-through-stop is not retroactively cancelled.',
    unchanged='Original 2025 frozen universe/plan, 09:30-14:00 submissions, fees, risk sizing, two fills per stock/day, five reserved/active slots, 2R target, 60-minute holding cap and 15:00 exit.',
    scenarios=[2,5,10],scenario_meaning='For market entries: adverse entry/exit slippage bps. For passive entries: entry penetration bps and adverse exit slippage bps. Same dated full Upstox fee schedule throughout.',
    gates=first.SPEC['candidate_gate'],
    decision='Require every original absolute gate plus higher 5bps net return than original market control. Passing warrants a later validation study only; no validation data or trading is enabled here.',
    limitations=['Passive fill/queue assumptions are unverified with five-minute candles; opening activation ignores real submission latency.',
                 'No options data or faithful reconstruction of discretionary video levels.',
                 'This is a diagnosed execution experiment on an already inspected period, with survivorship/data-exclusion biases inherited from the original snapshot.'])


def provider(mode):
    if mode not in ('market','passive'):
        raise ValueError('Unknown execution mode.')
    def selected_orders(bars,context,ignored_variant,sign,rules):
        if sign!=-1:
            raise ValueError('This experiment is short-only.')
        opportunities=source.signals(bars,context,'rejection',sign,rules)
        output={}
        for j,setup in opportunities.items():
            if sign*(bars[j]['open']-setup['level'])<=0:
                continue
            order=dict(setup,kind='market',reference=setup['level'])
            if mode=='passive':
                order.update(kind='limit',limit=bars[setup['signal_index']]['close'],active_index=j,expires_index=j+2)
            output[j]=order
        return output
    return selected_orders


def run(inputs,mode,slip):
    # Process-local signal injection reuses immutable engines; never edit the
    # frozen original implementation or its result directories.
    with patch.object(engine,'orders',provider(mode)):
        result=engine.simulate(inputs['sessions'],inputs['plan'],'impulse_control',-1,slip)
    if abs(result['metrics']['final_equity']-result['metrics']['initial_capital']-sum(t['pnl'] for t in result['trades']))>1e-6:
        raise ValueError('Passive-study accounting mismatch.')
    for t in result['trades']:
        if t['entry_timestamp']<t['signal_timestamp']+300000 or t['exit_timestamp']<t['entry_timestamp'] or t['exit_time']>'15:00':
            raise ValueError('Noncausal passive-study trade.')
        if t['kind']=='limit' and not t['active_index']<=t['entry_index']<=t['expires_index']:
            raise ValueError('Passive fill outside order lifetime.')
    if len(result['order_ledger'])!=result['diagnostics'].get('limit_orders_submitted',0):
        raise ValueError('Orders missing terminal states.')
    return result


def verify_control(original,control):
    for key,value in original['metrics'].items():
        if value is None:
            if control['metrics'][key] is not None:
                raise ValueError('Control metric mismatch: '+key)
        elif abs(control['metrics'][key]-value)>1e-7:
            raise ValueError('Control metric mismatch: '+key)
    fields=('symbol','date','entry_timestamp','exit_timestamp','quantity','entry','exit','pnl','fees','reason')
    if len(original['trades'])!=len(control['trades']):
        raise ValueError('Original market trade count did not reproduce.')
    for old,new in zip(original['trades'],control['trades']):
        for field in fields:
            a,b=old[field],new[field]
            if (abs(a-b)>1e-9 if isinstance(a,float) else a!=b):
                raise ValueError('Original market ledger did not reproduce: '+field)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=store.ROOT/'artifacts'/'candle_passive_20261029_v2')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    path=output/'specification.json'
    if path.exists() and json.loads(path.read_text())['spec']!=SPEC:
        raise ValueError('Frozen passive specification changed.')
    if not path.exists():
        first.save(path,dict(declared_at=datetime.now(intraday_data.IST).isoformat(),spec=SPEC,spec_sha256=first.digest(SPEC)))
    sources=[Path(__file__),Path(source.__file__),Path(engine.__file__),Path(first.__file__),store.ROOT/'core/research/intraday_costs.py']
    hashes={str(p.relative_to(store.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    manifest=output/'code_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text())!=hashes:
        raise ValueError('Passive research code changed; use new output.')
    first.save(manifest,hashes)
    print('Passive-entry specification frozen before outcomes.',flush=True)
    inputs,audit=first.load_inputs(store.ROOT/'artifacts'/'candle_rejection_20261029','research',SPEC['research'])
    summary=dict(spec_sha256=first.digest(SPEC),input_sha256=audit['input_sha256'],runs=[],validation_status='not loaded or simulated')
    passive={}
    for slip in SPEC['scenarios']:
        control=run(inputs,'market',slip)
        original=json.loads((store.ROOT/'artifacts'/'candle_rejection_20261029'/f'rejection_short_{slip}bps.json').read_text())
        verify_control(original,control)
        first.save(output/f'market_control_{slip}bps.json',control)
        result=run(inputs,'passive',slip)
        passive[slip]=result
        first.save(output/f'passive_{slip}bps.json',result)
        summary['runs'].append(dict(slippage_bps=slip,market=control['metrics'],passive=result['metrics'],
                                     diagnostics=result['diagnostics'],baseline_reproduced=True))
        first.save(output/'summary.json',summary)
        print(f"{slip}bps: market {control['metrics']['return_pct']:+.3f}% / passive {result['metrics']['return_pct']:+.3f}% / {result['metrics']['trade_count']} fills",flush=True)
    gate=first.eligible(passive[5],passive[10])
    baseline=next(r for r in summary['runs'] if r['slippage_bps']==5)['market']
    gate['checks']['beats_baseline_return']=passive[5]['metrics']['return_pct']>baseline['return_pct']
    gate['passed']=all(gate['checks'].values())
    summary.update(gate=gate,decision='Eligible for a later validation study; none run here.' if gate['passed'] else 'Passive execution also failed the research gates; no candidate advances.')
    first.save(output/'summary.json',summary)
    lines=['PASSIVE SHORT-REJECTION EXECUTION DIAGNOSTIC — 29 OCTOBER 2026 (IST)','',summary['decision'],
           '', 'Bps / Original market return % / Passive return % / Passive fills / Passive PF']
    for row in summary['runs']:
        lines.append(f"{row['slippage_bps']} / {row['market']['return_pct']:+.3f} / {row['passive']['return_pct']:+.3f} / {row['passive']['trade_count']} / {row['passive']['profit_factor']}")
    lines+=['', 'All three original market-control ledgers reproduced before comparison, allowing only floating-point rounding tolerance.',
            'Same signal, protective stop and sizing/exit rules; changed order price, fill selection and reservation lifetime are the declared treatment.',
            'Passive entries cannot fill above/below their limit adversely; exit slippage and full fees remain.',
            'Opening activation and queue fills are assumptions, not verified broker execution.',
            'Reserved validation remained untested. No trading enabled.', '',*SPEC['limitations']]
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(summary['decision'],flush=True)


if __name__=='__main__':
    main()
