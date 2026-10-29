"""Educational expiry stress test and local archive inventory; never sends orders."""
import argparse
from datetime import date
import hashlib
from html import escape
import json
from pathlib import Path


def payoff(legs, spot):
    """Points per underlying unit, including each leg's entry premium.

    Same-expiry European cash-settled options only. Costs and pre-expiry
    mark-to-market are deliberately excluded from this educational calculation.
    """
    if spot < 0 or not legs or len({leg['expiry'] for leg in legs}) != 1:
        raise ValueError('Require nonnegative spot and one common expiry.')
    total = 0
    for leg in legs:
        if leg['kind'] not in ('CE', 'PE'):
            raise ValueError('Unsupported option kind.')
        intrinsic = max(spot-leg['strike'], 0) if leg['kind'] == 'CE' else max(leg['strike']-spot, 0)
        total += leg['quantity'] * (intrinsic-leg['premium'])
    return round(total, 6)


def bounds(legs):
    # Piecewise-linear extrema occur at zero or a strike, unless the call tail
    # slopes down without limit. Do not mistake a finite stress grid for a cap.
    values = [payoff(legs, s) for s in [0]+[leg['strike'] for leg in legs]]
    slope = sum(leg['quantity'] for leg in legs if leg['kind'] == 'CE')
    return dict(max_loss_points=None if slope < 0 else max(0, -min(values)),
                max_profit_points=None if slope > 0 else max(values),
                unlimited_upside_loss=slope < 0)


def examples():
    def leg(kind, strike, premium, quantity):
        return dict(kind=kind, strike=strike, premium=premium, quantity=quantity, expiry='illustrative_common_expiry')
    debit = [leg('CE', 25000, 300, 1), leg('CE', 25500, 120, -1)]
    return {
        'bull_call_debit_spread': debit,
        'call_ladder_extra_short': debit+[leg('CE', 26000, 60, -1)],
        'bull_put_credit_spread': [leg('PE', 24500, 150, -1), leg('PE', 24000, 60, 1)],
        'bear_call_credit_spread': [leg('CE', 25500, 120, -1), leg('CE', 26000, 60, 1)],
        'same_expiry_iron_condor': [leg('PE', 24000, 60, 1), leg('PE', 24500, 150, -1),
                                  leg('CE', 25500, 120, -1), leg('CE', 26000, 60, 1)],
        'naked_short_strangle': [leg('PE', 24500, 150, -1), leg('CE', 25500, 120, -1)],
    }


def inventory(root):
    records = []
    paths = sorted((root/'artifacts/options_extended_2026').glob('*/research-manifest.json'))
    paths += list((root/'artifacts/options_research').glob('research-manifest.json'))
    for path in paths:
        raw = path.read_bytes()
        manifest = json.loads(raw)
        files = manifest.get('files', [])
        dtes = [(date.fromisoformat(r['instrument']['expiry'])-date.fromisoformat(r['start'])).days
                for r in files]
        records.append(dict(manifest=str(path.relative_to(root)), sha256=hashlib.sha256(raw).hexdigest(),
            status=manifest.get('status'), start=manifest.get('start'), end=manifest.get('end'),
            contract_files=len(files), nonempty_files=sum(r.get('bars', 0)>0 for r in files),
            max_possible_entry_dte=max(dtes, default=None),
            files_possibly_covering_30_to_60_dte=sum(d >= 30 for d in dtes)))
    return dict(method='Manifest metadata only; candle files not verified by this inventory.', archives=records,
        ready_for_30_to_60_dte_backtest=False,
        reason='Requires verified 30-60 DTE multi-leg prices, India VIX, spreads, costs, and margin history; inventory is not a backtest.')


