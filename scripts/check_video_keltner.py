"""Cache-only provisional Keltner/Chande adaptation; stdout only, no reports.

Previously inspected development quarters, current membership survivorship bias.
No faithful-source claim: oscillator name/chart and hidden settings unverified.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import corporate_actions,data_quality,intraday_data,market_history,store
from core.research.video_methods import portfolio_replay
from core.research.video_keltner import setups,replay,settle
from scripts.check_video_methods import WINDOWS
from scripts.check_video_timeframes import summary
from core.research.video_filters import prior_market_regimes
from core.research.video_selection import prior_liquidity_ranks,flags,time_bucket,VARIANTS

RULES=dict(source='0D9yyNrPwdY',source_fidelity='provisional Chande interpretation; chart unverified',
           timeframe=3,basis='EMA20 seeded first close',atr='Wilder10 seeded SMA10 TR, research choice',
           bands_multiple=1.5,cmo=14,rvol='signal volume / mean preceding20 completed3m bars >1.5',
           entry='next1m open adverse2bps',breakout='fresh completed close cross outside band',
           stop='signal midline plus adverse1bp buffer',stop_bounds=(.0005,.02),
           exits=('full2R','half1R_then_completed_midline_ratchet'),hold_minutes=45,
           risk_fraction=.001,capital=100000,participation='.01 of final signal1m volume',
           cost_guard=.25,stress='matched quantity, entry extra3bps, exit5bps, fees150%',
           partial_cash='reserved until final exit; no reinvestment')


def diagnose(candidates):
    for _,start,end in WINDOWS:
        pool=candidates[start,False]
        base=portfolio_replay(pool,max_friction_r=.25,settle=settle)
        for dimension,classify in (('direction',lambda t:'long' if t.get('direction',1)==1 else 'short'),
                                   ('time',time_bucket),
                                   ('liquidity',lambda t:'top10' if t['liquidity_rank']<=10 else 'other'),
                                   ('market',lambda t:'aligned' if flags(t)['market_aligned'] else 'other')):
            for label in sorted({classify(t) for t in base}):
                # Descriptive slices of the SAME baseline ledger, not standalone portfolios.
                selected=[t for t in base if classify(t)==label]
                print('SLICE',json.dumps(dict(start=start,dimension=dimension,label=label,summary=summary(selected))),flush=True)
        for name in VARIANTS:
            admitted=[t for t in pool if flags(t)[name]]
            ledger=portfolio_replay(admitted,max_friction_r=.25,settle=settle)
            stress=[settle(dict(t,entry=t['entry']*(1+t.get('direction',1)*.0003)),t['quantity'],5,1.5) for t in ledger]
            print('SELECTION',json.dumps(dict(start=start,end=end,variant=name,candidates=len(admitted),
                                             base=summary(ledger),matched_cost_stress=summary(stress))),flush=True)


def execution_check(candidates):
    from core.research.video_costs import reprice,break_even_extra_bps
    for _,start,end in WINDOWS:
        pool=candidates[start,False]
        ledger=portfolio_replay(pool,max_friction_r=.25,settle=settle)
        scenarios=[dict(extra_bps=b,fee_multiplier=f,summary=summary(reprice(ledger,b,f)))
                   for b,f in ((0,1),(.5,1),(1,1),(2,1),(3,1),(0,1.5),(3,1.5))]
        raw_pnl=sum(t.get('direction',1)*t['quantity']*(t['exit_raw']-t['entry_raw']) for t in ledger)
        before_fees=sum(t.get('direction',1)*t['quantity']*(t['exit']-t['entry']) for t in ledger)
        print('EXECUTION',json.dumps(dict(start=start,end=end,trades=len(ledger),
                                          raw_price_pnl=round(raw_pnl,2),
                                          modelled_slippage_cost=round(raw_pnl-before_fees,2),
                                          fees=round(sum(t['fees'] for t in ledger),2),
                                          break_even_extra_bps_per_market_side=break_even_extra_bps(ledger),
                                          scenarios=scenarios)),flush=True)


def run(diagnostics=False,execution=False):
    diagnostics=diagnostics or execution
    universe=store.read('universes/nifty50');reference=market_history.evidence(snapshot=True)
    rules=dict(RULES)
    if diagnostics:rules['selection']=dict(variants=VARIANTS,exit='full2R selected from prior three-quarter comparison',
                                         market='previous completed Nifty SMA20/50',liquidity='prior20 daily close*volume top10',
                                         early='09:45 inclusive to10:30 exclusive signal time')
    if execution:rules['execution_check']='prior top10 only; matched orders extra0/.5/1/2/3bps, fees100/150%; no historical quotes'
    digest=hashlib.sha256(json.dumps(dict(universe=universe,reference=reference,rules=rules),sort_keys=True).encode())
    benchmark=store.read('bars/NIFTY50',{})
    regimes=prior_market_regimes(benchmark['bars']) if diagnostics else {}
    ranks={}
    if diagnostics:
        digest.update(json.dumps(benchmark,sort_keys=True).encode())
        daily={}
        for item in universe['instruments']:
            raw=store.read('bars/'+item['isin'],{})
            rows,details=market_history.prepare(item,raw,reference=reference,fingerprint=False)
            if rows and not details.get('quarantine') and not data_quality.audit({item['symbol']:rows},start='2024-10-01',end='2026-10-09')['findings']:
                daily[item['symbol']]=rows
        ranks=prior_liquidity_ranks(daily)
    quality=Counter();excluded=[];examples=[]
    candidates={(start,scaled):[] for _,start,_ in WINDOWS for scaled in (False,True)}
    counts={start:Counter() for _,start,_ in WINDOWS}
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
                if day in intraday_data.SPECIAL_SESSIONS:previous=[];continue
                path=store.DATA/(intraday_data.cache_key(item['isin'],day,1)+'.json')
                if not path.exists():quality['missing_session']+=1;previous=[];continue
                blob=path.read_bytes();digest.update(blob)
                try:
                    bars=intraday_data.trading_bars(intraday_data.cached_bars(json.loads(blob),day,1),'15:29',1)
                    if max(abs(max(b['high'] for b in bars)/row['high']-1),abs(min(b['low'] for b in bars)/row['low']-1))>.01:
                        raise ValueError('Daily/minute extrema differ by>1%.')
                except (ValueError,KeyError) as error:
                    quality['invalid_session']+=1;previous=[]
                    if len(examples)<10:examples.append(dict(symbol=symbol,date=day,error=str(error)))
                    continue
                quality['valid_session']+=1
                if start<=day and len(previous)>=3 and j>=50:
                    if any(previous[0][0]['date']<a['ex_date']<=day for a in actions):quality['action_crossing_excluded']+=1
                    else:
                        quality['eligible_stock_session']+=1
                        for direction in (1,-1):
                            if execution and ranks.get(day,{}).get(symbol,{}).get('rank',999)>10:continue
                            signals,series=setups(bars,previous,direction)
                            counts[start]['setups']+=len(signals)
                            for signal in signals:
                                for scaled in ((False,) if diagnostics else (False,True)):
                                    trade=replay(signal,bars,series,scaled)
                                    if trade:
                                        metadata={}
                                        if diagnostics:
                                            regime=regimes.get(day,{})
                                            liquidity=ranks.get(day,{}).get(symbol,{})
                                            if regime.get('as_of',day)>=day or liquidity.get('as_of',day)>=day:
                                                raise ValueError('Missing or noncausal selection evidence.')
                                            metadata=dict(signal_time=bars[signal['signal_index']]['time'],
                                                          market_direction=regime['direction'],liquidity_rank=liquidity['rank'])
                                        candidates[start,scaled].append(dict(trade,symbol=symbol,**metadata))
                previous=(previous+[bars])[-3:]
        print('Checked',symbol,'sessions',quality['valid_session'],flush=True)
    print('INPUT',json.dumps(dict(sha256=digest.hexdigest(),rules=rules,quality=dict(quality),excluded=excluded,examples=examples)),flush=True)
    if diagnostics:
        if execution:execution_check(candidates)
        else:diagnose(candidates)
        return
    for _,start,end in WINDOWS:
        for scaled in (False,True):
            pool=candidates[start,scaled];parts=2 if scaled else 1
            baseline=portfolio_replay(pool,settle=settle,planned_exit_parts=parts)
            guarded=portfolio_replay(pool,max_friction_r=.25,settle=settle,planned_exit_parts=parts)
            stress=[settle(dict(t,entry=t['entry']*(1+t.get('direction',1)*.0003)),t['quantity'],5,1.5) for t in guarded]
            base_stress=[settle(dict(t,entry=t['entry']*(1+t.get('direction',1)*.0003)),t['quantity'],5,1.5) for t in baseline]
            print('KELTNER',json.dumps(dict(start=start,end=end,exit='half1R_trail' if scaled else 'full2R',
                                           candidates=len(pool),setups=dict(counts[start]),
                                           diagnostic_without_cost_guard=summary(baseline),
                                           diagnostic_matched_stress=summary(base_stress),
                                           cost_guard=summary(guarded),matched_cost_stress=summary(stress))),flush=True)


if __name__=='__main__':run(diagnostics='--diagnostics' in sys.argv,execution='--execution' in sys.argv)
