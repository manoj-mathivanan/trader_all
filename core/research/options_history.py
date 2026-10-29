"""Read-only Upstox options discovery and validated one-minute sample archives.

Sample archives are coverage evidence, not a complete historical option chain.
No order endpoints, account mutations or production data writes are used.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import gzip
import json
import math
from pathlib import Path
import time
from urllib.parse import quote
from uuid import uuid4

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
UNDERLYING = 'NSE_INDEX|Nifty 50'
BASE = 'https://api.upstox.com'


class ProviderError(ValueError):
    pass


def request(client, token, path, params=None):
    """Classify access failures without exposing credentials or response bodies."""
    for attempt in range(3):
        try:
            response = client.get(BASE + path, params=params,
                                  headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        except httpx.RequestError:
            if attempt == 2:
                raise ProviderError('Upstox connection failed.') from None
            time.sleep(attempt + 1)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < 2:
                time.sleep(attempt + 1)
                continue
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError(f'Upstox returned non-JSON HTTP {response.status_code}.') from None
        codes = {str(e.get('errorCode')) for e in payload.get('errors', []) if isinstance(e, dict)}
        if 'UDAPI1149' in codes:
            raise ProviderError('Expired options require Upstox Plus (UDAPI1149).')
        if response.status_code == 401:
            raise ProviderError('Upstox token is invalid or expired (HTTP 401).')
        if response.status_code != 200 or payload.get('status') != 'success':
            raise ProviderError(f'Upstox rejected request: HTTP {response.status_code}; codes={sorted(codes)}.')
        if 'data' not in payload:
            raise ProviderError('Upstox response has no data field.')
        return payload
    raise ProviderError('Upstox request failed.')


def normalize_candles(raw, start, end):
    """Preserve OI, require offset timestamps and reject duplicates/invalid OHLC."""
    bars, seen = [], set()
    for row in raw:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError('Malformed one-minute candle.')
        instant = datetime.fromisoformat(row[0])
        if instant.tzinfo is None:
            raise ValueError('Candle timestamp has no timezone.')
        instant = instant.astimezone(IST)
        if not start <= instant.date() <= end or instant.second or instant.microsecond:
            raise ValueError('Candle is outside request dates or minute boundaries.')
        stamp = int(instant.timestamp() * 1000)
        if stamp in seen:
            raise ValueError('Duplicate candle timestamp.')
        seen.add(stamp)
        o, h, l, c, v = map(float, row[1:6])
        if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c) or l > h:
            raise ValueError('Invalid candle OHLCV.')
        oi = float(row[6]) if len(row) > 6 and row[6] is not None else None
        if oi is not None and (not math.isfinite(oi) or oi < 0):
            raise ValueError('Invalid open interest.')
        bars.append(dict(date=instant.date().isoformat(), time=instant.strftime('%H:%M'),
                         timestamp=stamp, open=o, high=h, low=l, close=c, volume=v, open_interest=oi))
    return sorted(bars, key=lambda b: b['timestamp'])


def validate_contracts(raw, expiry, underlying=UNDERLYING):
    if not isinstance(raw, list):
        raise ValueError('Contract response must be a list.')
    seen = set()
    for item in raw:
        key = item.get('instrument_key')
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError('Missing or duplicate expired contract key.')
        seen.add(key)
        if item.get('expiry') != expiry or item.get('underlying_key') != underlying or item.get('instrument_type') not in ('CE', 'PE'):
            raise ValueError('Contract identity mismatch.')
        lot = float(item.get('lot_size', 0))
        strike = float(item.get('strike_price', 0))
        if not math.isfinite(lot) or lot <= 0 or not lot.is_integer() or not math.isfinite(strike) or strike <= 0:
            raise ValueError('Invalid historical lot size or strike.')
    return raw


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        pending.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
        for attempt in range(6):
            try:
                pending.replace(path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.05*2**attempt)
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass


def archive(path, payload, start, end):
    bars = normalize_candles(payload['data']['candles'], start, end)
    save_json(path, dict(raw_response=payload, bars=bars))
    return dict(file=Path(path).name, sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(), bars=len(bars))


def probe(client, token, reference_day):
    result = {}
    try:
        payload = request(client, token, f'/v3/historical-candle/{quote(UNDERLYING, safe="")}/days/1/{reference_day}/{reference_day}')
        result['ordinary_history'] = dict(status='accessible', candle_count=len(payload['data']['candles']))
    except ProviderError as exc:
        result['ordinary_history'] = dict(status='unavailable', reason=str(exc))
    try:
        payload = request(client, token, '/v2/expired-instruments/expiries', {'instrument_key': UNDERLYING})
        expiries = sorted({date.fromisoformat(x).isoformat() for x in payload['data']})
        result['expired_options'] = dict(status='accessible', expiries=expiries)
    except ProviderError as exc:
        result['expired_options'] = dict(status='unavailable', reason=str(exc))
    for check in result.values():
        check['checked_at'] = datetime.now(timezone.utc).isoformat()
        check['reference_day'] = str(reference_day)
    return result


def download_underlying(client, token, *, start, end, output):
    """Download underlying inputs independently of the expired-options entitlement."""
    from core.research.upstox import validate_candles
    today = datetime.now(IST).date()
    if start > end or end >= today or (end-start).days > 366:
        raise ValueError('Underlying research must end before today and span at most one year.')
    output = Path(output)
    first = start-timedelta(days=7)
    manifest = dict(status='downloading', purpose='underlying_signal_audit', start=str(start), end=str(end),
                    underlying_key=UNDERLYING, backtest_ready=False, files=[],
                    downloaded_at=datetime.now(timezone.utc).isoformat())
    save_json(output/'underlying-manifest.json', manifest)
    combined = []
    cursor = first
    while cursor <= end:
        last = min(end, cursor+timedelta(days=27))
        payload = request(client, token,
            f'/v3/historical-candle/{quote(UNDERLYING, safe="")}/minutes/1/{last}/{cursor}')
        bars = normalize_candles(payload['data']['candles'], cursor, last)
        combined.extend(bars)
        manifest['files'].append(archive(output/f'underlying-{cursor}-{last}.json', payload, cursor, last))
        cursor = last+timedelta(days=1)
    if not any(str(start) <= b['date'] <= str(end) for b in combined):
        raise ValueError('No underlying minute candles in requested window.')
    daily = request(client, token,
        f'/v3/historical-candle/{quote(UNDERLYING, safe="")}/days/1/{end}/{first}')
    daily_bars = validate_candles(daily['data']['candles'], first, end)
    if not daily_bars:
        raise ValueError('Underlying daily history unavailable.')
    daily_path = output/'underlying-daily.json'
    save_json(daily_path, dict(raw_response=daily, bars=daily_bars))
    manifest['files'].append(dict(file=daily_path.name, sha256=hashlib.sha256(daily_path.read_bytes()).hexdigest(),
                                  bars=len(daily_bars), interval='day'))
    manifest.update(status='underlying_downloaded', minute_bars=len(combined), daily_bars=len(daily_bars))
    save_json(output/'underlying-manifest.json', manifest)
    return manifest


def download_sample(client, token, *, start, end, output, max_contracts=40):
    """Archive earliest available expiry on/after end, with a bounded strike sample.

    Range-based strike selection is only a download scope, never a trading rule.
    Completeness and premium-selection eligibility require a later chain audit.
    """
    today = datetime.now(IST).date()
    if start > end or end >= today or (end-start).days > 28:
        raise ValueError('Sample must span at most 29 calendar dates and end before today IST.')
    if max_contracts < 2 or max_contracts % 2:
        raise ValueError('Contract limit must be an even number of at least two.')
    output = Path(output)
    access = probe(client, token, end)
    save_json(output / 'access.json', access)
    if any(x['status'] != 'accessible' for x in access.values()):
        raise ProviderError('History access check failed; see access.json.')
    eligible = [x for x in access['expired_options']['expiries'] if str(end) <= x < str(today)]
    if not eligible:
        raise ValueError('No discoverable expired contract covers the sample end date.')
    expiry = eligible[0]
    contracts = validate_contracts(request(client, token, '/v2/expired-instruments/option/contract',
        {'instrument_key': UNDERLYING, 'expiry_date': expiry})['data'], expiry)
    save_json(output / 'contracts.json', contracts)
    warmup_start = start - timedelta(days=7)
    payload = request(client, token, f'/v3/historical-candle/{quote(UNDERLYING, safe="")}/minutes/1/{end}/{warmup_start}')
    underlying = normalize_candles(payload['data']['candles'], warmup_start, end)
    observed = [b for b in underlying if str(start) <= b['date'] <= str(end)]
    if not observed:
        raise ValueError('No underlying candles in sample window.')
    center = (min(b['low'] for b in observed) + max(b['high'] for b in observed)) / 2
    strikes = sorted({c['strike_price'] for c in contracts}, key=lambda x: (abs(float(x)-center), float(x)))[:max_contracts//2]
    selected = [c for c in contracts if c['strike_price'] in strikes]
    if len(selected) > max_contracts:
        raise ValueError('Unexpected multiple contracts for a sampled strike.')
    manifest = dict(status='downloading', purpose='connectivity_and_data_quality_sample',
        backtest_ready=False, underlying_key=UNDERLYING, start=str(start), end=str(end), expiry=expiry,
        discovered_expiries=access['expired_options']['expiries'],
        catalog_evidence=dict(file='contracts.json', sha256=hashlib.sha256((output/'contracts.json').read_bytes()).hexdigest()),
        downloaded_at=datetime.now(timezone.utc).isoformat(), selected_contract_count=len(selected),
        limitations=['One expiry only; incomplete strike universe.',
                     'No bid/ask history; trade candles cannot establish executable spread.',
                     'No missing-candle imputation; no liquidity or chain-completeness certification.'], files=[], failures=[])
    manifest['files'].append(archive(output/'underlying.json', payload, warmup_start, end))
    save_json(output/'manifest.json', manifest)
    for item in selected:
        digest = hashlib.sha256(item['instrument_key'].encode()).hexdigest()[:20]
        try:
            path = f'/v2/expired-instruments/historical-candle/{quote(item["instrument_key"], safe="")}/1minute/{end}/{start}'
            data = request(client, token, path)
            evidence = archive(output/f'option-{digest}.json', data, start, end)
            manifest['files'].append(dict(evidence, instrument=item))
            if not evidence['bars']:
                manifest['failures'].append(dict(key=item['instrument_key'], reason='No candles returned.'))
        except (ValueError, KeyError) as exc:
            manifest['failures'].append(dict(key=item['instrument_key'], reason=str(exc)))
            if isinstance(exc, ProviderError):
                manifest['status'] = 'failed'
                save_json(output/'manifest.json', manifest)
                raise
        save_json(output/'manifest.json', manifest)
        time.sleep(.2)
    manifest['status'] = 'sample_downloaded_with_warnings' if manifest['failures'] else 'sample_downloaded'
    save_json(output/'manifest.json', manifest)
    return manifest


def download_research(client, token, *, start, end, output, log=print, request_interval=.2):
    """Resume a complete catalog download, scoped to each expiry's trading days."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock
    from core.research.options_backtest import load_underlying, read_evidence
    output = Path(output)
    underlying_manifest, minutes, _ = load_underlying(output)
    if (str(start), str(end)) != (underlying_manifest['start'], underlying_manifest['end']):
        raise ValueError('Research dates must match the verified underlying archive.')
    discovery = request(client, token, '/v2/expired-instruments/expiries', {'instrument_key': UNDERLYING})
    expiries = sorted({date.fromisoformat(x).isoformat() for x in discovery['data']})
    sessions = sorted({b['date'] for b in minutes if str(start) <= b['date'] <= str(end)})
    groups = {}
    for day in sessions:
        eligible = [e for e in expiries if e >= day]
        if not eligible:
            raise ValueError(f'No expired-contract catalog covers {day}.')
        groups.setdefault(eligible[0], []).append(day)
    path = output/'research-manifest.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    identity = dict(start=str(start), end=str(end), underlying_key=UNDERLYING)
    if previous and any(previous.get(k) != v for k,v in identity.items()):
        raise ValueError('Existing research archive has a different date range or underlying.')
    reusable = {r['instrument']['instrument_key']:r for r in previous.get('files', [])}
    manifest = dict(**identity, status='downloading', backtest_ready=False,
        discovered_expiries=expiries, discovery_response=discovery, catalogs=[], files=[], failures=[],
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        session_reference=dict(source='NSE closing-auction session information', derivatives_close='15:40',
            url='https://www.nseindia.com/static/products-services/closing-auction-session'),
        limitations=['Missing contract-minute observations remain unknown, never forward-filled.',
                     'Catalogs can include strikes not yet listed on early dates; no listing time is assumed.',
                     'No bid/ask history or independently verified historical trading calendar.'])
    tasks = []
    for expiry, days in groups.items():
        contracts = validate_contracts(request(client, token, '/v2/expired-instruments/option/contract',
            {'instrument_key': UNDERLYING, 'expiry_date': expiry})['data'], expiry)
        catalog_path = output/f'catalog-{expiry}.json'
        save_json(catalog_path, contracts)
        manifest['catalogs'].append(dict(expiry=expiry, start=days[0], end=days[-1], contracts=len(contracts),
            file=catalog_path.name, sha256=hashlib.sha256(catalog_path.read_bytes()).hexdigest()))
        for item in contracts:
            old = reusable.get(item['instrument_key'])
            if old and old.get('start') == days[0] and old.get('end') == days[-1] and old['instrument'] == item:
                try:
                    evidence = read_evidence(output, old)
                    normalize_candles(evidence['raw_response']['data']['candles'], date.fromisoformat(days[0]), date.fromisoformat(days[-1]))
                    manifest['files'].append(old)
                    continue
                except (ValueError, KeyError, OSError):
                    pass
            tasks.append((item, days[0], days[-1]))
    manifest['expected_contracts'] = sum(r['contracts'] for r in manifest['catalogs'])
    save_json(path, manifest)
    log(f"Research download: {len(groups)} expiries, {manifest['expected_contracts']} contracts, {len(tasks)} requests remaining.")
    rate_lock = Lock()
    next_call = [0.0]
    def fetch(task):
        item, first, last = task
        with rate_lock:
            delay = max(0, next_call[0]-time.monotonic())
            if delay:
                time.sleep(delay)
            next_call[0] = time.monotonic()+request_interval
        endpoint = f'/v2/expired-instruments/historical-candle/{quote(item["instrument_key"], safe="")}/1minute/{last}/{first}'
        payload = request(client, token, endpoint)
        bars = normalize_candles(payload['data']['candles'], date.fromisoformat(first), date.fromisoformat(last))
        digest = hashlib.sha256(item['instrument_key'].encode()).hexdigest()[:20]
        archive_path = output/f'research-option-{digest}.json.gz'
        raw = gzip.compress(json.dumps(dict(raw_response=payload), allow_nan=False, separators=(',', ':')).encode(), mtime=0)
        pending = archive_path.with_suffix('.tmp')
        pending.write_bytes(raw)
        pending.replace(archive_path)
        return dict(instrument=item, start=first, end=last, file=archive_path.name,
                    sha256=hashlib.sha256(raw).hexdigest(), bars=len(bars))
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(fetch, task):task for task in tasks}
        for done, future in enumerate(as_completed(pending), 1):
            try:
                manifest['files'].append(future.result())
            except (ValueError, KeyError, OSError) as exc:
                manifest['failures'].append(dict(key=pending[future][0]['instrument_key'], reason=str(exc)))
            if done % 25 == 0 or done == len(tasks):
                save_json(path, manifest)
                log(f"Archived {len(manifest['files'])}/{manifest['expected_contracts']} contracts; failures={len(manifest['failures'])}.")
    manifest['files'].sort(key=lambda r:r['instrument']['instrument_key'])
    manifest['status'] = 'research_downloaded' if not manifest['failures'] else 'research_downloaded_with_warnings'
    save_json(path, manifest)
    return manifest
