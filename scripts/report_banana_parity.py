"""Render the frozen comparison evidence as a local, standalone HTML report."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/banana_parity_20261012'


def main():
    comparison=json.loads((OUT/'comparison.json').read_text())
    latest=json.loads((OUT/'latest_run_diagnosis.json').read_text())
    observed=dict(inspected='2026-10-12',url='https://bananapatterns.com/backtest',
        account=dict(capital=1000000,risk_pct=1,stop_pct=8,max_positions=10,
                     cost_bps_per_order=25,position_cap_pct=30,turnover_cap_pct=10,
                     exit='SMA50 close breach, next open',breakeven=False,squat_exit=False,chase_limit=False),
        results=[
            dict(screen='VCP',period='2016-04 to 2026-09',entry='pivot',return_pct=1910.9998,max_drawdown_pct=36,trade_count=841,win_rate=30.6,final_equity=20109998),
            dict(screen='VCP',period='2025-01-01 to 2025-12-31',entry='pivot',return_pct=-2.5203,max_drawdown_pct=25.6,trade_count=113,win_rate=23.9,final_equity=974797),
            dict(screen='VCP',period='2026-01-01 to 2026-09-30',entry='pivot',return_pct=12.0262,max_drawdown_pct=17.1,trade_count=72,win_rate=31.9,final_equity=1120262),
            dict(screen='VCP',period='2025-03-03 to 2026-09-30',entry='pivot',return_pct=35.201,max_drawdown_pct=38.2,trade_count=140,win_rate=30.7,final_equity=1352010),
            dict(screen='VCP',period='2025-03-03 to 2026-09-30',entry='next_open',return_pct=35.9054,max_drawdown_pct=28,trade_count=133,win_rate=30.1,final_equity=1359054),
            dict(screen='Blue sky',period='2025-03-03 to 2026-09-30',entry='next_open',return_pct=7.7523,max_drawdown_pct=24.8,trade_count=150,win_rate=29.3,final_equity=1077523)],
        rs_formula='0.4 * 3-month gain + 0.2 * 6-month gain + 0.2 * 9-month gain + 0.2 * 1-year gain; ranked 1–99 across the market',
        tightening='ATR percentage of second base half / first base half',
        dryup='Volume of second base half / first base half',
        live_vcp_filters=dict(market_cap_crore=300,median_turnover_crore=1,min_rs=70,
            price_above_sma=[50,200],max_below_52w_high_pct=30,min_above_52w_low_pct=15,
            min_base_weeks=3,max_base_depth_pct=35,max_atr_ratio=.9,max_volume_ratio=.9),
        limitations=['Manually observed headline results; no bulk site data copied.',
                    'Live screen filters are separate from proof of historical backend implementation.',
                    'Headline and chart annualized rates/equity multiples differ on the site; total headline account values are used.',
                    'No downloadable historical candle/base/RS dataset was available in the inspected backtest UI.'])
    observed['inspected_trade_samples']=[
        dict(symbol='POWERINDIA',entry_date='2025-04-29',exit_date='2025-08-26',entry=14050,exit=19540),
        dict(symbol='A1',entry_date='2025-04-17',exit_date='2025-12-22',entry=12.61,exit=41.85),
        dict(symbol='PGEL',entry_date='2025-03-07',exit_date='2025-04-07',entry=876,exit=714.7),
        dict(symbol='MUTHOOTFIN',entry_date='2025-03-19',exit_date='2025-04-09',entry=2335,exit=2148.2),
        dict(symbol='SUNDARMFIN',entry_date='2025-03-18',exit_date='2025-03-28',entry=4780,exit=4572.1),
    ]
    source=json.loads((ROOT/'data/runs/b4584ee01955.json').read_text())
    members={m['symbol'] for m in source['manifest']}
    sample_comparison=[]
    for trade in observed['inspected_trade_samples']:
        local={}
        for variant in ['local_vcp_signals_reference_exit','fixed30_atr_close_next_open_weighted_rs70']:
            ledger=json.loads((OUT/f'matched_{variant}.json').read_text())['trades']
            matching=[t for t in ledger if t['symbol']==trade['symbol']]
            local[variant]=dict(trades=matching,exact_match=any(all(t.get(k)==trade[k] for k in ['entry_date','exit_date','entry','exit']) for t in matching))
        sample_comparison.append(dict(reference=trade,in_local_frozen_universe=trade['symbol'] in members,local=local))
    (OUT/'trade_sample_comparison.json').write_text(json.dumps(sample_comparison,indent=2))
    (OUT/'reference_observations.json').write_text(json.dumps(observed,indent=2,ensure_ascii=False),encoding='utf-8')
    def table(rows,first):
        body=''.join('<tr><td>'+html.escape(name)+'</td>'+''.join('<td>'+v+'</td>' for v in [f"{m['return_pct']:+.2f}%",f"{m['max_drawdown_pct']:.2f}%",str(m['trade_count']),f"{m['win_rate']:.1f}%"])+'</tr>' for name,m in rows)
        return '<table><thead><tr>'+''.join('<th>'+x+'</th>' for x in [first,'Return','Max drawdown','Trades','Win rate'])+'</tr></thead><tbody>'+body+'</tbody></table>'
    labels={
        'local_vcp_signals_local_trailing':'Local VCP signals + local breakeven/SMA stop convention',
        'local_vcp_signals_reference_exit':'Same local VCP signals + reference SMA50 close exit',
        'local_vcp_signals_reference_exit_rs70':'Same, local six-month RS ≥70',
        'local_vcp_signals_weighted_rs70':'Same, weighted RS ≥70 (session-month approximation)',
        'local_vcp_setup_high_pivot_conservative':'Local 3-window VCP setup + high pivot',
        'local_vcp_setup_close_pivot_conservative':'Local 3-window VCP setup + close pivot',
        'local_vcp_setup_close_pivot_reference_order':'Same close pivot, reference same-day ordering assumption',
        'local_blue_sky_signals_reference_exit_rs70':'Local Blue Sky signals + SMA50 exit, six-month RS ≥70',
        'fixed30_atr_close_pivot_weighted_rs70':'Fixed 30-session ATR/volume base proxy + close pivot + weighted RS',
        'fixed30_atr_close_next_open_weighted_rs70':'Same fixed-base proxy + next-open confirmation',
    }
    content='''<!doctype html><html><head><meta charset="utf-8"><title>BananaPatterns comparison · 12 October 2026</title>
<style>body{font:16px/1.6 system-ui;background:#f5f7f8;color:#17262d;margin:0}main{max-width:1120px;margin:auto;padding:36px}h1{font-size:32px}h2{margin-top:38px}p{max-width:1000px}.note{background:#fff3cc;padding:20px;border-left:5px solid #c79619}.good{background:#e5f4eb;padding:20px}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{padding:10px;text-align:right;border-bottom:1px solid #dde3e6}th:first-child,td:first-child{text-align:left}th{background:#173d38;color:white}code{font-size:14px}a{color:#146d58}.scroll{overflow:auto}footer{margin-top:40px}</style></head><body><main>
<h1>Why the BananaPatterns backtest differs</h1><p>Inspected 12 October 2026. Research results only; trading defaults and paper portfolios are unchanged.</p>
<div class="note"><b>Dates matched; site data not matched.</b> We can reproduce our own frozen inputs and model published execution rules. This is not an exact reproduction of BananaPatterns: its full historical market, corporate-action series, detected base records and historical ranks are unavailable.</div>
<h2>Your latest losing run: exact replay and controlled changes</h2>
<p>Source 6abcabe9224a: 428 stocks; 2 January 2025–9 October 2026; ₹1 lakh; five positions; fundamental ranking, sector breadth/trend gates and Zerodha fees. Original trades and metrics replay exactly; price, financial and sector snapshots verified. Each trial below uses identical frozen inputs. These dates differ from the reference comparisons below.</p>'''
    names={'original':'Actual original: 3% stop, +8% target','stop8_only':'Only widen stop to 8%; retain +8% target','stop8_take15':'8% stop, +15% target','stop8_local_sma_trail':'8% stop, existing local SMA/breakeven trail','stop8_local_sma_trail_gates_off':'Same local trail; sector trend and breadth gates off'}
    content+=table([(names[k],m) for k,m in latest['results'].items()],'Controlled change')
    content+='''<p>The tight stop is a demonstrated contributor to this run's loss. Changing it also changes quantities, stop/breakeven timing and subsequent account selections; this is a portfolio-level intervention, not a claim that every original losing trade would have won. Wider stops and uncapped exits merit testing; they do not establish a deployable edge.</p>
<h2>Verified reference headlines</h2><p>Reference account: ₹10 lakh, risk 1%, ten positions, 8% initial stop, SMA50 close exit at next open, 0.25% costs per order, 30% position cap, 10% median-turnover cap. Optional breakeven, squat exit and chase limit off.</p>'''
    content+=table([(m['screen']+' · '+m['period']+' · '+m['entry'],m) for m in observed['results']],'Reference run')
    content+='''<p>The ten-year headline includes very different market regimes. The 2025 VCP run lost money. On matched recent dates, changing reference pivot entry to next-open entry barely changes total return, while drawdown falls from 38.2% to 28.0%.</p>
<h2>Matched account and dates on our frozen candles</h2><p>433 eligible stocks from b4584ee01955; source candle manifest verified. 3 March 2025–30 September 2026; reference account parameters above. Both first rows use identical local VCP predicates, RS ordering and ₹5 crore turnover floor; only the exit convention changes. RS variants change that filter explicitly. Fixed-base proxies use the observed ₹1 crore floor, SMA50/SMA200, near-high/low, depth, ATR/volume-half ratios and weighted RS; market cap and actual base detection remain missing. All local variants liquidate tradable holdings at period end with costs; reference marks its held shares.</p>'''
    content+=table([(labels[k],m) for k,m in comparison['results']['matched'].items()],'Local model, not site parity')
    content+='''<p>A similar aggregate return does not prove matching trades. The local VCP signal + reference-exit model returns about 32%, but adding weighted RS alone changes it to a loss. The fixed-base proxy can improve results while still selecting different stocks. The component definitions and historical market ranks matter.</p>
<h2>What we implemented differently</h2><div class="scroll"><table><thead><tr><th>Component</th><th>Our actual implementation</th><th>Observed reference</th></tr></thead><tbody>
<tr><td>VCP</td><td>Three fixed windows with decreasing high-low ranges and volumes</td><td>Detected base; second-half / first-half ATR% and volume ratios</td></tr>
<tr><td>Pivot entry</td><td>Waits for a prior completed breakout, then may buy a retouch next day; VCP signal uses 10-session high, execution uses base_days high</td><td>Prior-day qualified setup; cross its tracked pivot today</td></tr>
<tr><td>Blue Sky</td><td>Close above highest loaded-history intraday high</td><td>Tracked base at all-time-high structure; historical wick and base ceiling need not coincide</td></tr>
<tr><td>Relative strength</td><td>126-session return percentile in loaded subset, 0–100</td><td>40/20/20/20 weighting of 3/6/9/12-month gains; full-market rank 1–99</td></tr>
<tr><td>Winner exit</td><td>SMA becomes an intraday stop after a profit trigger, combined with breakeven; targets can cap winners</td><td>Close below SMA50 triggers next-open exit; optional breakeven off by default</td></tr>
<tr><td>Cash and sizing</td><td>Open exits can finance same-open buys; sizing includes expected stop costs; no explicit position/turnover caps</td><td>Sales fund next-day entries; price-distance risk size plus 30% equity and turnover caps</td></tr>
<tr><td>Universe</td><td>Current Nifty members, exclusions and incomplete history</td><td>NSE/BSE liquid market including companies that later stop trading</td></tr>
<tr><td>Same-day pivot stop</td><td>Protection deferred to next session for pivot fills</td><td>OHLC direction-based ordering assumption; both conservative and reference sensitivities tested locally</td></tr>
</tbody></table></div>
<h2>Period sensitivity</h2><p>Each annual window restarts with cash. They are previously inspected samples, not independent holdouts.</p>'''
    for period in ['2025','2026']:
        content+='<h3>'+period+'</h3>'+table([(labels[k],m) for k,m in comparison['results'][period].items()],'Model')
    content+='''<h2>Selected trade checks</h2><p>Five manually inspected reference next-open trades are saved in trade_sample_comparison.json; this small sample is not a historical recall estimate. The fixed-base proxy reproduces SUNDARMFIN exactly: entry 18 March 2025 at ₹4,780, exit 28 March at ₹4,572.10. It takes none of the inspected POWERINDIA, PGEL or MUTHOOTFIN trades. The original local VCP + reference-exit model enters POWERINDIA on 23 July at ₹20,205, versus the reference 29 April entry at ₹14,050; both exit on 26 August at ₹19,540. A1, a reference +230% trade, is absent from our frozen universe. A different selection or account allocation can therefore dominate returns even where quoted prices agree.</p>'''
    content+='<h2>What exact replication still needs</h2><p>A permitted, frozen export or licensed equivalent of the reference historical stock universe and adjusted OHLCV, historical market capitalization/turnover, prior-day base/pivot identifiers, historical RS values, and chronological breakout candidates. Compare candidate sets, fills, exits, quantities and cash before judging aggregate equity. No export was exposed in the inspected backtest UI. Re-downloading Upstox candles would not make them the same as Accord/NSE/BSE data.</p>'
    content+='<p>Observed calculation details: '+html.escape(observed['rs_formula'])+'. The fixed 30-session proxy uses average true-range percentages rather than an unverified ATR smoothing convention, and 63/126/189/252-session month proxies rather than verified calendar windows.</p>'
    content+='<h2>Validation and saved evidence</h2><p>Eight execution tests cover close-trigger/next-open exits, breakeven differences, deferred sale cash, circuit locks, entry-day ordering, gap entries and future-data invariance. Every portfolio balances closed-trade P&amp;L plus marked open P&amp;L against equity. Frozen price manifests and latest financial/sector evidence verified. No defaults or production files changed.</p><ul>'
    for f in ['comparison.json','latest_run_diagnosis.json','reference_observations.json','trade_sample_comparison.json','reference-next-open.png']:
        content+='<li><a href="'+f+'">'+f+'</a></li>'
    content+='</ul><p>Reproduce: <code>.venv/Scripts/python.exe scripts/research_banana_parity.py</code> and <code>.venv/Scripts/python.exe scripts/research_banana_current_run.py</code>.</p><footer>Sources: <a href="https://bananapatterns.com/backtest">reference backtest and methodology</a>; <a href="https://bananapatterns.com/screens">screen filters and calculation editor</a>. Headline and chart annualized metrics differ on the site; total account headline values are used here. Historical comparisons are hypotheses for further validation, not recommendations to trade.</footer></main></body></html>'
    (OUT/'report.html').write_text(content,encoding='utf-8')
    print(OUT/'report.html')


if __name__=='__main__':
    main()
