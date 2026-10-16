"""Cache-only development diagnostics printed to stdout; creates no reports.

Fixed current Nifty50 membership is survivorship biased. Independent trades
share neither cash nor portfolio risk limits; results cannot be account returns.
The inspected historical window is development data, not a clean holdout.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import corporate_actions, data_quality, intraday_data, market_history, store
from core.research.sneaky_pivot import (
    earlier_session_support, level_long_setups, opening_long_setup, replay_long_setup,
    reprice_diagnostic_trade,
)

VARIANTS = ('opening_range_control', 'delayed_range', 'delayed_range_and_earlier_low_proxy')
SCENARIOS = ((2, 1), (5, 1), (10, 1.5))


def run(start, end):
    universe=store.read('universes/nifty50')
    reference=market_history.evidence(snapshot=True)
    digest=hashlib.sha256(json.dumps(universe,sort_keys=True).encode())
    counters={v:Counter() for v in VARIANTS}
    base_trades={v:[] for v in VARIANTS}
    rejects={v:Counter() for v in VARIANTS}
    quality=Counter(); quality_examples=[]; excluded=[]
    for item in universe['instruments']:
        raw=store.read('bars/'+item['isin'],{})
        digest.update(json.dumps(raw,sort_keys=True).encode())
        daily,details=market_history.prepare(item,raw,reference=reference,fingerprint=False)
        if not daily or details.get('quarantine'):
            excluded.append(item['symbol']); continue
        gap_audit=data_quality.audit({item['symbol']:daily},start=start,end=end)
        if gap_audit['findings']:
            excluded.append(item['symbol']); quality['unresolved_price_gap_stock']+=1; continue
        by_day={b['date']:b for b in daily}
        minutes={}; invalid=set()
        warmup_start_index=next((i for i,b in enumerate(daily) if b['date']>=start),len(daily))
        selected=daily[max(0,warmup_start_index-22):]
        for row in selected:
            day=row['date']
            if day>end: break
            if day in intraday_data.SPECIAL_SESSIONS: continue
            path=store.DATA/(intraday_data.cache_key(item['isin'],day)+'.json')
            if not path.exists():
                quality['missing_stock_session']+=1; invalid.add(day); continue
            blob=path.read_bytes(); digest.update(blob)
            try:
                bars=intraday_data.cached_bars(json.loads(blob),day)
                bars=intraday_data.trading_bars(bars,'15:25')
                if max(abs(max(b['high'] for b in bars)/row['high']-1),
                       abs(min(b['low'] for b in bars)/row['low']-1))>.01:
                    raise ValueError('Daily/minute high-low differs by more than1%; price basis needs review.')
                minutes[day]=bars; quality['valid_stock_session']+=1
            except (ValueError,KeyError) as error:
                invalid.add(day); quality['invalid_stock_session']+=1
                if len(quality_examples)<10:
                    quality_examples.append(dict(symbol=item['symbol'],date=day,error=str(error)))
        for i,row in enumerate(daily):
            day=row['date']
            if not start<=day<=end or i<21 or day in intraday_data.SPECIAL_SESSIONS:
                continue
            prior_day=daily[i-1]['date']
            if prior_day in intraday_data.SPECIAL_SESSIONS: continue
            if day not in minutes or prior_day not in minutes:
                quality['excluded_incomplete_session_pair']+=1; continue
            prior_rows=corporate_actions.adjusted_bars(daily[:i],day)
            # Adjustments affecting this warmup need independent minute-basis evidence.
            if any(prior_rows[-21]['date']<a['ex_date']<=day for a in corporate_actions.actions(daily)):
                quality['excluded_action_crossing']+=1; continue
            ranges=[max(prior_rows[j]['high']-prior_rows[j]['low'],
                        abs(prior_rows[j]['high']-prior_rows[j-1]['close']),
                        abs(prior_rows[j]['low']-prior_rows[j-1]['close']))
                    for j in range(len(prior_rows)-14,len(prior_rows))]
            atr=mean(ranges)
            previous=minutes[prior_day]; current=minutes[day]
            control,control_reason=opening_long_setup(previous,current,atr)
            delayed,delayed_reason=level_long_setups(previous,current,atr)
            range_low=min(b['low'] for b in previous)
            earlier=earlier_session_support(
                [b for b in prior_rows if b['date'] not in intraday_data.SPECIAL_SESSIONS],
                range_low,prior_day=prior_day)
            # A proxy only enters research if its own historical minute price is checked.
            if earlier and earlier['source_date'] not in minutes:
                earlier=None; quality['unavailable_proxy_session']+=1
            extended,extended_reason=level_long_setups(previous,current,atr,extra_support=earlier)
            inputs=((VARIANTS[0],[control] if control else [],control_reason),
                    (VARIANTS[1],delayed,delayed_reason),
                    (VARIANTS[2],extended,extended_reason))
            quality['valid_development_pair']+=1
            for variant,setups,reason in inputs:
                counters[variant]['eligible_pairs']+=1
                counters[variant][reason]+=1
                counters[variant]['setup_count']+=len(setups)
                for setup in setups:
                    trade,outcome=replay_long_setup(setup,current,slippage_bps=2,fee_multiplier=1)
                    rejects[variant][outcome]+=1
                    if trade:
                        trade.update(symbol=item['symbol'],support_kind=setup.get('support_kind','prior_session_low'),
                                     confirmation_candle=setup.get('confirmation_candle',2))
                        base_trades[variant].append(trade)
                        break  # At most one filled trade per stock/session.
        print('Checked',item['symbol'], 'valid_pairs_so_far',quality['valid_development_pair'],flush=True)
    results=[]
    trades={(v,s,f):[reprice_diagnostic_trade(t,slippage_bps=s,fee_multiplier=f)
                     for t in base_trades[v]] for v in VARIANTS for s,f in SCENARIOS}
    for (variant,slip,fees),ledger in trades.items():
        wins=sum(t['net_pnl']>0 for t in ledger)
        gains=sum(max(0,t['net_pnl']) for t in ledger)
        losses=-sum(min(0,t['net_pnl']) for t in ledger)
        results.append(dict(variant=variant,slippage_bps_per_side=slip,fee_multiplier=fees,
                            trades=len(ledger),sessions=len({t['date'] for t in ledger}),
                            win_rate_pct=100*wins/len(ledger) if ledger else None,
                            mean_net_r=mean(t['net_r'] for t in ledger) if ledger else None,
                            net_profit_factor=gains/losses if losses else None,
                            ambiguity_trades=sum(t['ambiguous_entry'] or t['ambiguous_exit'] for t in ledger),
                            largest_gap_loss=max((-t['net_pnl'] for t in ledger),default=0),
                            mean_fees=mean(t['fees'] for t in ledger) if ledger else None,
                            by_year=dict(Counter(t['date'][:4] for t in ledger)),
                            by_support=dict(Counter(t['support_kind'] for t in ledger)),
                            by_confirmation=dict(Counter(t['confirmation_candle'] for t in ledger)),
                            outcomes=dict(rejects[variant])))
    print(json.dumps(dict(
        diagnostic='independent_trade_development_only',start=start,end=end,
        universe='fixed current Nifty50 snapshot',input_sha256=digest.hexdigest(),
        quality=dict(quality),quality_examples=quality_examples,excluded_stocks=excluded,
        signal_funnels={k:dict(v) for k,v in counters.items()},results=results,
        limitations=['Inspected development data; no holdout claims.',
                     'Current constituents introduce survivorship bias.',
                     '0.05 ATR level tolerance /0.25 ATR body unchanged; no optimization.',
                     'v2 adds structural invalidation as well as delayed confirmation.',
                     'Daily-extreme proxy is not verified discretionary swing selection.',
                     'Independent trade cash100000/risk1000; no portfolio returns or drawdown.',
                     'Cost scenarios freeze base2bps trade identities, quantity, raw path and R denominator; no stress reselection or resizing.',
                     'Five-minute candle order ambiguity handled adversely; no spread/queue/tick model.',
                     'Price-basis comparison is a diagnostic, not corporate-action verification.',
                     'No strategy defaults, orders, dashboards or reports are written.'],
    ),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',default='2024-10-08')
    parser.add_argument('--end',default='2026-10-09')
    args=parser.parse_args()
    from datetime import date
    if not date(2024,10,1)<=date.fromisoformat(args.start)<date.fromisoformat(args.end):
        parser.error('Choose increasing development dates within the fee model window.')
    run(args.start,args.end)
