"""Upstox company snapshots and explicit, advisory purchase gates."""
import hashlib
import json
import math
import time
from datetime import datetime
import statistics
from urllib.parse import quote
import httpx
from core.research import store, investor_intelligence as intel, market_history, corporate_actions, data_quality

ENDPOINTS = {
    'profile': ('profile', {}), 'ratios': ('key-ratios', {}),
    'annual_income': ('income-statement', dict(type='consolidated', time_period='yearly', fs='true')),
    'quarterly_income': ('income-statement', dict(type='consolidated', time_period='quarterly', fs='true')),
    'balance_sheet': ('balance-sheet', dict(type='consolidated', fs='true')),
    'cash_flow': ('cash-flow', dict(type='consolidated', fs='true')),
    'shareholding': ('share-holdings', {}), 'corporate_actions': ('corporate-actions', {}),
    'competitors': ('competitors', {}),
}


def request(client, url, params):
    with client.stream('GET', url, params=params) as response:
        if response.status_code != 200:
            raise ValueError('Provider returned HTTP ' + str(response.status_code))
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 5_000_000:
                raise ValueError('Oversized provider response')
    payload = json.loads(body)
    if not isinstance(payload, dict) or payload.get('status') != 'success' or not isinstance(payload.get('data'), (dict, list)):
        raise ValueError('Invalid provider response')
    sha = hashlib.sha256(body).hexdigest()
    identity=hashlib.sha256(json.dumps(dict(url=url,params=params,response=payload),sort_keys=True).encode()).hexdigest()
    store.write('investor/feed_responses/details-' + identity, dict(as_of=store.now(), url=url, params=params, response=payload))
    return payload['data'], sha


def number(value):
    try:
        result = float(str(value).replace(',', '').replace('%', ''))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def history(data, field, category):
    rows = data.get(field, []) if isinstance(data, dict) else []
    result=next((r.get('history', []) for r in rows if r.get('category') == category), [])
    return sorted([r for r in result if period_date(r.get('period'))],key=lambda r:period_date(r['period']),reverse=True)


def period_date(value):
    try:return datetime.strptime(value or '', '%b %Y').date()
    except (ValueError,TypeError):return None


def statement_usable(sections, *, require_cash=True):
    today=intel.company.utcnow().date()
    for name,limit in [('annual_income',550),('quarterly_income',210)]:
        section=sections.get(name,{})
        if section.get('status')!='available':return False
        for category in ('revenue','net_profit'):
            rows=history(section.get('data',{}),'income_statement',category)
            if not rows or number(rows[0].get('value')) is None or not 0<=(today-period_date(rows[0]['period'])).days<=limit:return False
    if require_cash:
        cash=history(sections.get('cash_flow',{}).get('data',{}),'cash_flow','operating')
        if sections.get('cash_flow',{}).get('status')!='available' or not cash or number(cash[0].get('value')) is None or not 0<=(today-period_date(cash[0]['period'])).days<=550:return False
    return True


def financial_summary(sections):
    def data(key, default):
        return sections.get(key, {}).get('data', default)
    annual = data('annual_income', {})
    quarter = data('quarterly_income', {})
    metrics = {}
    for category in ('revenue', 'operating_profit', 'net_profit'):
        rows = history(annual, 'income_statement', category)
        quarterly = history(quarter, 'income_statement', category)
        current = rows[0] if rows else {}
        period=period_date(current.get('period'))
        prev = next((r for r in rows[1:] if period and period_date(r['period']).year==period.year-1 and period_date(r['period']).month==period.month),{})
        a, b = number(current.get('value')), number(prev.get('value'))
        metrics[category] = dict(value=a, period=current.get('period'), annual_yoy_pct=(a/b-1)*100 if a is not None and b is not None and b>0 else None,
                                 quarterly=quarterly[0] if quarterly else None)
    operating = history(data('cash_flow', {}), 'cash_flow', 'operating')
    metrics['operating_cash_flow'] = operating[0] if operating else None
    ratios = {r['name']: dict(company=number(r.get('company_value')), sector=number(r.get('sector_value'))) for r in data('ratios', []) if isinstance(r, dict) and 'name' in r}
    shares = {r['category']: r.get('history', []) for r in data('shareholding', []) if isinstance(r, dict) and 'category' in r}
    profile = data('profile', {})
    basis=sections.get('annual_income',{}).get('statement_basis') or annual.get('type','consolidated')
    return dict(metrics=metrics, ratios=ratios, shareholding=shares, sector=profile.get('sector'),statement_basis=basis,
                business=profile.get('company_profile'), units=annual.get('units_in'),
                notice='Upstox current snapshot. Reporting period is separate from retrieval date; publication-time history is unavailable. Total liabilities are not debt.')


