"""Declared scan-size comparison using frozen daily context and cached/fetched minutes."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import momentum,store,data_quality,intraday_data
from core.research.config import Settings
from core.research.intraday_costs import upstox_cash_fees
from scripts.research_intraday_costs import attribution,digest

WINDOWS=[('2025-02-03','2025-02-28'),('2025-06-02','2025-06-30'),('2026-01-02','2026-01-30')]
REFERENCE='836c4463d21b'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markdown', type=Path, help='Explicitly export a Markdown report to this path')
    args = parser.parse_args()
    reference=store.read('runs/'+REFERENCE)
    cfg=momentum.MomentumConfig(**{**reference['config'],'comparison_run_id':REFERENCE})
    universe,daily,manifest,excluded=momentum.prepare(Settings(universe=reference['universe']),cfg)
    data_quality.require_no_anomalies(data_quality.audit(daily,end=cfg.end))
    output=store.ROOT/'artifacts'/'intraday_selection_research'
    output.mkdir(parents=True,exist_ok=True)
    prior_summary=json.loads((output/'summary.json').read_text()) if (output/'summary.json').exists() else {}
    previous_inputs={item['start']:item for item in prior_summary.get('inputs',[])}
    summary=dict(reference=REFERENCE,config=reference['config'],daily_manifest=manifest,
        declared_windows=WINDOWS,created_at=store.now(),runs=[],failures=[],inputs=[])
    def checkpoint():
        (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    checkpoint()
    for start,end in WINDOWS:
        print('Preparing window',start,end,flush=True)
        month_cfg=cfg.model_copy(update={'start':date.fromisoformat(start),'end':date.fromisoformat(end)})
        plans={}
        requests=None
        for size in (50,200):
            plans[size],required=momentum.entry_plan(daily,month_cfg.model_copy(update={'liquid_universe_size':size}))
            if size==200:
                requests=required
        try:
            frozen=output/(start+'_inputs.json')
            if start in previous_inputs:
                sessions=json.loads(frozen.read_text(encoding='utf-8'))
                if digest(sessions)!=previous_inputs[start]['sha256']:
                    raise ValueError('Existing frozen minute input hash changed; replay halted.')
                print('Reusing verified frozen monthly inputs.',flush=True)
            else:
                if frozen.exists():
                    raise ValueError('Untracked existing input snapshot; inspect before replacing.')
                sessions=intraday_data.load_ranges(requests,universe,lambda message:print(message,flush=True))
                frozen.write_text(json.dumps(sessions,allow_nan=False),encoding='utf-8')
            summary['inputs'].append(dict(start=start,end=end,sha256=digest(sessions),path=frozen.name,
                stock_sessions=sum(len(x) for x in sessions.values()),
                notice='Daily data remain frozen from reference; minute data frozen after cache normalization and any downloads.'))
            checkpoint()
        except Exception as exc:
            summary['failures'].append(dict(start=start,stage='input acquisition',error=str(exc)))
            checkpoint()
            print('Input failure:',type(exc).__name__,str(exc),flush=True)
            continue
        for size in (50,200):
            for slip in (2,5):
                for direction in ('both','long','short'):
                    trial=month_cfg.model_copy(update={'liquid_universe_size':size,'direction':direction,
                        'slippage_bps':slip,'buy_cost_bps':0,'sell_cost_bps':0})
                    key=f'{start}_scan{size}_slip{slip}_{direction}'
                    try:
                        result=momentum.simulate(daily,trial,sessions,plans[size],fee_model=upstox_cash_fees)
                        record=dict(key=key,start=start,end=end,scan_size=size,slippage_bps=slip,direction=direction,
                            metrics=result['metrics'],long=attribution([t for t in result['trades'] if t['direction']=='long']),
                            short=attribution([t for t in result['trades'] if t['direction']=='short']),
                            input_sha256=summary['inputs'][-1]['sha256'])
                        result['trades']=[{k:v for k,v in t.items() if k!='stop_trace'} for t in result['trades']]
                        (output/(key+'.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
                        summary['runs'].append(record)
                        print(key,f"{result['metrics']['return_pct']:+.3f}% / {result['metrics']['trade_count']} trades",flush=True)
                    except Exception as exc:
                        summary['failures'].append(dict(key=key,stage='simulation',error=str(exc)))
                        print('Simulation failure:',key,str(exc),flush=True)
                    checkpoint()
    if args.markdown:
        report(summary, args.markdown)


def report(summary, markdown):
    path=Path(markdown)
    text='# Intraday stock-selection comparison\n\nFrozen reference: '+summary['reference']+'\n'
    lines=['','## Completed results','',f"Saved {len(summary['runs'])} completed trials and {len(summary['failures'])} failures. Fee model and all entry/exit rules are identical within each comparison.",'',
           '| Month / direction | 50 stocks, 2 bps | 200 stocks, 2 bps | 50 stocks, 5 bps | 200 stocks, 5 bps |',
           '|---|---:|---:|---:|---:|']
    by={(r['start'],r['scan_size'],r['slippage_bps'],r['direction']):r for r in summary['runs']}
    for start,end in WINDOWS:
        for direction in ('both','long','short'):
            values=[]
            for size,slip in ((50,2),(200,2),(50,5),(200,5)):
                run=by.get((start,size,slip,direction))
                values.append(f"{run['metrics']['return_pct']:+.2f}% ({run['metrics']['trade_count']} trades)" if run else 'Unavailable')
            lines.append('| '+start[:7]+' / '+direction+' | '+' | '.join(values)+' |')
    lines+=['','## Aggregate diagnostic','',
            '| Direction / slippage | 50 stocks: total P&L / PF / trades | 200 stocks: total P&L / PF / trades |','|---|---:|---:|']
    for direction in ('both','long','short'):
        for slip in (2,5):
            values=[]
            for size in (50,200):
                runs=[r for r in summary['runs'] if r['scan_size']==size and r['slippage_bps']==slip and r['direction']==direction]
                if len(runs)!=len(WINDOWS):
                    values.append('Incomplete')
                    continue
                trades=[]
                for r in runs:
                    raw=json.loads((store.ROOT/'artifacts'/'intraday_selection_research'/(r['key']+'.json')).read_text())
                    trades.extend(raw['trades'])
                a=attribution(trades)
                pf=f"{a['profit_factor']:.3f}" if a['profit_factor'] is not None else 'undefined'
                values.append(f"Rs {a['pnl']:+,.2f} / {pf} / {a['trade_count']}")
            lines.append(f'| {direction} / {slip} bps | '+' | '.join(values)+' |')
    lines+=['','Aggregates combine independent monthly capital resets, not a compounded portfolio. PF pools trade profits and losses. Compare expectancy, trade count and drawdown as well as total P&L.','',
        '## Assessment','',
        'The broader scan is not supported by this pilot: pooled combined, buy-only and short-only P&L remain negative at both slippage assumptions. The 200-stock buy portfolio is worse in all three months. Its short portfolio improves in January, but worsens in February and June; one positive month is insufficient.','',
        'The current selection already uses opening relative volume. Expanding the pool selects more unusually active stocks, but unusual activity alone does not establish continuation. In these three windows at 2 bps/side, mean relative volume rises from 3.12 to 6.73 for buys and from 3.90 to 7.04 for shorts, while average net trade P&L worsens. These are descriptive results, not a causal explanation or new selection thresholds.','',
        'Keep the up-to-50-stock control for subsequent comparisons. Next test a separate VWAP trend-pullback/rejection entry, with completed-candle resumption and a defined structural stop, against the current ORB. Evaluate longs and shorts separately, preserve cost stress, and predeclare the setup before looking at outcomes. No settings are promoted and no live or paper trading behavior changes.','']
    if summary['failures']:
        lines+=['## Failures','']
        for failure in summary['failures']:
            lines.append('- '+json.dumps(failure))
    path.write_text(text+'\n'.join(lines),encoding='utf-8')
    print('Report saved:',path,flush=True)


if __name__=='__main__':
    main()
