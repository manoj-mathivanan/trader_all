"""Expand research from cached, ISIN-matched data without rewriting paper universes."""
from core.research import store,market_history,data_quality

def cached_expansion(reference_id,log=lambda _:None):
    original=store.read('runs/'+reference_id)
    base=store.read('run_data/'+reference_id)
    if not original or not base:raise ValueError('Frozen comparison inputs are required.')
    hashes={m['symbol']:m['sha256'] for m in original['manifest']}
    if any(market_history.digest(bs)!=hashes.get(s) for s,bs in base.items()):
        raise ValueError('Frozen comparison input hash mismatch.')
    universe=store.read('universes/niftytotalmarket',{})
    items=universe.get('instruments',[])
    if len({i['isin'] for i in items})!=len(items):raise ValueError('Duplicate universe ISINs.')
    used={i['isin'] for i in original['universe_snapshot']['instruments'] if i['symbol'] in base}
    evidence=market_history.evidence(snapshot=True)
    additions={};excluded=[];histories=[]
    for item in items:
        if item['isin'] in used:continue
        record=store.read('bars/'+item['isin'],{})
        if not record or not record.get('bars'):
            excluded.append(dict(symbol=item['symbol'],reason='No cached candles'));continue
        if record.get('requested_end','')<'2026-09-30' or record['bars'][-1]['date']<'2026-09-30':
            excluded.append(dict(symbol=item['symbol'],reason='Incomplete requested test coverage'));continue
        rows,history=market_history.prepare(item,record,reference=evidence)
        if len(rows)<254 or item['symbol'] in base:
            excluded.append(dict(symbol=item['symbol'],reason='Insufficient history or ambiguous ticker'));continue
        additions[item['symbol']]=rows
        histories.append(dict(symbol=item['symbol'],isin=item['isin'],first=rows[0]['date'],last=rows[-1]['date'],
                              sha256=market_history.digest(rows),history_evidence=history))
    combined={**base,**additions}
    quality=data_quality.audit(combined,end='2026-09-30')
    combined=data_quality.exclude_anomalies(combined,quality,log)
    if set(base)-set(combined):raise ValueError('Expansion would remove baseline stocks; resolve baseline data quality first.')
    notice=('Current Total Market membership and cached history, not full historical NSE/BSE membership. '
            'Additional stocks may have shorter price histories; market-wide RS, combined exchange turnover '
            'and historical market-cap eligibility are not established. Original stock inputs are retained byte-for-byte.')
    return base,combined,dict(reference_id=reference_id,baseline=len(base),current_members=len(items),
        expanded=len(combined),added=len(combined)-len(base),excluded=excluded,
        price_gap_exclusions=quality['excluded_symbols'],added_histories=histories,notice=notice)
