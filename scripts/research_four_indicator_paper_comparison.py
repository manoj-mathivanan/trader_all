"""Read-only paper counterfactuals and predeclared RS robustness diagnostics."""
import argparse
from collections import defaultdict
from datetime import date
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys
import csv

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs
from scripts.research_four_indicator_selection import Plan, SelectionFeatures, simulate, save
from core.execution.upstox import equity_charges


STARTS = ['2026-04-10','2026-05-04','2026-06-01','2026-07-01','2026-08-03','2026-09-01']
RANKS = [Plan(),Plan('rs63_rank',rank_sessions=63),Plan('rs126_rank',rank_sessions=126)]
PAPER_PLANS = [(p,1) for p in RANKS]+[
    (Plan('baseline_75pct_slot'),.75),
    (Plan('rs63_75pct_slot',rank_sessions=63),.75),
    (Plan('rs126_75pct_slot',rank_sessions=126),.75),
    (Plan('sector_cap_30',sector_cap_pct=30),1)]
SLIPPAGE = [10,25,50]


def concentration(result):
    by_stock = defaultdict(float)
    for t in result['trades']: by_stock[t['symbol']] += t['pnl']
    ledger = result.get('ledger',{})
    for s,p in ledger.get('positions',{}).items():
        by_stock[s] += p['quantity']*ledger['marks'][s]-p['entry_cost']
    positive = sum(v for v in by_stock.values() if v > 0)
    ordered = sorted(by_stock.items(),key=lambda x:x[1],reverse=True)
    return dict(stock_pnl=dict(ordered),top_five=ordered[:5],bottom_five=ordered[-5:],
                gross_positive_stock_pnl=positive,
                top_stock_share_of_positive_pct=max(by_stock.values())/positive*100 if positive else None,
                top_three_share_of_positive_pct=sum(v for _,v in ordered[:3] if v > 0)/positive*100 if positive else None,
                net_pnl_excluding_top_three_stocks=result['metrics']['net_pnl']-sum(v for _,v in ordered[:3] if v > 0))


def config_for(portfolio):
    c=portfolio['config']
    keys=('capital','max_positions','rsi_threshold','bollinger_multiplier','slippage_bps','buy_cost_bps','sell_cost_bps')
    return fs.SwingConfig(start=portfolio['start_session'],end=portfolio['ledger']['last_session'],
                          rule_set=c['rule_set'],coverage_mode='available_history',**{k:c[k] for k in keys})


def infer_fee_schedule(portfolio):
    schedule=[]
    for cycle in portfolio['cycles']:
        orders=[o for o in portfolio['ledger']['orders'] if o.get('job_id')==cycle['job_id']]
        if not orders: raise ValueError('Cannot infer a fee model from an empty paper cycle.')
        modes=[]
        for mode in ('legacy_bps','upstox_plus'):
            expected=[o['price']*o['quantity']*cycle['config']['buy_cost_bps' if o['side']=='BUY' else 'sell_cost_bps']/10000
                      if mode=='legacy_bps' else equity_charges(o['price'],o['quantity'],o['side'].lower(),o['date'])['total'] for o in orders]
            if all(abs(o['fees']-v)<1e-6 for o,v in zip(orders,expected)): modes.append(mode)
        if len(modes)!=1: raise ValueError('Paper fee model cannot be uniquely reconciled.')
        schedule.append(dict(start=cycle['start'],end=cycle['end'],mode=modes[0],verified_orders=len(orders)))
    return schedule


def verify_paper(result,portfolio):
    ledger=portfolio['ledger']
    if result['curve']!=ledger['curve']: raise ValueError('Recorded paper equity curve did not reproduce.')
    for k,v in portfolio['metrics'].items():
        if result['metrics'].get(k)!=v: raise ValueError('Recorded paper metric mismatch: '+k)
    if result['ledger']['cash']!=ledger['cash']: raise ValueError('Recorded cash mismatch.')
    if set(result['ledger']['positions'])!=set(ledger['positions']): raise ValueError('Recorded holdings mismatch.')
    keys=('entry','entry_date','quantity','entry_fee','entry_cost','signal_date')
    for s,p in ledger['positions'].items():
        if any(result['ledger']['positions'][s][k]!=p[k] for k in keys): raise ValueError('Recorded position mismatch: '+s)
    keys=('symbol','side','date','price','quantity','fees')
    if [{k:o[k] for k in keys} for o in result['orders']] != [{k:o[k] for k in keys} for o in ledger['orders']]:
        raise ValueError('Recorded paper orders did not reproduce.')
    return dict(equity_curve=True,metrics=True,cash=True,holdings=True,orders=True)


