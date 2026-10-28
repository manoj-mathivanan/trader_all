"""Frozen-input diagnosis and retrospective parameter validation; no trading writes."""
import argparse
import copy
import csv
from collections import Counter, defaultdict
from datetime import date
import gzip
import json
import math
from pathlib import Path
from statistics import mean, median, pstdev
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import store
from core.research import four_indicator_swing as fs

ROLLING = {}


def copy_signals(original):
    return {s:[None if x is None else {**x,'checks':[dict(c) for c in x['checks']]} for x in values]
            for s,values in original.items()}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def atr_signals(data, original, period, multiplier):
    """Change only Supertrend; retain production RSI/R1/Bollinger values."""
    result = copy_signals(original)
    for symbol, bars in data.items():
        atr = upper = lower = trend = None
        ranges = []
        for i, b in enumerate(bars):
            prior = bars[i-1]['close'] if i else b['close']
            tr = max(b['high']-b['low'], abs(b['high']-prior), abs(b['low']-prior))
            ranges.append(tr)
            if i == period-1:
                atr = mean(ranges)
            elif i >= period:
                atr = (atr*(period-1)+tr)/period
            if atr is not None:
                bu = (b['high']+b['low'])/2 + multiplier*atr
                bl = (b['high']+b['low'])/2 - multiplier*atr
                upper = bu if upper is None or bu < upper or prior > upper else upper
                lower = bl if lower is None or bl > lower or prior < lower else lower
                if trend is None:
                    trend = -1
                elif trend == -1 and b['close'] > upper:
                    trend = 1
                elif trend == 1 and b['close'] < lower:
                    trend = -1
            if result[symbol][i]:
                s = result[symbol][i]
                s['checks'][0].update(value=lower if trend == 1 else upper,
                                      passed=trend == 1 and b['close'] > lower)
                s['exit'] = trend != 1
    return result


def modify(data, original, *, rsi=70, bb=2, exit_sma=0, market=None, index=None):
    signals = copy_signals(original)
    for symbol, bars in data.items():
        closes = [b['close'] for b in bars]
        for i, s in enumerate(signals[symbol]):
            if not s:
                continue
            s['checks'][1]['passed'] = s['checks'][1]['value'] is not None and s['checks'][1]['value'] > rsi
            if bb != 2 and i >= 19:
                average = ROLLING[symbol][20][i]
                value = average+(original[symbol][i]['checks'][3]['value']-average)*bb/2
                s['checks'][3].update(value=value, passed=closes[i] > value)
            if exit_sma and i >= exit_sma-1:
                s['exit'] = s['exit'] or closes[i] < ROLLING[symbol][exit_sma][i]
            if market and not market.get(bars[i]['date'], False):
                s['checks'][0]['passed'] = False
    return signals


def describe(result, capital):
    trades, curve = result['trades'], result['curve']
    negative, monthly, last = [], {}, capital
    peak, peak_day, deepest = capital, curve[0]['date'], {}
    underwater_start = None
    for c in curve:
        if c['equity'] < capital:
            negative.append(c['date'])
        key = c['date'][:7]
        if key not in monthly:
            monthly[key] = dict(start_equity=last, end_equity=c['equity'])
        monthly[key]['end_equity'] = c['equity']
        if c['equity'] >= peak:
            peak, peak_day = c['equity'], c['date']
        dd = (peak-c['equity'])/peak*100
        if dd > deepest.get('drawdown_pct', -1):
            deepest = dict(peak_date=peak_day, peak_equity=peak, trough_date=c['date'],
                           trough_equity=c['equity'], drawdown_pct=dd)
        last = c['equity']
    for m in monthly.values():
        m['pnl'] = m['end_equity']-m['start_equity']
        m['return_pct'] = m['pnl']/m['start_equity']*100
    recovery = next((c['date'] for c in curve if c['date'] > deepest['trough_date'] and c['equity'] >= deepest['peak_equity']), None)
    deepest['recovery_date'] = recovery
    exits = defaultdict(lambda: dict(trades=0, pnl=0, wins=0))
    for t in trades:
        x = exits[t['exit_date'][:7]]
        x['trades'] += 1
        x['pnl'] += t['pnl']
        x['wins'] += t['pnl'] > 0
    wins = sorted([t for t in trades if t['pnl'] > 0], key=lambda t:-t['pnl'])
    losses = [t for t in trades if t['pnl'] < 0]
    return dict(monthly_mark_to_market=monthly, monthly_closed_trades=dict(exits),
                below_starting_capital_sessions=len(negative), first_negative=negative[0] if negative else None,
                last_negative=negative[-1] if negative else None,
                minimum_equity=min(curve,key=lambda c:c['equity']), deepest_drawdown=deepest,
                full_capacity_sessions=sum(c['positions'] >= result.get('max_positions', 5) for c in curve[:-1]),
                average_invested_pct=mean((c['equity']-c['cash'])/c['equity']*100 for c in curve),
                average_win=mean(t['pnl'] for t in wins) if wins else None,
                average_loss=mean(t['pnl'] for t in losses) if losses else None,
                gross_winning_pnl=sum(t['pnl'] for t in wins), gross_losing_pnl=sum(t['pnl'] for t in losses),
                top_three_winner_pnl=sum(t['pnl'] for t in wins[:3]),
                pnl_without_top_three=result['metrics']['net_pnl']-sum(t['pnl'] for t in wins[:3]))


