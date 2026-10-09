"""Replay frozen momentum inputs; no downloads, defaults or live orders."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import momentum,store,data_quality
from core.research.config import Settings
from core.research.intraday_costs import upstox_cash_fees

SCENARIOS = [
    ('original',10,10,10,None),
    ('zero_cost',0,0,0,None),
    ('public_fees_slip_0',0,0,0,1),
    ('public_fees_slip_2',2,0,0,1),
    ('public_fees_slip_5',5,0,0,1),
    ('public_fees_slip_10',10,0,0,1),
    ('stress_fees_150_slip_15',15,0,0,1.5),
]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def attribution(trades):
    wins = sum(t['pnl'] for t in trades if t['pnl']>0)
    losses = -sum(t['pnl'] for t in trades if t['pnl']<0)
    return {**momentum.trade_summary(trades),'profit_factor':wins/losses if losses else None,
            'average_pnl':sum(t['pnl'] for t in trades)/len(trades) if trades else None}


def main(reference_id):
    reference = store.read('runs/'+reference_id)
    if not reference:
        raise ValueError('Missing reference.')
    cfg = momentum.MomentumConfig(**{**reference['config'],'comparison_run_id':reference_id})
    if cfg.execution_mode != 'follow' or cfg.require_fundamentals or cfg.breakeven_after_r:
        raise ValueError('This declared suite requires a follow control without fundamentals or breakeven.')
    settings = Settings(universe=reference['universe'])
    print('Checking frozen daily inputs...',flush=True)
    universe,daily,manifest,excluded = momentum.prepare(settings,cfg)
    data_quality.require_no_anomalies(data_quality.audit(daily,end=cfg.end))
    print('Loading and checking frozen minute inputs...',flush=True)
    sessions = store.read('run_intraday/'+reference_id)
    if not sessions or digest(sessions) != reference['intraday_source']['sha256']:
        raise ValueError('Frozen minute hash mismatch.')
    print('Building prior-session liquidity plan once...',flush=True)
    plan = momentum.entry_plan(daily,cfg)[0]
    output = store.ROOT/'artifacts'/'intraday_cost_research'
    output.mkdir(parents=True,exist_ok=True)
    summary = dict(reference_id=reference_id,config=reference['config'],
        minute_sha256=reference['intraday_source']['sha256'],manifest=manifest,
        created_at=store.now(),source='https://upstox.com/brokerage-charges/',
        notice='Public basic Upstox fee hypothesis; account and historical brokerage unverified. Slippage is sensitivity, not measured execution. All periods already inspected. Direction-only runs reselect eligible stocks and are standalone portfolios.',runs=[])
    for name,slip,buy,sell,multiplier in SCENARIOS:
        for direction in ('both','long','short'):
            trial = cfg.model_copy(update={'direction':direction,'slippage_bps':slip,'buy_cost_bps':buy,'sell_cost_bps':sell})
            fees = None if multiplier is None else lambda p,q,s,d,m=multiplier:upstox_cash_fees(p,q,s,d,m)
            result = momentum.simulate(daily,trial,sessions,plan,fee_model=fees)
            if name == 'original' and direction == 'both':
                for key in ('final_equity','modeled_fees','modeled_slippage'):
                    if abs(result['metrics'][key]-reference['metrics'][key])>1e-6:
                        raise ValueError('Baseline replay mismatch: '+key)
                entries = lambda r:[(t['symbol'],t['entry_timestamp'],t['quantity'],t['exit'],t['pnl']) for t in r['trades']]
                if entries(result) != entries(reference):
                    raise ValueError('Baseline trade replay mismatch.')
                summary['baseline_replay_verified'] = True
            record = dict(scenario=name,direction=direction,slippage_bps=slip,fee_multiplier=multiplier,
                metrics=result['metrics'],diagnostics=result['diagnostics'],
                long=attribution([t for t in result['trades'] if t['direction']=='long']),
                short=attribution([t for t in result['trades'] if t['direction']=='short']),
                yearly=[])
            for year in sorted({p['date'][:4] for p in result['curve']}):
                prior = [p for p in result['curve'] if p['date'][:4]<year]
                points = [p for p in result['curve'] if p['date'][:4]==year]
                start = prior[-1]['equity'] if prior else cfg.capital
                record['yearly'].append(dict(year=year,return_pct=(points[-1]['equity']/start-1)*100,
                    **attribution([t for t in result['trades'] if t['entry_date'][:4]==year])))
            # Retain exact trades and curve without duplicating 570MB inputs per trial.
            result['trades'] = [{k:v for k,v in t.items() if k!='stop_trace'} for t in result['trades']]
            (output/(name+'_'+direction+'.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
            summary['runs'].append(record)
            (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
            print(f"{name:28} {direction:5}: {result['metrics']['return_pct']:+.3f}% / {result['metrics']['trade_count']} trades / PF {result['metrics']['profit_factor']:.3f}",flush=True)
    print('Saved:',output,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('reference_id',nargs='?',default='836c4463d21b')
    main(parser.parse_args().reference_id)
