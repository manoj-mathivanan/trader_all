"""Read-only database audit and frozen Tamil-video-inspired equity experiments.

Outputs are local artifacts. No downloads, database mutations or trading actions.
"""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import candle_rejection as engine
from core.research import corporate_actions, data_quality, intraday_data, market_history, postgres_store as pg, store

SPEC = dict(
    version=1,
    sources=[dict(video='Eb3tyXLZEeA', role='order lifecycle only'),
             dict(video='EMsbckJq3gE', role='inspiration; numerical rules are our interpretation')],
    research=dict(start='2025-01-01', end='2025-12-31'),
    validation=dict(start='2026-01-01', end='2026-06-30'),
    prospective=dict(start='2026-11-02', end='2027-01-29', status='reserved; no scheduled runner'),
    universe='niftytotalmarket', scan_size=50, liquidity_lookback=20,
    minimum_prior_turnover=50_000_000,
    selection='Prior 20 observed daily sessions mean close*volume; descending, symbol tie-break. No replacement after data exclusion.',
    levels='Previous observed session high/low; current 09:15-09:30 range. No pivots requiring future candles.',
    baseline='Candle overlaps level within 0.05 prior daily ATR and closes on the reclaimed side.',
    rejection='Baseline plus rejection-side wick >=50% of range and directional close location >=70%. Colour unrestricted.',
    confirmation='Rejection plus a close beyond its opposite extreme in the next 1 or 2 candles; discard if rejection extreme breaks first.',
    execution='Signal candle must complete; next-bar open. Gap must retain reclaimed level. Fixed 2R target and structural stop buffered by 0.05 prior ATR.',
    atr='Mean of preceding 14 daily true ranges, with at least 21 consecutive benchmark sessions; verified split/bonus rebasing as of trade date.',
    variants=['level', 'rejection', 'confirmation'], directions=['long', 'short'], slippage_bps=[2, 5, 10],
    fees='Existing dated Upstox basic cash-equity hypothesis, both legs; historical account plan unverified.',
    rules=asdict(engine.Rules()),
    risk='Sizing includes adverse stop slippage and both fees. Fully collateralized shorts; no leverage or daily capital recycling. Gaps can exceed planned risk.',
    ordering='Prior-turnover rank at each entry open. Entries before intrabar exits, conservatively retaining occupied slots.',
    ambiguity='Gap stop at open; otherwise stop before target when both touched. Target fills assume sufficient liquidity. No limit-entry simulation.',
    data_policy='Exact 75 contiguous regular-session bars, finite positive prices/nonnegative volume, positive session volume. Special sessions excluded. Daily/minute OHLC mismatch >2% excluded. Every exclusion retained, matched across trials.',
    candidate_gate=dict(min_trades=200, min_profit_factor=1.1, max_drawdown_pct=15,
                        min_positive_month_fraction=.5, max_positive_stock_profit_share=.3,
                        net_positive_at_bps=[5, 10], beats_same_direction_baseline_return=True,
                        selection='Highest return at 5 bps among rejection/confirmation candidates passing every gate; no tuning.'),
    validation_gate='Only selected candidate and its same-direction baseline, at 5 and 10 bps; positive candidate net at both, PF>1 at 5, observed-close DD<=15%. No promotion to live execution.',
    limitations=['Current membership survivorship bias', 'Prior studies already inspected some calendar periods; validation is held out for this specification only',
                 'Retrospectively archived provider data and corporate-action evidence', 'Short eligibility/circuits/borrow and actual spreads/executable volume unverified',
                 'Candle-close drawdown misses within-bar extremes; target liquidity and slippage are assumptions',
                 'Prospective period requires later paper implementation and observation; no automatic schedule created'],
)


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(pack(value)).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def freeze(path, value):
    raw = pack(value)
    if path.exists():
        if gzip.decompress(path.read_bytes()) != raw:
            raise ValueError('Frozen inputs changed: '+str(path))
    else:
        path.write_bytes(gzip.compress(raw, mtime=0))
    return hashlib.sha256(raw).hexdigest()


def exact_session(record, day):
    bars = intraday_data.cached_bars(record, day)
    expected = [f'{minute//60:02d}:{minute%60:02d}' for minute in range(555, 930, 5)]
    if [b['time'] for b in bars] != expected or sum(b['volume'] for b in bars) <= 0:
        raise ValueError('Expected exactly 75 regular-session candles and positive total volume.')
    return bars