def technical(item):
    record = store.read('bars/' + item['isin'], {})
    if not record.get('bars'):
        return dict(status='unavailable', reason='Missing daily candles')
    bars, detail = market_history.prepare(item, record, reference=market_history.evidence(snapshot=True), fingerprint=False)
    today = intel.company.utcnow().astimezone(intel.company.IST).date()
    clock=intel.company.utcnow().astimezone(intel.company.IST)
    bars = [b for b in bars if b['date'] < today.isoformat() or (b['date']==today.isoformat() and clock.hour>=16)]
    if detail.get('quarantine') or len(bars) < 100:
        return dict(status='unavailable', reason='Quarantined or insufficient history')
    bars = corporate_actions.adjusted_bars(bars, bars[-1]['date'])
    if data_quality.audit({item['symbol']: bars[-101:]})['findings']:
        return dict(status='unavailable', reason='Unresolved price discontinuity')
    if (today-datetime.fromisoformat(bars[-1]['date']).date()).days > 7:
        return dict(status='unavailable', reason='Daily history is stale')
    prices = [b['close'] for b in bars]
    ma = {str(n): sum(prices[-n:])/n for n in (20, 50, 100)}
    changes = [prices[i]-prices[i-1] for i in range(len(prices)-14, len(prices))]
    gains, losses = sum(max(c, 0) for c in changes)/14, sum(max(-c, 0) for c in changes)/14
    rsi = 100-100/(1+gains/losses) if losses else (100 if gains else 50)
    ranges = [max(bars[i]['high']-bars[i]['low'], abs(bars[i]['high']-prices[i-1]), abs(bars[i]['low']-prices[i-1])) for i in range(len(bars)-14, len(bars))]
    trend = 'bullish' if prices[-1] >= ma['20'] >= ma['50'] >= ma['100'] else 'bearish' if prices[-1] < ma['50'] < ma['100'] else 'neutral'
    volume = sum(b['volume'] for b in bars[-21:-1])/20
    returns=[math.log(prices[i]/prices[i-1]) for i in range(len(prices)-20,len(prices))]
    peak=prices[-61];drawdown=0
    for price in prices[-60:]:
        peak=max(peak,price);drawdown=min(drawdown,(price/peak-1)*100)
    benchmark=store.read('bars/NIFTY50',{}).get('bars',[])
    dates=[b['date'] for b in bars[-61:]]
    bench={b['date']:b for b in benchmark if b.get('date') in dates}
    aligned=[bench[d] for d in dates if d in bench]
    valid_benchmark=len(aligned)==61 and not data_quality.audit({'NIFTY50':aligned})['findings']
    rs=(prices[-1]/prices[-61]-aligned[-1]['close']/aligned[0]['close'])*100 if valid_benchmark else None
    behaviour=dict(relative_strength60_pp=rs,max_drawdown60_pct=drawdown,volatility20_annual_pct=statistics.stdev(returns)*math.sqrt(252)*100,
                   turnover20_rupees=sum(b['close']*b['volume'] for b in bars[-20:])/20,
                   benchmark='Nifty 50',benchmark_sha256=market_history.digest(aligned) if valid_benchmark else None,
                   notice='Price return relative to Nifty 50; sector-relative strength and breadth are not included.')
    return dict(status='available', price_date=bars[-1]['date'], close=prices[-1], trend=trend, moving_averages=ma,price_behaviour=behaviour,
                audited_bars=bars[-101:],benchmark_bars=aligned if valid_benchmark else [],
                observation_bars=[{k:b[k] for k in ('date','open','close')} for b in bars[-61:]],
                rsi14=rsi, rsi_method='14-session simple average gains/losses', atr14=sum(ranges)/14,
                return20_pct=(prices[-1]/prices[-21]-1)*100, volume_ratio=bars[-1]['volume']/volume if volume else None,
                source='Derived from adjusted, audited Upstox daily candles', evidence_sha256=market_history.digest(bars[-101:]))


