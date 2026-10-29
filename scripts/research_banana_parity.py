"""Isolated BananaPatterns execution comparison; never changes paper defaults.

The public execution rules were inspected on 12 October 2026. The site's
base detector and RS recipe are unknown: signals here remain local proxies.
"""
import argparse
import hashlib
import json
import math
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import backtest, corporate_actions, market_history
from core.research.config import BacktestConfig
from strategies.swing_patterns.patterns.signals import matches, vcp_setup


def simulate(data, cfg, *, exits='reference', setup='confirmed', entry='next_open',
             ranking='rs', min_rs=0, turnover_floor=0, cost_bps=25,
             same_day='conservative', cap_pct=30, turnover_pct=10, rs_method='126'):
    """Cash portfolio with yesterday's decisions and next-day sale settlement.

    confirmed: original local completed-close signals, bought next open.
    setup: local three-window VCP setup, prior-window high/close pivot crossed
    today. No claim of reproducing the proprietary base/lifecycle algorithm.
    """
    days = {}
    indices = {s: {b['date']: i for i, b in enumerate(rows)} for s, rows in data.items()}
    for s, rows in data.items():
        for i, b in enumerate(rows):
            if str(cfg.start) <= b['date'] <= str(cfg.end):
                days.setdefault(b['date'], {})[s] = (i, b)
    cash, unsettled = cfg.capital, 0.0
    positions, marks, trades, curve = {}, {}, [], []
    rejected = Counter()
    peak, drawdown, fees, exposure = cash, 0.0, 0.0, []
    from core.execution.upstox import equity_charges, size_order, breakeven_price
    rs_cache = {}

    def context(s, day):
        return corporate_actions.adjusted_bars(data[s], day)

    def rs(day):
        if day not in rs_cache:
            returns = {}
            for s in data:
                j = indices[s].get(day)
                lookback = 252 if rs_method=='weighted' else 126
                if j is not None and j >= lookback:
                    rows = context(s, day)
                    returns[s] = (sum(w*(rows[j]['close']/rows[j-n]['close']-1)
                                  for w,n in [(0.4,63),(0.2,126),(0.2,189),(0.2,252)])
                                  if rs_method=='weighted' else rows[j]['close']/rows[j-126]['close']-1)
            values = sorted(returns.values())
            ranks = {s: (bisect_left(values, r)+bisect_right(values, r)-1)/2
                         /max(len(values)-1, 1) for s,r in returns.items()}
            rs_cache[day] = {s: 1+98*r if rs_method=='weighted' else 100*r for s,r in ranks.items()}
        return rs_cache[day]

    def close(s, price, day, reason):
        nonlocal unsettled, fees
        p = positions.pop(s)
        charge = equity_charges(price,p['quantity'],'sell',day,intraday=p['entry_date']==day)['total']
        proceeds = p['quantity'] * price - charge
        unsettled += proceeds
        fees += charge
        trades.append(dict(symbol=s, entry_date=p['entry_date'], exit_date=day,
                           entry=p.get('entry_fill', p['entry']), exit=price,
                           quantity=p.get('entry_quantity', p['quantity']),
                           pnl=proceeds-p['entry_cost'], reason=reason,
                           fees=p['entry_fee']+charge))

    for day, session in sorted(days.items()):
        cash += unsettled
        unsettled = 0
        exited = set()
        for s, p in list(positions.items()):
            for action in corporate_actions.actions(data[s]):
                if action['ex_date'] == day and action['price_basis'] == 'raw':
                    positions[s], marks[s] = corporate_actions.rebase_position(p, marks[s], action)
                    p = positions[s]
            if s not in session:
                continue
            i, b = session[s]
            if b['high'] == b['low']:
                if b['low'] <= p['stop'] or p.get('pending'):
                    p['pending'] = 'Deferred locked-circuit exit'
                continue
            if p.get('pending') or b['open'] <= p['stop']:
                close(s, b['open'], day, p.get('pending', 'Gap through stop'))
                exited.add(s)
        equity_open = cash + unsettled + sum(p['quantity']*session[s][1]['open']
                      if s in session else p['quantity']*marks[s] for s,p in positions.items())
        candidates = []
        for s, (i, b) in session.items():
            if i < max(cfg.minimum_warmup_sessions, backtest.required_warmup(cfg))+1:
                continue
            prior_day = data[s][i-1]['date']
            rows = context(s, day)
            prior_rows = context(s, prior_day)
            pivot = None
            if setup == 'confirmed':
                qualified = matches(prior_rows, i-1, cfg)
            else:
                field = 'close' if setup in ('setup_close','atr30_close') else 'high'
                length = 30 if setup=='atr30_close' else cfg.vcp_window_days
                window=prior_rows[i-1-length:i-1]
                pivot = max(x[field] for x in window)
                if setup=='atr30_close':
                    # Declared fixed-window approximation, not detected bases.
                    first,second=window[:15],window[15:]
                    def tr_pct(j):
                        row=prior_rows[j]
                        return max(row['high']-row['low'],abs(row['high']-prior_rows[j-1]['close']),
                                   abs(row['low']-prior_rows[j-1]['close']))/row['close']
                    atr1=sum(tr_pct(j) for j in range(i-31,i-16))/15
                    atr2=sum(tr_pct(j) for j in range(i-16,i-1))/15
                    volume1=sum(x['volume'] for x in first)
                    high=max(x['high'] for x in prior_rows[max(0,i-253):i])
                    low=min(x['low'] for x in prior_rows[max(0,i-253):i])
                    price=prior_rows[i-1]['close']
                    qualified=(atr1>0 and atr2/atr1<=.9 and volume1>0
                        and sum(x['volume'] for x in second)/volume1<=.9
                        and (max(x['high'] for x in window)-min(x['low'] for x in window))
                            /max(x['high'] for x in window)*100<=35
                        and price>=sum(x['close'] for x in prior_rows[i-50:i])/50
                        and price>=sum(x['close'] for x in prior_rows[i-200:i])/200
                        and price>=high*.7 and price>=low*1.15)
                else:
                    qualified = vcp_setup(prior_rows, i-1, cfg)
                # Setup is fixed yesterday; current high only triggers the order.
                if entry == 'pivot':
                    qualified = qualified and prior_rows[i-1]['close'] <= pivot
                    pivot = max(x[field] for x in rows[i-1-length:i-1])
                    qualified = qualified and b['high'] > pivot
                else:
                    # A completed breakout yesterday, then today's open.
                    qualified = qualified and prior_rows[i-1]['close'] > pivot
            if not qualified:
                continue
            strength = rs(prior_day).get(s, -1)
            liquidity = median(x['close']*x['volume'] for x in prior_rows[max(0,i-21):i-1])
            if strength < min_rs or liquidity < turnover_floor:
                rejected['RS / liquidity'] += 1
                continue
            candidates.append((s, strength, liquidity, pivot))
        candidates.sort(key=lambda x: (-x[1],-x[2],x[0]) if ranking=='rs' else (x[0],))
        entered = set()
        for s, strength, liquidity, pivot in candidates:
            if s in positions or s in exited:
                rejected['Already held / exited today'] += 1
                continue
            if len(positions) >= cfg.max_positions:
                rejected['Book full'] += 1
                continue
            i,b = session[s]
            if b['high'] == b['low']:
                rejected['Locked circuit'] += 1
                continue
            price = max(b['open'], pivot) if entry=='pivot' else b['open']
            stop = price*(1-cfg.stop_pct/100)
            qty = max(0, math.floor(min(equity_open*cfg.risk_pct/100/(price-stop),
                      equity_open*cap_pct/100/price, liquidity*turnover_pct/100/price,
                      cash/price)))
            qty = min(qty,size_order(equity_open,cash,price,stop,cfg.risk_pct,day))
            if not qty:
                rejected['Cash / size'] += 1
                continue
            charge = equity_charges(price,qty,'buy',day)['total']
            cash -= qty*price+charge
            fees += charge
            positions[s] = dict(entry=price, quantity=qty, stop=stop, best_close=price,
                entry_date=day, entry_cost=qty*price+charge, entry_fee=charge, line_armed=False)
            marks[s] = price
            entered.add(s)
        for s,p in list(positions.items()):
            if s not in session:
                continue
            i,b = session[s]
            locked = b['high'] == b['low']
            # Daily OHLC does not prove ordering. Reference convention is an
            # explicit sensitivity, never silently selected as conservative.
            exempt = (s in entered and entry=='pivot' and same_day=='reference'
                      and b['open'] < p['entry'] and b['close'] > b['open'])
            if not locked and not exempt and b['low'] <= p['stop']:
                close(s,p['stop'],day,'Stop / intraday trail')
                continue
            rows = context(s,day)
            average = sum(x['close'] for x in rows[i-49:i+1])/50
            p['best_close'] = max(p['best_close'],b['close'])
            if exits=='reference':
                if b['close'] > average:
                    p['line_armed'] = True
                elif p['line_armed'] and b['close'] < average:
                    p['pending'] = 'Close below SMA50; next open'
            else:
                if b['close'] >= p['entry']*(1+cfg.stop_pct/100*cfg.breakeven_r):
                    breakeven = breakeven_price(p['entry_cost'],p['quantity'],day,0)
                    p['stop'] = max(p['stop'],breakeven,average)
            marks[s] = b['close']
            if not locked and (i==len(data[s])-1 or data[s][i+1]['date']>str(cfg.end)):
                close(s,b['close'],day,'Period-end liquidation (local cost convention)')
        equity = cash+unsettled+sum(p['quantity']*marks[s] for s,p in positions.items())
        peak = max(peak,equity)
        drawdown = max(drawdown,(peak-equity)/peak*100)
        exposure.append(sum(p['quantity']*marks[s] for s,p in positions.items())/equity*100)
        curve.append(dict(date=day,equity=round(equity,2)))
    wins=[t for t in trades if t['pnl']>0]
    losses=[t for t in trades if t['pnl']<0]
    return dict(metrics=dict(return_pct=(equity/cfg.capital-1)*100,final_equity=equity,
        max_drawdown_pct=drawdown,trade_count=len(trades),win_rate=len(wins)/len(trades)*100 if trades else 0,
        profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
        fees=fees,average_deployed_pct=sum(exposure)/len(exposure)),
        rejections=dict(rejected),trades=trades,curve=curve,open_positions=positions,
        open_pnl=sum(p['quantity']*marks[s]-p['entry_cost'] for s,p in positions.items()))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference',default='b4584ee01955')
    parser.add_argument('--output',default='artifacts/banana_parity_20261012')
    parser.add_argument('--extended-only',action='store_true')
    args=parser.parse_args()
    report=json.loads((ROOT/f'data/runs/{args.reference}.json').read_text())
    path=ROOT/f'data/run_data/{args.reference}.json'
    data=json.loads(path.read_text())
    if not all(market_history.digest(data[m['symbol']])==m['sha256'] for m in report['manifest']):
        raise ValueError('Frozen input hash mismatch')
    out=ROOT/args.output
    out.mkdir(parents=True,exist_ok=True)
    base=dict(report['config'],capital=1000000,risk_pct=1,stop_pct=8,max_positions=10,
              min_rs_rating=0,candidate_rank='rs_126',fee_model='custom_bps',
              buy_cost_bps=25,sell_cost_bps=25,slippage_bps=0,skip_weak_markets=False,
              sector_filter='off',max_sector_positions=0,max_hold_days=1000,winner_exit='trail_50d')
    variants={
        'local_vcp_signals_local_trailing':dict(exits='local'),
        'local_vcp_signals_reference_exit':{},
        'local_vcp_signals_reference_exit_rs70':dict(min_rs=70),
        'local_vcp_setup_high_pivot_conservative':dict(setup='setup_high',entry='pivot',min_rs=70),
        'local_vcp_setup_close_pivot_conservative':dict(setup='setup_close',entry='pivot',min_rs=70),
        'local_vcp_setup_close_pivot_reference_order':dict(setup='setup_close',entry='pivot',min_rs=70,same_day='reference'),
        'local_blue_sky_signals_reference_exit_rs70':dict(min_rs=70),
        'local_vcp_signals_weighted_rs70':dict(min_rs=70,rs_method='weighted'),
        'fixed30_atr_close_pivot_weighted_rs70':dict(setup='atr30_close',entry='pivot',min_rs=70,rs_method='weighted',turnover_floor=10000000),
        'fixed30_atr_close_next_open_weighted_rs70':dict(setup='atr30_close',entry='next_open',min_rs=70,rs_method='weighted',turnover_floor=10000000),
    }
    protocol=dict(reference=args.reference,price_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        symbols=len(data),manifest_verified=True,variants=variants,
        caveats=['Current Nifty subset; not all NSE/BSE or historical membership.',
                 'Local VCP and Blue Sky detectors; no proprietary base/lifecycle parity.',
                 'RS variants use either 126-session returns or observed .4/.2/.2/.2 weighting with 63/126/189/252-session month proxies; full-market ranks and calendar conventions remain unmatched.',
                 'Median turnover uses 20 preceding sessions; reference length unverified.',
                 'Market cap/near-high/base-age/ATR filters and delisted names are unavailable.',
                 'Period end liquidates with sell costs; reference marks held shares.',
                 'Daily-bar pivot stop ordering is ambiguous; both conventions reported.',
                 'All periods previously inspected; no independent holdout or optimization.'],
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [Path(__file__),ROOT/'core/research/backtest.py',ROOT/'strategies/swing_patterns/patterns/signals.py']})
    if args.extended_only:
        variants={k:v for k,v in variants.items() if 'weighted' in k}
    results=(json.loads((out/'comparison.json').read_text())['results']
             if args.extended_only and (out/'comparison.json').exists() else {})
    for label,start,end in [('matched','2025-03-03','2026-09-30'),('2025','2025-01-01','2025-12-31'),('2026','2026-01-01','2026-09-30')]:
        results.setdefault(label,{})
        for name,settings in variants.items():
            cfg=BacktestConfig(**{**base,'pattern':'blue_sky' if 'blue_sky' in name else 'vcp','start':start,'end':end})
            result=simulate(data,cfg,**{'turnover_floor':50000000,**settings})
            assert abs(cfg.capital+sum(t['pnl'] for t in result['trades'])+result['open_pnl']-result['metrics']['final_equity'])<.01
            (out/f'{label}_{name}.json').write_text(json.dumps(dict(config=cfg.model_dump(mode='json'),settings=settings,**result),indent=2))
            results[label][name]=result['metrics']
            (out/'comparison.json').write_text(json.dumps(dict(protocol=protocol,results=results),indent=2))
            print(label,name,json.dumps(result['metrics']),flush=True)


if __name__=='__main__':
    main()
