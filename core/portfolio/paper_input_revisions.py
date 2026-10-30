"""Audit daily finalisation without rewriting observations used by paper decisions."""
from datetime import datetime
import hashlib
import json

from core.research import store, market_data

VALUES = ('open', 'high', 'low', 'close', 'volume')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def provisional_evidence(frozen, symbol, item, bar):
    known = frozen.get('history', {}).get(symbol, {}).get('provisional_daily', {}).get(bar['date'], {})
    if known.get('provisional') is True:
        return 'Captured provisional daily provenance'
    # Older paper snapshots did not carry forward per-day provisional flags.
    # Migrate only when the original values exactly match a complete session
    # archived before that snapshot; numerical tolerances cannot prove origin.
    minute = store.read('intraday/5m/'+item['isin']+'/'+bar['date'], {})
    if minute.get('source') != 'Upstox current session V3' or not market_data.complete_minutes(minute, bar['date']):
        return None
    try:
        if datetime.fromisoformat(minute['fetched_at']) > datetime.fromisoformat(frozen['captured_at']):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    bars = sorted(minute['bars'], key=lambda b: b['timestamp'])
    values = dict(open=bars[0]['open'], high=max(b['high'] for b in bars), low=min(b['low'] for b in bars),
                  close=bars[-1]['close'], volume=sum(b['volume'] for b in bars))
    if all(bar.get(k) == values[k] for k in VALUES):
        return 'Exact complete-session minute evidence archived before paper capture'
    return None


def reconcile(frozen, symbol, item, old, current, record):
    """Keep processed inputs; allow only proven first publication or its repeat."""
    end = old[-1]['date']
    prefix = [b for b in current if b['date'] <= end]
    if [b['date'] for b in prefix] != [b['date'] for b in old]:
        raise ValueError(f'{symbol}: previously processed input dates changed; ledger unchanged.')
    audits = frozen.setdefault('published_input_reconciliations', {})
    count = 0
    for original, published in zip(old, prefix):
        day = original['date']
        fields = {k for k in set(original) | set(published) if original.get(k) != published.get(k)}
        key = symbol+'/'+day
        previous = audits.get(key)
        if previous:
            if previous['original_sha256'] != digest(original) or previous['published_sha256'] != digest(published):
                raise ValueError(f'{symbol}: published history revised again on {day}; ledger unchanged.')
            continue
        if original == published:
            known = frozen.get('history', {}).get(symbol, {}).get('provisional_daily', {}).get(day, {})
            if (known.get('provisional') is not True or record.get('source') != 'upstox_v3'
                    or day in record.get('provisional_daily', {})):
                continue
        evidence = provisional_evidence(frozen, symbol, item, original)
        if (not fields <= set(VALUES) or not evidence or record.get('source') != 'upstox_v3'
                or day in record.get('provisional_daily', {})):
            raise ValueError(f'{symbol}: previously processed inputs changed on {day}; ledger unchanged.')
        audits[key] = dict(symbol=symbol, date=day, at=store.now(), evidence=evidence,
            original_sha256=digest(original), published_sha256=digest(published),
            differences={k:dict(recorded=original.get(k), published=published.get(k)) for k in sorted(fields)},
            policy='Preserve recorded paper observations, signals, fills and equity; append only new sessions.')
        frozen.setdefault('history', {}).setdefault(symbol, {}).setdefault('provisional_daily', {}).setdefault(
            day, dict(provisional=True, source=evidence))
        count += 1
    return list(old) + [b for b in current if b['date'] > end], count


def capture_provisional(frozen, symbol, record, after, through):
    dates = {day:details for day,details in record.get('provisional_daily', {}).items() if after < day <= through}
    known = frozen.get('history', {}).get(symbol, {}).get('provisional_daily', {})
    # Initial input evidence can describe dates beyond a published-only cutoff.
    # A newly appended published candle must not inherit such an unused flag.
    for day in list(known):
        if after < day <= through and day not in dates:
            known.pop(day)
    if dates:
        frozen.setdefault('history', {}).setdefault(symbol, {}).setdefault('provisional_daily', {}).update(dates)
