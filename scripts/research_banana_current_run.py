"""Replay the user's actual latest Swing run and isolate risk/exit changes."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.research import backtest, fundamental_history, market_history, sector
from core.research.config import BacktestConfig


def main():
    rid='6abcabe9224a'
    read=lambda name:json.loads((ROOT/f'data/{name}.json').read_text())
    original=read('runs/'+rid)
    data=read('run_data/'+rid)
    financial=read('run_fundamentals/'+rid)
    sectors=read('run_sector/'+rid)
    if not all(market_history.digest(data[m['symbol']])==m['sha256'] for m in original['manifest']):
        raise ValueError('Price manifest mismatch')
    if financial['sha256']!=original['fundamental_reference']['sha256']:
        raise ValueError('Financial snapshot mismatch')
    sector.verify(sectors,original['sector_reference']['sha256'])
    cfg=BacktestConfig(**original['config'])
    scores=fundamental_history.Scores(financial,cfg.entry_mode)
    gate=sector.Gate(sectors,cfg.sector_filter)
    out=ROOT/'artifacts/banana_parity_20261012'
    out.mkdir(parents=True,exist_ok=True)
    summary=dict(reference=rid,hashes_verified=True,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'core/research/backtest.py']},results={})
    variants={
        'original':{},
        'stop8_only':{'stop_pct':8},
        'stop8_take15':{'stop_pct':8,'winner_exit':'take_15'},
        'stop8_local_sma_trail':{'stop_pct':8,'winner_exit':'trail_50d'},
        'stop8_local_sma_trail_gates_off':{'stop_pct':8,'winner_exit':'trail_50d','skip_weak_markets':False,'sector_filter':'off'},
    }
    for name,changes in variants.items():
        c=BacktestConfig(**{**original['config'],**changes})
        result=backtest.simulate(data,c,fundamental_scores=scores,
            sector_gate=gate if c.sector_filter!='off' else None,
            sector_instruments=original['universe_snapshot']['instruments'])
        if name=='original':
            summary['baseline_metrics_exact']=result['metrics']==original['metrics']
            summary['baseline_trades_exact']=result['trades']==original['trades']
            if not summary['baseline_metrics_exact'] or not summary['baseline_trades_exact']:
                raise ValueError('Latest baseline does not replay exactly')
        result.pop('state')
        (out/f'latest_{name}.json').write_text(json.dumps(dict(config=c.model_dump(mode='json'),**result),indent=2))
        summary['results'][name]=result['metrics']
        (out/'latest_run_diagnosis.json').write_text(json.dumps(summary,indent=2))
        print(name,json.dumps(result['metrics']),flush=True)


if __name__=='__main__':
    main()
