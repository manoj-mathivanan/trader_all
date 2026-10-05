"""Conservative diagnostics; a price gap is evidence to review, not an adjustment."""
from datetime import date

GAP_THRESHOLD_PCT = 35
VERSION = 'price-gap-v1'


def audit(datasets, *, start=None, end=None, after=None):
    from core.research.corporate_actions import adjusted_bars
    findings = []
    for symbol, bars in sorted(datasets.items()):
        if bars:
            bars = adjusted_bars(bars, end or bars[-1]['date'])
        for previous, current in zip(bars, bars[1:]):
            day = current['date']
            if (start and day < str(start)) or (end and day > str(end)) or (after and day <= after):
                continue
            gap = (current['open'] - previous['close']) / previous['close'] * 100
            if abs(gap) >= GAP_THRESHOLD_PCT:
                findings.append({'symbol': symbol, 'date': day, 'previous_date': previous['date'],
                                 'previous_close': previous['close'], 'open': current['open'],
                                 'gap_pct': gap, 'status': 'needs_review'})
    return {'version': VERSION, 'adjustment_status': 'unverified',
            'gap_threshold_pct': GAP_THRESHOLD_PCT, 'findings': findings,
            'notice': 'Gaps are not proof of a corporate action. Smaller events and already adjusted data can pass this check.'}


def require_no_anomalies(report):
    if report['findings']:
        item = report['findings'][0]
        raise ValueError(f"Price discontinuity needs review: {item['symbol']} on {item['date']} "
                         f"({item['gap_pct']:+.2f}% versus previous observed close). "
                         f"{len(report['findings'])} anomaly(s); simulation halted before ledger changes. "
                         "Verify provider adjustment behaviour and the event; do not automatically repair prices.")


def audit_cached_universe(settings):
    from core.research import store, market_history
    universe = store.read('universes/' + settings.universe, {})
    report = audit({})
    report.update(universe=settings.universe, symbols_scanned=0, missing_symbols=[],
                  raw_findings=[], history_changes=[])
    reference = market_history.evidence(snapshot=True)
    for item in universe.get('instruments', []):
        record = store.read('bars/' + item['isin'], {})
        if not record.get('bars'):
            report['missing_symbols'].append(item['symbol'])
            continue
        report['raw_findings'].extend(audit({item['symbol']: record['bars']})['findings'])
        bars, history = market_history.prepare(item, record, reference=reference, fingerprint=False)
        if history.get('quarantine') or history.get('removed_prelisting_bars'):
            report['history_changes'].append({'symbol': item['symbol'], **history})
        report['findings'].extend(audit({item['symbol']: bars})['findings'])
        report['symbols_scanned'] += 1
    return report


def with_listing_metadata(bars, metadata):
    """Freeze verified listing evidence in inputs, never infer it from the first candle."""
    if not bars or not metadata:
        return bars
    if metadata.get('verified') is not True or not metadata.get('source'):
        raise ValueError('Listing metadata requires verified=true and a source.')
    listing_date = date.fromisoformat(metadata['listing_date']).isoformat()
    if metadata.get('ipo_verified') is True:
        ipo_day = date.fromisoformat(metadata.get('ipo_date', listing_date)).isoformat()
        if ipo_day > listing_date or not metadata.get('ipo_source', metadata.get('source')):
            raise ValueError('Verified IPO date must have a source and cannot follow the exchange listing date.')
    return [dict(bars[0], listing_metadata={**metadata, 'listing_date': listing_date}), *bars[1:]]