def refresh(items, *, force=False, transport=None, log=lambda message: None):
    items = list({i['isin']: i for i in items}.values())
    try:
        token = store.token()
    except ValueError:
        token = None
    rows = []
    with httpx.Client(timeout=20, transport=transport, follow_redirects=False,
                      headers={'Authorization': 'Bearer ' + (token or ''), 'Accept': 'application/json'}) as client:
        quotes = {}
        for offset in range(0, len(items), 30):
            batch = items[offset:offset+30]
            try:
                if not token: raise ValueError('Missing Upstox token')
                payload, sha = request(client, 'https://api.upstox.com/v2/market-quote/quotes', dict(instrument_key=','.join(i.get('key') or 'NSE_EQ|' + i['isin'] for i in batch)))
                if not isinstance(payload,dict): raise ValueError('Invalid quote data')
                quotes.update({q['instrument_token']: dict(q, response_sha256=sha, retrieved_at=store.now()) for q in payload.values() if isinstance(q, dict) and 'instrument_token' in q})
            except (httpx.HTTPError, ValueError):
                pass
        for item in items:
            key = 'investor/stock_details/' + item['isin']
            previous = store.read(key, {})
            sections = {}
            log('Checking company data for ' + item['symbol'] + '.')
            for name, (endpoint, params) in ENDPOINTS.items():
                old = previous.get('statement_alternatives',{}).get('consolidated',{}).get(name,previous.get('sections', {}).get(name, {}))
                if not force and old.get('status') in ('available', 'empty') and old.get('statement_basis','consolidated')!='standalone' and 0 <= intel.cache_age(old) < (3600 if name=='quarterly_income' else 21600):
                    sections[name] = old
                    continue
                # Live competitors currently requires instrument key despite the ISIN documentation.
                identity = (item.get('key') or 'NSE_EQ|' + item['isin']) if name == 'competitors' else item['isin']
                url = 'https://api.upstox.com/v2/fundamentals/' + quote(identity, safe='') + '/' + endpoint
                try:
                    if not token: raise ValueError('Missing Upstox token')
                    payload, sha = request(client, url, params)
                    expected_type=list if name in ('ratios','shareholding','corporate_actions','competitors') else dict
                    if not isinstance(payload,expected_type): raise ValueError('Invalid company data shape')
                    sections[name] = dict(status='available' if payload else 'empty', data=payload, response_sha256=sha, as_of=store.now(), url=url,params=params,statement_basis=params.get('type'))
                except (httpx.HTTPError, ValueError):
                    sections[name] = dict(status='unavailable', reason='Upstox endpoint unavailable; prior data is retained as background.',
                                          data=old.get('data'), as_of=store.now(), last_success=old.get('last_success', old.get('as_of')), url=url)
                if transport is None: time.sleep(.15)
            financial_names=('annual_income','quarterly_income','balance_sheet','cash_flow')
            consolidated={n:sections[n] for n in financial_names};standalone={};basis='consolidated'
            sector=(sections.get('profile',{}).get('data') or {}).get('sector','') or ''
            require_cash=not any(s in sector.lower() for s in ('bank','finance','financial'))
            if not statement_usable(sections,require_cash=require_cash):
                log('Checking consistent standalone financials for '+item['symbol']+'.')
                for name in financial_names:
                    endpoint,params=ENDPOINTS[name];params=dict(params,type='standalone')
                    old=previous.get('statement_alternatives',{}).get('standalone',{}).get(name,{})
                    if not force and old.get('status') in ('available','empty') and 0<=intel.cache_age(old)<(3600 if name=='quarterly_income' else 21600):
                        standalone[name]=old;continue
                    url='https://api.upstox.com/v2/fundamentals/'+quote(item['isin'],safe='')+'/'+endpoint
                    try:
                        if not token:raise ValueError('Missing token')
                        payload,sha=request(client,url,params)
                        if not isinstance(payload,dict):raise ValueError('Invalid statement shape')
                        standalone[name]=dict(status='available' if payload else 'empty',data=payload,response_sha256=sha,as_of=store.now(),url=url,params=params,statement_basis='standalone')
                    except (httpx.HTTPError,ValueError):standalone[name]=dict(status='unavailable',as_of=store.now(),statement_basis='standalone')
                if statement_usable(standalone,require_cash=require_cash):sections.update(standalone);basis='standalone'
            # Select the entire statement family; never mix consolidated and standalone growth.
            usable = {k: v for k, v in sections.items() if v['status'] == 'available'}
            value = dict(company=item, as_of=store.now(), sections=sections, fundamentals=financial_summary(usable),
                         statement_basis=basis,statement_alternatives=dict(consolidated=consolidated,standalone=standalone),
                         technical=technical(item), quote=quotes.get(item.get('key') or 'NSE_EQ|' + item['isin']),
                         partial=any(v['status'] == 'unavailable' for v in sections.values()))
            store.write(key, value)
            snapshot_sha=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
            store.write(key+'-'+snapshot_sha,value)
            rows.append(dict(isin=item['isin'], symbol=item['symbol'], partial=value['partial']))
    return dict(stocks=rows, partial=any(r['partial'] for r in rows))


