"""Render the declared frozen-input fee sensitivity suite and its limits."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scripts.research_intraday_costs import SCENARIOS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'intraday_cost_research'
LABELS={
 'original':'Original flat costs; 10 bps slippage/side',
 'zero_cost':'Zero fees and zero slippage',
 'public_fees_slip_0':'Public Upstox fees; zero slippage',
 'public_fees_slip_2':'Public Upstox fees; 2 bps slippage/side',
 'public_fees_slip_5':'Public Upstox fees; 5 bps slippage/side',
 'public_fees_slip_10':'Public Upstox fees; 10 bps slippage/side',
 'stress_fees_150_slip_15':'150% public fees; 15 bps slippage/side',
}


def bootstrap(curve,capital):
    equity=np.array([capital,*[p['equity'] for p in curve]])
    returns=np.diff(equity)/equity[:-1]
    rng=np.random.default_rng(20261009)
    # Circular moving blocks of five sessions retain short-range dependence.
    starts=rng.integers(0,len(returns),size=(2000,(len(returns)+4)//5))
    samples=returns[(starts[:,:,None]+np.arange(5))%len(returns)].reshape(2000,-1)[:,:len(returns)]
    ci=np.percentile(samples.mean(axis=1)*100,[2.5,97.5]).tolist()
    return dict(mean_daily_return_pct=float(returns.mean()*100),ci_95_pct=ci,
                method='2000 circular moving-block resamples, 5 sessions per block, fixed seed; arithmetic daily returns. Diagnostic on inspected data, not independent validation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markdown', type=Path, help='Explicitly export a Markdown report to this path')
    args = parser.parse_args()
    summary=json.loads((OUT/'summary.json').read_text())
    if len(summary['runs']) != len(SCENARIOS)*3 or not summary.get('baseline_replay_verified'):
        raise ValueError('Suite incomplete or baseline not verified.')
    runs={(r['scenario'],r['direction']):r for r in summary['runs']}
    lines=['# Intraday momentum cost diagnosis — 9 October 2026','',
      'Twenty-one full simulations on identical frozen inputs, 8 October 2024–7 October 2026. Reference `'+summary['reference_id']+'`. No downloads or default changes. Baseline replay matches recorded equity, fees, slippage and every trade exactly.','',
      'Direction-only portfolios select their own qualifying stocks and size from their own capital. They are not the buy/sell attribution of the combined portfolio. Every run starts at Rs 1,000,000.','',
      '| Cost scenario | Combined return | Buy-only return | Short-only return |',
      '|---|---:|---:|---:|']
    for name,*_ in SCENARIOS:
        values=[f"{runs[name,d]['metrics']['return_pct']:+.2f}%" for d in ('both','long','short')]
        lines.append('| '+LABELS[name]+' | '+' | '.join(values)+' |')
    lines+=['','## Profit factor and trade counts','','| Scenario | Combined PF / trades | Buy-only PF / trades | Short-only PF / trades |','|---|---:|---:|---:|']
    for name,*_ in SCENARIOS:
        values=[f"{runs[name,d]['metrics']['profit_factor']:.3f} / {runs[name,d]['metrics']['trade_count']}" for d in ('both','long','short')]
        lines.append('| '+LABELS[name]+' | '+' | '.join(values)+' |')
    lines+=['','## Calendar-period attribution','','| Scenario / direction | 2024 partial | 2025 | 2026 partial |','|---|---:|---:|---:|']
    for name in ('zero_cost','public_fees_slip_2','public_fees_slip_5'):
        for direction in ('both','long','short'):
            values=[f"{y['return_pct']:+.2f}%" for y in runs[name,direction]['yearly']]
            lines.append('| '+name+' / '+direction+' | '+' | '.join(values)+' |')
    uncertainty={}
    lines+=['','## Uncertainty diagnostics','','| Public fees + 2 bps/side | Mean daily return | 95% block interval |','|---|---:|---:|']
    for direction in ('both','long','short'):
        raw=json.loads((OUT/('public_fees_slip_2_'+direction+'.json')).read_text())
        b=bootstrap(raw['curve'],1000000)
        uncertainty[direction]=b
        lines.append(f"| {direction} | {b['mean_daily_return_pct']:+.4f}% | {b['ci_95_pct'][0]:+.4f}% to {b['ci_95_pct'][1]:+.4f}% |")
    (OUT/'uncertainty.json').write_text(json.dumps(uncertainty,indent=2),encoding='utf-8')
    lines+=['','Moving blocks: five consecutive sessions, 2,000 resamples, fixed seed. These intervals describe arithmetic daily-return uncertainty in an inspected sample. They do not resolve survivorship, exclusions, model selection or executable-fill bias.','',
      '## Cost model and interpretation','',
      '[Upstox public fee schedule](https://upstox.com/brokerage-charges/) checked 9 October 2026. Model assumes basic brokerage min(Rs 20, 0.1% notional) per order throughout this history; actual historical account plans are unverified. Cash intraday STT applies to sells, stamp duty to buys; exchange rates change on 1 March 2026. IPFT and SEBI levies are included; GST on applicable fees is modeled conservatively. Contract-note rounding, promotions, forced square-off fees and account-specific charges are excluded.','',
      'Exact nonlinear fees affect the simulated quantity, reserved capital and stop-risk budget, as well as final P&L. Slippage affects fills and protective levels; reducing it is a sensitivity experiment, not an assertion that such fills are attainable. The stress case multiplies charges by 1.5 and raises slippage from 10 to 15 bps/side.','',
      '## Limits and next research','',
      'This is the existing ORB setup, not a test of VWAP pullbacks or failed breakouts. Current constituents, explicit corporate-action exclusions, session-end drawdown and unverified short/circuit/participation constraints are inherited. All historical periods have already been inspected. Before claiming improvement, use a distinct untouched period and observed paper fills.','',
      'If profits disappear with public fees even at zero slippage, prioritize signal/selection changes. If they survive fees but disappear with small slippage, execution quality and expected movement are binding. A less negative result remains a loss, and a positive zero-cost result does not establish a tradeable edge.','',
      'Next controlled experiment: broaden liquid-stock selection without changing the entry setup, then test VWAP pullback/rejection as a separate strategy. Keep all cost assumptions and candidate thresholds declared before outcomes.','',
      '## Reproduction','',
      '`.venv/Scripts/python.exe scripts/research_intraday_costs.py 836c4463d21b` followed by `.venv/Scripts/python.exe scripts/report_intraday_costs.py`.','',
      'Raw run ledgers, equity curves and summary are retained in `artifacts/intraday_cost_research/`; these reference the original frozen daily/minute hashes rather than duplicating inputs.','']
    if args.markdown:
        args.markdown.write_text('\n'.join(lines),encoding='utf-8')
    fig,axes=plt.subplots(1,3,figsize=(15,4.8),layout='constrained',sharey=True)
    colors=['#b91c1c','#15803d','#0369a1','#d97706']
    for ax,direction in zip(axes,('both','long','short')):
        for name,color in zip(('original','zero_cost','public_fees_slip_2','public_fees_slip_5'),colors):
            raw=json.loads((OUT/(name+'_'+direction+'.json')).read_text())
            ax.plot([datetime.fromisoformat(p['date']) for p in raw['curve']],
                    [p['equity']/100000 for p in raw['curve']],color=color,label=LABELS[name],linewidth=1.3)
        ax.axhline(10,color='#999',linestyle='--',linewidth=.7)
        ax.set_title({'both':'Combined','long':'Buy only','short':'Short only'}[direction])
        ax.grid(alpha=.15)
        ax.tick_params(axis='x',rotation=35)
    axes[0].set_ylabel('Portfolio equity (Rs lakh)')
    fig.suptitle('Identical frozen inputs — cost sensitivity, not live performance')
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='outside lower center',ncols=2,fontsize=8)
    fig.savefig(OUT/'equity.png',dpi=160)
    plt.close(fig)
    if args.markdown:
        print('Report:', args.markdown)
    print(json.dumps(uncertainty,indent=2))


if __name__=='__main__':
    main()
