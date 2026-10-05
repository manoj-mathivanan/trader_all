"""Evidence-backed derived inputs; provider candles and saved ledgers remain intact."""
import hashlib
import json
from datetime import date
from pathlib import Path

from core.research import store, data_quality, corporate_actions

EVIDENCE_FILE = Path(__file__).resolve().parents[2] / 'reference_data/history_evidence.json'
VERSION = 'history-evidence-v1'


def evidence(*, snapshot=False):
    ref = json.loads(EVIDENCE_FILE.read_text(encoding='utf-8'))
    if snapshot:
        ref['listings'] = merge_listings(ref.get('listings', {}), store.read('metadata/listings', {}))
        ref['corporate_actions'] = store.read('metadata/corporate_actions', {})
        ref['local_metadata_frozen'] = True
    return ref


def merge_listings(base, overrides):
    result = dict(base)
    for isin, item in overrides.items():
        result[isin] = {**base.get(isin, {}), **item}
    return result


def listing_for(item, listings):
    found = listings.get(item['isin'])
    if found:
        if found.get('ipo_verified') is None:
            ipo = [x for x in listings.values() if x.get('symbol') == item['symbol'] and x.get('ipo_verified') is True]
            if len(ipo) == 1:
                return {**found, 'ipo_verified': True, 'ipo_date': ipo[0].get('ipo_date', ipo[0]['listing_date']),
                        'ipo_source': ipo[0].get('ipo_source', ipo[0]['source'])}
        return found
    # A sourced issuer listing date survives a split-related ISIN change. Match
    # only an explicit exact symbol, never company-name guessing.
    matches = [x for x in listings.values() if x.get('symbol') == item['symbol']]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous listing evidence for {item['symbol']}.")
    return matches[0] if matches else None


def prepare(item, record, *, reference=None, fingerprint=True):
    ref = reference if reference is not None else evidence(snapshot=True)
    listings = ref.get('listings', {}) if ref.get('local_metadata_frozen') else merge_listings(ref.get('listings', {}), store.read('metadata/listings', {}))
    listing = listing_for(item, listings)
    raw = record['bars']
    bars = raw
    details = {'version': VERSION, 'removed_prelisting_bars': 0}
    if fingerprint:
        details['source_sha256'] = digest(raw)
    quarantine = ref.get('quarantine', {}).get(item['isin'])
    if quarantine:
        details['quarantine'] = quarantine
        return [], details
    if listing:
        # Validate before filtering. The original cache remains unchanged.
        data_quality.with_listing_metadata(raw, listing)
        bars = [b for b in raw if b['date'] >= listing['listing_date']]
        details.update(listing=listing, removed_prelisting_bars=len(raw) - len(bars))
        bars = data_quality.with_listing_metadata(bars, listing)
    action_records = (ref.get('corporate_actions', {}) if ref.get('local_metadata_frozen')
                      else store.read('metadata/corporate_actions', {})).get(item['isin'], [])
    bars = corporate_actions.attach(bars, action_records)
    details['corporate_actions'] = action_records
    if fingerprint:
        details['derived_sha256'] = digest(bars)
    return bars, details


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