def prepare_plan(daily, calendar, start, end):
    plan, excluded = {}, []
    indices = {s: {b['date']: i for i, b in enumerate(rows)} for s, rows in daily.items()}
    for day in calendar:
        if not start <= day <= end or day in intraday_data.SPECIAL_SESSIONS:
            continue
        selected = []
        day_index = calendar.index(day)
        previous_days = calendar[max(0, day_index-21):day_index]
        for symbol, rows in daily.items():
            i = indices[symbol].get(day)
            if i is None or i < 21 or len(previous_days) < 21:
                continue
            prior = rows[i-21:i]
            if [b['date'] for b in prior] != previous_days:
                continue
            # Include metadata-bearing first bar for as-of-date adjustments.
            adjusted = corporate_actions.adjusted_bars(rows[:i], day)[-21:]
            turnover = sum(b['close'] * b['volume'] for b in adjusted[-20:]) / 20
            if turnover < SPEC['minimum_prior_turnover']:
                continue
            atr = sum(max(b['high']-b['low'], abs(b['high']-a['close']), abs(b['low']-a['close']))
                      for a, b in zip(adjusted[-15:-1], adjusted[-14:])) / 14
            if atr <= 0:
                continue
            selected.append(dict(symbol=symbol, turnover=turnover, atr=atr,
                                 previous_high=adjusted[-1]['high'], previous_low=adjusted[-1]['low']))
        plan[day] = sorted(selected, key=lambda x: (-x['turnover'], x['symbol']))[:SPEC['scan_size']]
        if len(plan[day]) < SPEC['scan_size']:
            excluded.append(dict(date=day, reason='insufficient_daily_eligible_symbols', available=len(plan[day])))
    return plan, excluded


def acquire(output, start, end, phase):
    """Consistent read-only transaction; database refreshes cannot alter this snapshot."""
    if not store.database_enabled():
        raise ValueError('Configure the existing PostgreSQL connection first.')
    conn = pg.connection()
    audit = dict(phase=phase, start=start, end=end, created_at=store.now(), exclusions=[], stocks=[])
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        ns = pg.namespace()
        audit['namespace'] = ns
        audit['database_coverage'] = [dict(interval=r[0], stock_sessions=r[1], first=r[2], last=r[3], candles=r[4])
            for r in conn.execute('SELECT interval_minutes,count(*),min(session),max(session),sum(candle_count) '
                                  'FROM trader.intraday_sessions WHERE namespace=%s GROUP BY 1 ORDER BY 1', (ns,))]
        if phase == 'research':
            audit['coverage_by_stock'] = [dict(isin=r[0], sessions=r[1], first=r[2], last=r[3], exact_count_sessions=r[4])
                for r in conn.execute('SELECT isin,count(*),min(session),max(session),count(*) FILTER(WHERE candle_count=75) '
                                      'FROM trader.intraday_sessions WHERE namespace=%s AND interval_minutes=5 GROUP BY 1 ORDER BY 1', (ns,))]
        universe = store.read('universes/'+SPEC['universe'])
        if not universe:
            raise ValueError('Missing universe.')
        reference = market_history.evidence(snapshot=True)
        records = {}
        print('Reading daily history and provenance...', flush=True)
        for name, blob, checksum in conn.execute('SELECT d.name,c.content,d.sha256 FROM trader.documents d '
                'JOIN trader.contents c USING(sha256) WHERE d.namespace=%s AND d.name LIKE %s', (ns, 'bars/%')):
            records[name[5:]] = json.loads(pg.unpack(blob, checksum))
        benchmark = records.get('NIFTY50', {}).get('bars', [])
        calendar = sorted(b['date'] for b in benchmark if b['date'] <= end)
        if not calendar or calendar[0] >= start or calendar[-1] < end and not any(d >= end[:7]+'01' for d in calendar):
            raise ValueError('Benchmark calendar missing or insufficient.')
        daily, items, raw_hashes = {}, {}, {}
        for item in universe['instruments']:
            record = records.get(item['isin'])
            if not record:
                audit['exclusions'].append(dict(symbol=item['symbol'], reason='missing_daily'))
                continue
            # Do not expose validation daily prices to the research stage.
            record = {**record, 'bars': [b for b in record['bars'] if b['date'] <= end]}
            try:
                rows, evidence = market_history.prepare(item, record, reference=reference)
                findings = data_quality.audit({item['symbol']: rows}, end=end)['findings']
                if not rows or findings:
                    audit['exclusions'].append(dict(symbol=item['symbol'], reason='daily_quarantine_or_discontinuity', findings=findings, evidence=evidence))
                    continue
            except ValueError as exc:
                audit['exclusions'].append(dict(symbol=item['symbol'], reason='daily_evidence_failure', detail=str(exc)))
                continue
            daily[item['symbol']], items[item['symbol']] = rows, item
            raw_hashes[item['symbol']] = digest(record)
            audit['stocks'].append(dict(symbol=item['symbol'], isin=item['isin'], first=rows[0]['date'], last=rows[-1]['date'], bars=len(rows), evidence=evidence))
        plan, shortfalls = prepare_plan(daily, calendar, start, end)
        audit['daily_selection_shortfalls'] = shortfalls
        requests = {intraday_data.cache_key(items[c['symbol']]['isin'], day): (c['symbol'], day)
                    for day, selected in plan.items() for c in selected}
        sessions, retrieved = {}, {}
        names = sorted(requests)
        print(f'Checking {len(names)} selected five-minute stock-sessions...', flush=True)
        for offset in range(0, len(names), 500):
            for name, bars, checksum in conn.execute('SELECT document_name,bars,source_sha256 FROM trader.intraday_sessions '
                    'WHERE namespace=%s AND document_name=ANY(%s)', (ns, names[offset:offset+500])):
                symbol, day = requests[name]
                retrieved[name] = checksum
                try:
                    normalized = exact_session({'bars': bars}, day)
                    day_bar = next(b for b in daily[symbol] if b['date'] == day)
                    observed = dict(open=normalized[0]['open'], close=normalized[-1]['close'],
                                    high=max(b['high'] for b in normalized), low=min(b['low'] for b in normalized))
                    differences = {k: abs(v/day_bar[k]-1) for k, v in observed.items()}
                    if max(differences.values()) > .02:
                        raise ValueError('Daily/minute price-basis mismatch >2%: '+str(differences))
                    sessions.setdefault(symbol, {})[day] = normalized
                except (KeyError, TypeError, ValueError) as exc:
                    audit['exclusions'].append(dict(symbol=symbol, date=day, reason='invalid_intraday', detail=str(exc)))
            if offset % 2500 == 0:
                print(f'  checked {min(offset+500,len(names))}/{len(names)}', flush=True)
        for name in names:
            if name not in retrieved:
                symbol, day = requests[name]
                audit['exclusions'].append(dict(symbol=symbol, date=day, reason='missing_intraday'))
        matched = {day: [c for c in selected if day in sessions.get(c['symbol'], {})] for day, selected in plan.items()}
        audit.update(selected_stock_sessions=len(requests), valid_stock_sessions=sum(map(len, sessions.values())),
                     session_count=len(plan), source_session_checksums=retrieved,
                     daily_source_hashes=raw_hashes, exclusion_counts=dict(Counter(x['reason'] for x in audit['exclusions'])))
    # Freeze exact causal daily inputs, reference evidence, plan and minute bars locally.
    inputs = dict(spec_sha256=digest(SPEC), daily=daily, reference=reference, universe=universe,
                  sessions=sessions, plan=matched, selected_plan=plan, calendar=calendar)
    audit['input_sha256'] = freeze(output/(phase+'_inputs.json.gz'), inputs)
    save(output/(phase+'_coverage.json'), audit)
    if not requests or audit['valid_stock_sessions']/len(requests) < .95 or len(plan) < 100:
        raise ValueError('Coverage gate failed: require >=95% selected sessions and >=100 trading days; see saved audit.')
    return inputs, audit


