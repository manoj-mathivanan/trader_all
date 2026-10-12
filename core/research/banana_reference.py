"""Independent fixed-window screen proxies with observed Banana execution rules.

The licensed source prices, historical market-wide ranks, market caps and
proprietary nested-base lifecycle are unavailable. No detector parity claim.
"""
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import date
from statistics import median
from core.research import backtest, corporate_actions
from strategies.swing_patterns.patterns.signals import matches, vcp_setup

NOTICES = [
    'Independent fixed-window proxies, not Banana detector parity: VCP/IPO use 30 sessions; multi-year uses 252; Blue sky uses the highest loaded historical close. Nested structure levels and base lifecycle are unavailable.',
    'Historical market cap is unavailable: the observed â‚¹300 crore source filter is recorded but NOT enforced. Results are a partial-rule sensitivity.',
    'Weighted RS uses 63/126/189/252-session month proxies and ranks only eligible local stocks, not the source market-wide NSE/BSE population.',
    'Median turnover uses the preceding 20 sessions; source lookback and ATR smoothing are unverified. ATR tightening uses average daily true range / close in each base half.',
    'Reference execution: fixed entry-relative stop; armed SMA50 close breach exits next open; sale cash available next session; position and turnover caps; locked one-price sessions defer fills; period end marks open holdings.',
]


def setup_proxy(rows, i, cfg, historical_pivot=None):
    """Completed setup only; never inspect candles after i."""
    length = 252 if cfg.pattern == 'multiyear' else 30
    if i < (50 if cfg.pattern == 'ipo' else 252):
        return False, None
    window = rows[max(0, i-length+1):i+1]
    pivot = historical_pivot if cfg.pattern == 'blue_sky' and historical_pivot is not None else max(b['close'] for b in (rows[:i+1] if cfg.pattern == 'blue_sky' else window))
    price = rows[i]['close']
    if price > pivot or price <= 0:
        return False, pivot
    if cfg.pattern == 'vcp':
        halves = len(window)//2
        first, second = window[:halves], window[halves:]
        def atr_part(begin, count):
            values = []
            for j in range(begin, begin+count):
                b = rows[j]
                previous = rows[j-1]['close']
                values.append(max(b['high']-b['low'], abs(b['high']-previous), abs(b['low']-previous))/b['close'])
            return sum(values)/count
        a1 = atr_part(i-length+1, halves)
        a2 = atr_part(i-length+1+halves, len(second))
        v1 = sum(b['volume'] for b in first)/len(first)
        v2 = sum(b['volume'] for b in second)/len(second)
        high = max(b['high'] for b in rows[i-251:i+1])
        low = min(b['low'] for b in rows[i-251:i+1])
        depth = (max(b['high'] for b in window)-min(b['low'] for b in window))/max(b['high'] for b in window)*100
        qualified = (a1 > 0 and a2/a1 <= .9 and v1 > 0 and v2/v1 <= .9
                     and depth <= 35 and price >= high*.7 and price >= low*1.15
                     and price >= sum(b['close'] for b in rows[i-49:i+1])/50
                     and price >= sum(b['close'] for b in rows[i-199:i+1])/200)
    elif cfg.pattern == 'multiyear':
        qualified = price >= pivot*.8 and price >= sum(b['close'] for b in rows[i-199:i+1])/200
    elif cfg.pattern == 'blue_sky':
        qualified = price >= pivot*.8
    elif cfg.pattern == 'ipo':
        metadata = rows[0].get('listing_metadata', {})
        listing = metadata.get('ipo_date', metadata.get('listing_date'))
        if not listing or metadata.get('verified') is not True or not metadata.get('source') or metadata.get('ipo_verified') is not True:
            return False, pivot
        age = (date.fromisoformat(rows[i]['date'])-date.fromisoformat(listing)).days
        depth = (max(b['high'] for b in window)-min(b['low'] for b in window))/max(b['high'] for b in window)*100
        qualified = (0 <= age <= 350 and depth <= 35 and price >= pivot*.8
                     and price >= sum(b['close'] for b in rows[i-49:i+1])/50)
    else:
        raise ValueError('Reference proxies support VCP, Blue sky, multi-year and IPO only.')
    return qualified, pivot


