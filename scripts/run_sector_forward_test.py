"""Prospective daily shadow ledgers. Never sends broker orders.

Run init once, then cycle --refresh after each completed NSE session.
All arms commit together; only previously captured signals can enter.
"""
import argparse
import hashlib
import inspect
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research import backtest, corporate_actions, fundamental_history, market_history, store, upstox
from core.research.config import BacktestConfig, Settings
from core.research.relative_strength import StrengthHistory
from core.research.sector_breadth import SectorBreadth

KEY = 'forward_tests/sector_20261011'
IST = timezone(timedelta(hours=5, minutes=30), 'IST')
ARMS = {'control': {}, 'rs70': {'min_short_rs_rating': 70}, 'sector_cap2': {}}


def fingerprint():
    files = [Path(__file__), Path(backtest.__file__), Path(corporate_actions.__file__),
             Path(fundamental_history.__file__), ROOT / 'core/research/config.py',
             ROOT / 'core/research/relative_strength.py', ROOT / 'core/research/sector_breadth.py',
             ROOT / 'core/research/market_history.py', ROOT / 'core/research/candle_repairs.py',
             ROOT / 'core/execution/paper.py', ROOT / 'core/risk/position_sizer.py',
             ROOT / 'core/research/company_review.py']
    files += list((ROOT / 'strategies/swing_patterns/patterns').rglob('*.py'))
    files += list((ROOT / 'core/execution').rglob('*.py'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}


def inputs(protocol, through):
    data = {}
    for item in protocol['instruments']:
        record = store.read('bars/' + item['isin'])
        if not record:
            raise ValueError('Missing price history: ' + item['symbol'])
        rows, _ = market_history.prepare(item, record, reference=protocol['history_reference'], fingerprint=False)
        rows = [b for b in rows if b['date'] <= through]
        if not rows:
            raise ValueError('No usable history: ' + item['symbol'])
        data[item['symbol']] = rows
    return data


def hashes(data, through):
    return {s: market_history.digest([b for b in rows if b['date'] <= through]) for s, rows in data.items()}


def timely_capture(captures, symbol, signal_day, entry_day):
    capture = captures.get(signal_day)
    if capture is None or symbol not in capture['signals'] or signal_day >= entry_day:
        return False
    captured = datetime.fromisoformat(capture['captured_at'])
    return captured < datetime.combine(date.fromisoformat(entry_day), time(9, 15), IST)


def engine(cap, sectors, audit):
    """Instrument an isolated engine; keep production simulate unchanged."""
    source = inspect.getsource(backtest.simulate)
    anchor = "            signal_day = datasets[symbol][signal_idx]['date']"
    assert source.count(anchor) == 1
    source = source.replace(anchor, anchor + "\n            audit.append({'symbol': symbol, 'signal_date': signal_day, 'entry_date': day, 'status': 'candidate', 'open': b['open']})")
    # Every candidate-path continue gets an audit reason before returning to loop.
    begin = source.index(anchor)
    end = source.index("            execution = broker.fill", begin)
    block = source[begin:end]
    replacements = {
        "            if denial:": "            if denial:\n                audit[-1].update(status='blocked', reason=denial)",
        "                if not sector_decision['allowed'] and not sector_observe_only:": "                if not sector_decision['allowed'] and not sector_observe_only:\n                    audit[-1].update(status='blocked', reason=sector_decision['reason'])",
        "                if not breadth_decision['allowed']:": "                if not breadth_decision['allowed']:\n                    audit[-1].update(status='blocked', reason=breadth_decision['reason'])",
        "            if entry_check is not None and not entry_check(symbol,day):": "            if entry_check is not None and not entry_check(symbol,day):\n                audit[-1].update(status='missed', reason='Signal not captured before entry open')",
        "            if strength is not None and not strength.passes(symbol, signal_day, cfg):": "            if strength is not None and not strength.passes(symbol, signal_day, cfg):\n                audit[-1].update(status='blocked', reason='RS below threshold')",
        "            if len(positions) >= cfg.max_positions:": "            if len(positions) >= cfg.max_positions:\n                audit[-1].update(status='blocked', reason='Portfolio full')",
        "            if qty < 1:": "            if qty < 1:\n                audit[-1].update(status='blocked', reason='Insufficient sizing capacity')",
    }
    for old, new in replacements.items():
        assert block.count(old) == 1, old
        block = block.replace(old, new)
    capacity = '            if len(positions) >= cfg.max_positions:'
    block = block.replace(capacity,
        "            if cap and sum(sectors.get(s) == sectors.get(symbol) for s in positions) >= cap:\n"
        "                skipped += 1\n"
        "                audit[-1].update(status='blocked', reason='Two positions in sector')\n"
        "                continue\n" + capacity)
    source = source[:begin] + block + source[end:]
    anchor = '            cash -= qty * fill + fee'
    assert source.count(anchor) == 1
    source = source.replace(anchor, "            audit[-1].update(status='filled', simulated_price=fill, quantity=qty)\n" + anchor)
    scope = {**backtest.__dict__, 'cap': cap, 'sectors': sectors, 'audit': audit}
    exec(source, scope)
    return scope['simulate']


def initialize(now):
    if store.read(KEY):
        return status(store.read(KEY))
    run = store.read('runs/5cafe09b6cdc')
    frozen = store.read('run_data/5cafe09b6cdc')
    instruments = [i for i in run['universe_snapshot']['instruments'] if i['symbol'] in frozen]
    start = (now.date() + timedelta(days=1)).isoformat()
    protocol = dict(source_run='5cafe09b6cdc', registered_at=now.isoformat(), decision_start=start,
                    config=run['config'], instruments=instruments, arms=ARMS,
                    history_reference=market_history.evidence(snapshot=True), code=fingerprint(),
                    notes=['Daily OHLC modeled fills, not broker executions.',
                           'Fixed eligible universe and sector labels; inherited fundamental exclusions are not reassessed.',
                           'Fundamental ranks captured from verified local archives at signal close; archive refresh is external.',
                           'Missing captures cannot produce retrospective entries.',
                           'Historical price/metadata revisions pause the study; no automatic rule changes.'],
                    review_sessions=[20, 60], minimum_closed_trades_per_arm=30)
    through = now.date().isoformat()
    data = inputs(protocol, through)
    # Pin the initial historical prefix, including sessions predating registration.
    last = max(rows[-1]['date'] for rows in data.values())
    record = dict(protocol=protocol, protocol_sha256=market_history.digest(protocol),
                  verified_through=last, price_hashes=hashes(data, last), captures={}, audits=[],
                  arms={a: {'cash': 100000.0, 'last_session': last} for a in ARMS})
    store.write(KEY, record)
    return status(record)


def status(record):
    output = dict(study=KEY, decision_start=record['protocol']['decision_start'],
                  last_session=record['verified_through'], captured_sessions=len(record['captures']), arms={})
    for arm, state in record['arms'].items():
        equity = state.get('curve', [{}])[-1].get('equity', state['cash']) if state.get('curve') else state['cash']
        output['arms'][arm] = dict(equity=round(equity, 2), return_pct=round((equity / 100000 - 1) * 100, 3),
                                  closed_trades=len(state.get('trades', [])), positions=len(state.get('positions', {})),
                                  modeled_orders=len(state.get('orders', [])), max_drawdown_pct=state.get('max_dd', 0))
    return output


def cycle(now, refresh=False):
    record = store.read(KEY)
    if not record:
        raise ValueError('Initialize study first.')
    if record.get('status') == 'superseded_before_first_trade':
        raise ValueError('This study was superseded by the native midday paper scenarios.')
    p = record['protocol']
    if market_history.digest(p) != record['protocol_sha256'] or fingerprint() != p['code']:
        raise ValueError('Frozen rules or code changed; review required before continuing.')
    current_actions = store.read('metadata/corporate_actions', {})
    for item in p['instruments']:
        if current_actions.get(item['isin'], []) != p['history_reference'].get('corporate_actions', {}).get(item['isin'], []):
            raise ValueError('Corporate-action evidence changed; review required: ' + item['symbol'])
    if now.time() < time(16, 30):
        raise ValueError('Run after 16:30 IST, once daily candles are complete.')
    today = now.date().isoformat()
    if refresh:
        upstox.ingest(Settings(start=date(2018, 10, 1), end=now.date()),
                      lambda message: None, universe={'instruments': p['instruments']}, extend_history=False)
    data = inputs(p, today)
    if hashes(data, record['verified_through']) != record['price_hashes']:
        raise ValueError('Previously observed prices changed; study paused for data review.')
    latest = max(rows[-1]['date'] for rows in data.values())
    if latest <= record['verified_through']:
        return {**status(record), 'result': 'No new completed session'}
    stale = [s for s, rows in data.items() if rows[-1]['date'] != latest]
    if stale:
        raise ValueError('Incomplete universe prices; no ledger advanced: ' + ', '.join(stale[:20]))
    sectors = {i['symbol']: i['sector'] for i in p['instruments']}
    # Rank only information captured before the entry session.
    indices = {s: {b['date']: i for i, b in enumerate(rows)} for s, rows in data.items()}
    def prior(s, day):
        i = indices[s][day]
        return data[s][i - 1]['date'] if i else ''
    def check(s, day):
        return timely_capture(record['captures'], s, prior(s, day), day)
    def rank(s, day):
        cap = record['captures'].get(prior(s, day), {})
        return cap.get('scores', {}).get(s, {'score': None, 'coverage_pct': 0, 'flags': ['Not captured']})
    all_audits = []
    engine_start = (date.fromisoformat(p['decision_start']) - timedelta(days=1)).isoformat()
    for arm, delta in ARMS.items():
        cfg = BacktestConfig(**{**p['config'], **delta, 'start': engine_start, 'end': latest})
        audit = []
        result = engine(2 if arm == 'sector_cap2' else 0, sectors, audit)(
            data, cfg, state=record['arms'][arm], liquidate=False,
            entry_check=check, fundamental_scores=rank, sector_instruments=p['instruments'])
        record['arms'][arm] = result['state']
        all_audits.extend(dict(row, arm=arm) for row in audit)
    record['audits'].extend(all_audits)
    # Older unobserved sessions update exits but never recreate signals for entries.
    if latest == today and today >= p['decision_start']:
        cfg = BacktestConfig(**{**p['config'], 'start': engine_start, 'end': latest})
        fundamentals = fundamental_history.capture({'instruments': p['instruments']})
        scores = fundamental_history.Scores(fundamentals, entry_mode='close')
        strength = StrengthHistory(data)
        gate = SectorBreadth(data, p['instruments'], cfg.market_breadth_pct, cfg.market_min_coverage_pct)
        signals = {}
        for s, rows in data.items():
            i = len(rows) - 1
            adjusted = corporate_actions.adjusted_bars(rows, latest)
            if backtest.signal(adjusted, i, cfg):
                signals[s] = dict(close=rows[-1]['close'], rs63=strength.ratings(latest, 63).get(s),
                                  sector=gate.decision(s, latest))
        record['captures'][today] = dict(captured_at=now.isoformat(), signals=signals,
                                         scores={s: scores(s, latest) for s in data},
                                         fundamentals_sha256=fundamentals['sha256'],
                                         bars={s: rows[-1] for s, rows in data.items()})
    record.update(verified_through=latest, price_hashes=hashes(data, latest), updated_at=now.isoformat())
    store.write(KEY, record)
    return {**status(record), 'new_candidate_decisions': len(all_audits),
            'latest_signals': len(record['captures'].get(latest, {}).get('signals', {}))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'cycle', 'status'])
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    # Cross-process exclusion covers ingestion and the three-arm atomic commit.
    lock = store.DATA / 'forward_tests' / '.sector_20261011.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    try:
        with lock.open('x'):
            acquired = True
            now = datetime.now(IST)
            output = initialize(now) if args.action == 'init' else cycle(now, args.refresh) if args.action == 'cycle' else status(store.read(KEY))
            print(json.dumps(output, indent=2))
    finally:
        # Only the process that acquired the lock may remove it.
        if acquired:
            lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
