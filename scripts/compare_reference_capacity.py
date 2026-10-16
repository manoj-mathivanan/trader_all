"""Print controlled risk/universe experiments; never write report files."""
import argparse,json,sys,gc
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import reference_universe,banana_reference,strategy_presets
from core.research.config import BacktestConfig

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pattern',choices=['vcp','blue_sky','multiyear'])
    parser.add_argument('--risk',type=float,choices=[.5,1])
    parser.add_argument('--universe',choices=['frozen','expanded_rs_only','expanded_trading'])
    parser.add_argument('--capital',type=float,default=1000000)
    parser.add_argument('--source-prefix',help='Prefix of previously captured visible Banana ledger JSON files.')
    args=parser.parse_args()
    base,expanded,coverage=reference_universe.cached_expansion('b4584ee01955')
    print(json.dumps({'coverage':{k:v for k,v in coverage.items() if k!='added_histories'}}),flush=True)
    presets=[p for p in strategy_presets.available() if p.get('backtest_defaults') and p['pattern']!='ipo']
    for preset in presets:
        if args.pattern and preset['pattern']!=args.pattern:continue
        source=None
        if args.source_prefix:
            raw=json.loads(Path(args.source_prefix+preset['pattern']+'.json').read_text(encoding='utf-8'))
            source={(a[0].split('\n')[0],datetime.strptime(a[2].split('\n')[0],'%d %b %y').date().isoformat()) for a in raw}
            if len(source)!=len(raw):raise ValueError('Source ledger contains duplicate entry identities.')
        for label,trade_data,ranking in [('frozen',base,None),('expanded_rs_only',base,expanded),('expanded_trading',expanded,None)]:
            if args.universe and label!=args.universe:continue
            for risk in ([args.risk] if args.risk else [1,.5]):
                cfg=BacktestConfig(**{**preset['backtest_defaults'],'risk_pct':risk,
                    'capital':args.capital,'reference_same_day':'conservative','slippage_bps':10},
                    start='2020-01-01',end='2026-09-30',acknowledge_limitations=True)
                result=banana_reference.simulate(trade_data,cfg,rs_data=ranking)
                m=result['metrics'];m['xirr_pct']=((m['final_equity']/cfg.capital)**(365/(cfg.end-cfg.start).days)-1)*100
                counts=result['audit_summary']
                matches=None
                if source is not None:
                    entries={(t['symbol'],t['entry_date']) for t in result['trades']}
                    entries.update((s,t['entry_date']) for s,t in result['open_positions'].items())
                    matches=dict(source_trades=len(source),source_entries_in_trading_universe=sum(s in trade_data for s,d in source),
                                 exact_entry_matches=len(entries&source))
                print(json.dumps(dict(pattern=cfg.pattern,universe=label,risk_pct=risk,stocks=len(trade_data),
                    rs_population_max=max(a['rs_population'] for a in result['candidate_audit']),metrics=m,
                    opportunities=len(result['candidate_audit']),technical_eligible=sum(a['technical_eligible'] for a in result['candidate_audit']),
                    decisions=counts,source_comparison=matches)),flush=True)
                del result;gc.collect()

if __name__=='__main__':main()
