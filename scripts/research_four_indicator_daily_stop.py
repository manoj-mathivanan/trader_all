"""Research-only daily close loss exits, retaining next-open execution."""
import argparse
from dataclasses import dataclass, asdict
import gzip
from html import escape
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs
from scripts.research_four_indicator_exits import exit_features
import math

@dataclass(frozen=True)
class StopPlan:
    name: str = 'Supertrend only'
    stop_pct: float = 0
    sma_days: int = 0
    atr_multiple: float = 0
    partial_profit_pct: float = 0
    partial_fraction: float = .5

def simulate(data, signals, levels, cfg, plan):
    events = {}
    for symbol,bars in data.items():
        for i,b in enumerate(bars):
            if str(cfg.start) <= b['date'] <= str(cfg.end): events.setdefault(b['date'],{})[symbol] = i
    days = sorted(events)
    cash, peak, drawdown = cfg.capital, cfg.capital, 0
    positions, marks, trades, curve, orders = {}, {}, [], [], []
    from core.execution.upstox import equity_charges, size_order
    dp_charged = set()
    fees = slippage = skipped = 0
    slip, buyfee, sellfee = cfg.slippage_bps/10000,cfg.buy_cost_bps/10000,cfg.sell_cost_bps/10000

    def sell(symbol, day, raw, reason, quantity=None):
        nonlocal cash, fees, slippage
        p = positions[symbol]
        q = p['quantity'] if quantity is None else quantity
        price = raw*(1-slip)
        fee = equity_charges(price,q,'sell',day,dp=(symbol,day) not in dp_charged)['total']
        dp_charged.add((symbol,day))
        allocated_fee = p['remaining_entry_fee']*q/p['quantity']
        pnl = (price-p['entry'])*q-allocated_fee-fee
        cash += price*q-fee
        fees += fee
        slippage += (raw-price)*q
        p['quantity'] -= q
        p['remaining_entry_fee'] -= allocated_fee
        p['realized_pnl'] += pnl
        p['exit_fees'] += fee
        orders.append(dict(symbol=symbol,side='SELL',date=day,price=price,quantity=q,fees=fee,reason=reason))
        if p['quantity'] == 0:
            trades.append(dict(symbol=symbol,entry_date=p['entry_date'],exit_date=day,entry=p['entry'],exit=price,
                               quantity=p['original_quantity'],pnl=p['realized_pnl'],fees=p['entry_fee']+p['exit_fees'],
                               return_pct=p['realized_pnl']/p['entry_cost']*100,partial_taken=p['partial_taken'],reason=reason))
            del positions[symbol]

    for day in days:
        available, exited = events[day], set()
        for symbol in sorted(positions):
            if symbol not in available: continue
            i = available[symbol]
            if not i: continue
            previous, feature = data[symbol][i-1], levels[symbol][i-1]
            signal, p = signals[symbol][i-1], positions[symbol]
            # All additional decisions use a completed post-entry candle.
            reason = 'Supertrend reversal' if signal and signal['exit'] else None
            if previous['date'] >= p['entry_date']:
                if plan.stop_pct and previous['close'] <= p['entry']*(1-plan.stop_pct/100):
                    reason = reason or f'{plan.stop_pct:g}% loss at daily close'
                if plan.sma_days and previous['close'] < feature[f'sma{plan.sma_days}']:
                    reason = reason or f'SMA{plan.sma_days} close exit'
                if plan.atr_multiple and feature['atr'] is not None:
                    p['highest_close'] = max(previous['close'], p['highest_close'] or previous['close'])
                    level = p['highest_close']-plan.atr_multiple*feature['atr']
                    p['trail'] = max(level,p['trail']) if p['trail'] is not None else level
                    if previous['close'] <= p['trail']: reason = reason or 'ATR close trail'
            if reason:
                sell(symbol,day,data[symbol][i]['open'],reason+' · next open')
                exited.add(symbol)
            elif (plan.partial_profit_pct and not p['partial_taken'] and previous['date'] >= p['entry_date']
                  and (previous['close']/p['entry']-1)*100 >= plan.partial_profit_pct):
                q = math.floor(p['quantity']*plan.partial_fraction)
                if 0 < q < p['quantity']:
                    sell(symbol,day,data[symbol][i]['open'],f'Partial at +{plan.partial_profit_pct:g}% close · next open',q)
                    p['partial_taken'] = True
        candidates = []
        for symbol,i in available.items():
            if symbol in positions or symbol in exited or i < 100: continue
            previous = data[symbol][i-1]
            if previous['date'] < str(cfg.start): continue
            signal = signals[symbol][i-1]
            if signal and all(c['passed'] for c in signal['checks']):
                candidates.append((-(previous['close']*previous['volume']),symbol,i))
        equity_open = cash+sum(p['quantity']*(data[s][available[s]]['open'] if s in available else marks[s]) for s,p in positions.items())
        budget = equity_open/cfg.max_positions
        for _,symbol,i in sorted(candidates):
            if len(positions) >= cfg.max_positions:
                skipped += 1; continue
            raw = data[symbol][i]['open']; price = raw*(1+slip)
            q = size_order(equity_open,min(budget,cash),price,price,100,day)
            if q <= 0:
                skipped += 1; continue
            fee = equity_charges(price,q,'buy',day)['total']
            cash -= price*q+fee; fees += fee; slippage += (price-raw)*q
            positions[symbol] = dict(entry=price,entry_date=day,quantity=q,original_quantity=q,
                entry_fee=fee,remaining_entry_fee=fee,entry_cost=price*q+fee,realized_pnl=0,exit_fees=0,
                partial_taken=False,highest_close=None,trail=None)
            orders.append(dict(symbol=symbol,side='BUY',date=day,price=price,quantity=q,fees=fee))
        for symbol,i in available.items(): marks[symbol] = data[symbol][i]['close']
        for symbol in list(positions):
            i = available.get(symbol)
            if i is not None and (day == days[-1] or i+1 == len(data[symbol])):
                sell(symbol,day,data[symbol][i]['close'],'End of backtest · final observed close')
        equity = cash+sum(p['quantity']*marks[s] for s,p in positions.items())
        accounted = cfg.capital+sum(t['pnl'] for t in trades)+sum(
            p['realized_pnl']+p['quantity']*(marks[s]-p['entry'])-p['remaining_entry_fee'] for s,p in positions.items())
        assert abs(equity-accounted) < 1e-5, 'Daily partial-fill accounting failed'
        assert cash >= -.001 and len(positions) <= cfg.max_positions
        peak = max(peak,equity); drawdown = max(drawdown,(peak-equity)/peak*100)
        curve.append(dict(date=day,equity=equity,cash=cash,positions=len(positions)))
    assert not positions
    assert abs(cash-cfg.capital-sum(t['pnl'] for t in trades)) < 1e-5
    assert abs(fees-sum(o['fees'] for o in orders)) < 1e-5
    wins, losses = [t['pnl'] for t in trades if t['pnl']>0], [t['pnl'] for t in trades if t['pnl']<0]
    return dict(trades=trades,curve=curve,orders=orders,metrics=dict(final_equity=cash,net_pnl=cash-cfg.capital,
        return_pct=(cash/cfg.capital-1)*100,max_drawdown_pct=drawdown,trade_count=len(trades),
        sell_fill_count=sum(o['side']=='SELL' for o in orders),partial_positions=sum(t['partial_taken'] for t in trades),
        win_rate=len(wins)/len(trades)*100 if trades else None,profit_factor=sum(wins)/-sum(losses) if losses else None,
        modeled_fees=fees,modeled_slippage=slippage,skipped_entries=skipped))