def run(root, transcript, output):
    raw = transcript.read_bytes()
    scenarios = []
    for name, legs in examples().items():
        scenarios.append(dict(name=name, legs=legs, **bounds(legs),
            stress=[dict(spot=s, pnl_points=payoff(legs, s)) for s in (0, 20000, 24000, 24500, 25000, 25500, 26000, 28000, 30000)]))
    lessons = [
        ['09:48-12:00', 'Start with a debit spread to reduce the premium at risk.', 'Useful bounded-risk teaching example; it is still a net option purchase.'],
        ['13:20-17:28', 'Add a short call and buy shorter-dated protection.', 'Extra short call creates unlimited upside loss; shorter hedge expiry does not cap lifetime loss.'],
        ['18:13-20:39', 'Check India VIX and the previous 3-4 weekly candles.', 'Use completed candles; VIX 14/18 thresholds are hypotheses, not established signals.'],
        ['27:13-35:47', 'Trade a longer-dated strangle with nearer hedges.', 'Compare with a same-expiry iron condor; high win rate can conceal large tail losses.'],
        ['36:12-39:20', 'Save every leg and adjustment; backtest while learning.', 'Keep exact entry/exit prices, reasons, costs, risk, and missing-data exclusions.'],
        ['44:40-48:44', 'Take profits before expiry and account for volatility changes.', 'Predeclare exits and test them; 3-10% return claims and automatic recovery after a few days are unverified.'],
    ]
    plan = dict(status='proposed_unvalidated_research_rules', source='Our mechanical adaptation, not exact video rules.',
        candidates=['bull_put_credit_spread', 'bear_call_credit_spread', 'same_expiry_iron_condor'],
        expiry='30-60 calendar days; all legs same expiry, underlying and verified contract multiplier.',
        signal='Prior completed 4 weekly highs/lows. Daily close above range: bull put; below: bear call; inside: condor.',
        strikes='Short puts strictly below prior range low, calls strictly above range high; protective wings 500 points farther OTM. Skip absent strikes.',
        entry='First synchronized next-session prices at or after 09:30 IST. One position at a time; skip incomplete chains or stale quotes.',
        exit='First observed 50% credit capture, loss equal to initial credit, or 7 DTE; execute all legs on next synchronized prices. Gaps may exceed stop.',
        sizing='Illustrative risk budget 0.5% of research equity, using contractual max loss plus cost reserve. Skip if one verified lot exceeds budget or margin unavailable.',
        volatility='Log India VIX; compare unfiltered vs VIX >=18 with identical rules. No assumed edge from threshold.',
        costs='Actual dated brokerage/statutory charges per leg, spread-aware execution, overnight margin and adverse slippage stress required.',
        evaluation='Freeze inputs; separate development and untouched holdout; compare net expectancy, drawdown, tail loss, cost drag and no-trade baseline.',
        missing_inputs=['30-60 DTE contract candles through exits', 'India VIX history', 'bid/ask or declared conservative fill model', 'historical margin and dated lot sizes'],
        paper_activation='Only after replay and margin/quote checks; this script neither activates paper trading nor places orders.')
    report = dict(status='educational_stress_test_complete_historical_backtest_unavailable',
        source=dict(path=str(transcript), sha256=hashlib.sha256(raw).hexdigest(), type='User-supplied transcript; no video charts available'),
        assumptions=['All quoted premiums and strikes are invented examples, not market observations.',
            'Results are expiry payoff points per underlying unit, before fees, taxes and slippage; not rupee P&L.',
            'No probability, win rate, return or margin is inferred. Pre-expiry P&L depends on time and volatility.'],
        lessons=lessons, scenarios=scenarios, coverage=inventory(root), proposed_plan=plan,
        references=['https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread',
            'https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/option-strategies/bull-call-ladder',
            'https://www.nseindia.com/static/products-services/equity-derivatives-margins'])
    output.mkdir(parents=True, exist_ok=True)
    (output/'research.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    def table(headers, rows):
        return '<table><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in headers)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    html = '<!doctype html><meta charset="utf-8"><title>Option selling: transcript review and first experiment</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#172238}table{border-collapse:collapse;width:100%;margin:24px 0}td,th{border:1px solid #ccd4df;padding:10px;text-align:left}th{background:#eef3fa}p{line-height:1.6}</style>'
    html += '<h1>Option selling: what to keep and what to test</h1><p>First experiment completed: illustrative expiry stress tests. Historical strategy performance remains unavailable.</p>'
    html += ''.join('<p>'+escape(s)+'</p>' for s in report['assumptions'])
    html += '<h2>Transcript lessons</h2>'+table(['Time','Video idea','Assessment'], lessons)
    html += '<h2>Stress results in points per unit</h2>'+table(['Structure','Max loss','Max profit','P&L at 25,000','P&L at 30,000'],
        [[s['name'], 'Unlimited' if s['unlimited_upside_loss'] else s['max_loss_points'], s['max_profit_points'],
          payoff(s['legs'],25000),payoff(s['legs'],30000)] for s in scenarios])
    html += '<p>A bounded expiry loss assumes every leg remains intact through common cash settlement. It does not establish interim liquidity, margin sufficiency, or realizable early-exit prices.</p>'
    html += '<h2>Local data coverage</h2><p>'+escape(report['coverage']['method'])+'</p>'+table(
        ['Archive','Contract files','Nonempty','Maximum entry DTE','Files possibly at 30+ DTE'],
        [[r['manifest'],r['contract_files'],r['nonempty_files'],r['max_possible_entry_dte'],r['files_possibly_covering_30_to_60_dte']] for r in report['coverage']['archives']])
    html += '<h2>Proposed first historical experiment</h2>'+table(['Item','Rule'], [[k,v] for k,v in plan.items()])
    html += '<h2>Each simulated position must record</h2><p>Signal timestamp, completed range, VIX, all contract identities and expiries, lot size, bid/ask, fills, fees, margin, maximum loss, every adjustment, exit reason, and realized P&L.</p>'
    html += '<h2>Source checks</h2>'+''.join('<p><a href="'+escape(url)+'">'+escape(url)+'</a></p>' for url in report['references'])
    (output/'report.html').write_text(html, encoding='utf-8')
    print(json.dumps(dict(status=report['status'], output=str(output), coverage=report['coverage'],
        bounds={s['name']:{k:s[k] for k in ('max_loss_points','max_profit_points','unlimited_upside_loss')} for s in scenarios}),indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transcript', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('artifacts/option_selling_masterclass'))
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], args.transcript, args.output)
