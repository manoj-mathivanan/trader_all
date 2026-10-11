"""Unlimited independent signal outcomes for every active saved swing screen."""
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import corporate_actions, data_quality, market_history, store, strategy_presets
from core.research.config import TradingConfig
from core.research.relative_strength import StrengthHistory
from strategies.swing_patterns.patterns.signals import matches


def interval(wins, n):
    if not n:
        return None, None
    z = 1.959963984540054
    p = wins / n
    denominator = 1 + z*z/n
    centre = (p + z*z/(2*n)) / denominator
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denominator
    return round(100*(centre-half), 3), round(100*(centre+half), 3)


def outcome(bars, signal_index, cfg):
    """Each signal owns its own virtual call; no cash, quantity or occupancy."""
    entry_index = signal_index if cfg.entry_mode == 'close' else signal_index + 1
    if entry_index >= len(bars):
        return dict(signal_date=bars[signal_index]['date'], status='no_next_session')
    b = bars[entry_index]
    pivot_length = (cfg.blue_sky_lookback_days if cfg.pattern == 'blue_sky' else
                    cfg.multiyear_base_days if cfg.pattern == 'multiyear' else cfg.base_days)
    pivot = max(x['high'] for x in bars[max(0, signal_index-pivot_length):signal_index])
    entry = b['close'] if cfg.entry_mode == 'close' else b['open']
    if cfg.entry_mode == 'pivot':
        entry = max(entry, pivot)
        if b['high'] < entry:
            return dict(signal_date=bars[signal_index]['date'], status='pivot_not_filled')
    stop = entry * (1-cfg.stop_pct/100)
    best = entry
    pending = None
    target = {'take_8': 8, 'take_15': 15, 'take_25': 25}.get(cfg.winner_exit)
    base = dict(signal_date=bars[signal_index]['date'], entry_date=b['date'], entry=entry)
    for i in range(entry_index, len(bars)):
        row = bars[i]
        reason, price = None, None
        if i > entry_index and (row['open'] <= stop or pending):
            reason, price = ('Gap through stop' if row['open'] <= stop else pending), row['open']
        elif i == entry_index and cfg.entry_mode in ('pivot', 'close'):
            continue
        elif row['low'] <= stop:
            reason, price = 'Stop loss / trailing stop', stop
        else:
            best = max(best, row['close'])
            if row['close'] >= entry * (1+cfg.stop_pct/100*cfg.breakeven_r):
                length = 150 if cfg.winner_exit == 'trail_30w' else 50
                if cfg.winner_exit in ('trail_30w', 'trail_50d') and i+1 >= length:
                    stop = max(stop, entry, sum(x['close'] for x in bars[i-length+1:i+1])/length)
                elif target is not None and row['close'] >= entry*(1+target/100):
                    reason, price = f'Take profit +{target}%', row['close']
                else:
                    stop = max(stop, entry, best*(1-cfg.trail_pct/100))
            age = i-entry_index+1
            if cfg.failed_breakout_sessions and age <= cfg.failed_breakout_sessions and row['close'] < pivot:
                pending = 'Early breakout failure (next open)'
            elif cfg.stalled_exit_sessions and age >= cfg.stalled_exit_sessions and best < entry*(1+cfg.stop_pct/100*cfg.stalled_min_r):
                pending = 'Stalled trade (next open)'
        if reason:
            change = (price/entry-1)*100
            label = 'correct' if change > 1e-8 else 'incorrect' if change < -1e-8 else 'flat'
            return dict(base, status=label, exit_date=row['date'], exit=price,
                        return_pct=change, holding_sessions=i-entry_index+1, reason=reason)
    return dict(base, status='open', last_date=bars[-1]['date'],
                unrealized_return_pct=(bars[-1]['close']/entry-1)*100)


