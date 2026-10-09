"""Completed-session sector trend gates with frozen, auditable inputs."""
import csv
import gzip
import io
import json
from datetime import date, timedelta
import httpx
from core.research import store, upstox, market_history

VERSION = 'sector-trend-v1'
NOTICE = ('Sector mappings use current official constituents and industry labels, not historical '
          'classifications. Historical mapping bias and pre-launch index backfills are unverified.')
# Narrow benchmarks take precedence only for these explicitly declared overlaps.
INDICES = {
    'bank': ('Nifty Bank', 'ind_niftybanklist.csv'),
    'financial': ('Nifty Financial Services', 'ind_niftyfinancelist.csv'),
    'it': ('Nifty IT', 'ind_niftyitlist.csv'),
    'auto': ('Nifty Auto', 'ind_niftyautolist.csv'),
    'pharma': ('Nifty Pharma', 'ind_niftypharmalist.csv'),
    'healthcare': ('Nifty Healthcare Index', 'ind_niftyhealthcarelist.csv'),
    'fmcg': ('Nifty FMCG', 'ind_niftyfmcglist.csv'),
    'metal': ('Nifty Metal', 'ind_niftymetallist.csv'),
    'realty': ('Nifty Realty', 'ind_niftyrealtylist.csv'),
    'oil_gas': ('Nifty Oil & Gas', 'ind_niftyoilgaslist.csv'),
    'consumer_durables': ('Nifty Consumer Durables', 'ind_niftyconsumerdurableslist.csv'),
}
BENCHMARK = 'Nifty 500'
PROVIDER_NAMES = {
    'financial': 'Nifty Fin Service', 'healthcare': 'NIFTY HEALTHCARE',
    'oil_gas': 'NIFTY OIL AND GAS', 'consumer_durables': 'NIFTY CONSR DURBL',
}


def resolve(options):
    options = set(options)
    if 'bank' in options:
        options.discard('financial')
    if 'pharma' in options:
        options.discard('healthcare')
    return next(iter(options)) if len(options) == 1 else None


def build_mapping(instruments, constituents):
    members, industries = {}, {}
    for identifier, record in constituents.items():
        for row in record['rows']:
            members.setdefault(row['ISIN Code'].strip(), set()).add(identifier)
            industry = row.get('Industry', '').strip()
            if industry:
                industries.setdefault(industry, set()).add(identifier)
    result = {}
    for item in instruments:
        exact = members.get(item['isin'], set())
        options = exact or industries.get(item.get('sector', '').strip(), set())
        # An industry label shared by Bank and Financial Services is ambiguous
        # outside verified index membership: do not infer that every issuer is a bank.
        identifier = resolve(options) if exact else next(iter(options)) if len(options) == 1 else None
        result[item['symbol']] = dict(isin=item['isin'], industry=item.get('sector', ''),
            index=identifier, method='official_isin_membership' if exact else 'unique_industry_label',
            candidates=sorted(options), status='mapped' if identifier else 'unmapped')
    return result


def annual_ranges(start, end):
    """Isolate defective historical years without discarding other valid years."""
    while start <= end:
        boundary = min(end, date(start.year,12,31))
        yield start, boundary
        start = boundary+timedelta(days=1)


