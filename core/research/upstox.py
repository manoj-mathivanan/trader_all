import csv
import gzip
import io
import json
import math
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote
import httpx
from core.research import store

INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
UNIVERSES = {"nifty50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
             "nifty500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
             "niftytotalmarket": "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"}
MIN_CONSTITUENTS = {"nifty50": 45, "nifty500": 450, "niftytotalmarket": 700}


def get(client, url, *, headers=None):
    for attempt in range(3):
        try:
            response = client.get(url, headers=headers)
        except httpx.RequestError:
            if attempt == 2:
                raise ValueError("Data provider could not be reached. Check connectivity and retry.") from None
            time.sleep(attempt + 1)
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(attempt + 1)
            continue
        if response.status_code in (401, 403):
            raise ValueError("Provider rejected access (401/403). Check your Upstox token or provider network access.")
        if response.status_code != 200:
            raise ValueError(f"Provider returned HTTP {response.status_code}. Retry later or check instrument availability.")
        return response
    raise ValueError("Provider remained busy after three attempts. Retry later.")


def match_constituents(rows, master):
    """Match official cash constituents by ISIN, retaining series and dummy exclusions."""
    by_isin = {}
    for item in master:
        if item.get('segment') == 'NSE_EQ' and item.get('isin'):
            by_isin.setdefault(item['isin'], []).append(item)
    instruments, missing, excluded = [], [], []
    for row in rows:
        symbol, isin = row['Symbol'].strip(), row['ISIN Code'].strip()
        if symbol.startswith('DUMMY') and isin.startswith('DU') and row['Company Name'].lower().startswith('dummy'):
            excluded.append({'symbol': symbol, 'isin': isin,
                             'reason': 'Official index placeholder, no tradeable provider instrument.'})
            continue
        candidates = by_isin.get(isin, [])
        preferred = [x for x in candidates if x.get('instrument_type') == 'EQ'] or candidates
        keys = {x['instrument_key'] for x in preferred}
        if len(keys) != 1:
            missing.append(symbol)
            continue
        item = preferred[0]
        instruments.append({'symbol': symbol, 'name': row['Company Name'],
            'sector': row.get('Industry', ''), 'key': item['instrument_key'], 'isin': isin,
            'series': item.get('instrument_type', '')})
    if missing:
        raise ValueError('Unmatched or ambiguous constituents: ' + ', '.join(missing) + '. No partial universe was saved.')
    if len({x['isin'] for x in instruments}) != len(instruments):
        raise ValueError('Duplicate constituent ISINs. No universe was replaced.')
    return instruments, excluded


