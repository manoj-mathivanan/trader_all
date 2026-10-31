"""Frozen research on selection, extension, gaps and portfolio correlation; no trading writes."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
from datetime import date
import gzip
from html import escape
import json
from math import floor, fsum, sqrt
from pathlib import Path
import hashlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs
from core.execution.upstox import equity_charges, size_order
from core.strategies.four_indicator_allocation import AllocationContext


@dataclass(frozen=True)
class Plan:
    name: str = 'baseline'
    rank_sessions: int = 0
    require_rs63: bool = False
    extension_atr: float = 0
    gap_atr: float = 0
    correlation_limit: float = 0
    sector_cap_pct: float = 100
    sector_rs: bool = False
    index_trend: bool = False


PLANS = [Plan(), Plan('rs63_rank',rank_sessions=63), Plan('rs126_rank',rank_sessions=126),
         Plan('rs63_positive',require_rs63=True), Plan('extension_2atr',extension_atr=2),
         Plan('extension_3atr',extension_atr=3), Plan('gap_1atr',gap_atr=1),
         Plan('correlation_080',correlation_limit=.8), Plan('correlation_060',correlation_limit=.6),
         Plan('sector_cap_30',sector_cap_pct=30), Plan('sector_rs63_positive',sector_rs=True),
         Plan('index_sma50',index_trend=True)]


class SelectionFeatures:
    def __init__(self, data, index, instruments, cfg):
        self.data = data
        self.index = {b['date']: b for b in index}
        self.days = sorted(self.index)
        if len(self.index) != len(index) or any(b['close'] <= 0 for b in index):
            raise ValueError('Invalid or duplicated benchmark prices.')
        self.market = {}
        self.previous = {self.days[i]: self.days[i-1] for i in range(1,len(self.days))}
        for i, day in enumerate(self.days):
            self.market[day] = self.index[day]['close'] > fsum(self.index[d]['close'] for d in self.days[i-49:i+1])/50 if i >= 49 else None
        self.allocation = AllocationContext(data,cfg,instruments)
        self.sectors = self.allocation.sectors
        self.values, self.returns, self.correlation_cache = {}, {}, {}
        self.sector_values = defaultdict(dict)
        self.sector_starts = defaultdict(dict)
        for symbol, bars in data.items():
            sector = self.sectors.get(symbol,'')
            self.sector_starts[sector][symbol] = bars[0]['date']
            values, returns = [], {}
            for i,b in enumerate(bars):
                day = b['date']
                item = dict(atr=self.allocation.values[symbol][i]['atr_pct']*b['close']/100 if i >= 19 else None)
                for n in (63,126):
                    first = bars[i-n] if i >= n else None
                    a, z = self.index.get(first['date']) if first else None, self.index.get(day)
                    item[f'rs{n}'] = ((b['close']/first['close'])/(z['close']/a['close'])-1)*100 if a and z else None
                values.append(item)
                if i and self.previous.get(day) == bars[i-1]['date']:
                    returns[day] = b['close']/bars[i-1]['close']-1
                if sector and item['rs63'] is not None:
                    self.sector_values[(sector,day)][symbol] = item['rs63']
            self.values[symbol], self.returns[symbol] = values, returns

    def sector_strength(self, symbol, day):
        sector = self.sectors.get(symbol,'')
        total = sum(s != symbol and start <= day for s,start in self.sector_starts[sector].items())
        peers = [v for s,v in self.sector_values[(sector,day)].items() if s != symbol]
        coverage = len(peers)/total*100 if total else 0
        known = bool(sector and len(peers) >= 3 and coverage >= 80)
        return dict(sector=sector or 'Unknown',eligible=len(peers),total=total,coverage_pct=coverage,
                    excess_return_pct=fsum(peers)/len(peers) if known else None)

    def correlation(self, symbol, other, day):
        key = (*sorted((symbol,other)), day)
        if key not in self.correlation_cache:
            end = bisect_right(self.days,day)
            days = self.days[max(1,end-60):end]
            a, b = self.returns[symbol], self.returns[other]
            valid = len(days) == 60 and all(d in a and d in b for d in days)
            value = None
            if valid:
                x, y = [a[d] for d in days], [b[d] for d in days]
                mx, my = fsum(x)/60, fsum(y)/60
                xx, yy = fsum((v-mx)**2 for v in x), fsum((v-my)**2 for v in y)
                if xx > 0 and yy > 0:
                    value = max(-1,min(1,fsum((u-mx)*(v-my) for u,v in zip(x,y))/sqrt(xx*yy)))
            self.correlation_cache[key] = value
        return self.correlation_cache[key]

    def rank(self, symbol, i, plan):
        bar = self.data[symbol][i]
        turnover = bar['close']*bar['volume']
        if plan.rank_sessions:
            value = self.values[symbol][i][f'rs{plan.rank_sessions}']
            return (value is None,-value if value is not None else 0,-turnover,symbol)
        return (-turnover,symbol)

    def assess(self, symbol, i, opening, signal, holdings, plan):
        bar = self.data[symbol][i]
        day, feature = bar['date'], self.values[symbol][i]
        atr = feature['atr']
        stop = signal['checks'][0].get('value')
        extension = (bar['close']-stop)/atr if atr and atr > 0 and stop is not None else None
        gap = (opening-bar['close'])/atr if atr and atr > 0 else None
        sector = self.sector_strength(symbol,day) if plan.sector_rs else None
        evidence = dict(signal_date=day,rs63=feature['rs63'],rs126=feature['rs126'],atr=atr,
                        extension_atr=extension,opening_gap_atr=gap,index_above_sma50=self.market.get(day),
                        sector_strength=sector)
        reason = None
        if plan.require_rs63 and (feature['rs63'] is None or feature['rs63'] <= 0): reason = 'rs63_not_positive_or_unknown'
        if plan.extension_atr and (extension is None or extension > plan.extension_atr): reason = reason or 'extension_exceeded_or_unknown'
        if plan.gap_atr and (gap is None or gap > plan.gap_atr): reason = reason or 'opening_gap_exceeded_or_unknown'
        if plan.index_trend and not self.market.get(day): reason = reason or 'index_trend_weak_or_unknown'
        if plan.sector_rs and (sector['excess_return_pct'] is None or sector['excess_return_pct'] <= 0): reason = reason or 'sector_rs_weak_or_unknown'
        if plan.correlation_limit:
            correlations = {other:self.correlation(symbol,other,day) for other in holdings}
            evidence['correlations'] = correlations
            if any(v is None for v in correlations.values()): reason = reason or 'correlation_unknown'
            elif any(v > plan.correlation_limit for v in correlations.values()): reason = reason or 'correlation_limit'
        return reason, evidence


def simulate(data, signals, cfg, features, plan, *, liquidate=True, slot_scale=1, fee_schedule=None):
    if not 0 < slot_scale <= 1:
        raise ValueError('Slot scale must be between zero and one.')
    events = defaultdict(dict)
    for symbol,bars in data.items():
        for i,b in enumerate(bars):
            if str(cfg.start) <= b['date'] <= str(cfg.end): events[b['date']][symbol] = i
    days = sorted(events)
    cash = peak = cfg.capital
    fees = slippage = drawdown = skipped = 0
    positions, marks, trades, curve, orders, decisions = {}, {}, [], [], [], []
    rejected = Counter()
    slip = cfg.slippage_bps/10000

    def fee_mode(day):
        if fee_schedule is None: return 'upstox_plus'
        matches=[p['mode'] for p in fee_schedule if p['start'] <= day <= p['end']]
        if len(matches)!=1: raise ValueError('Missing or ambiguous fee schedule: '+day)
        return matches[0]

    def charge_for(price,quantity,side,day):
        mode=fee_mode(day)
        if mode=='upstox_plus': return equity_charges(price,quantity,side,day)['total']
        if mode=='legacy_bps': return price*quantity*(getattr(cfg,'buy_cost_bps' if side=='buy' else 'sell_cost_bps')/10000)
        raise ValueError('Unknown fee model: '+mode)

    def close(symbol,bar,raw,reason):
        nonlocal cash,fees,slippage
        p = positions.pop(symbol)
        price = raw*(1-slip)
        charge = charge_for(price,p['quantity'],'sell',bar['date'])
        cash += price*p['quantity']-charge
        fees += charge
        slippage += (raw-price)*p['quantity']
        pnl = (price-p['entry'])*p['quantity']-p['entry_fee']-charge
        trades.append(dict(p,symbol=symbol,exit=price,exit_date=bar['date'],reason=reason,pnl=pnl,
                           fees=p['entry_fee']+charge,return_pct=pnl/(p['entry']*p['quantity']+p['entry_fee'])*100))
        orders.append(dict(symbol=symbol,side='SELL',date=bar['date'],price=price,quantity=p['quantity'],fees=charge,reason=reason))

    for day in days:
        available, exited = events[day], set()
        for symbol in sorted(positions):
            if symbol not in available: continue
            i = available[symbol]
            signal = signals[symbol][i-1] if i else None
            if signal and signal['exit']:
                close(symbol,data[symbol][i],data[symbol][i]['open'],'Supertrend reversal · next open')
                exited.add(symbol)
        candidates = []
        for symbol,i in available.items():
            if symbol in positions or symbol in exited or i < 100 or data[symbol][i-1]['date'] < str(cfg.start): continue
            signal = signals[symbol][i-1]
            if signal and all(c['passed'] for c in signal['checks']):
                candidates.append((features.rank(symbol,i-1,plan),symbol,i))
        equity_open = cash+sum(p['quantity']*(data[s][available[s]]['open'] if s in available else marks[s]) for s,p in positions.items())
        for _,symbol,i in sorted(candidates):
            if len(positions) >= cfg.max_positions:
                skipped += 1; rejected['position_limit'] += 1; continue
            bar = data[symbol][i]
            reason,evidence = features.assess(symbol,i-1,bar['open'],signals[symbol][i-1],positions,plan)
            decision = dict(symbol=symbol,date=day,evidence=evidence)
            if reason:
                skipped += 1; rejected[reason] += 1
                decisions.append(dict(decision,status='rejected',reason=reason)); continue
            budget = equity_open/cfg.max_positions*slot_scale
            if plan.sector_cap_pct < 100:
                sector = features.sectors.get(symbol,'')
                exposure = sum(p['quantity']*(data[s][available[s]]['open'] if s in available else marks[s])
                               for s,p in positions.items() if features.sectors.get(s,'') == sector)
                budget = min(budget,max(0,equity_open*plan.sector_cap_pct/100-exposure))
                evidence.update(sector=sector or 'Unknown',sector_exposure_before=exposure)
            price = bar['open']*(1+slip)
            quantity = (floor(min(budget,cash)/(price*(1+cfg.buy_cost_bps/10000))) if fee_mode(day)=='legacy_bps'
                        else size_order(equity_open,min(budget,cash),price,price,100,day))
            if quantity <= 0:
                skipped += 1; rejected['cash_or_sector_cap'] += 1
                decisions.append(dict(decision,status='rejected',reason='cash_or_sector_cap')); continue
            charge = charge_for(price,quantity,'buy',day)
            cash -= price*quantity+charge
            fees += charge
            slippage += (price-bar['open'])*quantity
            positions[symbol] = dict(entry=price,entry_date=day,quantity=quantity,entry_fee=charge,
                                     entry_cost=price*quantity+charge,signal_date=data[symbol][i-1]['date'],selection=evidence)
            orders.append(dict(symbol=symbol,side='BUY',date=day,price=price,quantity=quantity,fees=charge))
            decisions.append(dict(decision,status='filled',cash_budget=min(budget,cash+price*quantity+charge)))
        for symbol,i in available.items(): marks[symbol] = data[symbol][i]['close']
        for symbol in list(positions):
            i = available.get(symbol)
            if liquidate and i is not None and (day == days[-1] or i+1 == len(data[symbol])):
                close(symbol,data[symbol][i],data[symbol][i]['close'],'End of backtest · final observed close')
        equity = cash+sum(p['quantity']*marks[s] for s,p in positions.items())
        accounted = cfg.capital+fsum(t['pnl'] for t in trades)+fsum(p['quantity']*marks[s]-p['entry_cost'] for s,p in positions.items())
        if abs(equity-accounted) > 1e-5 or cash < -.001 or len(positions) > cfg.max_positions:
            raise ValueError('Daily accounting or portfolio limits failed.')
        peak = max(peak,equity)
        drawdown = max(drawdown,(peak-equity)/peak*100)
        curve.append(dict(date=day,equity=equity,cash=cash,positions=len(positions)))
    if positions and liquidate: raise ValueError('Unclosed terminal positions.')
    wins, losses = [t['pnl'] for t in trades if t['pnl'] > 0], [t['pnl'] for t in trades if t['pnl'] < 0]
    equity = cash+sum(p['quantity']*marks[s] for s,p in positions.items())
    metrics = dict(final_equity=equity,return_pct=(equity/cfg.capital-1)*100,max_drawdown_pct=drawdown,
                   trade_count=len(trades),win_rate=100*len(wins)/len(trades) if trades else None,
                   profit_factor=sum(wins)/-sum(losses) if losses else None,modeled_fees=fees,modeled_slippage=slippage,
                   skipped_entries=skipped,drawdown_basis='Marked at daily closes',net_pnl=equity-cfg.capital,
                   average_exposure_pct=sum((c['equity']-c['cash'])/c['equity']*100 if c['equity'] > 0 else 0 for c in curve)/len(curve) if curve else 0,
                   traded_notional=sum(o['price']*o['quantity'] for o in orders),top_five_pnl=sum(sorted(wins,reverse=True)[:5]))
    unrealized = fsum(p['quantity']*marks[s]-p['entry_cost'] for s,p in positions.items())
    if abs(equity-cfg.capital-fsum(t['pnl'] for t in trades)-unrealized) > 1e-5 or abs(fees-fsum(o['fees'] for o in orders)) > 1e-5:
        raise ValueError('Final accounting mismatch.')
    result = dict(metrics=metrics,trades=trades,orders=orders,curve=curve,decisions=decisions,rejections=dict(rejected))
    if not liquidate:
        result['ledger'] = dict(cash=cash,positions=positions,marks=marks,last_session=days[-1] if days else None)
    return result


def save(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def report(output,plan,records):
    save(output/'comparison.json',dict(plan=plan,results=records))
    columns = ['period','variant','return_pct','max_drawdown_pct','trade_count','win_rate','profit_factor',
               'average_exposure_pct','turnover_multiple','modeled_fees','pnl_excluding_top_five']
    with (output/'comparison.csv').open('w',newline='',encoding='utf-8') as handle:
        writer = csv.DictWriter(handle,fieldnames=columns,extrasaction='ignore')
        writer.writeheader(); writer.writerows(records)
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>Four-indicator selection research</title><style>body{font:15px/1.55 system-ui;color:#203341;margin:32px}'
            'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5dd;padding:8px;text-align:right}'
            'th{background:#eef3f6}.scroll{overflow:auto}p{max-width:1100px}.baseline{background:#f0f7f2}</style>'
            '<h1>Four-indicator selection research</h1><p>9 October 2025–9 October 2026 · 737 frozen stocks · '
            'INR 10 lakh · ten positions · RSI &gt;65 · Bollinger 20/2.5 · prior-day R1 · Supertrend 10/3.</p>'
            '<p>Each period starts independently in cash. Daily completed-candle signals and next-open Supertrend exits remain fixed. '
            'These are retrospective experiments on previously inspected data, not untouched validation or win probabilities.</p>'
            '<h2>Results</h2><p>Return, drawdown, win rate and exposure are percentages. Turnover includes buys and sells; fees exclude slippage. '
            'P&amp;L excluding top five subtracts the five largest winning trades, without rerunning the portfolio.</p>'
            '<div class="scroll"><table><tr>'+''.join(f'<th>{escape(c.replace("_"," "))}</th>' for c in columns)+'</tr>')
    for row in records:
        page += ('<tr class="baseline">' if row['variant'] == 'baseline' else '<tr>')+''.join(
            '<td>'+escape(f'{row[c]:,.2f}' if isinstance(row[c],float) else str(row[c]) if row[c] is not None else '—')+'</td>' for c in columns)+'</tr>'
    page += '</table></div><h2>Fixed experiment definitions</h2>'
    page += ''.join('<p><b>'+escape(p['name'])+'</b>: '+escape(json.dumps(p))+'</p>' for p in plan['plans'])
    page += '<h2>Method and limitations</h2>'+''.join('<p>'+escape(x)+'</p>' for x in plan['methodology'])
    page += '<p>Machine-readable comparison, individual trade ledgers, rejection evidence and frozen source hashes are saved alongside this report.</p></html>'
    (output/'report.html').write_text(page,encoding='utf-8')


def run(snapshot,output):
    source = json.loads(gzip.decompress(snapshot.read_bytes()))
    frozen, original, index = source['frozen'], source['report'], source['index']
    if fs.digest(frozen) != original['input_sha256']: raise ValueError('Frozen stock checksum mismatch.')
    cfg = fs.SwingConfig(start=original['config']['start'],end=original['config']['end'],coverage_mode='available_history',
                         capital=1000000,max_positions=10,rule_set='bollinger',rsi_threshold=65,bollinger_multiplier=2.5,
                         slippage_bps=original['config'].get('slippage_bps',10))
    middle = cfg.start+(cfg.end-cfg.start)//2
    periods = dict(full=cfg,earlier=cfg.model_copy(update={'end':middle}),later=cfg.model_copy(update={'start':date.fromordinal(middle.toordinal()+1)}))
    files = ['scripts/research_four_indicator_selection.py','core/research/four_indicator_swing.py',
             'core/strategies/four_indicator.py','core/strategies/four_indicator_allocation.py','core/execution/upstox.py']
    root = Path(__file__).resolve().parents[1]
    plan = dict(input_sha256=original['input_sha256'],benchmark_sha256=fs.digest(index),
                snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),config=cfg.model_dump(mode='json'),
                plans=[asdict(p) for p in PLANS],periods={k:dict(start=str(v.start),end=str(v.end)) for k,v in periods.items()},
                source_sha256={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},
                methodology=[
                    'Twelve fixed variants across full, earlier and later cash-start windows. No combinations selected after looking at results.',
                    'Stock relative strength = (stock gross return / Nifty 50 gross return - 1) x 100 over the same endpoint dates; 63 or 126 stock sessions. Missing ranking data sorts last; gates reject unknowns.',
                    'Extension = (signal close - signal Supertrend) / simple ATR20. Opening gap = (next open - signal close) / signal ATR20. Only positive gaps above the threshold are rejected. The opening price is observed at execution; same-open fills remain an idealized daily-bar assumption.',
                    'Correlation uses 60 Nifty-session aligned daily simple returns ending at the completed signal date. Missing/constant series reject the new entry when holdings exist. Only positive correlation above the limit is blocked, including stocks selected earlier at the same open.',
                    'Sector strength is an equal-weight mean of peer stock relative returns versus Nifty over 63 sessions, excluding the candidate; minimum three valid peers and 80% coverage. It is a frozen-universe proxy, not an official sector index.',
                    'Index trend gate requires the completed signal-day Nifty close above its SMA50. Sector exposure cap marks existing holdings at the entry open and groups missing labels as Unknown.',
                    'All entry conditions, Supertrend exits, equal cash slots, fee schedule, daily-close marking and final liquidation follow the current engine. Baseline curve and metrics must match exactly in every period.',
                    'Controls change entries and subsequent cash availability. Report includes turnover, exposure, fees, and P&L excluding the five largest winners; smaller exposure can explain lower return and drawdown.',
                    'Current universe and sector labels cause survivorship/classification bias. Known excluded corporate actions, omitted dividends, fixed Plus tariff and unverified daily-bar execution assumptions remain.',
                    'All windows have already been inspected. These are retrospective diagnostics, not untouched validation. No production settings, paper portfolios or broker orders are modified.',
                ])
    output.mkdir(parents=True,exist_ok=True)
    path = output/'frozen-plan.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) != plan: raise ValueError('Plan changed; choose a new output directory.')
    save(path,plan)
    data = frozen['datasets']
    features = SelectionFeatures(data,index,frozen['universe']['instruments'],cfg)
    signals = fs.features(data,lambda s:print(s,flush=True),**fs.stored_parameters(cfg.model_dump()))
    records = []
    parity = {}
    for period,settings in periods.items():
        reference = fs.simulate(data,signals,settings,fs.RULES[3],instruments=frozen['universe']['instruments'])
        for p in PLANS:
            result = simulate(data,signals,settings,features,p)
            if p.name == 'baseline':
                if result['curve'] != reference['curve'] or result['metrics'] != reference['metrics']:
                    raise ValueError('Baseline mismatch: '+period)
                keys = ('symbol','entry_date','exit_date','entry','exit','quantity','fees','pnl')
                if [{k:t[k] for k in keys} for t in result['trades']] != [{k:t[k] for k in keys} for t in reference['trades']]:
                    raise ValueError('Baseline trade mismatch: '+period)
                parity[period] = dict(curve_identical=True,metrics_identical=True)
            row = dict(period=period,variant=p.name,**result['metrics'],rejections=result['rejections'],
                       turnover_multiple=result['metrics']['traded_notional']/settings.capital,
                       pnl_excluding_top_five=result['metrics']['net_pnl']-result['metrics']['top_five_pnl'])
            records.append(row)
            save(output/f'{period}-{p.name}.json',dict(plan=asdict(p),config=settings.model_dump(mode='json'),**result))
            print(f'{period}/{p.name}: return {row["return_pct"]:.2f}%; DD {row["max_drawdown_pct"]:.2f}%; {row["trade_count"]} trades',flush=True)
    save(output/'baseline-parity.json',parity)
    report(output,plan,records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=Path('artifacts/four_indicator_year_20261025/frozen.json.gz'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/four_indicator_selection_20261030'))
    args = parser.parse_args()
    run(args.snapshot,args.output)