def fetch(settings, log, job_id=None, *, universe=None, start=None, end=None):
    """Explicit tracked fetch; failures retain old data but never mark it fresh."""
    universe = universe or store.read('universes/'+settings.universe, {})
    instruments = universe.get('instruments', [])
    if not instruments:
        raise ValueError('Refresh the stock universe before fetching sector data.')
    from core.research import market_data
    token = store.token()
    with httpx.Client(timeout=40, follow_redirects=True, headers={'User-Agent':'Mozilla/5.0'}) as client:
        completed = market_data.last_traded_day(client, token)
        end = min(end or completed, completed)
        catalog = store.read('bar_catalog', {})
        first = [catalog[x['isin']]['first'] for x in instruments if catalog.get(x['isin'], {}).get('first')]
        start = start or (date.fromisoformat(min(first)) if first else end-timedelta(days=730))
        if start > end:
            raise ValueError('Sector history start must not follow the completed-session cutoff.')
        raw = upstox.get(client, upstox.INSTRUMENTS).content
        master = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
        constituents, failures = {}, []
        for identifier, (name, filename) in INDICES.items():
            source = 'https://www.niftyindices.com/IndexConstituent/'+filename
            try:
                response = upstox.get(client, source)
                rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
                if not rows or any(not row.get('ISIN Code') or not row.get('Symbol') for row in rows):
                    raise ValueError('Invalid official sector constituent CSV.')
                constituents[identifier] = dict(name=name, source=source, rows=rows)
            except ValueError as exc:
                failures.append(dict(index=identifier, stage='mapping', message=str(exc)))
                log(f'{name}: {exc}')
        # Partial classification cannot establish that an industry maps uniquely.
        if len(constituents) != len(INDICES):
            raise ValueError('Incomplete official sector mapping downloads; previous mappings retained. Inspect job logs.')
        mapping = build_mapping(instruments, constituents)
        store.write('sector/mapping', dict(version=VERSION, captured_at=store.now(),
            universe=settings.universe, mappings=mapping, constituents=constituents, notice=NOTICE))
        for identifier, name in [(k, v[0]) for k,v in INDICES.items()]+[('benchmark', BENCHMARK)]:
            try:
                provider_name = PROVIDER_NAMES.get(identifier, name)
                candidates = [x for x in master if x.get('segment') == 'NSE_INDEX'
                              and provider_name in (x.get('trading_symbol'), x.get('name'))]
                if len({x['instrument_key'] for x in candidates}) != 1:
                    raise ValueError('Index instrument missing or ambiguous in Upstox master.')
                item = dict(key=candidates[0]['instrument_key'], isin='SECTOR_'+identifier,
                            symbol=identifier, name=name)
                prior = store.read('sector/prices/'+identifier, {})
                old = prior.get('bars', [])
                ranges = [(start, end)] if not old else []
                if old:
                    first, last = date.fromisoformat(old[0]['date']), date.fromisoformat(old[-1]['date'])
                    if start < first:
                        ranges.append((start, min(end, first-timedelta(days=1))))
                    # Refresh the last observed session as well as the new boundary.
                    if end >= last:
                        ranges.append((max(start, last), end))
                additions = []
                rejected_ranges = []
                for range_start, range_end in ranges:
                    for chunk_start, chunk_end in annual_ranges(range_start, range_end):
                        try:
                            chunk = upstox.fetch_range(client, item, token, chunk_start, chunk_end)
                            if not chunk:
                                raise ValueError('Provider returned no sector index history.')
                            additions.extend(chunk)
                        except ValueError as exc:
                            problem = dict(index=identifier, stage='prices', start=str(chunk_start),
                                           end=str(chunk_end), message=str(exc))
                            rejected_ranges.append(problem)
                            failures.append(problem)
                            log(f'{name} {chunk_start} to {chunk_end}: {exc}; rejected range, other years retained.')
                if not old and not additions:
                    raise ValueError('Provider returned no sector index history.')
                bars = upstox.merge_candles(prior.get('bars', []), additions)
                store.write('sector/prices/'+identifier, dict(instrument=item, bars=bars,
                    source='upstox_v3', fetched_at=store.now(), requested_start=str(start), requested_end=str(end),
                    rejected_ranges=rejected_ranges))
                log(f'{name}: {len(additions)} downloaded daily bars; {bars[-1]["date"]} latest.')
            except ValueError as exc:
                failures.append(dict(index=identifier, stage='prices', message=str(exc)))
                log(f'{name}: {exc}; existing data retained.')
    result = dict(job_id=job_id, completed_at=store.now(), start=str(start), end=str(end),
        mapped=sum(x['status']=='mapped' for x in mapping.values()), total=len(mapping),
        failures=failures, partial=bool(failures))
    store.write('sector/fetch', result)
    return result


def capture(universe):
    record = store.read('sector/mapping', {})
    mappings = record.get('mappings', {})
    # Universe expansion must not silently reuse a mapping from a different stock.
    selected = {x['symbol']: mappings[x['symbol']] for x in universe['instruments']
                if mappings.get(x['symbol'], {}).get('isin') == x['isin']}
    prices = {identifier:store.read('sector/prices/'+identifier, {})
              for identifier in sorted({v['index'] for v in selected.values() if v['index']} | {'benchmark'})}
    payload = dict(version=VERSION, captured_at=store.now(), mapping_captured_at=record.get('captured_at'),
                   mappings=selected, prices=prices, notice=NOTICE)
    payload['sha256'] = market_history.digest(payload)
    return payload


