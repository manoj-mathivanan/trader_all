"""Research-only next-open exits on frozen four-indicator inputs; no store writes."""
import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import date
import gzip
import html
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs


@dataclass(frozen=True)
class ExitPlan:
    name: str = 'Supertrend only'
    sma_days: int = 0
    atr_multiple: float = 0
    partial_profit_pct: float = 0
    partial_fraction: float = .5


def plans():
    return ([ExitPlan()] + [ExitPlan(f'SMA{n} exit', sma_days=n) for n in (10,20,30,50,75)]
            + [ExitPlan(f'ATR14 x{k:g} close trail', atr_multiple=k) for k in (2,2.5,3,4,5)]
            + [ExitPlan(f'Half at +{n}%', partial_profit_pct=n) for n in (10,15,20,30,40)]
            + [ExitPlan(f'Half at +{n}% + SMA50', partial_profit_pct=n,sma_days=50) for n in (20,30)]
            + [ExitPlan(f'Half at +{n}% + ATR4', partial_profit_pct=n,atr_multiple=4) for n in (20,30)])


def exit_features(data):
    output = {}
    for symbol,bars in data.items():
        closes = [b['close'] for b in bars]
        ranges, atr, values = [], None, []
        for i,b in enumerate(bars):
            previous = closes[i-1] if i else b['close']
            ranges.append(max(b['high']-b['low'],abs(b['high']-previous),abs(b['low']-previous)))
            if i == 13: atr = math.fsum(ranges)/14
            elif i > 13: atr = (atr*13+ranges[-1])/14
            values.append(dict(atr=atr,**{f'sma{n}': math.fsum(closes[i-n+1:i+1])/n if i >= n-1 else None
                                        for n in (10,20,30,50,75)}))
        output[symbol] = values
    return output


