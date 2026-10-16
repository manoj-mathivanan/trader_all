"""Completed-session early-breakout watchlist, with explicit experimental rules."""
import hashlib
import json
import math
import uuid
from datetime import date
from core.research.investor_rules import Rules
from core.research import company_review as company, store, market_history, corporate_actions, data_quality


def setup(bars, rules):
    if len(bars) < max(100,rules.resistance_sessions+1):
        return None
    prices = [b['close'] for b in bars]
    if any(not math.isfinite(b[k]) or b[k] <= 0 for b in bars[-100:] for k in ('open','high','low','close')):
        return None
    if any(not math.isfinite(b['volume']) or b['volume'] < 0 for b in bars[-101:]):
        return None
    prior = bars[-rules.resistance_sessions-1:-1]
    last = bars[-1]
    pivot = max(b['high'] for b in prior)
    ma20 = sum(prices[-20:])/20
    ma50 = sum(prices[-50:])/50
    old_ma50 = sum(prices[-55:-5])/50
    ma100 = sum(prices[-100:])/100
    base_range = (max(b['high'] for b in prior[-20:])/min(b['low'] for b in prior[-20:])-1)*100
    recent_range = sum((b['high']-b['low'])/b['close'] for b in bars[-6:-1])/5
    earlier_range = sum((b['high']-b['low'])/b['close'] for b in bars[-21:-6])/15
    contraction = recent_range/earlier_range if earlier_range else math.inf
    average_volume = sum(b['volume'] for b in bars[-21:-1])/20
    dry_volume = sum(b['volume'] for b in bars[-6:-1])/5/average_volume if average_volume else math.inf
    volume_ratio = last['volume']/average_volume if average_volume else 0
    turnover = sum(b['close']*b['volume'] for b in bars[-20:])/20
    distance = (last['close']/pivot-1)*100
    trend = (last['close'] >= ma20 >= ma50 >= ma100 if rules.strict_trend else last['close'] >= ma50 >= ma100) and ma50 > old_ma50
    compression = base_range <= rules.max_base_range_pct and contraction <= rules.max_contraction_ratio
    stage = ('early_breakout' if 0 < distance <= rules.max_extension_pct and volume_ratio >= rules.min_breakout_volume_ratio
             else 'approaching_breakout' if -rules.max_distance_pct <= distance <= 0 and dry_volume <= rules.max_dry_volume_ratio else None)
    if not trend or not compression or turnover < rules.min_turnover_rupees or not stage:
        return None
    return dict(stage=stage, close=last['close'], pivot=pivot, distance_pct=distance, base_range_pct=base_range,
                contraction_ratio=contraction, dry_volume_ratio=dry_volume, volume_ratio=volume_ratio,
                average_turnover=turnover, ma20=ma20, ma50=ma50, ma100=ma100,
                price_date=last['date'], invalidation_reference=min(b['low'] for b in bars[-5:]),
                evidence_sha256=hashlib.sha256(json.dumps(bars[-101:],sort_keys=True).encode()).hexdigest())


def scan(settings, rules=None):
    rules = rules or Rules(**store.read('investor/rules',{}))
    today = company.utcnow().astimezone(company.IST).date()
    reference = market_history.evidence(snapshot=True)
    histories, excluded = [], []
    for item in company.instruments(settings):
        record = store.read('bars/'+item['isin'], {})
        if not record.get('bars'):
            excluded.append(dict(symbol=item['symbol'],reason='Missing daily history'))
            continue
        bars, detail = market_history.prepare(item,record,reference=reference,fingerprint=False)
        bars = [b for b in bars if b['date'] < today.isoformat()]
        if detail.get('quarantine') or len(bars)<100:
            excluded.append(dict(symbol=item['symbol'],reason='Quarantined or insufficient completed history'))
            continue
        histories.append((item,bars))
    as_of = max((bars[-1]['date'] for _,bars in histories),default=None)
    matches=[]
    for item,bars in histories:
        if bars[-1]['date'] != as_of or (today-date.fromisoformat(bars[-1]['date'])).days > 7:
            excluded.append(dict(symbol=item['symbol'],reason='Stale daily history'))
            continue
        bars=corporate_actions.adjusted_bars(bars,as_of)
        if data_quality.audit({item['symbol']:bars[-101:]})['findings']:
            excluded.append(dict(symbol=item['symbol'],reason='Unresolved price discontinuity'))
            continue
        result=setup(bars,rules)
        if result:
            matches.append(dict(company=item,**result))
    matches.sort(key=lambda x:(x['stage']!='early_breakout',abs(x['distance_pct']),-x['average_turnover'],x['company']['symbol']))
    result=dict(id=uuid.uuid4().hex,as_of=store.now(),price_date=as_of,rules=rules.model_dump(),
                matches=matches,excluded=excluded,scanned=len(histories),
                notice='Experimental completed-session watchlist; no validated edge. Near resistance is not a confirmed breakout. News and execution checks remain separate.')
    store.write('investor/scans/'+result['id'],result)
    store.write('investor/scan',result)
    return result
