"""Cache-only fixed-window comparison; prints results, never writes reports.

Historical robustness only: these dates have been used in previous research.
Current Nifty50 membership introduces survivorship bias. Long-only cash equity
adaptation does not establish an edge on the videos' crypto/futures instruments.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import corporate_actions, data_quality, intraday_data, market_history, store
from core.research.video_methods import daily_sma_account, fvg_setups, metrics, portfolio_replay, replay_limit, settlement

WINDOWS = (('2024-12-20','2025-01-01','2025-03-31'),
           ('2025-12-20','2026-01-01','2026-03-31'),
           ('2026-06-20','2026-07-01','2026-09-30'))
VARIANTS = ('fvg_3r','fvg_4r','fvg_3r_sma50','fvg_3r_cost_guard','fvg_3r_both')
DAILY_WINDOWS = tuple((s,e) for _,s,e in WINDOWS) + (('2024-10-01','2026-09-30'),)


def run(include_daily=True, include_intraday=True):
    universe = store.read('universes/nifty50')
    reference = market_history.evidence(snapshot=True)
    digest = hashlib.sha256(json.dumps(universe,sort_keys=True).encode())
    digest.update(json.dumps(reference,sort_keys=True).encode())
    candidates = {(start,v):[] for _,start,_ in WINDOWS for v in VARIANTS}
    daily_results = {(start,slip):[] for start,_ in DAILY_WINDOWS for slip in (2,5)}
    quality = Counter(); examples=[]; excluded=[]
    for item in universe['instruments']:
        symbol = item['symbol']
        raw = store.read('bars/'+item['isin'],{})
        digest.update(json.dumps(raw,sort_keys=True).encode())
        rows,details = market_history.prepare(item,raw,reference=reference,fingerprint=False)
        if not rows or details.get('quarantine') or data_quality.audit({symbol:rows},start='2024-10-01',end='2026-10-09')['findings']:
            excluded.append(symbol); continue
        actions = corporate_actions.actions(rows)
        for start,end in DAILY_WINDOWS:
            # Cross-window raw split/bonus positions require physical share rebasing.
            daily_ok = not any(a['price_basis']=='raw' and '2024-08-01'<=a['ex_date']<=end for a in actions)
            if daily_ok and include_daily:
                for slip in (2,5):
                    strategy = daily_sma_account(rows,start,end,slippage_bps=slip)
                    baseline = daily_sma_account(rows,start,end,slippage_bps=slip,buy_hold=True)
                    if strategy and baseline:
                        daily_results[start,slip].append(dict(symbol=symbol,strategy=strategy,baseline=baseline))
        if not include_intraday:
            print('Checked daily',symbol,flush=True)
            continue
        for warmup,start,end in WINDOWS:
            previous=[]
            for j,row in enumerate(rows):
                day=row['date']
                if not warmup<=day<=end:
                    continue
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
                        raise ValueError('Daily/minute price extrema differ by >1%.')
                except (ValueError,KeyError) as error:
                    quality['invalid_session']+=1;previous=[]
                    if len(examples)<12:
                        examples.append(dict(symbol=symbol,date=day,error=str(error)))
                    continue
                quality['valid_session']+=1
                if start<=day and len(previous)>=3 and j>=50:
                    # Confirmed action crossing needs independently verified minute units.
                    action_cross=any(previous[0][0]['date']<a['ex_date']<=day for a in actions)
                    if not action_cross:
                        history=corporate_actions.adjusted_bars(rows[:j],day)
                        filter50=history[-1]['close']>mean(b['close'] for b in history[-50:])
                        setups=fvg_setups(bars,previous)
                        shorts=fvg_setups(bars,previous,direction=-1)
                        quality['eligible_stock_session']+=1
                        quality['setups']+=len(setups)
                        for setup in setups:
                            for variant,target in (('fvg_3r',3),('fvg_4r',4)):
                                trade=replay_limit(setup,bars,target_r=target,gap_policy='legacy_cancel')
                                if trade:
                                    trade['symbol']=symbol
                                    candidates[start,variant].append(trade)
                                    if variant=='fvg_3r':
                                        candidates[start,'fvg_3r_cost_guard'].append(trade)
                                        candidates[start,'fvg_3r_both'].append(trade)
                                    if variant=='fvg_3r' and filter50:
                                        candidates[start,'fvg_3r_sma50'].append(trade)
                        for setup in shorts:
                            trade=replay_limit(setup,bars,target_r=3,gap_policy='legacy_cancel')
                            if trade:
                                candidates[start,'fvg_3r_both'].append(dict(trade,symbol=symbol))
                    else:
                        quality['action_crossing_excluded']+=1
                previous=(previous+[bars])[-3:]
        print('Checked',symbol,'sessions',quality['valid_session'],'setups',quality['setups'],flush=True)
    print('INPUT',json.dumps(dict(sha256=digest.hexdigest(),quality=dict(quality),excluded=excluded,examples=examples)),flush=True)
    for _,start,end in WINDOWS if include_intraday else ():
        for variant in VARIANTS:
            pool=candidates[start,variant]
            base=portfolio_replay(pool,max_friction_r=.25 if variant=='fvg_3r_cost_guard' else None)
            # Freeze admitted trades and quantities for matched execution-cost stress.
            stress=[settlement(t,t['quantity'],5,1.5) for t in base]
            print('FVG',json.dumps(dict(start=start,end=end,variant=variant,candidate_fills=len(pool),
                                        base=metrics(base),matched_exit_5bps_fees_150pct=metrics(stress))),flush=True)
    for start,end in DAILY_WINDOWS:
        for slip in (2,5):
            group=daily_results[start,slip]
            # Equal capital in independent sleeves, no daily rebalancing. Flat sleeves
            # retain cash; both methods use same eligible instruments and fee assumptions.
            if group:
                days=sorted({d for g in group for d,_ in g['strategy']['path']})
                last={g['symbol']:100000 for g in group};paths={g['symbol']:dict(g['strategy']['path']) for g in group}
                peak=100000*len(group);dd=0
                for day in days:
                    for symbol,path in paths.items():
                        if day in path:last[symbol]=path[day]
                    equity=sum(last.values());peak=max(peak,equity);dd=max(dd,(peak-equity)/peak)
                print('SMA',json.dumps(dict(start=start,end=end,slippage_bps_per_side=slip,sleeves=len(group),
                                            strategy_return_pct=mean(g['strategy']['return_pct'] for g in group),
                                            buy_hold_return_pct=mean(g['baseline']['return_pct'] for g in group),
                                            strategy_portfolio_drawdown_pct=100*dd,
                                            closed_trades=sum(len(g['strategy']['trades']) for g in group),
                                            active_sleeves=sum(bool(g['strategy']['trades']) for g in group))),flush=True)


if __name__=='__main__':
    run(include_daily='--intraday-only' not in sys.argv,
        include_intraday='--daily-only' not in sys.argv)
