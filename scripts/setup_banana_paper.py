"""Create independent forward paper controls without touching existing portfolios."""
import json
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.portfolio import manager,paper
from core.research import store,strategy_presets,fundamentals,market_history,data_quality
from core.research.config import Settings

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path)
    parser.add_argument('--manual',action='store_true',help='Create local scenarios with automatic cycles disabled.')
    args=parser.parse_args()
    source=json.loads(args.source.read_text()) if args.source else {}
    frozen=source.get('frozen') or store.read('runs/b4584ee01955')
    old=source.get('old') or store.read('runs/6abcabe9224a')
    if not frozen or not old:
        raise ValueError('Saved source universes and prior control settings are required.')
    clock=paper.local_now()
    reference=market_history.evidence(snapshot=True)
    prepared={}
    candidates=[]
    excluded=[]
    for item in frozen['universe_snapshot']['instruments']:
        if item['symbol'] not in {m['symbol'] for m in frozen['manifest']}:continue
        record=store.read('bars/'+item['isin'],{})
        bars,_=market_history.prepare(item,record,reference=reference)
        if len(bars)<254:
            excluded.append(item['symbol']);continue
        prepared[item['symbol']]=bars
        candidates.append(item)
    quality=data_quality.audit(prepared,end=clock.date().isoformat())
    eligible=data_quality.exclude_anomalies(prepared,quality,lambda _:None)
    universe={**frozen['universe_snapshot'],'instruments':[i for i in candidates if i['symbol'] in eligible]}
    if not universe['instruments']:
        raise ValueError('No audited shared universe for forward paper.')
    settings=Settings(universe=frozen['universe'],start='2018-01-01',end=clock.date())
    gate=fundamentals.buy_screen('swing_patterns').model_dump()
    variants=[]
    prior={k:v for k,v in old['config'].items() if k in paper.PaperConfig.model_fields}
    variants.append(('banana_old_blue_control',paper.PaperConfig(**{**prior,'name':'Old Blue Sky - forward control',
        'capital':1000000,'fee_model':'custom_bps','buy_cost_bps':25,'sell_cost_bps':25,'slippage_bps':10,
        'auto_run':not args.manual,'run_hour':16,'run_minute':15,'execution_time':'next_open',
        'sector_observe_only':False,'investor_news_exits':False,'acknowledge_limitations':True})))
    for preset in strategy_presets.available():
        if not preset.get('paper_defaults') or preset['pattern']=='ipo':continue
        for mode in ('observe','required'):
            label='technical only' if mode=='observe' else 'fundamentals required'
            cfg=paper.PaperConfig(**{**preset['paper_defaults'],'name':preset['name']+' - '+label,
                'fundamental_mode':mode,'auto_run':not args.manual,'acknowledge_limitations':True})
            variants.append(('banana_'+preset['pattern']+'_'+mode,cfg))
    results=[]
    for identity,cfg in variants:
        existing=manager.get('swing_patterns',identity)
        if existing:
            if existing['config']!=cfg.model_dump(mode='json'):
                raise ValueError('Existing scenario settings differ: '+identity+'; not overwritten.')
        else:
            existing=manager.save('swing_patterns',cfg,settings,create=True,clock=clock,
                                  portfolio_id=identity,universe_snapshot=universe)
            existing.update(fundamental_screen=gate,comparison_source_run='b4584ee01955',
                            setup_exclusions=sorted(set(excluded+quality['excluded_symbols'])),
                            comparison_notice='Forward-only; shared audited universe and 25 bps fees plus 10 bps slippage. News exits disabled. Technical-only scenarios observe financial checks without blocking.')
            store.write(manager.key('swing_patterns',identity),existing)
        results.append(dict(id=identity,name=cfg.name,start=existing['start_session'],stocks=len(existing['universe_snapshot']['instruments']),
                            capital=cfg.capital,auto_run=cfg.auto_run,fundamentals=cfg.fundamental_mode,news_exits=cfg.investor_news_exits))
    print(json.dumps(dict(scenarios=results,fundamental_screen=gate),indent=2))

if __name__=='__main__':main()
