"""Audit NIFTY entry signals from checksum-verified underlying sample data."""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import options_backtest as backtest, options_history as history, options_strategy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('artifacts/options_research'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--replay', action='store_true', help='Replay archived options; requires all four explicit cost inputs.')
    parser.add_argument('--brokerage-per-order', type=float)
    parser.add_argument('--buy-charge-bps', type=float)
    parser.add_argument('--sell-charge-bps', type=float)
    parser.add_argument('--slippage-bps', type=float)
    parser.add_argument('--fee-model', choices=['custom_bps', 'upstox_options'], default='upstox_options')
    parser.add_argument('--chain-policy', choices=['strict', 'observed_traded'], default='strict')
    args = parser.parse_args()
    if args.replay and any(getattr(args, key) is None for key in
            ('brokerage_per_order', 'buy_charge_bps', 'sell_charge_bps', 'slippage_bps')):
        parser.error('Replay requires explicit --brokerage-per-order, --buy-charge-bps, --sell-charge-bps and --slippage-bps.')
    output = args.output or args.input/'signal-audit.json'
    manifest, minutes, daily = backtest.load_underlying(args.input)
    start, end = map(date.fromisoformat, (manifest['start'], manifest['end']))
    reports = {}
    for timeframe in (3, 5):
        audit = backtest.prepare_signals(minutes, daily, start=start, end=end, timeframe=timeframe)
        by_day = {}
        for event in audit['events']:
            counts = by_day.setdefault(event['date'], Counter(call=0, put=0, ready_bars=0))
            counts['ready_bars'] += event['ready']
            if event['ready'] and event['entry_window']:
                counts['call'] += event['call']
                counts['put'] += event['put']
        audit['daily_signal_bars'] = by_day
        reports[str(timeframe)] = audit
    report = dict(status='underlying_signal_audit_only', start=str(start), end=str(end),
        option_backtest_complete=False, performance_summary=None,
        notes=['Signal bars are not executed trades; consecutive bars can repeat the same setup.',
               'No option contract selection, option fills, or returns are inferred from underlying moves.',
               'Incomplete/special sessions are excluded and indicator warmup resets after gaps.',
               'Daily provider observations define sessions; an independent exchange-calendar audit is still required.'],
        specification=options_strategy.specification(), inputs=manifest['files'], timeframes=reports)
    if args.replay:
        try:
            option_bars, catalogs, expiries = backtest.load_option_sample(args.input)
        except ValueError as exc:
            report['replay_status'] = dict(status='unavailable', reason=str(exc))
        else:
            report['replays'] = {}
            for tf, audit in reports.items():
                for variant in ('fixed_250', 'underlying_1pct'):
                    config = backtest.ReplayConfig(timeframe=int(tf), premium_variant=variant, fee_model=args.fee_model, chain_policy=args.chain_policy,
                        **{key: getattr(args, key) for key in ('brokerage_per_order', 'buy_charge_bps', 'sell_charge_bps', 'slippage_bps')})
                    report['replays'][tf+'m_'+variant] = backtest.replay(audit, option_bars, catalogs, expiries, config)
            report['replay_status'] = dict(status='diagnostic_replays_saved', costs_verified=False)
    history.save_json(output, report)
    print(json.dumps(dict(file=str(output), status=report['status'], replay_status=report.get('replay_status'), timeframes={tf: {
        k: audit[k] for k in ('session_count', 'call_signal_bars', 'put_signal_bars', 'excluded_sessions')}
        for tf, audit in reports.items()})))
    if args.replay and (report.get('replay_status', {}).get('status') == 'unavailable' or
                        any(r['status'] not in ('replay_complete', 'diagnostic_replay_complete') for r in report.get('replays', {}).values())):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