def summarize(result,scope,variant,cfg,scale):
    ledger=result.get('ledger',{})
    realized=sum(t['pnl'] for t in result['trades'])
    return dict(scope=scope,variant=variant,start=str(cfg.start),end=str(cfg.end),slippage_bps=cfg.slippage_bps,
                slot_scale=scale,**result['metrics'],realized_pnl=realized,
                unrealized_pnl=result['metrics']['net_pnl']-realized,open_positions=len(ledger.get('positions',{})),
                turnover_multiple=result['metrics']['traded_notional']/cfg.capital,
                concentration=concentration(result))


def table(rows,columns):
    page='<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(k.replace('_',' '))+'</th>' for k in columns)+'</tr></thead><tbody>'
    for r in rows:
        page+=('<tr class="base">' if r['variant']=='baseline' else '<tr>')+''.join(
            '<td>'+escape(f'{r[k]:,.2f}' if isinstance(r[k],float) else str(r[k]) if r[k] is not None else '—')+'</td>' for k in columns)+'</tr>'
    return page+'</tbody></table></div>'


def report(output,plan,rows,parity):
    paper=[r for r in rows if r['scope']=='recorded_paper' and r['slippage_bps']==10]
    starts=[r for r in rows if r['scope']=='start_sensitivity']
    base={r['start']:r for r in starts if r['variant']=='baseline'}
    stability={}
    for name in ('rs63_rank','rs126_rank'):
        subset=[r for r in starts if r['variant']==name]
        stability[name]=dict(start_count=len(subset),higher_return_count=sum(r['return_pct']>base[r['start']]['return_pct'] for r in subset),
                            lower_drawdown_count=sum(r['max_drawdown_pct']<base[r['start']]['max_drawdown_pct'] for r in subset),
                            higher_return_and_lower_drawdown_count=sum(r['return_pct']>base[r['start']]['return_pct'] and r['max_drawdown_pct']<base[r['start']]['max_drawdown_pct'] for r in subset),
                            worst_return_difference_pp=min(r['return_pct']-base[r['start']]['return_pct'] for r in subset))
    save(output/'comparison.json',dict(plan=plan,results=rows,baseline_parity=parity,start_stability=stability))
    cols=['scope','variant','start','end','slippage_bps','slot_scale','return_pct','max_drawdown_pct','final_equity',
          'trade_count','open_positions','average_exposure_pct','modeled_fees','modeled_slippage','realized_pnl','unrealized_pnl']
    with (output/'comparison.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    p=plan['paper']
    primary=next(r for r in paper if r['variant']=='baseline')
    page=('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
          '<title>Paper comparison and RS robustness</title><style>body{font:15px/1.55 system-ui;color:#203341;margin:32px}'
          'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5dd;padding:8px;text-align:right}'
          'th{background:#eef3f6}.scroll{overflow:auto}.base{background:#eef6ef}p{max-width:1100px}</style>'
          '<h1>Four-indicator paper comparison and RS robustness</h1>'
          f'<p>Recorded paper: {escape(p["name"])} · {p["start"]} to {p["end"]} · {p["sessions"]} sessions · INR 10 lakh.</p>'
          f'<p>The recorded baseline was reproduced exactly: equity INR {primary["final_equity"]:,.2f}, return {primary["return_pct"]:.2f}%. '
          'Comparison portfolios start in cash on the same date and retain open positions at the same closing marks. No forced final sale or estimated exit fees are added.</p>'
          '<p>This October paper record is shorter than a full month. It includes historical replay before creation; alternative rankings are hypothetical reruns, not orders that were actually paper traded or untouched validation.</p>'
          '<p>Recorded fees changed from flat 10 bps per side through 28 October to detailed Upstox Plus on 29 October. The direct comparison reproduces this schedule for every variant; the standardized comparison applies Plus to the entire interval.</p>'
          '<h2>Same paper dates and standard execution assumptions</h2>')
    page+=table(paper,['variant','return_pct','max_drawdown_pct','final_equity','trade_count','open_positions','average_exposure_pct','realized_pnl','unrealized_pnl'])
    page+='<h2>Same paper dates with detailed Plus charges throughout</h2>'
    page+=table([r for r in rows if r['scope']=='standardized_paper' and r['slippage_bps']==10],['variant','return_pct','max_drawdown_pct','final_equity','modeled_fees','open_positions'])
    page+='<h2>Different starting dates in the later historical period</h2><p>All end on 9 October 2026 and liquidate at the final close. These overlapping cash-start windows are diagnostics, not independent samples. Their returns are not annualized.</p>'
    page+=table(starts,['variant','start','return_pct','max_drawdown_pct','average_exposure_pct','trade_count'])
    page+='<h2>Execution stress and smaller positions</h2><p>10, 25 and 50 basis points per side represent 0.10%, 0.25% and 0.50% slippage. The same broker/tax model applies to all; fees and slippage are already deducted. A 0.75 slot scale reduces each cash slot by 25%; this is a fixed exposure experiment, not calibrated equal-risk sizing.</p>'
    page+=table([r for r in rows if r['scope']!='start_sensitivity'],['scope','variant','slippage_bps','slot_scale','return_pct','max_drawdown_pct','average_exposure_pct','modeled_fees','modeled_slippage'])
    page+='<h2>Profit concentration</h2><p>Contributions include realized trade P&amp;L and marked open holdings, grouped by stock. Excluding winners is arithmetic attribution; it does not rerun the portfolio without those stocks.</p>'
    for r in rows:
        if r['scope'] in ('historical_stress','recorded_paper') and r['slippage_bps']==10 and r['slot_scale']==1 and r['variant'] in ('baseline','rs63_rank','rs126_rank'):
            c=r['concentration']
            top=', '.join(f'{s}: INR {v:,.0f}' for s,v in c['top_five'])
            share=c['top_three_share_of_positive_pct']
            page+=f'<p><b>{escape(r["scope"]+" / "+r["variant"])}</b>: '+escape(top)+f'. Top three share of positive stock P&amp;L: {share:.2f}%.'+'</p>' if share is not None else f'<p>{escape(r["scope"]+" / "+r["variant"])}: no positive stock contributions.</p>'
    page+='<h2>Method and limitations</h2>'+''.join('<p>'+escape(x)+'</p>' for x in plan['methodology'])+'</html>'
    (output/'report.html').write_text(page,encoding='utf-8')


def run(paper_snapshot,historical_snapshot,output):
    production=json.loads(gzip.decompress(paper_snapshot.read_bytes()))
    item=production['records']['indicator_all4_20261012']
    portfolio,frozen=item['portfolio'],item['frozen']
    if fs.digest(frozen)!=portfolio['cycles'][-1]['input_sha256']: raise ValueError('Paper frozen checksum mismatch.')
    if portfolio.get('config_history'): raise ValueError('Configuration changes require a scheduled-config replay; do not use a static rerun.')
    cfg=config_for(portfolio)
    fee_schedule=infer_fee_schedule(portfolio)
    historic=json.loads(gzip.decompress(historical_snapshot.read_bytes()))
    if fs.digest(historic['frozen'])!=historic['report']['input_sha256']: raise ValueError('Historical checksum mismatch.')
    root=Path(__file__).resolve().parents[1]
    files=['scripts/research_four_indicator_paper_comparison.py','scripts/research_four_indicator_selection.py',
           'core/research/four_indicator_swing.py','core/strategies/four_indicator.py',
           'core/strategies/four_indicator_allocation.py','core/execution/upstox.py']
    plan=dict(paper_snapshot_sha256=hashlib.sha256(paper_snapshot.read_bytes()).hexdigest(),
              historical_snapshot_sha256=hashlib.sha256(historical_snapshot.read_bytes()).hexdigest(),
              paper_input_sha256=fs.digest(frozen),historical_input_sha256=fs.digest(historic['frozen']),
              paper=dict(id=portfolio['id'],name=portfolio['config']['name'],start=str(cfg.start),end=str(cfg.end),
                         sessions=len(portfolio['ledger']['curve']),created_at=portfolio['created_at'],replay_through=portfolio.get('replay_through'),config=portfolio['config']),
              starting_dates=STARTS,slippage_bps=SLIPPAGE,paper_plans=[dict(plan=p.__dict__,slot_scale=s) for p,s in PAPER_PLANS],fee_schedule=fee_schedule,
              source_sha256={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},
              methodology=[
                  'Production data was exported under a read-only repeatable-read transaction; no refresh, cycle, configuration edit, deployment or order was submitted.',
                  'The current October paper record spans 12–29 October 2026, not a complete month. It was created on 29 October and includes historical replay, not a month of prospective observation.',
                  'Paper baseline must reproduce the recorded curve, existing metrics, cash, orders and holdings exactly. Alternatives use identical frozen stocks, signal thresholds, costs and marked terminal positions.',
                  'Recorded orders reconcile to legacy flat basis-point fees through 28 October and detailed Plus on 29 October. Direct counterfactuals reproduce this transition; standardized paper results use Plus throughout. No historical recorded fees are rewritten.',
                  'Historical starts are fixed at 10 April, 4 May, 1 June, 1 July, 3 August and 1 September 2026, all ending 9 October. These overlapping previously inspected windows are not independent or untouched validation.',
                  'Historical stock snapshots and the newer paper snapshot differ in date coverage and eligible universe. Each variant is compared only to its own same-input baseline.',
                  'RS63/RS126 rank already eligible signals by stock return relative to Nifty on the same endpoint dates. Entry conditions and Supertrend exits remain unchanged.',
                  'Execution stress uses 10/25/50 bps slippage per side. Broker charges remain the same. Fixed 75% cash slots test lower exposure; they are not retrospectively optimized to match drawdown. A baseline at the same 75% slot size separates lower exposure from ranking effects; this control was added after the first run, not an untouched test.',
                  'Profit concentration aggregates closed P&L and open marked contributions per stock; removing top winners arithmetically does not rerun allocation.',
                  'Current membership, sector classifications, daily-bar timing, omitted dividends and fixed broker tariff limitations remain. No current paper settings are changed.',
              ])
    output.mkdir(parents=True,exist_ok=True)
    path=output/'frozen-plan.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=plan: raise ValueError('Plan changed; choose a new output directory.')
    save(path,plan)
    records=[]
    signals=fs.features(frozen['datasets'],lambda s:print('Paper: '+s,flush=True),**fs.stored_parameters(portfolio['config']))
    features=SelectionFeatures(frozen['datasets'],production['index']['bars'],frozen['universe']['instruments'],cfg)
    parity={}
    for bps in SLIPPAGE:
        settings=cfg.model_copy(update={'slippage_bps':bps})
        for p,scale in PAPER_PLANS:
            result=simulate(frozen['datasets'],signals,settings,features,p,liquidate=False,slot_scale=scale,fee_schedule=fee_schedule)
            if p.name=='baseline' and bps==10: parity['recorded_paper']=verify_paper(result,portfolio)
            records.append(summarize(result,'recorded_paper',p.name,settings,scale))
            save(output/f'paper-{p.name}-{bps}bps.json',result)
            print(f'paper/{p.name}/{bps}bps: {result["metrics"]["return_pct"]:.2f}% return; {result["metrics"]["max_drawdown_pct"]:.2f}% DD',flush=True)
    for p,scale in PAPER_PLANS:
        result=simulate(frozen['datasets'],signals,cfg,features,p,liquidate=False,slot_scale=scale)
        records.append(summarize(result,'standardized_paper',p.name,cfg,scale))
        save(output/f'standardized-paper-{p.name}.json',result)
    data=historic['frozen']['datasets']
    base=cfg.model_copy(update={'start':date(2026,4,10),'end':date(2026,10,9)})
    signals=fs.features(data,lambda s:print('Historical: '+s,flush=True),**fs.stored_parameters(base.model_dump()))
    features=SelectionFeatures(data,historic['index'],historic['frozen']['universe']['instruments'],base)
    for start in STARTS:
        settings=base.model_copy(update={'start':date.fromisoformat(start)})
        for p in RANKS:
            result=simulate(data,signals,settings,features,p)
            if p.name=='baseline':
                expected=fs.simulate(data,signals,settings,fs.RULES[3],instruments=historic['frozen']['universe']['instruments'])
                if result['metrics']!=expected['metrics'] or result['curve']!=expected['curve']: raise ValueError('Historical baseline mismatch: '+start)
            records.append(summarize(result,'start_sensitivity',p.name,settings,1))
            save(output/f'start-{start}-{p.name}.json',result)
            print(f'start {start}/{p.name}: {result["metrics"]["return_pct"]:.2f}% return',flush=True)
    for bps in SLIPPAGE:
        settings=base.model_copy(update={'slippage_bps':bps})
        for p,scale in PAPER_PLANS:
            if p.name=='sector_cap_30': continue
            result=simulate(data,signals,settings,features,p,slot_scale=scale)
            records.append(summarize(result,'historical_stress',p.name,settings,scale))
            save(output/f'history-{p.name}-{bps}bps.json',result)
            print(f'history/{p.name}/{bps}bps: {result["metrics"]["return_pct"]:.2f}% return',flush=True)
    save(output/'baseline-parity.json',parity)
    report(output,plan,records,parity)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paper-snapshot',type=Path,default=Path('artifacts/four_indicator_paper_comparison_20261030/production_snapshot.json.gz'))
    parser.add_argument('--historical-snapshot',type=Path,default=Path('artifacts/four_indicator_year_20261025/frozen.json.gz'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/four_indicator_paper_comparison_20261030/results'))
    args=parser.parse_args()
    run(args.paper_snapshot,args.historical_snapshot,args.output)
