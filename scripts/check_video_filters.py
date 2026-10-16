"""Fixed filter comparison on cached minutes; stdout only, no result files.

These periods were already inspected. Filter changes are development research,
not fresh out-of-sample validation. Current membership is survivorship biased.
Both trade directions, costs, conservative limit-gap fills and shared cash apply.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import corporate_actions,data_quality,intraday_data,market_history,store
from core.research.video_methods import fvg_setups,replay_limit,portfolio_replay,settlement,metrics
from core.research.video_filters import prior_market_regimes,setup_features,filter_flags,context_features
from scripts.check_video_methods import WINDOWS

VARIANTS=('corrected_base','market','relative_volume','displacement','combined')
CONTEXT_VARIANTS=('context_invalidation','higher_fvg_zone','source_context')
RULES=dict(target_r=3,signal_rvol=1.5,volume_lookback=20,displacement_atr=1,
           atr_lookback=14,market_sma=(20,50),base_exit_slippage_bps=2,
           stress_exit_slippage_bps=5,stress_fee_multiplier=1.5,
           gap_fill='resting_fill_no_price_improvement')


def condensed(values):
    keys=('trades','net_pnl','profit_factor','mean_net_r','mean_raw_r','win_pct','realised_drawdown',
          'net_without_best_stock','net_without_best_day')
    return {k:values[k] for k in keys}


def run(include_context=False,compact=False,source_only=False):
    universe=store.read('universes/nifty50')
    reference=market_history.evidence(snapshot=True)
    benchmark=store.read('bars/NIFTY50',{})
    if not benchmark.get('bars'):
        raise ValueError('Nifty50 benchmark history must be downloaded before this cache-only test.')
    regimes=prior_market_regimes(benchmark['bars'])
    rules=dict(RULES,source_context=include_context,
               source_zone='preidentified15m gap, low touch, invalidated by completed close through far edge',
               source_invalidation='latched until fresh HH/HL pivots after the break')
    digest=hashlib.sha256(json.dumps(dict(universe=universe,reference=reference,
                                        benchmark=benchmark,rules=rules),sort_keys=True).encode())
    quality=Counter();excluded=[];examples=[]
    candidates={start:[] for _,start,_ in WINDOWS}
    old_candidates={start:[] for _,start,_ in WINDOWS}
    for item in universe['instruments']:
        symbol=item['symbol']
        raw=store.read('bars/'+item['isin'],{})
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
                    if len(examples)<12:examples.append(dict(symbol=symbol,date=day,error=str(error)))
                    continue
                quality['valid_session']+=1
                if start<=day and len(previous)>=3 and j>=50:
                    if any(previous[0][0]['date']<a['ex_date']<=day for a in actions):
                        quality['action_crossing_excluded']+=1
                    else:
                        quality['eligible_stock_session']+=1
                        for direction in (1,-1):
                            setups=fvg_setups(bars,previous,direction)
                            contexts=context_features(bars,previous,direction) if include_context else None
                            quality['setups']+=len(setups)
                            for setup in setups:
                                features=setup_features(setup,bars)
                                flags=filter_flags(setup,features,regimes.get(day),rows[j-1]['date'],
                                                   contexts[setup['signal_index']] if contexts else None)
                                trade=replay_limit(setup,bars,target_r=3)
                                legacy=replay_limit(setup,bars,target_r=3,gap_policy='legacy_cancel')
                                if legacy:old_candidates[start].append(dict(legacy,symbol=symbol))
                                if trade:
                                    candidates[start].append(dict(trade,symbol=symbol,filters=flags,features=features))
                                    quality['filled_candidates']+=1
                previous=(previous+[bars])[-3:]
        print('Checked',symbol,'sessions',quality['valid_session'],flush=True)
    print('INPUT',json.dumps(dict(sha256=digest.hexdigest(),rules=rules,quality=dict(quality),excluded=excluded,examples=examples)),flush=True)
    for _,start,end in WINDOWS:
        pool=candidates[start]
        baseline=portfolio_replay(pool)
        old=portfolio_replay(old_candidates[start])
        old_summary=metrics(old);base_summary=metrics(baseline)
        print('CONTROL',json.dumps(dict(start=start,legacy_cancel=condensed(old_summary) if compact else old_summary,
                                       corrected_base=condensed(base_summary) if compact else base_summary)),flush=True)
        variants=('corrected_base',)+CONTEXT_VARIANTS if source_only else VARIANTS+(CONTEXT_VARIANTS if include_context else ())
        for variant in variants:
            selected=pool if variant=='corrected_base' else [t for t in pool if t['filters'][variant]]
            ledger=baseline if variant=='corrected_base' else portfolio_replay(selected)
            stress=[settlement(t,t['quantity'],5,1.5) for t in ledger]
            # Same old admitted trade identities/quantities make signal selection's
            # effect inspectable separately from freed cash and new admissions.
            matched=baseline if variant=='corrected_base' else [t for t in baseline if t['filters'][variant]]
            summary=metrics(ledger);stress_summary=metrics(stress);matched_summary=metrics(matched)
            if compact:
                summary=condensed(summary)
                stress_summary={k:stress_summary[k] for k in ('net_pnl','profit_factor','mean_net_r')}
                matched_summary={k:matched_summary[k] for k in ('trades','mean_net_r')}
            print('FILTER',json.dumps(dict(start=start,end=end,variant=variant,candidates=len(selected),
                                          portfolio=summary,matched_exit_cost_stress=stress_summary,
                                          fixed_baseline_subset=matched_summary)),flush=True)
    return candidates


if __name__=='__main__':run(include_context='--source-context' in sys.argv or '--source-only' in sys.argv,
                          compact='--compact' in sys.argv,source_only='--source-only' in sys.argv)
