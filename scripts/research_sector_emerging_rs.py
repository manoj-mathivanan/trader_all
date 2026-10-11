"""Fixed-rule emerging-leadership diagnostics on a frozen sector backtest.

Writes research JSON/CSV only. Does not change screens, orders, or portfolio settings.
Watchlist outcomes are separate from portfolio simulations and use future prices
only for evaluation. All signal inputs end at the completed decision session.
"""
import argparse
import csv
import hashlib
import inspect
import json
import statistics
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import backtest, corporate_actions, fundamental_history, market_history
from core.research.config import BacktestConfig
from core.research.relative_strength import StrengthHistory
from core.research.sector_breadth import SectorBreadth

VARIANTS = {
    'control': {},
    'rs63_level': {'min_short_rs_rating': 70},
    'rs63_improving': {'min_short_rs_rating': 70, 'min_rs_improvement': 10},
    'vcp_rs63_improving': {'pattern': 'vcp', 'min_short_rs_rating': 70, 'min_rs_improvement': 10},
    'limited_sector_exception': {},
}
PERIODS = {
    'full': ('2025-03-03', '2026-10-08'),
    'earlier': ('2025-03-03', '2026-02-27'),
    'middle': ('2026-03-02', '2026-06-30'),
    'recent': ('2026-07-01', '2026-10-08'),
}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def csv_write(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


class LimitedException:
    """Only bypass weak breadth, never missing mappings/history/coverage."""
    def __init__(self, gate, strength, cfg, data):
        self.gate, self.strength, self.cfg, self.data = gate, strength, cfg, data

    def decision(self, symbol, day):
        decision = dict(self.gate.decision(symbol, day))
        decision['rs_exception'] = False
        if decision['allowed'] or decision['reason'] != 'sector_breadth_weak':
            return decision
        value = self.strength.measure(symbol, day, self.cfg)
        i = self.strength.indices[symbol][day]
        bars = corporate_actions.adjusted_bars(self.data[symbol], day)
        positive = bars[i]['close'] > bars[i-63]['close'] if i >= 63 else False
        if (decision['breadth_pct'] >= 40 and decision['coverage_pct'] >= 80
                and value['short_rs_rating'] is not None and value['short_rs_rating'] >= 90
                and value['rs_improvement'] is not None and value['rs_improvement'] >= 10
                and positive):
            decision.update(allowed=True, reason='limited_emerging_leader_exception',
                            rs_exception=True, original_reason='sector_breadth_weak', **value)
        return decision


def exception_engine():
    # Isolated copy: the shared production engine is never edited. The additional
    # controls require live holdings, which an ordinary sector gate cannot read.
    source = inspect.getsource(backtest.simulate)
    capacity = '            if len(positions) >= cfg.max_positions:'
    sizing = '            qty = percent_risk_size(equity_at_open, cash, fill, stop, sizing_cfg, day=day)'
    assert source.count(capacity) == source.count(sizing) == 1
    source = source.replace(capacity,
        "            if sector_decision and sector_decision.get('rs_exception') and any(\n"
        "                    p.get('sector', {}).get('rs_exception') for p in positions.values()):\n"
        "                skipped += 1\n"
        "                skip_reasons['Exception slot occupied'] = skip_reasons.get('Exception slot occupied', 0) + 1\n"
        "                continue\n" + capacity)
    source = source.replace(sizing,
        "            if sector_decision and sector_decision.get('rs_exception'):\n"
        "                sizing_cfg = SimpleNamespace(**{**vars(sizing_cfg), 'risk_pct': min(sizing_cfg.risk_pct, .75)})\n" + sizing)
    namespace = dict(backtest.__dict__)
    exec(source, namespace)
    return namespace['simulate']


def portfolio_summary(result, indices, original):
    trades = result['trades']
    winners = [t for t in original['trades'] if t['pnl'] > 1e-6]
    exact_entries = {(t['symbol'], t['entry_date']) for t in trades}
    exceptions = [t for t in trades if t.get('sector', {}).get('rs_exception')]
    return dict(**result['metrics'], losses=sum(t['pnl'] < -1e-6 for t in trades),
        false_starts=sum(t['pnl'] < -1e-6 and
                        indices[t['symbol']][t['exit_date']]-indices[t['symbol']][t['entry_date']]+1 <= 10
                        for t in trades),
        baseline_winning_entries_retained=sum((t['symbol'], t['entry_date']) in exact_entries for t in winners),
        exception_trade_count=len(exceptions), exception_net_pnl=sum(t['pnl'] for t in exceptions),
        exception_wins=sum(t['pnl'] > 1e-6 for t in exceptions),
        exception_losses=sum(t['pnl'] < -1e-6 for t in exceptions),
        entry_filter_rejections=result['entry_filter_rejections'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', default='5cafe09b6cdc')
    parser.add_argument('--output', default='artifacts/sector_emerging_rs')
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    original = json.loads((ROOT/f'data/runs/{args.reference}.json').read_text(encoding='utf-8'))
    data_path = ROOT/f'data/run_data/{args.reference}.json'
    financial_path = ROOT/f'data/run_fundamentals/{args.reference}.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))
    financial = json.loads(financial_path.read_text(encoding='utf-8'))
    assert all(market_history.digest(data[m['symbol']]) == m['sha256'] for m in original['manifest'])
    assert financial['sha256'] == original['fundamental_reference']['sha256']
    base = BacktestConfig(**original['config'])
    assert base.market_breadth_scope == 'sector' and base.market_breadth_pct == 60
    assert base.entry_mode == 'next_open' and base.sector_filter == 'off'
    scores = fundamental_history.Scores(financial)
    indices = {s: {b['date']: i for i,b in enumerate(rows)} for s,rows in data.items()}
    gate = SectorBreadth(data, original['universe_snapshot']['instruments'], 60, 80)
    strength = StrengthHistory(data)
    rs_cfg = base.model_copy(update={'min_short_rs_rating': 70, 'min_rs_improvement': 10})
    protocol = dict(reference=args.reference, eligible_symbols=len(data), variants=VARIANTS, periods=PERIODS,
        watchlist_rules=dict(return_lookback=63, rs_minimum=70, improvement_minimum_pp=10,
            improvement_sessions=20, positive_return=True, above_sma50=True,
            average_turnover_minimum=base.min_turnover, prior_pivot_sessions=20,
            close_below_or_at_pivot=True, distance_below_pivot_max_pct=5,
            tight_rule='latest 10-session high-low range and mean volume below preceding 10 sessions'),
        exception_rules=dict(breadth_minimum=40, coverage_minimum=80, rs_minimum=90,
            improvement_minimum_pp=10, positive_return=True, max_concurrent_exception_positions=1,
            exception_risk_pct=.75, entry_pattern='unchanged Blue Sky completed-session signal'),
        watchlist_episode_rule='First qualifying session; suppress subsequent episodes in that stock for 60 sessions, separately by rule.',
        watchlist_outcomes='Next-open reference; full 20/60-session horizons only. +15% high vs -8% low ordering is daily-OHLC conservative; same-session ties count stop first. These are diagnostic barriers, not trade returns.',
        winner_lead_rule='Earliest qualifying watchlist date 1-20 stock sessions before the baseline signal session; same-stock timing association, not proof of same rally.',
        notice='Thresholds fixed before this run; no optimization. Every historical window was previously inspected. Reset period simulations are diagnostics, not untouched validation.',
        price_file_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
        financial_file_sha256=hashlib.sha256(financial_path.read_bytes()).hexdigest(),
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),Path(backtest.__file__),Path(StrengthHistory.__module__.replace('.', '/'))] if p.is_file()})
    dump(output/'protocol.json', protocol)
    # Share the immutable signal and historical rank caches between simulations.
    original_signal, original_strength_class = backtest.signal, backtest.emerging_rs.StrengthHistory
    signal_cache = {}
    def cached_signal(bars, i, cfg):
        key=(id(bars),i,cfg.pattern,cfg.sma_days,cfg.min_turnover,cfg.volume_multiple,
             cfg.require_long_trend,cfg.require_rising_long_trend,cfg.blue_sky_lookback_days,
             cfg.vcp_window_days,cfg.vcp_volume_multiple)
        if key not in signal_cache:
            signal_cache[key]=original_signal(bars,i,cfg)
        return signal_cache[key]
    # Cache by list identity is valid only because these inputs do not need raw
    # action rebasing. Refuse a future dataset for which that assumption changes.
    assert not any(a['price_basis']=='raw' or a['volume_basis']=='raw'
                   for rows in data.values() for a in corporate_actions.actions(rows))
    backtest.signal=cached_signal
    backtest.emerging_rs.StrengthHistory=lambda datasets, context=None: strength
    results={}
    try:
        isolated_engine=exception_engine()
        for name, changes in VARIANTS.items():
            results[name]={}
            for period,(start,end) in PERIODS.items():
                cfg=base.model_copy(update={**changes,'skip_weak_markets':False,
                    'start':date.fromisoformat(start),'end':date.fromisoformat(end)})
                sector_gate=LimitedException(gate,strength,rs_cfg,data) if name=='limited_sector_exception' else gate
                engine=isolated_engine if name=='limited_sector_exception' else backtest.simulate
                result=engine(data,cfg,fundamental_scores=scores,sector_gate=sector_gate)
                if name=='control' and period=='full':
                    fields=['symbol','entry_date','exit_date','entry','exit','quantity','pnl','r','reason','fees']
                    assert result['metrics']==original['metrics'] and result['curve']==original['curve']
                    assert [{k:t[k] for k in fields} for t in result['trades']]==[{k:t[k] for k in fields} for t in original['trades']]
                    assert result['sector_checks']==original['sector_checks']
                    # Verify the instrumented copy produces the same control.
                    copy_control=isolated_engine(data,cfg,fundamental_scores=scores,sector_gate=gate)
                    assert copy_control['metrics']==result['metrics'] and copy_control['trades']==result['trades']
                    protocol['baseline_and_instrumented_control_exact']=True
                    dump(output/'protocol.json',protocol)
                if name=='limited_sector_exception':
                    for bar in result['curve']:
                        held=[t for t in result['trades'] if t.get('sector',{}).get('rs_exception')
                              and t['entry_date'] <= bar['date'] < t['exit_date']]
                        assert len(held)<=1
                summary=portfolio_summary(result,indices,original)
                results[name][period]=summary
                dump(output/f'{name}_{period}.json',dict(config=cfg.model_dump(mode='json'),
                    metrics=summary,trades=result['trades'],curve=result['curve'],sector_checks=result['sector_checks']))
                dump(output/'portfolio_comparison.json',results)
                print('PORTFOLIO',name,period,round(summary['return_pct'],2),
                      'DD',round(summary['max_drawdown_pct'],2),'trades',summary['trade_count'],flush=True)
    finally:
        backtest.signal=original_signal
        backtest.emerging_rs.StrengthHistory=original_strength_class

    # Watchlists are evaluated independently of holdings, sector gate and scores.
    # The structural control isolates whether adding RS improves a comparable list.
    rows_by_rule={rule:[] for rule in ['structure_only','structure_rs','tight_only','tight_rs']}
    for s,raw in data.items():
        for i in range(max(83,base.minimum_warmup_sessions),len(raw)-1):
            day=raw[i]['date']
            if not str(base.start)<=day<=str(base.end):continue
            bars=corporate_actions.adjusted_bars(raw,day)
            close=bars[i]['close']
            sma=sum(b['close'] for b in bars[i-49:i+1])/50
            turnover=sum(b['close']*b['volume'] for b in bars[i-50:i])/50
            pivot=max(b['high'] for b in bars[i-20:i])
            distance=(pivot-close)/pivot*100
            positive=close>bars[i-63]['close']
            if not (close>sma and turnover>=base.min_turnover and positive and 0<=distance<=5):continue
            value=strength.measure(s,day,rs_cfg)
            passes=value['short_rs_rating'] is not None and value['short_rs_rating']>=70 and value['rs_improvement'] is not None and value['rs_improvement']>=10
            recent=bars[i-9:i+1];prior=bars[i-19:i-9]
            range_pct=lambda bs:(max(b['high'] for b in bs)-min(b['low'] for b in bs))/max(b['high'] for b in bs)*100
            tight=range_pct(recent)<range_pct(prior) and sum(b['volume'] for b in recent)<sum(b['volume'] for b in prior)
            row=dict(symbol=s,date=day,session_index=i,close=close,pivot=pivot,distance_below_pivot_pct=distance,
                extension_pct=(close/sma-1)*100,range10_pct=range_pct(recent),prior_range10_pct=range_pct(prior),
                breadth_pct=gate.decision(s,day)['breadth_pct'],**value)
            rows_by_rule['structure_only'].append(row)
            if passes:rows_by_rule['structure_rs'].append(row)
            if tight:rows_by_rule['tight_only'].append(row)
            if tight and passes:rows_by_rule['tight_rs'].append(row)
    episodes=[];watch_summary={};winner_matches=[]
    for rule,rows in rows_by_rule.items():
        last={};selected=[]
        for row in rows: # Each symbol's rows are chronological.
            s=row['symbol'];i=row['session_index']
            if i-last.get(s,-100000)<=60:continue
            last[s]=i
            future=data[s][i+1:];entry=future[0]['open']
            episode=dict(rule=rule,**row,next_open_date=future[0]['date'],next_open=entry)
            for horizon in [20,60]:
                path=future[:horizon]
                complete=len(path)==horizon and path[-1]['date']<=str(base.end)
                episode[f'complete{horizon}']=complete
                if not complete:continue
                episode[f'return{horizon}_pct']=(path[-1]['close']/entry-1)*100
                up=next((j for j,b in enumerate(path) if b['high']>=entry*1.15),None)
                down=next((j for j,b in enumerate(path) if b['low']<=entry*.92),None)
                episode[f'rally{horizon}']=up is not None
                episode[f'barrier{horizon}']=('rally_first' if up is not None and (down is None or up<down)
                    else 'stop_first' if down is not None else 'neither')
                episode[f'same_bar_tie{horizon}']=up is not None and down is not None and up==down
            selected.append(episode)
        episodes.extend(selected)
        summary=dict(raw_candidate_days=len(rows),unique_symbols=len({x['symbol'] for x in rows}),episodes=len(selected))
        for horizon in [20,60]:
            complete=[x for x in selected if x[f'complete{horizon}']]
            summary[f'horizon{horizon}']=dict(evaluable=len(complete),
                positive_closes=sum(x[f'return{horizon}_pct']>0 for x in complete),
                median_return_pct=statistics.median(x[f'return{horizon}_pct'] for x in complete) if complete else None,
                rally_reached=sum(x[f'rally{horizon}'] for x in complete),
                barriers=dict(Counter(x[f'barrier{horizon}'] for x in complete)),
                same_bar_ties=sum(x[f'same_bar_tie{horizon}'] for x in complete))
        for t in original['trades']:
            if t['pnl']<=1e-6:continue
            signal_i=indices[t['symbol']][t['entry_date']]-1
            earlier=[x for x in rows if x['symbol']==t['symbol'] and 1<=signal_i-x['session_index']<=20]
            first=min(earlier,key=lambda x:x['session_index']) if earlier else None
            winner_matches.append(dict(rule=rule,symbol=t['symbol'],baseline_entry=t['entry_date'],
                watch_date=first['date'] if first else None,
                lead_to_signal_sessions=signal_i-first['session_index'] if first else None))
        matches=[x for x in winner_matches if x['rule']==rule and x['watch_date']]
        summary['baseline_winners_early_alerted']=len(matches)
        summary['baseline_winners_total']=sum(t['pnl']>1e-6 for t in original['trades'])
        summary['median_lead_to_signal_sessions']=statistics.median(x['lead_to_signal_sessions'] for x in matches) if matches else None
        watch_summary[rule]=summary
        print('WATCHLIST',rule,json.dumps(summary),flush=True)
    csv_write(output/'watchlist_candidates.csv',[dict(rule=rule,**row) for rule,rows in rows_by_rule.items() for row in rows])
    csv_write(output/'watchlist_episodes.csv',episodes)
    csv_write(output/'winner_alert_matching.csv',winner_matches)
    dump(output/'watchlist_summary.json',watch_summary)
    # Latest frozen session candidates are a historical list, not today's quotes.
    latest=max(b['date'] for bars in data.values() for b in bars if b['date']<=str(base.end))
    dump(output/'last_frozen_session_watchlist.json',dict(date=latest,
        structure_rs=[x for x in rows_by_rule['structure_rs'] if x['date']==latest],
        tight_rs=[x for x in rows_by_rule['tight_rs'] if x['date']==latest]))
    print('DONE',output,flush=True)


if __name__=='__main__':
    main()