def load_inputs(output, phase, window):
    path = output/(phase+'_inputs.json.gz')
    if path.exists():
        raw = gzip.decompress(path.read_bytes())
        audit = json.loads((output/(phase+'_coverage.json')).read_text())
        inputs = json.loads(raw)
        if hashlib.sha256(raw).hexdigest() != audit['input_sha256'] or inputs['spec_sha256'] != digest(SPEC):
            raise ValueError('Frozen snapshot verification failed.')
        if audit['valid_stock_sessions']/max(1,audit['selected_stock_sessions']) < .95 or audit['session_count'] < 100:
            raise ValueError('Previously frozen coverage failed; choose a new output for a new audit.')
        print('Reusing verified '+phase+' inputs.', flush=True)
        return inputs, audit
    return acquire(output, window['start'], window['end'], phase)


def eligible(result, stress):
    m, gate = result['metrics'], SPEC['candidate_gate']
    positives = [v for v in result['stock_pnl'].values() if v > 0]
    concentration = max(positives)/sum(positives) if positives else 1
    months = result['monthly_pnl']
    # Count all observed research months, including months with zero trades.
    observed_months = {p['date'][:7] for p in result['curve']}
    tests = dict(enough_trades=m['trade_count'] >= gate['min_trades'],
                 profitable=m['final_equity'] > m['initial_capital'],
                 profitable_stress=stress['metrics']['return_pct'] > 0,
                 profit_factor=(m['profit_factor'] or 0) >= gate['min_profit_factor'],
                 drawdown=m['max_observed_close_drawdown_pct'] <= gate['max_drawdown_pct'],
                 months=sum(v > 0 for v in months.values())/max(1,len(observed_months)) > gate['min_positive_month_fraction'],
                 concentration=concentration <= gate['max_positive_stock_profit_share'])
    return dict(passed=all(tests.values()), checks=tests, positive_stock_profit_share=concentration)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=store.ROOT/'artifacts'/'candle_rejection_20261029')
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    spec_path = output/'specification.json'
    if spec_path.exists():
        if json.loads(spec_path.read_text())['spec'] != SPEC:
            raise ValueError('Saved specification differs. Preserve it and use a new experiment directory.')
    else:
        save(spec_path, dict(declared_at=datetime.now(intraday_data.IST).isoformat(), spec=SPEC, spec_sha256=digest(SPEC)))
    source_paths = [Path(__file__), Path(engine.__file__), Path(intraday_data.__file__), Path(market_history.__file__),
                    Path(corporate_actions.__file__), Path(data_quality.__file__), Path(store.ROOT/'core/research/intraday_costs.py')]
    code = {str(p.relative_to(store.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    code_path = output/'code_manifest.json'
    if code_path.exists() and json.loads(code_path.read_text()) != code:
        raise ValueError('Research implementation changed. Use a new output directory to preserve prior evidence.')
    save(code_path, code)
    print('Specification frozen before outcome inspection: '+str(spec_path), flush=True)
    inputs, audit = load_inputs(output, 'research', SPEC['research'])
    print(f"Coverage: {audit['valid_stock_sessions']}/{audit['selected_stock_sessions']} selected sessions usable", flush=True)
    if args.audit_only:
        return
    summary = dict(spec_sha256=digest(SPEC), research_input_sha256=audit['input_sha256'], runs=[],
                   validation_status='unread; pending research gates', prospective=SPEC['prospective'], limitations=SPEC['limitations'])
    results = {}
    for variant in SPEC['variants']:
        for direction in SPEC['directions']:
            for slip in SPEC['slippage_bps']:
                key = f'{variant}_{direction}_{slip}bps'
                result = engine.simulate(inputs['sessions'], inputs['plan'], variant, 1 if direction == 'long' else -1, slip)
                results[key] = result
                save(output/(key+'.json'), result)
                summary['runs'].append(dict(key=key, variant=variant, direction=direction, slippage_bps=slip, **result['metrics']))
                save(output/'summary.json', summary)
                print(f"{key}: {result['metrics']['return_pct']:+.3f}% / {result['metrics']['trade_count']} trades", flush=True)
    candidates = []
    summary['candidate_checks'] = {}
    for variant in SPEC['variants'][1:]:
        for direction in SPEC['directions']:
            key = f'{variant}_{direction}_5bps'
            gate = eligible(results[key], results[f'{variant}_{direction}_10bps'])
            # Require added value against the matched same-direction baseline.
            gate['checks']['beats_baseline_return'] = results[key]['metrics']['return_pct'] > results[f'level_{direction}_5bps']['metrics']['return_pct']
            gate['passed'] = all(gate['checks'].values())
            summary['candidate_checks'][key] = gate
            if gate['passed']:
                candidates.append((results[key]['metrics']['return_pct'], variant, direction))
    if not candidates:
        summary['validation_status'] = 'not opened: no research candidate passed the predeclared gates'
        summary['decision'] = 'No candidate advanced to paper or live trading. Validation remains reserved.'
    else:
        _, variant, direction = max(candidates)
        summary['selected_candidate'] = dict(variant=variant, direction=direction)
        summary['validation_status'] = 'candidate selected and frozen; acquiring validation'
        save(output/'summary.json', summary)
        validation, vaudit = load_inputs(output, 'validation', SPEC['validation'])
        summary['validation_input_sha256'] = vaudit['input_sha256']
        summary['validation_runs'] = []
        candidate_results = []
        for trial in ('level', variant):
            for slip in (5, 10):
                result = engine.simulate(validation['sessions'], validation['plan'], trial, 1 if direction == 'long' else -1, slip)
                save(output/f'validation_{trial}_{direction}_{slip}bps.json', result)
                summary['validation_runs'].append(dict(variant=trial, direction=direction, slippage_bps=slip, **result['metrics']))
                if trial == variant:
                    candidate_results.append(result['metrics'])
        passed = all(m['return_pct'] > 0 and m['max_observed_close_drawdown_pct'] <= 15 for m in candidate_results) and (candidate_results[0]['profit_factor'] or 0) > 1
        summary.update(validation_status='passed' if passed else 'failed',
                       decision='Candidate eligible for a separate forward paper implementation; no trading enabled.' if passed else 'Validation failed; no candidate advanced.')
    save(output/'summary.json', summary)
    print(summary['decision'], flush=True)
    print('Saved: '+str(output), flush=True)


if __name__ == '__main__':
    main()