def assessment(row, evidence, details):
    reasons, blockers, failures = [], [], []
    f, t = details.get('fundamentals', {}), details.get('technical', {})
    review = evidence.get('review') or {}
    metrics, ratios = f.get('metrics', {}), f.get('ratios', {})
    def metric(name, field='value'): return metrics.get(name, {}).get(field)
    def ratio(name): return ratios.get(name, {}).get('company')
    if not details or intel.cache_age(details) >= 3600 or details.get('partial'):
        blockers.append('Company data is missing, stale or incomplete.')
    if t.get('status') != 'available': blockers.append('Validated technical history is unavailable.')
    if not review.get('full_text') or intel.cache_age(review) >= 86400 or review.get('news_input_sha256') != __import__('core.research.investor_workflow', fromlist=['news_digest']).news_digest(evidence['articles']):
        blockers.append('Current full-article interpretation is required.')
    if not evidence['articles'] or any(c['status'] != 'available' for c in review.get('article_coverage', [])):
        blockers.append('News coverage is missing or includes unreadable articles.')
    reviewed_ids={s['article_id'] for s in review.get('article_summaries', [])}
    if any(a['id'] not in reviewed_ids for a in evidence['articles']):
        blockers.append('Some matching articles have not received a full-text summary.')
    if review.get('outlook')=='insufficient_evidence':
        blockers.append('Articles do not establish a company-specific event.')
    adverse = any(e['direction'] in ('negative', 'mixed') and e['materiality'] in ('high', 'medium') for e in review.get('events', []))
    if adverse: reasons.append('Material adverse or conflicting news requires investigation.')
    if metric('net_profit') is None or metric('revenue', 'annual_yoy_pct') is None:
        blockers.append('Profitability or annual revenue growth is unknown.')
    elif metric('net_profit') <= 0 or metric('revenue', 'annual_yoy_pct') <= 0:
        reasons.append('Positive earnings and annual revenue growth are required.')
    else: reasons.append('Positive annual profit and revenue growth are present.')
    periods = [metrics.get('revenue', {}).get('quarterly', {}) or {}]
    try:
        period = datetime.strptime(periods[0]['period'], '%b %Y').date()
        if (intel.company.utcnow().date()-period).days > 210: blockers.append('Quarterly financial period is stale.')
    except (ValueError, KeyError): blockers.append('Latest quarterly financial period is unknown.')
    financial_sector = any(s in (f.get('sector') or '').lower() for s in ('bank', 'finance', 'financial'))
    cash = number((metrics.get('operating_cash_flow') or {}).get('value'))
    if not financial_sector and cash is None: blockers.append('Operating cash flow is unknown.')
    elif not financial_sector and cash <= 0: failures.append('Operating cash flow is non-positive; the cash-flow buy condition is not met.')
    quarter_profit=number((metrics.get('net_profit',{}).get('quarterly') or {}).get('value'))
    if quarter_profit is None: blockers.append('Latest quarterly net profit is unknown.')
    elif quarter_profit < 0: reasons.append('Latest quarterly net profit is negative.')
    valuation = ratios.get('P/B' if financial_sector else 'P/E', {})
    cv, sv = valuation.get('company'), valuation.get('sector')
    valuation_ok = cv is not None and sv is not None and cv > 0 and sv > 0 and cv <= sv*2
    if cv is None or sv is None or sv<=0: blockers.append('Valuation or a positive sector benchmark is unknown.')
    elif not valuation_ok: failures.append('Valuation is non-positive or exceeds twice the sector benchmark; the valuation buy condition is not met.')
    trend_ok = t.get('trend') == 'bullish'
    breakout = row.get('stage') == 'early_breakout'
    fundamentals_ok = metric('net_profit') is not None and metric('net_profit') > 0 and metric('revenue', 'annual_yoy_pct') is not None and metric('revenue', 'annual_yoy_pct') > 0
    decision = 'avoid' if adverse or (metric('net_profit') is not None and metric('net_profit') <= 0) or (quarter_profit is not None and quarter_profit<0) else 'insufficient_data' if blockers else 'buy_candidate' if fundamentals_ok and not failures and trend_ok and breakout else 'wait'
    if row.get('kind')=='holding' and decision not in ('avoid','insufficient_data'):
        decision='monitor'
    if not breakout: reasons.append('Waiting for a completed-session breakout with qualifying volume.')
    if not trend_ok: reasons.append('Strict 20/50/100-day bullish alignment is required for a buy candidate.')
    quote_data = details.get('quote') or {}
    try:
        quote_age = (intel.company.utcnow().timestamp()*1000 - float(quote_data['last_trade_time']))/1000
    except (KeyError, TypeError, ValueError): quote_age = None
    from core.research import investor_scores
    return dict(as_of=store.now(), decision=decision, reasons=reasons+failures, blockers=blockers, advisory_only=True,
                scoring=investor_scores.evaluate(row,evidence,details),
                entry_trigger=row.get('pivot'), invalidation=row.get('invalidation_reference'), latest_price=quote_data.get('last_price'),
                quote_age_seconds=quote_age, technical_date=t.get('price_date'), details_as_of=details.get('as_of'), news_review_id=review.get('id'),
                details_sha256=hashlib.sha256(json.dumps(details,sort_keys=True).encode()).hexdigest() if details else None,
                notice='Experimental purchase assessment, not an order. Buy candidates still require a fresh executable quote, risk sizing and entry confirmation. No return target is predicted.')