def trade_details(result, data):
    out = []
    for t in result['trades']:
        path = [b for b in data[t['symbol']] if t['entry_date'] <= b['date'] <= t['exit_date']]
        # Exit is at the open; exclude exit-day later high/low from excursions.
        observed = path if 'final observed close' in t['reason'] else path[:-1]
        highs = [t['entry'],t['exit']]+[b['high'] for b in observed]
        lows = [t['entry'],t['exit']]+[b['low'] for b in observed]
        row = {k:v for k,v in t.items() if k != 'signal'}
        row.update(holding_calendar_days=(date.fromisoformat(t['exit_date'])-date.fromisoformat(t['entry_date'])).days,
                   holding_sessions=len(path), mfe_pct=(max(highs)/t['entry']-1)*100,
                   mae_pct=(min(lows)/t['entry']-1)*100,
                   signal_rsi=t['signal']['checks'][1]['value'],
                   gap_pct=(t['entry']/1.001/t['signal']['close']-1)*100)
        out.append(row)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', default='df20e2244b8c')
    parser.add_argument('--output', default='artifacts/four_indicator_year_20261025')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    cache = out/'frozen.json.gz'
    if cache.exists():
        saved = json.loads(gzip.decompress(cache.read_bytes()))
        report, frozen, index = saved['report'], saved['frozen'], saved['index']
    else:
        report = store.read('runs/'+args.run_id)
        frozen = store.read('run_data/'+args.run_id)
        index = store.read('bars/NIFTY50',{}).get('bars',[])
        cache.write_bytes(gzip.compress(json.dumps(dict(report=report,frozen=frozen,index=index)).encode()))
    assert report['id'] == args.run_id
    assert fs.digest(frozen) == report['input_sha256'], 'Frozen input checksum failed'
    data = frozen['datasets']
    cfg = fs.SwingConfig(**{**report['config'], **fs.stored_parameters(report['config'])})
    signals = fs.features(data, lambda x: print(x,flush=True))
    for symbol, bars in data.items():
        closes = [b['close'] for b in bars]
        ROLLING[symbol] = {n:[math.fsum(closes[i-n+1:i+1])/n if i >= n-1 else None for i in range(len(bars))]
                           for n in (10,20,50)}
        for i in range(20,len(bars)):
            if not signals[symbol][i]:
                continue
            for multiplier in (1.5,2.5):
                window = closes[i-19:i+1]
                direct = mean(window)+multiplier*pstdev(window)
                average = ROLLING[symbol][20][i]
                fast = average+(signals[symbol][i]['checks'][3]['value']-average)*multiplier/2
                assert abs(direct-fast)<max(1e-7,abs(direct)*1e-12)
                assert (closes[i]>direct)==(closes[i]>fast), 'Bollinger threshold parity failed'
    baseline = fs.simulate(data, signals, cfg, fs.RULES[3])
    for key in ('return_pct','max_drawdown_pct','trade_count','net_pnl'):
        assert abs(baseline['metrics'][key]-report['metrics'][key]) < 1e-7, key
    alternate_default = atr_signals(data,signals,10,3)
    assert all(a == b for s in signals for a,b in zip(signals[s],alternate_default[s])), 'Supertrend parity failed'
    del alternate_default
    print('Frozen baseline and generalized Supertrend verified.',flush=True)
    rows, details = [], []
    def run(label, sig=signals, rule=fs.RULES[3], **updates):
        conf = cfg.model_copy(update=updates)
        r = fs.simulate(data,sig,conf,rule)
        assert abs(sum(t['pnl'] for t in r['trades'])-r['metrics']['net_pnl']) < 1e-5
        row = dict(label=label,capital=conf.capital,max_positions=conf.max_positions,**r['metrics'])
        rows.append(row)
        return r
    # Separate portfolio capacity from entry quality.
    for rule in fs.RULES:
        for positions in (3,5,8,10,15,20,30):
            run(f'capacity:{rule[0]}:{positions}',rule=rule,max_positions=positions)
    print('35 rule/capacity comparisons complete.',flush=True)
    for capital in (50000,100000,250000,500000,1000000,2500000,5000000):
        for positions in (5,10,20):
            run(f'capital:{int(capital)}:{positions}',capital=capital,max_positions=positions)
    for bps in (0,5,10,20,30):
        run(f'cost:{bps}',slippage_bps=bps,buy_cost_bps=bps,sell_cost_bps=bps)
    # Declare all selection candidates before evaluating either subperiod.
    candidates = []
    for positions in (5,10,20):
        for rsi in (60,65,70,75):
            for bb in (1.5,2,2.5):
                candidates.append(dict(label=f'entry:p{positions}:rsi{rsi}:bb{bb}',positions=positions,rsi=rsi,bb=bb))
    for sma in (10,20,50):
        candidates.append(dict(label=f'exit:sma{sma}',positions=5,exit_sma=sma))
    for period in (7,10,14):
        for mult in (2,2.5,3,3.5,4):
            candidates.append(dict(label=f'supertrend:{period}:{mult}',positions=5,period=period,mult=mult))
    for period in (50,200):
        candidates.append(dict(label=f'market:sma{period}',positions=5,market_period=period))
    candidates.append(dict(label='baseline',positions=5))
    signal_cache = {}
    def candidate_signals(c):
        params = {k:v for k,v in c.items() if k not in ('label','positions')}
        key = json.dumps(params,sort_keys=True)
        if key in signal_cache:
            return signal_cache[key]
        sig = signals
        if 'period' in params:
            sig = atr_signals(data,signals,params.pop('period'),params.pop('mult'))
        if 'market_period' in params:
            n = params.pop('market_period')
            params['market'] = {b['date']: b['close'] > mean(x['close'] for x in index[i-n+1:i+1])
                                for i,b in enumerate(index) if i >= n-1}
        if params:
            sig = modify(data,sig,**params)
        signal_cache.clear()
        signal_cache[key] = sig
        return sig
    train_end, test_start = '2026-05-29','2026-06-01'
    train_cfg = cfg.model_copy(update=dict(end=date.fromisoformat(train_end)))
    train = []
    for number,c in enumerate(candidates,1):
        r = fs.simulate(data,candidate_signals(c),train_cfg.model_copy(update=dict(max_positions=c['positions'])),fs.RULES[3])
        m = r['metrics']
        score = m['return_pct']/max(m['max_drawdown_pct'],1) if m['trade_count'] >= 10 else -1e9
        train.append(dict(label=c['label'],score=score,**m))
        if number%10 == 0:
            print(f'Training comparisons: {number}/{len(candidates)}',flush=True)
    selected = max(train,key=lambda x:x['score'])['label']
    print('Training-only selection:',selected,flush=True)
    validation = []
    for number,c in enumerate(candidates,1):
        sig = candidate_signals(c)
        r = run(c['label'],sig,max_positions=c['positions'])
        test_cfg = cfg.model_copy(update=dict(start=date.fromisoformat(test_start),max_positions=c['positions']))
        t = fs.simulate(data,sig,test_cfg,fs.RULES[3])
        validation.append(dict(label=c['label'],**t['metrics']))
        if number%15 == 0:
            print(f'Parameter and validation comparisons: {number}/{len(candidates)}',flush=True)
    ledgers = trade_details(baseline,data)
    with (out/'baseline_trades.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(ledgers[0])); w.writeheader(); w.writerows(ledgers)
    with (out/'experiments.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    benchmark = [b for b in index if str(cfg.start) <= b['date'] <= str(cfg.end)]
    result = dict(reference_run_id=args.run_id,input_sha256=report['input_sha256'],config=report['config'],
        eligible=len(data),excluded=frozen['exclusion_reasons'],history_fragments=frozen.get('history_fragments',{}),
        late_eligible={s:v for s,v in frozen.get('coverage',{}).items() if v['eligible_from'] > str(cfg.start)},
        verification=dict(frozen_hash=True,baseline_reproduced=True,supertrend_parity=True,all_experiment_accounting=True),
        benchmark=dict(label='Cached Nifty50 price return, no dividends',start=benchmark[0]['date'],end=benchmark[-1]['date'],
                       return_pct=(benchmark[-1]['close']/benchmark[0]['close']-1)*100),
        baseline=baseline,diagnosis=describe(baseline,cfg.capital),trades=ledgers,experiments=rows,
        retrospective_validation=dict(train_end=train_end,test_start=test_start,selection_metric='training return/max(drawdown,1), >=10 training trades',
            candidate_count=len(candidates),selected=selected,train=train,validation=validation,
            note='Retrospective time split; not untouched prospective evidence. Each subperiod starts in cash; training positions are liquidated, not carried into validation. Universe eligibility was determined on the original full-year frozen snapshot.'),
        limitations=report['warnings'])
    dump(out/'research.json',result)
    print(json.dumps(dict(metrics=baseline['metrics'],diagnosis=result['diagnosis'],experiments=len(rows),
                          selected=selected,selected_test=next(x for x in validation if x['label']==selected)),indent=2),flush=True)


if __name__ == '__main__':
    main()