def refresh_universe(settings, log):
    # The public NSE download stalls with the default httpx user agent.
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,application/json,*/*"}) as client:
        log(f"Downloading official {settings.universe} current constituent list.")
        response = get(client, UNIVERSES[settings.universe])
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        if not rows or "ISIN Code" not in rows[0] or "Symbol" not in rows[0]:
            raise ValueError("NSE constituent file was not valid CSV. No universe was replaced.")
        log("Downloading Upstox NSE instrument master.")
        raw = get(client, INSTRUMENTS).content
        master = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    instruments, excluded = match_constituents(rows, master)
    if len(instruments) < MIN_CONSTITUENTS[settings.universe]:
        raise ValueError("Constituent count unexpectedly low. No universe was replaced.")
    record = {"name": settings.universe, "fetched_at": store.now(), "membership": "current_snapshot",
              "source": UNIVERSES[settings.universe], "instruments": instruments,
              "source_row_count": len(rows), "provider_exclusions": excluded}
    store.write("universes/" + settings.universe, record)
    log(f"Saved {len(instruments)} instruments. Historical membership is not yet verified.")
    for item in excluded:
        log(f"Excluded {item['symbol']}: {item['reason']}")
    return record


def ingest_expansion(settings, log):
    """Pull Total Market members without cached candles; paper stays frozen."""
    if settings.universe != "niftytotalmarket":
        raise ValueError("Universe expansion requires Nifty Total Market.")
    catalog = store.read('bar_catalog', {})
    cached_isins = {isin for isin, summary in catalog.items() if summary.get('count', 0) > 0}
    target = refresh_universe(settings, log)
    additional = [item for item in target["instruments"] if item["isin"] not in cached_isins]
    log(f"Pulling {len(additional)} uncached Nifty Total Market constituents; existing candles and paper portfolio are untouched.")
    result = ingest(settings, log, universe={**target, "instruments": additional})
    return {**result, "universe": settings.universe, "total_members": len(target["instruments"])}


def validate_candles(candles, start, end):
    result, dates = [], set()
    for row in candles:
        if len(row) < 6:
            raise ValueError("Provider returned a malformed candle.")
        day = date.fromisoformat(row[0][:10])
        if not start <= day <= end:
            raise ValueError("Provider returned a candle outside the requested range.")
        if day in dates:
            raise ValueError("Duplicate daily candle detected.")
        values = [float(x) for x in row[1:6]]
        o, h, l, c, v = values
        if not all(math.isfinite(x) for x in values) or min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c) or l > h:
            raise ValueError("Invalid OHLCV candle detected. Dataset was not replaced.")
        dates.add(day)
        result.append({"date": day.isoformat(), "timestamp": int(datetime.fromisoformat(row[0]).timestamp() * 1000),
                       "open": o, "high": h, "low": l, "close": c, "volume": v})
    return sorted(result, key=lambda x: x["date"])


def fetch_range(client, instrument, access_token, start, end):
    """Fetch one inclusive boundary range from Upstox and normalize it."""
    if start > end:
        return []
    url = f"https://api.upstox.com/v3/historical-candle/{quote(instrument['key'], safe='')}/days/1/{end}/{start}"
    payload = get(client, url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"}).json()
    if payload.get("status") != "success":
        raise ValueError("Upstox did not report a successful response.")
    candles = apply_verified_overrides(payload.get('data', {}).get('candles', []), instrument['isin'])
    return validate_candles(candles, start, end)


def apply_verified_overrides(candles, isin):
    """Use independently verified bars only when the exact documented bad row matches."""
    overrides = store.read('provider_overrides/' + isin, {}).get('repairs', [])
    by_date = {x['date']: x for x in overrides}
    output = []
    for row in candles:
        repair = by_date.get(row[0][:10])
        if repair and list(map(float, row[1:6])) == repair['provider_values']:
            replacement = repair['verified_candle']
            day = date.fromisoformat(repair['date'])
            validate_candles([replacement], day, day)
            output.append(replacement)
        else:
            output.append(row)
    return output


def merge_candles(existing, additions):
    """Keep one candle per session, with new boundary data taking precedence."""
    merged = {row["date"]: row for row in existing}
    merged.update({row["date"]: row for row in additions})
    return [merged[key] for key in sorted(merged)]


def ingest(settings, log, *, universe=None, extend_history=True):
    access_token = store.token()
    universe = universe or store.read("universes/" + settings.universe)
    if not universe:
        universe = refresh_universe(settings, log)
    failures, counts = [], []
    with httpx.Client(timeout=40, follow_redirects=False) as client:
        for index, instrument in enumerate(universe["instruments"]):
            symbol = instrument["symbol"]
            log(f"{index + 1}/{len(universe['instruments'])} · checking {symbol} daily coverage.")
            try:
                record = store.read("bars/" + instrument["isin"], {})
                existing = record.get("bars", [])
                additions = []
                if existing:
                    existing = validate_candles(
                        [[f"{row['date']}T00:00:00+05:30", row['open'], row['high'], row['low'], row['close'], row['volume']]
                         for row in existing], date.fromisoformat(existing[0]['date']), date.fromisoformat(existing[-1]['date']))
                    first, last = date.fromisoformat(existing[0]["date"]), date.fromisoformat(existing[-1]["date"])
                    if extend_history and settings.start < first:
                        end = min(settings.end, first - timedelta(days=1))
                        additions.extend(fetch_range(client, instrument, access_token, settings.start, end))
                        log(f"{symbol}: fetched earlier boundary {settings.start} to {end}.")
                    if settings.end > last:
                        start = max(settings.start, last + timedelta(days=1))
                        additions.extend(fetch_range(client, instrument, access_token, start, settings.end))
                        log(f"{symbol}: fetched later boundary {start} to {settings.end}.")
                    if not additions:
                        record.update(requested_start=min(record.get('requested_start', str(settings.start)), str(settings.start)) if extend_history else record.get('requested_start', str(first)),
                                      requested_end=max(record.get('requested_end', str(settings.end)), str(settings.end)),
                                      fetched_at=store.now())
                        store.write('bars/' + instrument['isin'], record)
                        counts.append(len(existing))
                        log(f"{symbol}: coverage complete; reused {len(existing)} local bars.")
                        continue
                    candles = merge_candles(existing, additions)
                else:
                    if not extend_history:
                        raise ValueError('Paper history is missing. Restore or fetch validated history before retrying.')
                    candles = fetch_range(client, instrument, access_token, settings.start, settings.end)
                    log(f"{symbol}: fetched initial range {settings.start} to {settings.end}.")
                if not candles:
                    raise ValueError("No candles returned.")
                # Validate the merged result before replacing the atomic local file.
                candles = validate_candles(
                    [[f"{row['date']}T00:00:00+05:30", row['open'], row['high'], row['low'], row['close'], row['volume']]
                     for row in candles], date.fromisoformat(candles[0]['date']), date.fromisoformat(candles[-1]['date']))
                store.write("bars/" + instrument["isin"], {"instrument": instrument, "bars": candles,
                            "fetched_at": store.now(), "source": "upstox_v3", "requested_start": str(settings.start) if extend_history else record.get('requested_start', existing[0]['date']),
                            "requested_end": str(settings.end), "adjustments": "unverified",
                            "verified_repairs": store.read('provider_overrides/' + instrument['isin'], {}).get('repairs', [])})
                with store.LOCK:
                    catalog = store.read("bar_catalog", {})
                    catalog[instrument["isin"]] = {
                        "count": len(candles), "first": candles[0]["date"], "last": candles[-1]["date"],
                        "close": candles[-1]["close"],
                        "change": (candles[-1]["close"] / candles[-2]["close"] - 1) * 100 if len(candles) > 1 else None,
                    }
                    store.write("bar_catalog", catalog)
                counts.append(len(candles))
                log(f"{symbol}: {len(candles)} bars, {candles[0]['date']} to {candles[-1]['date']}.")
            except ValueError as exc:
                failures.append(symbol)
                log(f"{symbol}: {exc}")
                if "401/403" in str(exc):
                    raise
            time.sleep(.15)
    if failures:
        raise ValueError(f"Partial ingestion: {len(counts)} symbols saved; failed: {', '.join(failures)}. Existing valid data retained.")
    return {"symbols": len(counts), "bars": sum(counts)}