def market_open(clock, *, transport=None):
    if clock.weekday() >= 5 or not (9, 15) <= (clock.hour, clock.minute) < (15, 30): return False
    cached = store.read('investor/discovery/market-status', {})
    if 0 <= intel.cache_age(cached) < 300: return cached.get('open', False)
    try:
        with httpx.Client(timeout=10, transport=transport, headers={'Authorization': 'Bearer ' + store.token()}) as client:
            data, sha = request(client, 'https://api.upstox.com/v2/market/status/NSE', {})
        opened = data.get('exchange') == 'NSE' and data.get('status') == 'NORMAL_OPEN'
        store.write('investor/discovery/market-status', dict(as_of=store.now(), open=opened, data=data, response_sha256=sha))
        return opened
    except (httpx.HTTPError, ValueError):
        store.write('investor/discovery/market-status', dict(as_of=store.now(), open=False, status='unavailable'))
        return False


def holding_changes(previous, current):
    """Alert on measured deterioration, without treating a ratio move as an order."""
    if not previous or previous.get('partial') or current.get('partial'): return []
    old, new = previous.get('fundamentals', {}), current.get('fundamentals', {})
    changes=[]
    for label in ('net_profit','operating_profit'):
        a=(old.get('metrics', {}).get(label, {}).get('quarterly') or {})
        b=(new.get('metrics', {}).get(label, {}).get('quarterly') or {})
        av,bv=number(a.get('value')),number(b.get('value'))
        if av is not None and bv is not None and av>=0>bv:
            changes.append(label.replace('_',' ')+' turned negative: '+str(av)+' ('+str(a.get('period'))+') to '+str(bv)+' ('+str(b.get('period'))+').')
    a=old.get('shareholding', {}).get('promoters', [])
    b=new.get('shareholding', {}).get('promoters', [])
    if a and b and number(a[0].get('value')) is not None and number(b[0].get('value')) is not None and number(a[0]['value'])-number(b[0]['value'])>=2:
        changes.append('Promoter ownership fell by at least 2 percentage points.')
    if previous.get('technical', {}).get('trend') in ('bullish','neutral') and current.get('technical', {}).get('trend')=='bearish':
        changes.append('Completed-session technical alignment changed to bearish.')
    return changes
