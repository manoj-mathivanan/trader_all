"""Matched four-indicator replay with one added completed-four-week-high gate."""
from datetime import date
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs
from core.research.weekly_range_daily import signals as ranges


def with_weekly_gate(data, features):
    output={}
    for symbol, rows in data.items():
        levels=ranges(rows)
        output[symbol]=[]
        for bar, signal in zip(rows,features[symbol]):
            if signal is None:
                output[symbol].append(None);continue
            level=levels.get(bar['date'])
            check=dict(name='Close above previous four completed weeks high',
                       passed=bool(level and level['bullish']),value=level['high'] if level else None)
            output[symbol].append(dict(signal,checks=[*signal['checks'],check],
                entry=signal['entry'] and check['passed'],weekly_range=level))
    return output


def verify(result, filtered):
    trades, curve=result['trades'],result['curve']
    assert abs(sum(t['pnl'] for t in trades)-result['metrics']['net_pnl'])<.001
    assert curve[-1]['positions']==0
    assert all(c['cash']>=-.001 and c['positions']<=10 for c in curve)
    for trade in trades:
        assert trade['signal_date']<trade['entry_date']<=trade['exit_date']
        if filtered:
            signal=trade['signal']; level=signal['weekly_range']
            assert level['last_input_date']<trade['signal_date']
            assert signal['close']>level['high']
            assert all(c['passed'] for c in signal['checks'])


