"""Package the selected historical candidate and its unresolved-call diagnostics."""
import csv
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.research import corporate_actions,market_history,store
from scripts.research_stock_call_accuracy import export_csv,summarize
from scripts.research_strategy_call_returns import OUT,PERIODS


def main():
    report=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    selected=report['selected']
    if selected is None:
        raise ValueError('No candidate met the declared sample requirements.')
    with (OUT/(selected['name']+'_calls.csv')).open(encoding='utf-8-sig',newline='') as f:
        calls=list(csv.DictReader(f))
    for call in calls:
        for k in ('entry','exit','return_pct','unrealized_return_pct'):
            if call.get(k):
                call[k]=float(call[k])
        if call.get('holding_sessions'):
            call['holding_sessions']=int(call['holding_sessions'])
    prices={}
    instruments={i['symbol']:i for i in store.read('universes/niftytotalmarket')['instruments']}
    coverage={x['symbol']:x for x in report['coverage']}
    for symbol in {c['symbol'] for c in calls}:
        item=instruments[symbol]
        rows,_=market_history.prepare(item,store.read('bars/'+item['isin']),reference=report['history_reference'])
        if market_history.digest(rows)!=coverage[symbol]['history']['derived_sha256']:
            raise ValueError('Inputs changed since comparison: '+symbol)
        rows=corporate_actions.adjusted_bars(rows,rows[-1]['date'])
        prices[symbol]={end:next((b['close'] for b in reversed(rows) if b['date']<=end),None)
                        for _,end in PERIODS.values()}
    marks={}
    for label,(start,end) in PERIODS.items():
        returns,unresolved=[],[]
        for c in calls:
            if not start<=c['signal_date']<=end or not c.get('entry_date') or c['entry_date']>end:
                continue
            if c.get('exit_date') and c['exit_date']<=end:
                returns.append(c['return_pct'])
            else:
                mark=prices[c['symbol']][end]
                value=(mark/c['entry']-1)*100
                returns.append(value)
                unresolved.append(value)
        marks[label]=dict(entered_calls=len(returns),unresolved_calls=len(unresolved),
                         realized_and_marked_mean_pct=sum(returns)/len(returns) if returns else None,
                         unresolved_mean_mark_pct=sum(unresolved)/len(unresolved) if unresolved else None,
                         note='Diagnostic valuation at period end; it does not force an exit or change the strategy.')
    closed=[c for c in calls if c['status'] in ('correct','incorrect','flat')]
    winners=[c['return_pct'] for c in closed if c['status']=='correct']
    losses=[c['return_pct'] for c in closed if c['status']=='incorrect']
    package=dict(name=selected['name'],selection_reason=report['protocol']['objective'],
                 engine_config=selected['config'],research_overrides=report['protocol'],results=selected,
                 mean_winning_call_pct=sum(winners)/len(winners) if winners else None,
                 mean_losing_call_pct=sum(losses)/len(losses) if losses else None,
                 period_end_marks=marks,
                 assessment='Highest selection-period mean among the declared eligible candidates; recent closed-call performance must be inspected before calling it robust.')
    (OUT/'selected_strategy.json').write_text(json.dumps(package,indent=2),encoding='utf-8')
    rows=[]
    for symbol in coverage:
        sample=[c for c in calls if c['symbol']==symbol]
        rows.append(dict(symbol=symbol,coverage_status=coverage[symbol]['status'],**summarize(sample)))
    export_csv(OUT/'selected_strategy_stocks.csv',rows)
    print(json.dumps({k:package[k] for k in ('name','mean_winning_call_pct','mean_losing_call_pct','period_end_marks')},indent=2))


if __name__=='__main__':
    main()
