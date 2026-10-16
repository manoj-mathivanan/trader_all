"""Declared historical strategy comparison: maximize average gross call return."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import corporate_actions, data_quality, market_history, store
from core.research.config import TradingConfig
from strategies.swing_patterns.patterns.signals import matches
from scripts.research_stock_call_accuracy import outcome, summarize, export_csv

OUT = ROOT / 'artifacts/strategy_call_returns_20261011'
PERIODS = {'selection': ('2019-01-01','2022-12-31'),
           'validation': ('2023-01-01','2024-12-31'),
           'recent_audit': ('2025-01-01','2026-10-09')}


def candidates():
    for pattern in ('breakout','blue_sky','vcp','multiyear'):
        for profile in ('standard','rising200_volume15'):
            for stop in (6,8):
                for exit_rule in ('take_15','take_25','trail_50d','trail_30w'):
                    name = f'{pattern}_{profile}_stop{stop}_{exit_rule}'
                    yield TradingConfig(name=name, pattern=pattern, entry_mode='next_open',
                        base_days=25, max_depth_pct=35, volume_multiple=1 if profile=='standard' else 1.5,
                        require_rising_long_trend=profile!='standard', sma_days=50,
                        vcp_volume_multiple=.9, min_turnover=50000000, stop_pct=stop,
                        breakeven_r=1, winner_exit=exit_rule, trail_pct=8, skip_weak_markets=False,
                        sector_filter='off', max_sector_positions=0, slippage_bps=0,
                        buy_cost_bps=0, sell_cost_bps=0)


def stats(calls):
    result = summarize(calls)
    closed = [c for c in calls if c['status'] in ('correct','incorrect','flat')]
    profits = sorted((c['return_pct'] for c in closed), reverse=True)
    gains = sum(p for p in profits if p>0)
    losses = -sum(p for p in profits if p<0)
    result.update(stock_count=len({c['symbol'] for c in closed}),
        profit_factor=gains/losses if losses else None,
        mean_without_top_1pct=(sum(profits[max(1,len(profits)//100):])/len(profits[max(1,len(profits)//100):])) if len(profits)>1 else None,
        mean_holding_sessions=sum(c['holding_sessions'] for c in closed)/len(closed) if closed else None,
        max_holding_sessions=max((c['holding_sessions'] for c in closed),default=None),
        best_call_pct=max(profits,default=None),worst_call_pct=min(profits,default=None))
    return result


def period_stats(calls,start,end):
    # Both signal AND entry belong to the period. A selection-period decision
    # cannot learn an exit occurring during a later validation period.
    within = [c for c in calls if start <= c['signal_date'] <= end and c.get('entry_date',c['signal_date'])<=end]
    observed = []
    for c in within:
        if c.get('exit_date','9999-12-31')<=end:
            observed.append(c)
        else:
            observed.append(dict(c,status='open' if 'entry_date' in c else c['status']))
    return stats(observed)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    trial_configs = list(candidates())
    protocol = dict(objective='Highest arithmetic mean gross percentage return per completed call in selection period.',
        periods=PERIODS, eligible='At least 100 completed selection-period calls across at least 30 stocks.',
        capital=None, quantity=None, market_breadth=False, sector_breadth=False, sector_filter=False,
        position_limit=None, holding_limit=None, costs=0, slippage=0,
        entry='Completed signal close, next-session open fill; same-day stop can trigger.',
        end_policy='Natural exits only; unresolved calls censored at each period boundary.',
        warmup=260, universes='All usable current Nifty Total Market stock records; no stock shortlist.',
        profiles={'standard':'Volume >=1x prior 50-session average; existing SMA50/liquidity/pattern predicates.',
                  'rising200_volume15':'Volume >=1.5x; price above rising SMA200, plus existing SMA50/liquidity/pattern predicates.'},
        caveats=['All historical periods have been inspected previously; this is retrospective research.',
                 'Current membership introduces survivorship bias.',
                 'Calls can overlap and share a trend episode.',
                 'Mean call return is not a portfolio return and ignores capital and costs.',
                 'Censoring and different holding times can change comparisons.'],
        candidate_configs=[c.model_dump(mode='json') for c in trial_configs],
        scripts={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (Path(__file__),ROOT/'scripts/research_stock_call_accuracy.py',ROOT/'strategies/swing_patterns/patterns/signals.py')})
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    reference = market_history.evidence(snapshot=True)
    datasets, coverage = {}, []
    for item in store.read('universes/niftytotalmarket',{})['instruments']:
        record = store.read('bars/'+item['isin'],{})
        row = dict(symbol=item['symbol'],isin=item['isin'])
        if not record.get('bars'):
            row['status']='missing_history'
        else:
            bars, history = market_history.prepare(item,record,reference=reference)
            findings = data_quality.audit({item['symbol']:bars})['findings']
            row.update(history=history,anomalies=findings)
            row['status']='quarantined' if history.get('quarantine') else 'unresolved_price_gaps' if findings else 'available'
            if bars and row['status']=='available':
                datasets[item['symbol']] = corporate_actions.adjusted_bars(bars,bars[-1]['date'])
        coverage.append(row)
    print('Coverage',dict(Counter(x['status'] for x in coverage)),flush=True)
    signal_cache,results = {},[]
    for cfg in trial_configs:
        key = cfg.pattern,cfg.require_rising_long_trend,cfg.volume_multiple
        if key not in signal_cache:
            print('Scanning',key,flush=True)
            signal_cache[key] = {symbol:[i for i in range(260,len(bars))
                if bars[i]['date']>='2019-01-01' and matches(bars,i,cfg)] for symbol,bars in datasets.items()}
        calls = []
        for symbol,indices in signal_cache[key].items():
            for i in indices:
                calls.append(dict(outcome(datasets[symbol],i,cfg),symbol=symbol,strategy=cfg.name))
        summary = dict(name=cfg.name,config=cfg.model_dump(mode='json'),full=stats(calls),
            periods={name:period_stats(calls,*bounds) for name,bounds in PERIODS.items()})
        train = summary['periods']['selection']
        summary['eligible'] = train['closed']>=100 and train['stock_count']>=30
        results.append(summary)
        export_csv(OUT/(cfg.name+'_calls.csv'),calls)
        (OUT/'trials.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(cfg.name,'train',train['mean_return_pct'],'validation',summary['periods']['validation']['mean_return_pct'],
              'recent',summary['periods']['recent_audit']['mean_return_pct'],'full',summary['full']['mean_return_pct'],flush=True)
    eligible = sorted((r for r in results if r['eligible']),key=lambda r:r['periods']['selection']['mean_return_pct'],reverse=True)
    retrospective = sorted((r for r in results if r['eligible']),key=lambda r:r['full']['mean_return_pct'],reverse=True)
    report = dict(protocol=protocol,coverage=coverage,history_reference=reference,trials=results,
        selected=eligible[0] if eligible else None,selection_ranking=[x['name'] for x in eligible],
        full_history_best=retrospective[0] if retrospective else None,
        notice='Selected candidate maximizes selection-period mean only. Full-history best is explicitly hindsight-selected.')
    (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    export_csv(OUT/'comparison.csv',[dict(strategy=r['name'],eligible=r['eligible'],
        **{f'{p}_{k}':r['periods'][p][k] for p in PERIODS for k in
           ('closed','accuracy_pct','mean_return_pct','mean_without_top_1pct','profit_factor','mean_holding_sessions','open')},
        **{f'full_{k}':r['full'][k] for k in ('closed','accuracy_pct','mean_return_pct','mean_holding_sessions')}) for r in results])
    print('SELECTED',json.dumps(report['selected']),flush=True)
    print('FULL_HISTORY_BEST',json.dumps(report['full_history_best']),flush=True)


if __name__=='__main__':
    main()