def run():
    root=Path(__file__).resolve().parents[1]
    source=root/'artifacts/four_indicator_year_20261025/frozen.json.gz'
    raw=source.read_bytes(); snapshot=json.loads(gzip.decompress(raw))
    frozen=snapshot['frozen']; data=frozen['datasets']
    assert fs.digest(frozen)==snapshot['report']['input_sha256']
    output=root/'artifacts/four_indicator_weekly_range_20261029';output.mkdir(parents=True,exist_ok=True)
    cfg=fs.SwingConfig(start=date(2025,10,9),end=date(2026,10,9),capital=1000000,max_positions=10,
        coverage_mode='available_history',rule_set='bollinger',rsi_threshold=65,bollinger_multiplier=2.5)
    spec=dict(config=cfg.model_dump(mode='json'),source=str(source.relative_to(root)),
        source_sha256=hashlib.sha256(raw).hexdigest(),input_sha256=fs.digest(frozen),symbols=len(data),
        filter='Signal-day close strictly above high of previous four completed ISO calendar weeks; current week excluded. Apply only to entry.',
        baseline='Current all-four defaults: Supertrend 10/3, RSI14 >65, close above prior-day R1, close above Bollinger20/2.5.',
        unchanged='Existing production simulator: next-observed-session-open fills, Supertrend reversal exits, turnover priority, ten equal cash slots, Upstox Plus fees, terminal close liquidation.',
        windows={'full':['2025-10-09','2026-10-09'],'earlier':['2025-10-09','2026-05-29'],'later':['2026-06-01','2026-10-09']},
        slippage_bps=[10,20],
        limitations=['Frozen 737-stock available-history universe retains source exclusions, variable eligibility and current-membership bias.',
          'Later window is previously inspected history, not an untouched holdout. Subperiod portfolios start from cash; full-year run carries positions continuously.',
          'Daily-close drawdown misses intraday extremes; dividends omitted; fees are the shared account-plan hypothesis, not contract-note reconstruction.',
          'This tests daily cash-equity entries, not option-selling returns. No production settings, paper portfolios or live trades are changed.'])
    (output/'specification.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    base=fs.features(data,lambda s:print(s,flush=True),rsi_threshold=65,bollinger_multiplier=2.5)
    gated=with_weekly_gate(data,base)
    base_rule=next(r for r in fs.RULES if r[0]=='bollinger')
    gate_rule=('four_week_gate','All four + four-week high',(0,1,2,3,4),False)
    rows=[]; reference_check=None
    for period,(start,end) in spec['windows'].items():
        for slip in spec['slippage_bps']:
            config=cfg.model_copy(update=dict(start=date.fromisoformat(start),end=date.fromisoformat(end),slippage_bps=slip))
            for name,features,rule in [('baseline',base,base_rule),('weekly_gate',gated,gate_rule)]:
                result=fs.simulate(data,features,config,rule)
                verify(result,name=='weekly_gate')
                key=f'{period}_{name}_{slip}bps'
                (output/(key+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
                row=dict(period=period,variant=name,slippage_bps=slip,**result['metrics']);rows.append(row)
                if key=='full_baseline_10bps':
                    prior_path=root/'artifacts/four_indicator_exits_20261028/research.json'
                    if prior_path.exists():
                        prior=json.loads(prior_path.read_text())
                        ref=next(r for r in prior['results'] if r['plan']['name']=='Supertrend only')
                        fields=('return_pct','max_drawdown_pct','trade_count','net_pnl','modeled_fees','modeled_slippage')
                        reference_check=dict(source=str(prior_path.relative_to(root)),
                            deltas={k:row[k]-ref[k] for k in fields},
                            reproduced=all(abs(row[k]-ref[k])<1e-7 for k in fields))
                print(json.dumps(row),flush=True)
    comparisons=[]
    for period in spec['windows']:
        for slip in spec['slippage_bps']:
            a=json.loads((output/f'{period}_baseline_{slip}bps.json').read_text())
            b=json.loads((output/f'{period}_weekly_gate_{slip}bps.json').read_text())
            comparisons.append(dict(period=period,slippage_bps=slip,
                identical_trade_fills=[{k:v for k,v in t.items() if k!='signal'} for t in a['trades']]==[{k:v for k,v in t.items() if k!='signal'} for t in b['trades']],identical_daily_equity=a['curve']==b['curve'],
                baseline_fills_passing_weekly_gate=sum(t['signal']['close']>gated[t['symbol']][
                    next(i for i,bar in enumerate(data[t['symbol']]) if bar['date']==t['signal_date'])]['weekly_range']['high'] for t in a['trades']),
                baseline_trades=len(a['trades']),return_difference_pct_points=b['metrics']['return_pct']-a['metrics']['return_pct']))
    report=dict(specification=spec,baseline_reference_check=reference_check,results=rows,comparisons=comparisons,
        verification='All twelve ledgers reconcile; entries causal; all filtered fills pass five checks; exits and production engine unchanged.')
    (output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    columns=['period','variant','slippage_bps','return_pct','max_drawdown_pct','trade_count','win_rate','profit_factor','modeled_fees']
    def val(x):return f'{x:.2f}' if isinstance(x,float) else str(x)
    html='<!doctype html><meta charset="utf-8"><title>Four indicators + weekly range</title><style>body{font:16px system-ui;max-width:1250px;margin:40px auto;padding:20px;color:#172238}table{border-collapse:collapse;width:100%;margin:25px 0}td,th{border:1px solid #ccd4df;padding:10px;text-align:right}th{background:#eef3fa}p{line-height:1.6}</style><h1>Four indicators with and without a weekly-range filter</h1><p>₹10 lakh; ten cash-equity positions; 737 frozen stocks; 9 October 2025–9 October 2026. Only entry qualification changes.</p>'
    html+='<table><tr>'+''.join('<th>'+escape(c)+'</th>' for c in columns)+'</tr>'+''.join('<tr>'+''.join('<td>'+escape(val(r[c]))+'</td>' for c in columns)+'</tr>' for r in rows)+'</table>'
    if all(c['identical_trade_fills'] and c['identical_daily_equity'] for c in comparisons):
        html+='<p><b>Finding: the weekly filter adds no portfolio benefit on this snapshot.</b> Every selected baseline entry already passes it. All six matched pairs have identical trade fills and daily equity curves.</p>'
    html+='<h2>Method and verification</h2>'+''.join('<p><b>'+escape(k)+': </b>'+escape(str(v))+'</p>' for k,v in spec.items())
    html+='<p>Prior baseline reproduction: '+escape(str(reference_check))+'</p><p>'+escape(report['verification'])+'</p>'
    (output/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    run()
