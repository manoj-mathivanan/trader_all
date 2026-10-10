"""Reconstruct research scores from archived filings, with publication-time cutoffs.

This is separate from the live cache: reconstructed evidence was downloaded later.
It must never be passed off as a contemporaneously recorded trading decision.
"""
from bisect import bisect_right
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from core.research import store, official_filings, company_review


def calculation_version():
    """Invalidate derived snapshots when parsing, reconstruction or identity rules change."""
    root = Path(__file__).resolve().parents[2]
    paths = [Path(__file__), Path(official_filings.__file__),
             root/'reference_data/filing_identities.json']
    return hashlib.sha256(b''.join(path.read_bytes() if path.exists() else b''
                                  for path in paths)).hexdigest()


def load_calculations(version):
    try:
        cached = store.read('cache/historical_calculations', {})
        if cached.get('version') == version and cached.get('sha256') == digest(cached):
            return cached.get('companies', {})
    except (OSError, ValueError, TypeError):
        pass
    return {}


def decision_time(day, entry_mode='next_open'):
    return datetime.fromisoformat(str(day)+('T15:30:00+05:30' if entry_mode == 'close' else 'T09:15:00+05:30'))


def rank_key(value, symbol):
    # Missing/stale evidence ranks last. Equal scores prefer greater coverage,
    # then symbol for reproducible ties. Ranking alone does not impose a buy gate.
    usable = value and value.get('score') is not None and not value.get('flags')
    return (-value['score'], -value['coverage_pct'], symbol) if usable else (1, 0, symbol)


def reconstruct(filings, item):
    """Never use a comparison/annual filing until its own publication time."""
    versions = []
    for published in sorted({f['filed_at'] for f in filings}, key=datetime.fromisoformat):
        cutoff = datetime.fromisoformat(published)
        available = [f for f in filings if datetime.fromisoformat(f['filed_at']) <= cutoff]
        latest_end = max(f['end'] for f in available)
        basis = 'consolidated' if any(f['end'] == latest_end and f['basis'] == 'consolidated'
                                      for f in available) else 'standalone'
        snapshot = official_filings.calculate([f for f in available if f['basis'] == basis], item)
        if snapshot:
            versions.append(dict(available_at=published, snapshot=snapshot,
                                 documents=[{k: f[k] for k in ('url', 'sha256', 'filed_at')} for f in available]))
    return versions


def capture(universe, log=lambda message: None):
    series, excluded = {}, []
    version = calculation_version()
    calculations = load_calculations(version)
    changed, reused, rebuilt = False, 0, 0
    at = datetime.now(timezone.utc)
    for index, item in enumerate(universe['instruments']):
        key = 'company/fundamentals/'+item['isin']
        records = [store.read(key, {})]
        records.extend(store.read(key+'/history/'+path.stem, {})
                       for path in sorted((store.DATA/key/'history').glob('*.json')))
        records = [record for record in records if record.get('validation', {}).get('status') == 'passed']
        if not records:
            excluded.append(dict(symbol=item['symbol'], reason='No validated archived financial evidence'))
            continue
        filings = []
        try:
            documents = {}
            for record in records:
                for document in record.get('documents', []):
                    documents[(document['url'], document['sha256'])] = document
            # Always verify archived bytes, including on a calculation cache hit.
            # This keeps corruption and removed artifacts visible on every run.
            verified = []
            for document in documents.values():
                path = (store.DATA/document['artifact']).resolve()
                if not path.is_relative_to((store.DATA/'company/filings').resolve()):
                    raise ValueError('Filing artifact outside archive')
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != document['sha256']:
                    raise ValueError('Filing checksum mismatch')
                verified.append((document, raw))
            signature = digest(dict(item=item, documents=list(documents.values())))
            cached = calculations.get(item['isin'], {})
            if cached.get('signature') == signature:
                series[item['symbol']] = cached['versions']
                reused += 1
            else:
                parsed_urls = {}
                for document, raw in verified:
                    parsed = official_filings.parse(raw.decode('utf-8'), document['url'], item, at)
                    # The exchange can change HTML presentation at the same URL.
                    # Verify every byte variant, then require identical parsed facts.
                    facts = {k: v for k, v in parsed.items() if k != 'rows'}
                    if document['url'] in parsed_urls:
                        if parsed_urls[document['url']] != facts:
                            raise ValueError('Conflicting archived filing facts')
                        continue
                    parsed_urls[document['url']] = facts
                    parsed['sha256'] = document['sha256']
                    filings.append(parsed)
                versions = reconstruct(filings, item)
                series[item['symbol']] = versions
                calculations[item['isin']] = dict(signature=signature, versions=versions)
                changed = True
                rebuilt += 1
        except (OSError, ValueError, KeyError, UnicodeError) as exc:
            excluded.append(dict(symbol=item['symbol'], reason=str(exc)))
        if index % 50 == 0:
            log(f'Verifying historical financial evidence: {index+1}/{len(universe["instruments"])}')
    if changed:
        cached = dict(version=version, companies=calculations)
        cached['sha256'] = digest(cached)
        store.write('cache/historical_calculations', cached)
    log(f'Historical financial calculations: reused {reused}, rebuilt {rebuilt}; '
        f'{len(excluded)} symbols without usable archived evidence. Filing checksums verified.')
    payload = dict(series=series, excluded=excluded, captured_at=store.now(),
                   method='reconstructed_from_verified_archived_NSE_filings',
                   notice='Downloaded retrospectively. Only filings published by the decision time are used. '
                   'The archive is incomplete and may omit intermediate quarters or earlier revisions; '
                   'current constituent survivorship and archival selection bias remain. '
                   'Missing, stale or flagged scores rank last; score ties use coverage then symbol. '
                   'Ranking does not change the fundamental eligibility filter.')
    payload['sha256'] = digest(payload)
    return payload


def digest(payload):
    return hashlib.sha256(json.dumps({k:v for k,v in payload.items() if k != 'sha256'}, sort_keys=True).encode()).hexdigest()


class Scores:
    def __init__(self, payload, entry_mode='next_open'):
        if payload.get('sha256') != digest(payload):
            raise ValueError('Frozen fundamental evidence checksum mismatch')
        self.series = payload['series']
        self.times = {s:[datetime.fromisoformat(v['available_at']) for v in rows] for s,rows in self.series.items()}
        self.entry_mode = entry_mode
        self.cache = {}

    def __call__(self, symbol, day, *, at=None):
        at = at or decision_time(day, self.entry_mode)
        if at.tzinfo is None:
            raise ValueError('Fundamental decision time requires an explicit timezone')
        key = symbol, at.isoformat()
        if key not in self.cache:
            idx = bisect_right(self.times.get(symbol, []), at)-1
            version = self.series[symbol][idx] if idx >= 0 else None
            result = company_review.score(version['snapshot'] if version else None, at=at)
            self.cache[key] = dict(score=result['score'], coverage_pct=result['coverage_pct'], flags=result['flags'],
                                   period_end=version['snapshot']['period_end'] if version else None,
                                   available_at=version['available_at'] if version else None,
                                   period_age_days=result.get('period_age_days'),checked_at=at.isoformat())
        return self.cache[key]