def summarize(calls):
    counts = Counter(c['status'] for c in calls)
    closed = [c for c in calls if c['status'] in ('correct', 'incorrect', 'flat')]
    n, wins = len(closed), counts['correct']
    low, high = interval(wins, n)
    years = {}
    for year in sorted({c['entry_date'][:4] for c in closed}):
        sample = [c for c in closed if c['entry_date'].startswith(year)]
        years[year] = dict(closed=len(sample), correct=sum(c['status']=='correct' for c in sample),
                           accuracy_pct=round(100*sum(c['status']=='correct' for c in sample)/len(sample), 3))
    return dict(signals=len(calls), closed=n, correct=wins, incorrect=counts['incorrect'], flat=counts['flat'],
                open=counts['open'], no_next_session=counts['no_next_session'],
                pivot_not_filled=counts['pivot_not_filled'], accuracy_pct=round(100*wins/n, 3) if n else None,
                wilson_low_pct=low, wilson_high_pct=high,
                mean_return_pct=round(sum(c['return_pct'] for c in closed)/n, 4) if n else None,
                median_holding_sessions=sorted(c['holding_sessions'] for c in closed)[n//2] if n else None,
                by_entry_year=years)


def export_csv(path, rows):
    keys = sorted(set().union(*(r.keys() for r in rows))) if rows else ['symbol']
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, (dict,list)) else v for k,v in r.items()} for r in rows)


