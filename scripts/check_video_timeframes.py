"""Cache-only, four fixed entry/stop designs; stdout only, no reports.

All dates are previously inspected development data and current membership is
survivorship biased. Each quarter starts with100k unlevered research capital.
Neither instrument permissions nor queue/spread fills are established by OHLC.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import corporate_actions,data_quality,intraday_data,market_history,store
from core.research.video_methods import fvg_setups,replay_limit,portfolio_replay,settlement,metrics
from core.research.video_timeframes import entry_setups
from scripts.check_video_methods import WINDOWS

DESIGNS=((1,False),(1,True),(5,False),(5,True))
RULES=dict(entry_minutes=(1,5),atr_minimum_multiple=1,atr_lookback=14,
           atr_ends='before middle impulse',stop_fraction_bounds=(.0005,.02),
           frozen_control_stop_fraction_bounds=(.0005,.005),
           context_minutes=15,pivot_wing_bars=2,choch_to_gap_max_entry_bars=5,
           expiry_minutes=5,hold_minutes=45,target_r=3,participation=.01,
           max_friction_r=.25,base_exit_slippage_bps=2,stress_exit_slippage_bps=5,
           stress_fee_multiplier=1.5)


def summary(ledger):
    values=metrics(ledger)
    values['exit_reasons']=dict(Counter(t['reason'] for t in ledger))
    keys=('trades','net_pnl','profit_factor','mean_net_r','mean_raw_r','realised_drawdown',
          'directions','gap_entries','net_without_best_stock','net_without_best_day','exit_reasons')
    return {k:values[k] for k in keys}


def run():
    universe=store.read('universes/nifty50')
    reference=market_history.evidence(snapshot=True)
    digest=hashlib.sha256(json.dumps(dict(universe=universe,reference=reference,rules=RULES),sort_keys=True).encode())
    quality=Counter();examples=[];excluded=[]
    candidates={(start,m,a):[] for _,start,_ in WINDOWS for m,a in DESIGNS}
    counters={(start,m,a):Counter() for _,start,_ in WINDOWS for m,a in DESIGNS}
    controls={start:[] for _,start,_ in WINDOWS}
    for item in universe['instruments']:
        symbol=item['symbol'];raw=store.read('bars/'+item['isin'],{})
        digest.update(json.dumps(raw,sort_keys=True).encode())
        rows,details=market_history.prepare(item,raw,reference=reference,fingerprint=False)
        if not rows or details.get('quarantine') or data_quality.audit({symbol:rows},start='2024-10-01',end='2026-10-09')['findings']:
            excluded.append(symbol);continue
        actions=corporate_actions.actions(rows)
        for warmup,start,end in WINDOWS:
            previous=[]
            for j,row in enumerate(rows):
                day=row['date']
                if not warmup<=day<=end:continue
                if day in intraday_data.SPECIAL_SESSIONS:
                    previous=[];continue
                path=store.DATA/(intraday_data.cache_key(item['isin'],day,1)+'.json')
                if not path.exists():
                    quality['missing_session']+=1;previous=[];continue
                blob=path.read_bytes();digest.update(blob)
                try:
                    bars=intraday_data.cached_bars(json.loads(blob),day,1)
                    bars=intraday_data.trading_bars(bars,'15:29',1)
                    if max(abs(max(b['high'] for b in bars)/row['high']-1),
                           abs(min(b['low'] for b in bars)/row['low']-1))>.01:
                        raise ValueError('Daily/minute extrema differ by>1%.')
                except (ValueError,KeyError) as error:
                    quality['invalid_session']+=1;previous=[]
                    if len(examples)<10:examples.append(dict(symbol=symbol,date=day,error=str(error)))
                    continue
                quality['valid_session']+=1
                if start<=day and len(previous)>=3 and j>=50:
                    if any(previous[0][0]['date']<a['ex_date']<=day for a in actions):
                        quality['action_crossing_excluded']+=1
                    else:
                        quality['eligible_stock_session']+=1
                        for direction in (1,-1):
                            old=fvg_setups(bars,previous,direction)
                            control=entry_setups(bars,previous,direction)
                            fields=('signal_index','available_at','entry','stop','volume','expires')
                            if len(old)!=len(control) or any(
                                a[f]!=b[f] if f!='stop' else abs(a[f]-b[f])>1e-10
                                for a,b in zip(old,control) for f in fields):
                                raise AssertionError('Generalised1m structural detector changed the frozen control.')
                            quality['control_signal_equivalence_checks']+=1
                            for setup in old:
                                trade=replay_limit(setup,bars,target_r=3)
                                if trade:controls[start].append(dict(trade,symbol=symbol))
                            for minutes,atr_min in DESIGNS:
                                key=(start,minutes,atr_min)
                                setups=entry_setups(bars,previous,direction,minutes,atr_min,max_stop_fraction=.02)
                                counters[key]['setups']+=len(setups)
                                for setup in setups:
                                    counters[key]['atr_floor_used']+=setup['atr_floor_used']
                                    trade=replay_limit(setup,bars,target_r=3)
                                    if trade:
                                        candidates[key].append(dict(trade,symbol=symbol,atr_floor_used=setup['atr_floor_used']))
                previous=(previous+[bars])[-3:]
        print('Checked',symbol,'sessions',quality['valid_session'],flush=True)
    print('INPUT',json.dumps(dict(sha256=digest.hexdigest(),rules=RULES,quality=dict(quality),excluded=excluded,examples=examples)),flush=True)
    for _,start,end in WINDOWS:
        print('CONTROL',json.dumps(dict(start=start,end=end,summary=summary(portfolio_replay(controls[start])))),flush=True)
        for minutes,atr_min in DESIGNS:
            key=(start,minutes,atr_min);pool=candidates[key]
            baseline=portfolio_replay(pool)
            guarded=portfolio_replay(pool,max_friction_r=.25)
            stress=[settlement(t,t['quantity'],5,1.5) for t in guarded]
            print('TIMEFRAME',json.dumps(dict(start=start,end=end,entry_minutes=minutes,
                                            stop='structural_with_1atr_floor' if atr_min else 'structural',
                                            candidates=len(pool),setup_counts=dict(counters[key]),
                                            diagnostic_without_cost_guard=summary(baseline),
                                            cost_guard=summary(guarded),matched_cost_stress=summary(stress))),flush=True)


if __name__=='__main__':run()
