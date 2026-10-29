"""Research-only entry/exit timing comparison on verified frozen daily prices."""
import gzip
import json
import math
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs
from core.execution.upstox import equity_charges, size_order, breakeven_price

OUT = Path('artifacts/entry_breakeven_20261029')


def simulate(data, signals, cfg, rule, activation=None, cost_cover=False):
    events = {}
    for s, bars in data.items():
        for i, b in enumerate(bars):
            if str(cfg.start) <= b['date'] <= str(cfg.end):
                events.setdefault(b['date'], {})[s] = i
    cash = peak = cfg.capital
    dd = fees = slippage = 0
    positions, marks, trades, curve = {}, {}, [], []
    slip = cfg.slippage_bps/10000

    def close(s, raw, day, reason):
        nonlocal cash, fees, slippage
        p = positions.pop(s)
        fill = raw*(1-slip)
        if p['day'] == day:
            actual=equity_charges(p['entry'],p['q'],'buy',day,intraday=True)['total']
            correction=actual-p['entry_fee']
            cash-=correction;fees+=correction;p['cost']+=correction;p['entry_fee']=actual
        fee = equity_charges(fill,p['q'],'sell',day,intraday=p['day']==day)['total']
        cash += fill*p['q']-fee
        fees += fee
        slippage += (raw-fill)*p['q']
        trades.append(dict(symbol=s,entry_date=p['day'],exit_date=day,entry=p['entry'],exit=fill,
                           quantity=p['q'],pnl=fill*p['q']-fee-p['cost'],reason=reason))

    days = sorted(events)
    for day in days:
        available, exited = events[day], set()
        # All stop activations use a prior completed post-entry close.
        for s in sorted(positions):
            if s not in available:
                continue
            p, i = positions[s], available[s]
            prev = data[s][i-1]
            if activation is not None and prev['date'] >= p['day'] and prev['close'] >= p['entry']*(1+activation/100):
                p['armed'] = True
            if signals[s][i-1] and signals[s][i-1]['exit']:
                close(s, data[s][i]['open'], day, 'Supertrend')
                exited.add(s)
            elif p['armed'] and data[s][i]['open'] <= p['stop']:
                close(s, data[s][i]['open'], day, 'Breakeven gap')
                exited.add(s)
        candidates = []
        for s, i in available.items():
            if s in positions or s in exited or i < 100 or data[s][i-1]['date'] < str(cfg.start):
                continue
            signal = signals[s][i-1]
            if signal and all(signal['checks'][j]['passed'] for j in rule[2]):
                candidates.append((-(data[s][i-1]['close']*data[s][i-1]['volume']), s, i))
        equity_open = cash+sum(p['q']*(data[s][available[s]]['open'] if s in available else marks[s]) for s,p in positions.items())
        budget = equity_open/cfg.max_positions
        for _, s, i in sorted(candidates):
            if len(positions) >= cfg.max_positions:
                continue
            raw = data[s][i]['open']
            entry = raw*(1+slip)
            q = size_order(equity_open,min(budget,cash),entry,entry,100,day)
            if q <= 0:
                continue
            fee = equity_charges(entry,q,'buy',day)['total']
            cost = entry*q+fee
            cash -= cost
            fees += fee
            slippage += (entry-raw)*q
            # Stop quoted before sell slippage. Gaps still fill at the open.
            stop = breakeven_price(cost,q,day,cfg.slippage_bps) if cost_cover else entry
            positions[s] = dict(q=q,entry=entry,cost=cost,entry_fee=fee,day=day,stop=stop,
                                armed=activation == 0)
        # Intraday lows test only stops known before that low; no high/low ordering assumption.
        for s in list(positions):
            if s not in available:
                continue
            p, b = positions[s], data[s][available[s]]
            if p['armed'] and b['low'] <= p['stop']:
                # On entry day an immediately active stop above the raw open triggers immediately.
                raw = min(b['open'],p['stop']) if p['day'] == day else p['stop']
                close(s,raw,day,'Breakeven stop')
        for s,i in available.items():
            marks[s] = data[s][i]['close']
        for s in list(positions):
            i = available.get(s)
            if i is not None and (day == days[-1] or i+1 == len(data[s])):
                close(s,data[s][i]['close'],day,'End of backtest')
        equity = cash+sum(p['q']*marks[s] for s,p in positions.items())
        assert abs(equity-(cfg.capital+sum(t['pnl'] for t in trades)+sum(p['q']*marks[s]-p['cost'] for s,p in positions.items()))) < 1e-5
        assert cash >= -.001 and len(positions) <= cfg.max_positions
        peak = max(peak,equity)
        dd = max(dd,(peak-equity)/peak*100)
        curve.append(dict(date=day,equity=equity,cash=cash,positions=len(positions)))
    assert not positions
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [t['pnl'] for t in trades if t['pnl'] < 0]
    return dict(trades=trades,curve=curve,metrics=dict(return_pct=(cash/cfg.capital-1)*100,
        max_drawdown_pct=dd,trade_count=len(trades),win_rate=len(wins)/len(trades)*100 if trades else None,
        profit_factor=sum(wins)/-sum(losses) if losses else None,modeled_fees=fees,modeled_slippage=slippage))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    snap = json.loads(gzip.decompress(Path('artifacts/four_indicator_year_20261025/frozen.json.gz').read_bytes()))
    assert fs.digest(snap['frozen']) == snap['report']['input_sha256']
    data = snap['frozen']['datasets']
    cfg = fs.SwingConfig(start=snap['report']['config']['start'],end=snap['report']['config']['end'],coverage_mode='available_history')
    signals = fs.features(data,lambda x:print(x,flush=True),rsi_threshold=65,bollinger_multiplier=2.5)
    baseline = simulate(data,signals,cfg,fs.RULES[3])
    production = fs.simulate(data,signals,cfg,fs.RULES[3])
    assert baseline['curve'] == production['curve']
    for k in baseline['metrics']:
        assert abs(baseline['metrics'][k]-production['metrics'][k]) < 1e-7, k
    trials = [('Current all-four entry / Supertrend exit',3,None,False),
              ('Earlier: Supertrend + RSI + R1',2,None,False),
              ('Earlier: Supertrend + RSI',1,None,False),
              ('Earlier: Supertrend alone',0,None,False),
              ('Entry-price stop immediately',3,0,False)]
    trials += [(f'Entry-price stop after +{n}% close',3,n,False) for n in (2,5,10)]
    trials += [('Cost-covering stop after +5% close',3,5,True)]
    results = []
    for n,(name,r,activation,cover) in enumerate(trials):
        full = simulate(data,signals,cfg,fs.RULES[r],activation,cover)
        later = simulate(data,signals,cfg.model_copy(update={'start':date(2026,6,1)}),fs.RULES[r],activation,cover)
        results.append(dict(name=name,**full['metrics'],later_return_pct=later['metrics']['return_pct'],later_trades=later['metrics']['trade_count']))
        (OUT/f'trial_{n}.json').write_text(json.dumps(full),encoding='utf-8')
        print(json.dumps(results[-1]),flush=True)
    # Fixed baseline entries: favorable excursion and return-to-entry before natural exit.
    diagnostic = []
    for t in baseline['trades']:
        bars = [b for b in data[t['symbol']] if t['entry_date'] <= b['date'] <= t['exit_date']]
        # Exclude exit day: its high can occur after the actual open exit.
        prior = [b for b in bars if b['date'] < t['exit_date']]
        best = max((b['high'] for b in prior),default=t['entry'])
        diagnostic.append(dict(**t,best_pre_exit_gain_pct=(best/t['entry']-1)*100))
    losers = [t for t in diagnostic if t['pnl']<0]
    result = dict(config=cfg.model_dump(mode='json'),eligible=len(data),input_sha256=snap['report']['input_sha256'],
        baseline_parity=True,results=results,losing_trades=len(losers),
        losers_previously_up_5pct=sum(t['best_pre_exit_gain_pct']>=5 for t in losers),
        caveats=['Retrospective inspected history; later period is not untouched validation.',
                 'Current universe and frozen snapshot exclusions carry over; no dividends.',
                 'Upstox Plus fees and 10 bps slippage per side; daily-close drawdowns.',
                 'Stops can gap below entry; stop activation after profit uses completed closes and starts next session.',
                 'Immediate stop at the slipped entry is already above the raw purchase open and churns immediately.',
                 'Portfolio reruns change subsequent entries; fixed-entry excursion diagnostic is separate.'])
    (OUT/'research.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('CONFIG',json.dumps(result['config']), 'ELIGIBLE',len(data),'LOSERS',len(losers),'UP5',result['losers_previously_up_5pct'],flush=True)


if __name__ == '__main__':
    main()