def simulate(data, signals, levels, cfg, plan):
    events = {}
    for symbol,bars in data.items():
        for i,b in enumerate(bars):
            if str(cfg.start) <= b['date'] <= str(cfg.end): events.setdefault(b['date'],{})[symbol] = i
    days = sorted(events)
    cash, peak, drawdown = cfg.capital, cfg.capital, 0
    positions, marks, trades, curve, orders = {}, {}, [], [], []
    fees = slippage = skipped = 0
    slip, buyfee, sellfee = cfg.slippage_bps/10000,cfg.buy_cost_bps/10000,cfg.sell_cost_bps/10000

    def sell(symbol, day, raw, reason, quantity=None):
        nonlocal cash, fees, slippage
        p = positions[symbol]
        q = p['quantity'] if quantity is None else quantity
        price = raw*(1-slip)
        fee = price*q*sellfee
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
            q = math.floor(min(budget,cash)/(price*(1+buyfee)))
            if q <= 0:
                skipped += 1; continue
            fee = price*q*buyfee
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', default='artifacts/four_indicator_year_20261025/frozen.json.gz')
    parser.add_argument('--output', default='artifacts/four_indicator_exits_20261028')
    args = parser.parse_args(); out = Path(args.output); out.mkdir(parents=True,exist_ok=True)
    snapshot = json.loads(gzip.decompress(Path(args.snapshot).read_bytes()))
    frozen, original = snapshot['frozen'], snapshot['report']
    assert fs.digest(frozen) == original['input_sha256']
    data = frozen['datasets']
    cfg = fs.SwingConfig(start=original['config']['start'],end=original['config']['end'],coverage_mode='available_history',
                         capital=1000000,max_positions=10,rsi_threshold=65,bollinger_multiplier=2.5,rule_set='bollinger')
    signals = fs.features(data,lambda x:print(x,flush=True),rsi_threshold=65,bollinger_multiplier=2.5)
    levels = exit_features(data)
    production = fs.simulate(data,signals,cfg,fs.RULES[3])
    baseline = simulate(data,signals,levels,cfg,ExitPlan())
    for k in ('return_pct','max_drawdown_pct','trade_count','net_pnl','modeled_fees','modeled_slippage','skipped_entries'):
        assert abs(baseline['metrics'][k]-production['metrics'][k]) < 1e-7, k
    assert baseline['curve'] == production['curve']
    print('Research engine matches production baseline, including every equity observation.',flush=True)
    configs = plans(); training = []; results = []
    train_cfg = cfg.model_copy(update=dict(end=date(2026,5,29)))
    for p in configs:
        m = simulate(data,signals,levels,train_cfg,p)['metrics']
        training.append(dict(plan=asdict(p),score=m['return_pct']/max(m['max_drawdown_pct'],1) if m['trade_count']>=10 else -1e9,**m))
    selected = max(training,key=lambda x:x['score'])['plan']['name']
    for p in configs:
        full = simulate(data,signals,levels,cfg,p)
        later = simulate(data,signals,levels,cfg.model_copy(update=dict(start=date(2026,6,1))),p)
        row = dict(plan=asdict(p),**full['metrics'],later_return_pct=later['metrics']['return_pct'],
                   later_drawdown_pct=later['metrics']['max_drawdown_pct'],later_trades=later['metrics']['trade_count'])
        may = next(c for c in reversed(full['curve']) if c['date'] <= '2026-05-29')
        row['continuous_later_return_pct'] = (full['metrics']['final_equity']/may['equity']-1)*100
        results.append(row)
        (out/(p.name.replace(' ','_').replace('+','plus').replace('%','pct')+'.json')).write_text(json.dumps(full,indent=2),encoding='utf-8')
        print(f"{p.name}: year {row['return_pct']:.2f}%, DD {row['max_drawdown_pct']:.2f}%, later {row['later_return_pct']:.2f}%",flush=True)
    # Execution stress is evaluated for the baseline and training-selected rule.
    stress=[]
    for p in configs:
        if p.name not in ('Supertrend only',selected): continue
        m = simulate(data,signals,levels,cfg.model_copy(update=dict(slippage_bps=20,buy_cost_bps=20,sell_cost_bps=20)),p)['metrics']
        stress.append(dict(name=p.name,**m))
    result=dict(config=cfg.model_dump(mode='json'),input_sha256=original['input_sha256'],eligible=len(data),
                training_end='2026-05-29',later_start='2026-06-01',selected_on_training=selected,
                training=training,results=results,stress=stress,
                verification=dict(production_baseline=True,every_equity_observation=True,daily_accounting=True),
                methodology=['Every exit, including partial profits and ATR trails, is decided at a completed daily close and fills at the next real open.',
                  'ATR14 trail ratchets from the highest completed close since entry; close at/below the prior ratcheted trail triggers an exit. It is not an intraday protective stop.',
                  'Partial profits sell half the remaining shares once per entry, rounded down, only when at least one share remains. The remainder follows the declared exit.',
                  'Trade counts are completed entry-to-final-exit positions, not sell legs. Partial positions retain their slot.',
                  'All exits retain the original Supertrend reversal as an additional exit. Risk exits take priority over partial profits.',
                  'Newly freed capital can change subsequent entries. These are portfolio reruns, not fixed-entry trade comparisons.',
                  'Time splits are retrospective and already-inspected history; not untouched validation. Later cash-start runs liquidate and reset the portfolio. Continuous later return includes holdings carried from May.',
                  'Current universe, data exclusions, omitted dividends, daily-close drawdowns and proportional fee/slippage assumptions carry over from the original snapshot.'])
    (out/'research.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    flat=[dict(name=r['plan']['name'],**{k:v for k,v in r.items() if k!='plan'}) for r in results]
    with (out/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0])); w.writeheader(); w.writerows(flat)
    cols=[('name','Exit'),('return_pct','Year %'),('max_drawdown_pct','Drawdown %'),('trade_count','Positions'),
          ('partial_positions','Partial positions'),('later_return_pct','Later cash-start %'),('continuous_later_return_pct','Later carry-over %')]
    def table(rows,columns):
        return '<div style="overflow:auto"><table><tr>'+''.join('<th>'+title+'</th>' for _,title in columns)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+(f'{r[k]:,.2f}' if isinstance(r[k],float) else html.escape(str(r[k])))+'</td>' for k,_ in columns)+'</tr>' for r in rows)+'</table></div>'
    page='<html><head><meta charset="utf-8"><title>Earlier exit study</title><style>body{font:16px/1.6 system-ui;max-width:1250px;margin:40px auto;padding:20px;color:#17283f}table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:right;border-bottom:1px solid #ddd}td:first-child,th:first-child{text-align:left}th{background:#edf2fa}</style></head><body>'
    page+='<h1>Earlier exits on the current all-four configuration</h1><p>9 October 2025–9 October 2026. INR 10 lakh, ten positions, RSI14 >65, Bollinger20/2.5, Supertrend10/3, prior-day R1. Same 737 frozen stocks. All decisions use completed daily closes; fills occur at the next session open.</p>'
    page+='<p>Training-only return/drawdown selection through 29 May: <b>'+html.escape(selected)+'</b>. The later cash-start period is 1 June–9 October. It is a retrospective comparison, not untouched prospective evidence.</p>'
    page+=table(flat,cols)+'<h2>Execution stress: 20 bps fees plus 20 bps slippage on each side</h2>'+table(stress,[('name','Exit'),('return_pct','Return %'),('max_drawdown_pct','Drawdown %'),('trade_count','Positions')])
    page+='<h2>Methods and limits</h2><ul>'+''.join('<li>'+html.escape(s)+'</li>' for s in result['methodology'])+'</ul><p>Production baseline and every equity observation matched exactly. Daily and final accounting, allocated fees and sell fill totals reconcile. This script makes no database, paper portfolio or trading setting changes. Per-rule JSON files retain every fill, position trade and equity observation.</p></body></html>'
    (out/'report.html').write_text(page,encoding='utf-8')
    print('Training-selected:',selected,'; saved',out,flush=True)


if __name__ == '__main__': main()