def verify(snapshot, expected=None):
    digest = market_history.digest({k:v for k,v in snapshot.items() if k != 'sha256'})
    if snapshot.get('sha256') != digest or (expected and expected != digest):
        raise ValueError('Frozen sector inputs are missing or changed.')


class Gate:
    def __init__(self, snapshot, mode):
        verify(snapshot)
        self.snapshot, self.mode, self.cache = snapshot, mode, {}
        self.rows, self.indices = {}, {}
        for identifier, record in snapshot['prices'].items():
            rows = record.get('bars', [])
            if rows:
                upstox.validate_candles([[b['date']+'T00:00:00+05:30', b['open'], b['high'], b['low'], b['close'], b['volume']]
                    for b in rows], date.fromisoformat(rows[0]['date']), date.fromisoformat(rows[-1]['date']))
            self.rows[identifier] = rows
            self.indices[identifier] = {b['date']:i for i,b in enumerate(rows)}

    def decision(self, symbol, day):
        mapping = self.snapshot['mappings'].get(symbol, {})
        identifier = mapping.get('index')
        key = (identifier, day)
        if key not in self.cache:
            value = dict(index=identifier, date=day, allowed=False, reason='unmapped_sector')
            if identifier:
                bars = self.rows.get(identifier, [])
                i = self.indices.get(identifier, {}).get(day)
                value['reason'] = 'missing_or_stale_sector_session'
                if i is not None:
                    value['reason'] = 'insufficient_sector_warmup'
                    if i >= 69:
                        sma = sum(b['close'] for b in bars[i-49:i+1])/50
                        prior = sum(b['close'] for b in bars[i-69:i-19])/50
                        value.update(close=bars[i]['close'], sma50=sma, previous_sma50=prior,
                                     sector_return_pct=(bars[i]['close']/bars[i-63]['close']-1)*100)
                        value.update(allowed=bars[i]['close'] > sma and sma > prior,
                                     reason='allowed' if bars[i]['close'] > sma and sma > prior else 'sector_trend_weak')
                        if self.mode == 'trend_rs':
                            benchmark = self.rows.get('benchmark', [])
                            j = self.indices.get('benchmark', {}).get(day)
                            if j is None or j < 63:
                                value.update(allowed=False, reason='missing_benchmark_history')
                            elif [b['date'] for b in benchmark[j-63:j+1]] != [b['date'] for b in bars[i-63:i+1]]:
                                value.update(allowed=False, reason='mismatched_index_sessions')
                            else:
                                ret = (benchmark[j]['close']/benchmark[j-63]['close']-1)*100
                                value.update(benchmark_return_pct=ret, relative_strength_pp=value['sector_return_pct']-ret)
                                if value['allowed'] and value['relative_strength_pp'] <= 0:
                                    value.update(allowed=False, reason='sector_underperforming')
            self.cache[key] = value
        return dict(self.cache[key], symbol=symbol, mapping_method=mapping.get('method'))


def audit(universe):
    snapshot = capture(universe)
    gate = Gate(snapshot, 'trend_rs')
    benchmark = gate.rows.get('benchmark', [])
    day = benchmark[-1]['date'] if benchmark else None
    return dict(notice=NOTICE, mapping_captured_at=snapshot['mapping_captured_at'], as_of=day,
        fetch=store.read('sector/fetch'), mappings=list(dict(symbol=s, **m) for s,m in snapshot['mappings'].items()),
        missing_symbols=[x['symbol'] for x in universe.get('instruments', []) if x['symbol'] not in snapshot['mappings']],
        decisions=[gate.decision(x['symbol'], day) for x in universe.get('instruments', [])] if day else [],
        indices=[dict(id=k, bars=len(rows), first=rows[0]['date'] if rows else None,
                      last=rows[-1]['date'] if rows else None) for k,rows in gate.rows.items()])
