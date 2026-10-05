"""Import official NSE listing dates by exact ISIN. No candle-derived dates."""
import argparse
import csv
import hashlib
import io
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE = 'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv'


def parse_master(raw):
    rows = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    result = {}
    for row in rows:
        row = {k.strip(): v.strip() for k, v in row.items()}
        if row.get('SERIES') not in ('EQ', 'BE', 'BZ'):
            continue
        isin = row['ISIN NUMBER']
        day = datetime.strptime(row['DATE OF LISTING'], '%d-%b-%Y').date().isoformat()
        if isin in result:
            raise ValueError('Duplicate ISIN in NSE listing master; no metadata replaced.')
        result[isin] = {'symbol': row['SYMBOL'], 'listing_date': day, 'verified': True,
                        'source': SOURCE, 'source_sha256': hashlib.sha256(raw).hexdigest()}
    if not result:
        raise ValueError('NSE master has no EQ records.')
    return result


def refresh(data_dir, raw):
    master = parse_master(raw)
    universe = json.loads((data_dir / 'universes/nifty500.json').read_text(encoding='utf-8'))
    path = data_dir / 'metadata/listings.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    selected, missing = {}, []
    for item in universe['instruments']:
        record = master.get(item['isin'])
        if not record or record['symbol'] != item['symbol']:
            missing.append(item['symbol']); continue
        existing = old.get(item['isin'])
        if existing and existing['listing_date'] != record['listing_date']:
            raise ValueError(f"Listing date conflicts for {item['symbol']}; existing metadata preserved.")
        selected[item['isin']] = record
    if not selected:
        raise ValueError('No exact universe/ISIN/symbol matches; metadata unchanged.')
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.tmp')
    with pending.open('w', encoding='utf-8') as stream:
        json.dump({**old, **selected}, stream, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    pending.replace(path)
    return {'matched':len(selected), 'total':len(universe['instruments']), 'missing_symbols':missing,
            'source':SOURCE, 'source_sha256':hashlib.sha256(raw).hexdigest(),
            'fetched_at':datetime.now(timezone.utc).isoformat()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--csv',type=Path,help='Use a previously downloaded official master')
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Use a new report filename.')
    if args.csv:
        raw = args.csv.read_bytes()
    else:
        with urllib.request.urlopen(urllib.request.Request(SOURCE,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as response:
            raw = response.read()
    report = refresh(args.data_dir,raw)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(f"Installed sourced listing dates: {report['matched']}/{report['total']}; missing: {report['missing_symbols']}.")