def main():
    import hashlib
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=Path('artifacts/four_indicator_year_20261025/frozen.json.gz'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/four_indicator_daily_stop_20261030'))
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    snapshot = json.loads(gzip.decompress(args.snapshot.read_bytes()))
    frozen, original = snapshot['frozen'], snapshot['report']
    if fs.digest(frozen) != original['input_sha256']: raise ValueError('Frozen checksum mismatch')
    data = frozen['datasets']
    cfg = fs.SwingConfig(start=original['config']['start'],end=original['config']['end'],coverage_mode='available_history',
                        capital=1000000,max_positions=10,rsi_threshold=65,bollinger_multiplier=2.5,rule_set='bollinger')
    plans = [StopPlan()] + [StopPlan(f'{n:g}% daily-close loss exit',n) for n in (2,3,5,7.5,10)]
    from datetime import date
    periods = [('full',cfg),('earlier',cfg.model_copy(update=dict(end=date(2026,5,29)))),
               ('later',cfg.model_copy(update=dict(start=date(2026,6,1))))]
    plan = dict(config=cfg.model_dump(mode='json'),input_sha256=original['input_sha256'],eligible_symbols=len(data),
                plans=[asdict(p) for p in plans],source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                methodology=[
                    'Daily swing study separate from five-minute intrabar protective-stop study.',
                    'Fixed entry-loss threshold checked at completed daily closes; exits fill at the following real open with fees and slippage.',
                    'A daily-close loss threshold is not an intraday stop; realized loss may exceed it due to gaps, daily confirmation and costs.',
                    'Retains existing Supertrend exit, sizing, current universe and frozen daily snapshot; baseline equity curve verified exactly.',
                    'Chronological cash-start periods are retrospective diagnostics on previously inspected data; not untouched validation.',
                    'Daily engine retains delivery fee assumptions, daily close drawdown, omitted dividends and survivorship limitations.',
                    'Portfolio reruns can change later entries. No live or paper settings changed.'
                ])
    (args.output/'frozen-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    signals = fs.features(data,lambda s:print(s,flush=True),rsi_threshold=65,bollinger_multiplier=2.5)
    levels = exit_features(data)
    results=[]
    for label,settings in periods:
        production = fs.simulate(data,signals,settings,fs.RULES[3])
        for p in plans:
            result = simulate(data,signals,levels,settings,p)
            if p.stop_pct == 0:
                if result['curve'] != production['curve']: raise ValueError('Baseline curve mismatch')
                for key in ('return_pct','max_drawdown_pct','trade_count','net_pnl','modeled_fees','modeled_slippage','skipped_entries'):
                    if abs(result['metrics'][key]-production['metrics'][key]) > 1e-7: raise ValueError('Baseline metric mismatch: '+key)
            returns = [t['return_pct'] for t in result['trades']]
            losses = [r for r in returns if r < 0]
            row = dict(period=label,plan=asdict(p),**result['metrics'],mean_loss_pct=sum(losses)/len(losses) if losses else None,
                       worst_trade_pct=min(returns) if returns else None,
                       early_stop_exits=sum('loss at daily close' in t['reason'] for t in result['trades']))
            results.append(row)
            (args.output/(label+'_'+str(p.stop_pct).replace('.','p')+'.json')).write_text(json.dumps(result),encoding='utf-8')
            print(json.dumps(row),flush=True)
    (args.output/'comparison.json').write_text(json.dumps(dict(plan=plan,results=results),indent=2),encoding='utf-8')
    columns = ['period','stop_pct','return_pct','max_drawdown_pct','trade_count','win_rate','profit_factor','mean_loss_pct','worst_trade_pct','early_stop_exits']
    rows = [dict(r,stop_pct=r['plan']['stop_pct']) for r in results]
    import csv
    with (args.output/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    page = '<!doctype html><meta charset="utf-8"><title>Daily four-rule early exits</title><style>body{font:16px/1.6 system-ui;max-width:1250px;margin:40px auto;padding:20px;color:#193044}table{border-collapse:collapse;width:100%}td,th{padding:9px;border:1px solid #ddd;text-align:right}th{background:#eaf3f4}</style><h1>Daily four-rule loss exits</h1><p>9 October 2025–9 October 2026 · 737 frozen stocks · INR 10 lakh · ten positions. 0% means Supertrend exit only. Earlier cash-start: through 29 May 2026; later cash-start: from 1 June 2026.</p><p>These thresholds require a completed daily close; they are not resting intraday stops. Every exit fills at the next observed open.</p><table><tr>'+''.join('<th>'+escape(c)+'</th>' for c in columns)+'</tr>'
    for r in rows:
        page += '<tr>'+''.join('<td>'+escape(f'{r[c]:,.2f}' if isinstance(r[c],float) else str(r[c]))+'</td>' for c in columns)+'</tr>'
    page += '</table><h2>Methods and limits</h2><ul>'+''.join('<li>'+escape(m)+'</li>' for m in plan['methodology'])+'</ul><p><a href="comparison.json">Complete results</a> · <a href="comparison.csv">CSV</a></p>'
    (args.output/'report.html').write_text(page,encoding='utf-8')


if __name__ == '__main__': main()