def _simulate(data, cfg, *, exits='reference', setup='confirmed', entry='next_open',
             ranking='rs', min_rs=0, turnover_floor=0, cost_bps=25,
             same_day='conservative', cap_pct=30, turnover_pct=10, rs_method='126', mark_end=True):
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
    cost = cost_bps / 10000
    rs_cache = {}
    context_cache = {}
    prefix_cache = {}

    def context(s, day):
        key = (s, tuple(a['id'] for a in corporate_actions.actions(data[s]) if a['ex_date'] <= day))
        if key not in context_cache:
            context_cache[key] = corporate_actions.adjusted_bars(data[s], day)
        return context_cache[key]

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
        charge = p['quantity'] * price * cost
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
            if setup == 'screen_proxy':
                signal_index = i-1 if entry == 'pivot' else i-2
                historical_pivot = None
                if cfg.pattern == 'blue_sky':
                    key = id(prior_rows)
                    if key not in prefix_cache:
                        values, highest = [], 0
                        for row in prior_rows:
                            highest = max(highest, row['close'])
                            values.append(highest)
                        prefix_cache[key] = values
                    historical_pivot = prefix_cache[key][signal_index]
                qualified, pivot = setup_proxy(prior_rows, signal_index, cfg, historical_pivot)
                if qualified:
                    # Orders use prior completed setup data. Translate only verified
                    # ex-date actions into today's price units.
                    for action in corporate_actions.actions(data[s]):
                        if action['ex_date'] == day and action['price_basis'] == 'raw':
                            pivot /= action['share_factor']
                    qualified = b['high'] > pivot if entry == 'pivot' else rows[i-1]['close'] > pivot
            elif setup == 'confirmed':
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
            decision_idx = i-1 if entry == 'pivot' else i-2
            strength = rs(data[s][decision_idx]['date']).get(s, 0 if cfg.pattern == 'ipo' else -1)
            liquidity = median(x['close']*x['volume'] for x in prior_rows[max(0,decision_idx-19):decision_idx+1])
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
                      cash/(price*(1+cost)))))
            if not qty:
                rejected['Cash / size'] += 1
                continue
            charge = qty*price*cost
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
                    breakeven = p['entry_cost']/p['quantity']/(1-cost)
                    p['stop'] = max(p['stop'],breakeven,average)
            marks[s] = b['close']
            if not mark_end and not locked and (i==len(data[s])-1 or data[s][i+1]['date']>str(cfg.end)):
                close(s,b['close'],day,'Period-end liquidation (local cost convention)')
        equity = cash+unsettled+sum(p['quantity']*marks[s] for s,p in positions.items())
        peak = max(peak,equity)
        drawdown = max(drawdown,(peak-equity)/peak*100)
        exposure.append(sum(p['quantity']*marks[s] for s,p in positions.items())/equity*100)
        curve.append(dict(date=day,equity=round(equity,2)))
    if not curve:
        raise ValueError('No candles in the chosen test interval.')
    wins=[t for t in trades if t['pnl']>0]
    losses=[t for t in trades if t['pnl']<0]
    return dict(metrics=dict(initial_capital=cfg.capital, return_pct=(equity/cfg.capital-1)*100,final_equity=equity,
        max_drawdown_pct=drawdown,trade_count=len(trades),win_rate=len(wins)/len(trades)*100 if trades else 0,
        profit_factor=sum(t['pnl'] for t in wins)/-sum(t['pnl'] for t in losses) if losses else None,
        fees=fees,modeled_fees=fees,modeled_slippage=0,expectancy_r=None,skipped_entries=sum(rejected.values()),average_deployed_pct=sum(exposure)/len(exposure)),
        rejections=dict(rejected),trades=trades,curve=curve,open_positions=positions,
        open_pnl=sum(p['quantity']*marks[s]-p['entry_cost'] for s,p in positions.items()))


def simulate(data, cfg):
    if cfg.pattern == 'ipo' and not any(rows and rows[0].get('listing_metadata', {}).get('ipo_verified') is True for rows in data.values()):
        raise ValueError('IPO backtest unavailable: frozen inputs contain no verified IPO listing evidence. A first candle is not an IPO date.')
    result = _simulate(data, cfg, setup='screen_proxy', entry=cfg.entry_mode,
                       min_rs={'vcp':70, 'blue_sky':70, 'multiyear':60, 'ipo':0}[cfg.pattern],
                       turnover_floor=10000000, cost_bps=cfg.buy_cost_bps,
                       cap_pct=cfg.reference_cap_pct, turnover_pct=cfg.reference_turnover_pct,
                       same_day=cfg.reference_same_day, rs_method='weighted')
    for trade in result['trades']:
        trade['r'] = trade['pnl']/(trade['entry']*trade['quantity']*cfg.stop_pct/100)
        trade['hold_days'] = (date.fromisoformat(trade['exit_date'])-date.fromisoformat(trade['entry_date'])).days
    result['metrics']['expectancy_r'] = sum(t['r'] for t in result['trades'])/len(result['trades']) if result['trades'] else None
    result['metrics']['trade_count'] = len(result['trades']) + len(result['open_positions'])
    result['metrics']['closed_trade_count'] = len(result['trades'])
    result['metrics']['open_trade_count'] = len(result['open_positions'])
    result['state'] = {}
    result['corporate_actions'] = []
    result['sector_checks'] = []
    result['entry_filter_rejections'] = result.pop('rejections')
    result['execution_notices'] = NOTICES + [
        'Entry-day OHLC stop ordering: '+cfg.reference_same_day+'. Daily bars do not establish the actual intraday path.',
        'Trade count includes open holdings; win rate and profit factor use closed trades only.'
    ]
    return result
