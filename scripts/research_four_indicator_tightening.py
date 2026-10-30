"""Five predeclared entry comparisons on the frozen one-year equity snapshot."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.strategies.four_indicator_intraday import completed_trend, pullback_signals
from scripts.research_four_indicator_5m import fast_values, simulate, save

VARIANTS = {
    'baseline': 'Original entries; corrected Upstox Plus costs',
    'trend_15m': 'Original entries + completed 15-minute Supertrend up',
    'pullback': 'All-four setup + SMA20 pullback + bullish resumption within 30 minutes',
    'one_per_day': 'Original entries; maximum one filled entry per stock per day',
    'combined': 'Pullback entry + completed 15-minute trend + one entry per stock per day',
}
BLOCKS = [('2025-10-29','2026-02-28'),('2026-03-01','2026-06-30'),('2026-07-01','2026-10-28')]


def run(source, output):
    import numpy as np
    from core.execution import upstox
    output.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[1]
    files=['core/execution/upstox.py','core/strategies/four_indicator_intraday.py',
           'scripts/research_four_indicator_5m.py','scripts/research_four_indicator_tightening.py']
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    eligible=json.loads((source/'eligibility.json').read_text(encoding='utf-8'))
    included=set(eligible['included'])
    stocks=sorted([s for s in manifest['stocks'] if s['symbol'] in included],key=lambda x:x['symbol'])
    cfg={k:v for k,v in manifest['config'].items() if k not in ('buy_cost_bps','sell_cost_bps')}
    cfg.update(fee_model=upstox.MODEL,slippage_bps=10)
    plan=dict(config=cfg,variants=VARIANTS,blocks=BLOCKS,input_directory=str(source.resolve()),
              input_manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
              eligibility_sha256=hashlib.sha256((source/'eligibility.json').read_bytes()).hexdigest(),
              source_hashes=hashes,eligible_symbols=len(stocks),
              fee_policy='Shared Upstox Plus. Reserve delivery buy charges; refund the difference only on same-day exit. Delivery sells include DP.',
              limitations=['All periods have already been inspected; chronological blocks are retrospective diagnostics, not untouched validation.',
                'Current membership survivorship bias; cached OHLCV cannot validate bid/ask or market impact.',
                'The current Plus tariff is applied retrospectively, not reconstructed historical account tariffs.',
                'Overnight positions carry; Supertrend reversal exits and final liquidation remain unchanged.'])
    path=output/'frozen-plan.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) != plan:
        raise ValueError('Frozen plan changed; choose a new output directory.')
    save(path,plan)
    n=len(manifest['days'])*75
    shape=(n,len(stocks))
    openings,closes,ranks=[np.empty(shape) for _ in range(3)]
    signals={key:np.empty(shape,dtype=bool) for key in ('baseline','trend_15m','pullback','combined')}
    exits=np.empty(shape,dtype=bool)
    zone=timezone(timedelta(hours=5,minutes=30))
    offset=len(manifest['warmup_days'])*75
    stamps=None
    for j,stock in enumerate(stocks):
        raw=gzip.decompress((source/stock['file']).read_bytes())
        if hashlib.sha256(raw).hexdigest()!=stock['sha256']:
            raise ValueError('Frozen candle checksum mismatch: '+stock['symbol'])
        payload=json.loads(raw)
        rows=np.array(payload['rows'])
        current=rows[offset:,0].astype('int64')
        if stamps is None:
            stamps=current
            dates=[datetime.fromtimestamp(t/1000,zone).date().isoformat() for t in rows[:,0]]
        elif not np.array_equal(current,stamps):
            raise ValueError('Stock does not match the common session clock.')
        r1=np.array([2*sum(payload['previous'][d][k] for k in ('high','low','close'))/3-payload['previous'][d]['low'] for d in dates])
        rsi,st,up,band=fast_values(rows,cfg['bollinger_multiplier'])
        base=up & (rows[:,4]>st) & (rsi>cfg['rsi_threshold']) & (rows[:,4]>r1) & (rows[:,4]>band)
        higher=completed_trend(rows,fast_values)
        pullback=pullback_signals(rows,base,rsi,st,up,r1)
        for key,signal in [('baseline',base),('trend_15m',base & higher),('pullback',pullback),('combined',pullback & higher)]:
            signals[key][:,j]=signal[offset-1:-1]
            signals[key][0,j]=False
        openings[:,j],closes[:,j]=rows[offset:,1],rows[offset:,4]
        exits[:,j]=~up[offset-1:-1]
        ranks[:,j]=rows[offset-1:-1,4]*rows[offset-1:-1,5]
        if j%50==0: print(f'Indicators {j+1}/{len(stocks)}',flush=True)
    summaries=[]
    for key,label in VARIANTS.items():
        settings=dict(cfg,name=label,one_entry_per_day=key in ('one_per_day','combined'))
        result=simulate(openings,closes,signals['baseline' if key=='one_per_day' else key],exits,ranks,stamps,
                        [s['symbol'] for s in stocks],settings)
        result.update(variant=key,description=label,config=settings,source_hashes=hashes,
                      input_manifest_sha256=plan['input_manifest_sha256'],eligible_symbols=len(stocks),
                      excluded_symbols=len(eligible['excluded']),assumptions=plan['limitations'])
        for trade in result['trades']:
            for field in ('entry','exit','signal'):
                trade[field+'_datetime']=datetime.fromtimestamp(trade[field+'_timestamp']/1000,zone).isoformat()
        blocks=[]
        start_equity=cfg['capital']
        for first,last in BLOCKS:
            curve=[p for p in result['curve'] if first<=datetime.fromtimestamp(p['timestamp']/1000,zone).date().isoformat()<=last]
            end_equity=curve[-1]['equity']
            blocks.append(dict(start=first,end=last,start_equity=start_equity,ending_equity=end_equity,
                               return_pct=(end_equity/start_equity-1)*100))
            start_equity=end_equity
        result['chronological_blocks']=blocks
        folder=output/key
        folder.mkdir(exist_ok=True)
        save(folder/'results.json',result)
        with (folder/'trades.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(result['trades'][0]) if result['trades'] else ['symbol'])
            writer.writeheader();writer.writerows(result['trades'])
        audit=validate(result,cfg['capital'])
        save(folder/'validation.json',audit)
        summary=dict(variant=key,description=label,**result['metrics'],chronological_blocks=blocks,validation=audit)
        summaries.append(summary)
        print(json.dumps(summary),flush=True)
    if any(hashlib.sha256((root/name).read_bytes()).hexdigest()!=value for name,value in hashes.items()):
        raise ValueError('Research source changed during the comparison.')
    save(output/'comparison.json',dict(plan=plan,results=summaries))
    write_report(output,summaries,plan)
    return summaries


def validate(result,capital):
    from core.execution.upstox import equity_charges
    from math import isclose
    fees=0
    for trade in result['trades']:
        entry,exit=trade['entry_datetime'][:10],trade['exit_datetime'][:10]
        intraday=entry==exit
        expected=equity_charges(trade['entry'],trade['quantity'],'buy',entry,intraday=intraday)['total']
        expected+=equity_charges(trade['exit'],trade['quantity'],'sell',exit,intraday=intraday)['total']
        if not isclose(expected,trade['fees'],abs_tol=1e-7): raise ValueError('Trade fee mismatch.')
        fees+=expected
    if not isclose(fees,result['metrics']['modeled_fees'],abs_tol=.01): raise ValueError('Aggregate fee mismatch.')
    if not isclose(capital+sum(t['pnl'] for t in result['trades']),result['metrics']['final_equity'],abs_tol=.01):
        raise ValueError('Trade P&L does not reconcile.')
    if result['config']['one_entry_per_day']:
        entries=[(t['symbol'],t['entry_datetime'][:10]) for t in result['trades']]
        if len(entries)!=len(set(entries)): raise ValueError('Duplicate stock/day entry.')
    return dict(status='passed',trades_verified=len(result['trades']),checks=['Per-trade and aggregate Upstox Plus charges','Cash/P&L reconciliation','Daily entry cap when enabled'])


def write_report(output,results,plan):
    html='<!doctype html><meta charset="utf-8"><title>Four-indicator entry comparison</title><style>body{font:16px system-ui;max-width:1300px;margin:40px auto;padding:0 20px;color:#192837}table{border-collapse:collapse;width:100%;margin:24px 0}th,td{padding:10px;border:1px solid #d5dce1;text-align:right}th{background:#edf4f3}td:first-child,th:first-child{text-align:left}</style>'
    html+='<h1>Four-indicator entry comparison</h1><p>29 October 2025–28 October 2026 · 705 stocks · INR 1,000,000 starting capital · 10 positions · shared Upstox Plus model · 10 bps slippage per side.</p>'
    html+='<p>Five fixed comparisons; RSI >65, Bollinger 2.5 and Supertrend exits retained. Each portfolio starts with its own capital and carries positions and equity across the year.</p><table><tr><th>Variant</th><th>Return %</th><th>Max DD %</th><th>Trades</th><th>Win %</th><th>PF</th><th>Fees INR</th><th>Slippage INR</th></tr>'
    for row in results:
        cells=[row[k] for k in ('return_pct','max_drawdown_pct','trade_count','win_rate','profit_factor','modeled_fees','modeled_slippage')]
        html+='<tr><td><a href="'+row['variant']+'/results.json">'+escape(row['variant'])+'</a></td>'+''.join('<td>'+escape(f'{x:,.2f}' if isinstance(x,float) else str(x))+'</td>' for x in cells)+'</tr>'
    html+='</table><h2>Chronological diagnostics</h2><p>The entire year was previously inspected. These are continuous-portfolio block returns, not independent or untouched tests.</p><table><tr><th>Variant</th>'+''.join('<th>'+first+'–'+last+'</th>' for first,last in BLOCKS)+'</tr>'
    for row in results:
        html+='<tr><td>'+row['variant']+'</td>'+''.join('<td>'+f'{b["return_pct"]:.2f}%'+'</td>' for b in row['chronological_blocks'])+'</tr>'
    html+='</table><h2>Declared rules</h2><ul>'+''.join('<li>'+escape(k+': '+v)+'</li>' for k,v in VARIANTS.items())+'</ul><p>Pullback: an all-four setup arms a 30-minute window; a later bar touches SMA20 while Supertrend remains up; a still-later bullish close exceeds the previous high, SMA20, Supertrend and R1 with RSI >65. Setups expire at session end. Signals fill at the next five-minute open. Fifteen-minute trend values appear only after the full candle closes.</p>'
    html+='<h2>Limitations</h2><ul>'+''.join('<li>'+escape(x)+'</li>' for x in plan['limitations'])+'</ul><p>'+escape(plan['fee_policy'])+'</p><p><a href="comparison.json">Complete comparison</a> · <a href="frozen-plan.json">Frozen plan and source/input hashes</a></p>'
    (output/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('artifacts/four_indicator_5m_year_20261029'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/four_indicator_tightening_20261029'))
    args=parser.parse_args()
    run(args.input,args.output)