def main():
    output = ROOT / 'artifacts/stock_call_accuracy_20261011'
    output.mkdir(parents=True, exist_ok=True)
    screens = strategy_presets.available()
    universe = store.read('universes/niftytotalmarket', {})
    items = universe['instruments']
    reference = market_history.evidence(snapshot=True)
    datasets, coverage, manifest = {}, {}, []
    for item in items:
        symbol = item['symbol']
        record = store.read('bars/'+item['isin'], {})
        row = dict(symbol=symbol, isin=item['isin'], status='missing_history')
        try:
            if record.get('bars'):
                bars, details = market_history.prepare(item, record, reference=reference)
                findings = data_quality.audit({symbol: bars})['findings']
                row.update(history=details, anomalies=findings)
                if bars:
                    row.update(first=bars[0]['date'], last=bars[-1]['date'], sessions=len(bars))
                if details.get('quarantine'):
                    row['status'] = 'quarantined'
                elif findings:
                    row['status'] = 'unresolved_price_gaps'
                elif bars:
                    row['status'] = 'available'
                    # Uniform split units preserve price ratios, turnover and pattern
                    # predicates. No future candle is used to compute a signal.
                    datasets[symbol] = corporate_actions.adjusted_bars(bars, bars[-1]['date'])
                manifest.append(dict(symbol=symbol, isin=item['isin'], **details))
        except (ValueError, KeyError) as error:
            row.update(status='invalid_history', error=str(error))
        coverage[symbol] = row
    print('Coverage:', dict(Counter(c['status'] for c in coverage.values())), flush=True)
    strength = StrengthHistory(datasets, context=lambda symbol, day: datasets[symbol])
    cache, call_cache, all_calls, summaries, configs = {}, {}, [], [], []
    per_symbol = {s: {} for s in coverage}
    for screen in screens:
        cfg = TradingConfig(**(screen.get('trading_defaults') or {k:v for k,v in screen.items() if k in TradingConfig.model_fields}))
        cfg = cfg.model_copy(update=dict(skip_weak_markets=False, sector_filter='off', max_sector_positions=0,
                                        candidate_rank='alphabetical', market_risk_scale=1,
                                        market_breadth_trend_sessions=0, reentry_cooldown_sessions=0,
                                        fee_model='custom_bps', buy_cost_bps=0, sell_cost_bps=0, slippage_bps=0))
        warmup = screen.get('minimum_warmup_sessions') or 50
        configs.append(dict(id=screen['id'], name=screen['name'], original=screen,
                            effective=cfg.model_dump(mode='json'), minimum_warmup_sessions=warmup,
                            ignored_fields=['capital','risk_pct','max_positions','max_hold_days']))
        screen_calls = []
        signal_key = tuple((k,getattr(cfg,k)) for k in strategy_presets.ScreenInput.model_fields if k in TradingConfig.model_fields and k!='name')
        exit_key = tuple(getattr(cfg,k) for k in ('entry_mode','stop_pct','winner_exit','breakeven_r','trail_pct','stalled_exit_sessions','stalled_min_r','failed_breakout_sessions'))
        for symbol, bars in datasets.items():
            calls = []
            key = symbol, signal_key, warmup
            if key not in cache:
                candidates = [i for i in range(warmup,len(bars)) if matches(bars,i,cfg)]
                cache[key] = [i for i in candidates if
                    (not cfg.min_rs_rating or strength.ratings(bars[i]['date'],126).get(symbol,-1)>=cfg.min_rs_rating)
                    and strength.passes(symbol,bars[i]['date'],cfg)]
            for i in cache[key]:
                outcome_key = symbol, i, exit_key
                if outcome_key not in call_cache:
                    call_cache[outcome_key] = outcome(bars,i,cfg)
                call = dict(call_cache[outcome_key], symbol=symbol, screen_id=screen['id'], screen=screen['name'],
                            unique_call_id=hashlib.sha256(repr(outcome_key).encode()).hexdigest()[:20])
                calls.append(call)
            per_symbol[symbol][screen['id']] = summarize(calls)
            screen_calls.extend(calls)
        summary = dict(screen=screen['name'], screen_id=screen['id'], **summarize(screen_calls))
        summaries.append(summary)
        all_calls.extend(screen_calls)
        print(screen['name'], 'signals',summary['signals'],'closed',summary['closed'],'accuracy',summary['accuracy_pct'], flush=True)
        (output/(screen['id']+'_calls.json')).write_text(json.dumps(screen_calls,indent=2),encoding='utf-8')
    unique = {c['unique_call_id']: c for c in all_calls}
    pooled = {s: [] for s in coverage}
    for call in unique.values():
        pooled[call['symbol']].append(call)
    rows, pairs = [], []
    for symbol, c in coverage.items():
        stats = summarize(pooled[symbol])
        years = stats['by_entry_year']
        # Explicit retrospective shortlist, without restricting evaluated calls.
        consistent = (stats['closed'] >= 30 and (stats['wilson_low_pct'] or 0)>50
                      and len(years)>=3 and all(y['accuracy_pct']>=50 for y in years.values() if y['closed']>=5))
        rows.append(dict(symbol=symbol, isin=c['isin'], coverage_status=c['status'], first=c.get('first'),
                         last=c.get('last'), sessions=c.get('sessions',0), consistent_observed=consistent,
                         **stats, per_screen=per_symbol[symbol]))
        for screen in screens:
            pairs.append(dict(symbol=symbol, screen=screen['name'], screen_id=screen['id'],coverage_status=c['status'],
                              **per_symbol[symbol].get(screen['id'],summarize([]))))
    rows.sort(key=lambda r: (r['wilson_low_pct'] if r['wilson_low_pct'] is not None else -1,r['closed']),reverse=True)
    report = dict(created_at=store.now(), universe='niftytotalmarket', stocks=len(items),
                  coverage_counts=dict(Counter(c['status'] for c in coverage.values())),
                  protocol=dict(correct='Positive gross price return at natural stop/profit/trailing exit; flat is not a correct call.',
                                range='All retained history, with each saved screen minimum warmup. No new provider download.',
                                independent_calls=True, overlapping_calls=True, capital=None, position_limit=None,
                                holding_limit=None, market_breadth=False, sector_breadth=False, sector_filter=False,
                                costs=0, slippage=0, end_liquidation=False,
                                pooled='Identical stock/signal-date/exit-rule calls across screens deduplicated; distinct exit rules retained.',
                                shortlist='At least 30 closed calls, Wilson lower bound >50%, at least 3 entry years, and >=50% accuracy in each year with >=5 closed calls.',
                                limitations=['Current constituent universe: survivorship bias.',
                                             'Historical observed frequency, not guaranteed future probability.',
                                             'Overlapping calls and different exits are correlated; Wilson intervals are descriptive, not independence-adjusted.',
                                             'Unfinished calls censored; missing/unverified histories have no estimate.',
                                             'Several saved screens become identical after the requested overrides.',
                                             'Blue Sky highs refer to retained history, not verified lifetime history.']),
                  screens=configs, screen_summaries=summaries, unique_summary=summarize(list(unique.values())),
                  ranked_stocks=rows, consistent_stocks=[r for r in rows if r['consistent_observed']],
                  coverage=list(coverage.values()), manifest=manifest,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    export_csv(output/'all_stocks.csv', [{k:v for k,v in r.items() if k!='per_screen'} for r in rows])
    export_csv(output/'stock_by_screen.csv', pairs)
    export_csv(output/'all_calls.csv', all_calls)
    export_csv(output/'consistent_stocks.csv', [{k:v for k,v in r.items() if k!='per_screen'} for r in report['consistent_stocks']])
    print('UNIQUE',json.dumps(report['unique_summary']), flush=True)
    print('CONSISTENT',len(report['consistent_stocks']),flush=True)
    print('REPORT', output, flush=True)


if __name__ == '__main__':
    main()
