"""Run daily-candle weekly range adaptation on an existing frozen equity snapshot."""
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.research import data_quality, weekly_range_daily as engine


def run():
    root=Path(__file__).resolve().parents[1]
    source=root/'artifacts/four_indicator_year_20261025/frozen.json.gz'
    raw=source.read_bytes(); frozen=json.loads(gzip.decompress(raw))
    output=root/'artifacts/weekly_range_daily_20261029'; output.mkdir(parents=True,exist_ok=True)
    sessions=[b['date'] for b in frozen['index']]
    start,end='2025-10-09','2026-10-09'
    required={d for d in sessions if '2025-09-01'<=d<=end}
    datasets={}; excluded=[]
    for symbol,bars in frozen['frozen']['datasets'].items():
        if not required.issubset({b['date'] for b in bars}):
            excluded.append(dict(symbol=symbol,reason='Incomplete common daily session window/warmup'));continue
        if bars[0].get('corporate_actions'):
            excluded.append(dict(symbol=symbol,reason='Corporate-action rebasing unsupported in this isolated experiment'));continue
        if data_quality.audit({symbol:bars},start='2025-09-01',end=end)['findings']:
            excluded.append(dict(symbol=symbol,reason='Unresolved daily price discontinuity'));continue
        datasets[symbol]=bars
    spec=dict(source=str(source.relative_to(root)),source_sha256=hashlib.sha256(raw).hexdigest(),
        start=start,end=end,capital=1000000,max_positions=5,risk_pct=.5,
        video_adaptation='Long cash-equity swing test of close above the prior four completed ISO calendar weeks high. Not an option-selling backtest.',
        entry='Next actual session open only if still above range high; prior 20-session turnover priority, then symbol.',
        exit='Original range low protective stop, gap at open; otherwise after 20 held sessions at next open. Final sample liquidated at close. Entry-session stop active.',
        sizing='At most 20% of opening equity per position; 0.5% equity risk including modeled stop fees. Five slots, no leverage.',
        costs='Shared Upstox Plus delivery fee hypothesis, including DP charges; 10/20 bps adverse slippage per side. Delivery fees also applied conservatively to same-day stopouts.',
        control='Prior 20 completed daily sessions high/low; every other execution rule identical.',
        included_symbols=len(datasets),excluded=excluded,
        caveats=['Current-membership/survivorship bias; omitted dividends and unverified smaller price events.',
            'Existing frozen snapshot reused; no new data refresh. Later period has been inspected in other studies and is not untouched validation.',
            'Daily-close drawdown understates possible intraday drawdown. No volatility filter: India VIX not in this snapshot.',
            'Weekly range direction alone does not reconstruct discretionary SMC, option premiums, theta, hedging or adjustments.',
            'These fixed numerical sizing and exit rules are our adaptation, not rules fully specified by the transcript.'])
    (output/'specification.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    results=[]
    for label,a,b in [('full',start,end),('earlier',start,'2026-06-30'),('later','2026-07-01',end)]:
        for variant in ('four_week','twenty_session'):
            for slip in (10,20):
                result=engine.simulate(datasets,sessions,a,b,variant,slip)
                key=f'{label}_{variant}_{slip}bps'
                (output/(key+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
                row=dict(period=label,variant=variant,slippage_bps=slip,**result['metrics']);results.append(row)
                print(json.dumps(row),flush=True)
    report=dict(specification=spec,results=results)
    (output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    columns=['period','variant','slippage_bps','return_pct','max_daily_close_drawdown_pct','trades','win_rate_pct','profit_factor','fees']
    def display(v):
        return f'{v:.2f}' if isinstance(v,float) else str(v)
    html='<!doctype html><meta charset="utf-8"><title>Weekly range on daily candles</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:20px;color:#172238}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd4df;text-align:right}th{background:#eef3fa}p{line-height:1.6}</style><h1>Weekly range tested on daily candles</h1>'
    html+=f'<p>{start} to {end}; {len(datasets)} stocks; ₹10 lakh capital; five positions maximum. Long cash equities; not option-selling performance.</p>'
    html+='<table><tr>'+''.join('<th>'+escape(c)+'</th>' for c in columns)+'</tr>'+''.join('<tr>'+''.join('<td>'+escape(display(r[c]))+'</td>' for c in columns)+'</tr>' for r in results)+'</table>'
    html+='<h2>Rules and limitations</h2>'+''.join('<p><b>'+escape(k)+': </b>'+escape(str(v))+'</p>' for k,v in spec.items() if k not in ('excluded',))
    html+=f'<p>{len(excluded)} stocks excluded; complete exclusions and ledgers are saved alongside this report.</p>'
    (output/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    run()
