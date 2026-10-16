"""Deterministic pilot scores, immutable recommendations and forward observations.

No orders are placed here. Unknown factors retain their weights and widen the
score interval. An opportunity score is not a probability of making a profit.
"""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from core.research import store, investor_intelligence as intel

VERSION='investor-score-v1'
WEIGHTS=dict(fundamentals=40,price_behaviour=20,technicals=20,news=20)
THRESHOLDS=dict(buy=75,confidence=80,hold=55,reduce=45,min_turnover=5_000_000,max_entry_risk_pct=8,max_extension_pct=5,min_volume_ratio=1.05)
MODEL=dict(version=VERSION,weights=WEIGHTS,thresholds=THRESHOLDS,validated=False,execution_mode='paper_observation',round_trip_cost_bps=50)
MODEL['implementation_sha256']=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')+b'\0'+(store.ROOT/'core/research/investor_details.py').read_bytes().replace(b'\r\n',b'\n')+b'\0'+(store.ROOT/'core/research/investor_financials.py').read_bytes().replace(b'\r\n',b'\n')+b'\0'+(store.ROOT/'core/research/investor_paper.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def num(value):
    try:
        value=float(str(value).replace(',','').replace('%',''))
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):return None


def curve(value,points):
    value=num(value)
    if value is None:return None
    if value<=points[0][0]:return points[0][1]
    for (a,x),(b,y) in zip(points,points[1:]):
        if value<=b:return x+(value-a)/(b-a)*(y-x)
    return points[-1][1]


def component(factors, *, fresh=True, confidence_multiplier=1):
    total=sum(f['weight'] for f in factors)
    known=sum(f['weight'] for f in factors if f['score'] is not None) if fresh else 0
    low=sum(f['weight']*f['score']/total for f in factors if f['score'] is not None) if fresh else 0
    high=low+(total-known)/total*100
    return dict(score=round(low,2) if known==total and fresh else None,range=[round(low,2),round(high,2)],
                confidence=round(known/total*100*confidence_multiplier,1),factors=factors,fresh=fresh)


def factor(name,value,points,weight=20):
    return dict(name=name,value=num(value),score=curve(value,points),weight=weight)


def evaluate(row,evidence,details):
    from core.research.investor_details import period_date
    f=details.get('fundamentals',{});t=details.get('technical',{});m=f.get('metrics',{});ratios=f.get('ratios',{})
    today=intel.company.utcnow().astimezone(intel.company.IST).date()
    def metric(name,key='value'):return num(m.get(name,{}).get(key))
    def ratio(*names):return next((num(ratios[n].get('company')) for n in names if n in ratios),None)
    def fresh_period(value,days):
        period=period_date(value)
        return period is not None and 0<=(today-period).days<=days
    annual_ok=fresh_period(m.get('revenue',{}).get('period'),550) and fresh_period(m.get('net_profit',{}).get('period'),550)
    quarter=m.get('net_profit',{}).get('quarterly') or {}
    quarterly_ok=fresh_period(quarter.get('period'),210)
    financial=any(s in (f.get('sector') or '').lower() for s in ('bank','finance','financial'))
    revenue,profit=metric('revenue'),metric('net_profit')
    margin=profit/revenue*100 if profit is not None and revenue is not None and revenue>0 and m.get('revenue',{}).get('period')==m.get('net_profit',{}).get('period') else None
    valuation=ratios.get('P/B' if financial else 'P/E',{})
    cv,sv=num(valuation.get('company')),num(valuation.get('sector'))
    valuation_method='P/B' if financial else 'P/E'
    if not financial and (cv is None or cv<=0 or sv is None or sv<=0):
        fallback=ratios.get('EV/EBITDA',{});a,b=num(fallback.get('company')),num(fallback.get('sector'))
        if a is not None and a>0 and b is not None and b>0:cv,sv=a,b;valuation_method='EV/EBITDA (P/E benchmark unavailable)'
    relative_value=cv/sv if cv is not None and cv>0 and sv is not None and sv>0 else None
    factors=[factor('Revenue growth (%)',metric('revenue','annual_yoy_pct'),[(-10,0),(0,40),(10,70),(25,100)]),
             factor('Net profit margin (%)',margin,[(-5,0),(0,40),(10,70),(20,100)]),
             factor('Valuation / sector benchmark',relative_value,[(0,100),(1,75),(2,25),(3,0)])]
    ocf=m.get('operating_cash_flow') or {}
    conversion=num(ocf.get('value'))/profit if num(ocf.get('value')) is not None and profit is not None and profit>0 and ocf.get('period')==m.get('net_profit',{}).get('period') and fresh_period(ocf.get('period'),550) else None
    if financial:
        factors.append(factor('Return on equity (%)',ratio('ROE','Return on Equity'),[(0,0),(10,40),(15,70),(25,100)],40))
    else:
        factors.extend([factor('Operating cash flow / profit',conversion,[(-.1,0),(0,20),(.5,50),(1,80),(1.5,100)]),
                        factor('Debt / equity',ratio('Debt/Equity','Debt to Equity','Debt/Equity Ratio','D/E'),[(0,100),(.5,80),(1,50),(2,0)])])
    sections=details.get('sections',{})
    fresh=bool(details) and 0<=intel.cache_age(details)<86400 and annual_ok and quarterly_ok and all(s.get('status')=='available' and 0<=intel.cache_age(s)<86400 for k,s in sections.items() if k in ('annual_income','quarterly_income','ratios'))
    supplement=sections.get('financial_supplement',{})
    if any(v.get('source','').startswith('https://www.screener.in/') for v in ratios.values()) or str(ocf.get('source','')).startswith('https://www.screener.in/'):
        fresh=fresh and supplement.get('status')=='available' and 0<=intel.cache_age(supplement)<86400
    fundamental=component(factors,fresh=fresh)
    b=t.get('price_behaviour',{})
    price=component([factor('60-session strength versus Nifty (pp)',b.get('relative_strength60_pp'),[(-15,0),(0,50),(15,100)],40),
                     factor('60-session maximum drawdown (%)',b.get('max_drawdown60_pct'),[(-30,0),(-15,50),(0,100)]),
                     factor('Annualised 20-session volatility (%)',b.get('volatility20_annual_pct'),[(0,100),(25,80),(50,30),(80,0)]),
                     factor('20-session average turnover (rupees)',b.get('turnover20_rupees'),[(0,0),(5e6,40),(5e7,80),(1e8,100)])],fresh=t.get('status')=='available')
    trend={'bullish':100,'neutral':50,'bearish':0}.get(t.get('trend'))
    pivot=num(row.get('pivot'));close=num(t.get('close'))
    distance=(close/pivot-1)*100 if close is not None and pivot is not None and pivot>0 else None
    entry_score=curve(distance,[(-10,10),(0,60),(2,100),(5,50),(10,0)])
    # An already held position is assessed without an entry breakout requirement.
    holding=row.get('kind')=='holding'
    tech_factors=[dict(name='Moving-average alignment',value=trend,score=trend,weight=40),
                  factor('RSI14',t.get('rsi14'),[(0,0),(30,25),(50,80),(60,100),(75,40),(100,0)],20),
                  factor('Completed-session volume ratio',t.get('volume_ratio'),[(0,0),(1,50),(1.5,80),(2,100)],20)]
    tech_factors.append(factor('Close / SMA50 (%)',(close/num(t.get('moving_averages',{}).get('50'))-1)*100 if close and num(t.get('moving_averages',{}).get('50')) else None,[(-10,0),(0,70),(5,100),(20,30)],20) if holding else dict(name='Distance to breakout entry',value=distance,score=entry_score,weight=20))
    technical=component(tech_factors,fresh=t.get('status')=='available')
    articles=evidence.get('articles',[]);review=evidence.get('review') or {};coverage=evidence.get('news_coverage',{})
    by_id={a['id']:a for a in articles}
    review_rows={a['id']:a for a in review.get('articles',[])}
    def body_matches(identity):
        a=review_rows.get(identity,{})
        body=store.read('investor/full_articles/'+identity,{})
        return identity in by_id and body.get('status')=='available' and bool(a.get('full_document_sha256')) and body.get('response_sha256')==a['full_document_sha256']
    review_fresh=review.get('full_text') and 0<=intel.cache_age(review)<86400
    verified_events=[e for e in review.get('events',[]) if review_fresh and e.get('citations') and all(body_matches(c['article_id']) for c in e['citations'])]
    adverse=any(e.get('direction')=='negative' and e.get('materiality')=='high' for e in verified_events)
    negative=any(e.get('direction') in ('negative','mixed') and e.get('materiality') in ('high','medium') for e in verified_events)
    challenged=bool(review_fresh and row.get('thesis') and review.get('context',{}).get('thesis')==row.get('thesis') and review.get('context',{}).get('entry_date')==row.get('entry_date') and review.get('thesis_assessment',{}).get('status')=='challenged' and review.get('thesis_assessment',{}).get('citations') and all(body_matches(c['article_id']) for c in review['thesis_assessment']['citations']))
    summary_ids={s['article_id'] for s in review.get('article_summaries',[])}
    from core.research.investor_workflow import news_digest
    news_complete=bool(articles) and review_fresh and review.get('news_input_sha256')==news_digest(articles) and all(a['id'] in summary_ids and body_matches(a['id']) for a in articles)
    news_value=None;news_confidence=1
    if not articles and coverage.get('status')=='no_relevant_news_found':news_value=50;news_confidence=.8
    elif news_complete:
        impacts=[]
        for event in verified_events:
            dates=[datetime.fromisoformat(by_id[c['article_id']]['published_at']) for c in event['citations']]
            age=max(0,(intel.company.utcnow()-max(dates)).total_seconds()/86400)
            impact={'positive':1,'negative':-1,'mixed':-.25,'neutral':0}.get(event.get('direction'),0)*{'high':20,'medium':10,'low':3}.get(event.get('materiality'),0)
            impacts.append(impact*{'strong':1,'moderate':.75,'limited':.5}.get(event.get('evidence_quality','moderate'),.5)*(.5**(age/14)))
        # One event cannot be amplified by counting syndicated copies repeatedly.
        news_value=max(0,min(100,50+max([x for x in impacts if x>0],default=0)+min([x for x in impacts if x<0],default=0)))
    news=component([dict(name='Verified event impact',value=news_value,score=news_value,weight=100)],confidence_multiplier=news_confidence)
    components=dict(fundamentals=fundamental,price_behaviour=price,technicals=technical,news=news)
    bounds=[round(sum(WEIGHTS[k]*v['range'][i]/100 for k,v in components.items()),2) for i in (0,1)]
    complete=all(v['score'] is not None for v in components.values())
    score=bounds[0] if complete else None
    confidence=round(sum(WEIGHTS[k]*v['confidence']/100 for k,v in components.items()),1)
    blockers=[];reasons=[]
    if not fresh:blockers.append('Current annual/quarterly financial evidence is missing or stale.')
    if fundamental['score'] is None:blockers.append('Some fundamental factors are unknown; their weights were retained.')
    if price['score'] is None:blockers.append('Price behaviour or aligned Nifty history is incomplete.')
    if technical['score'] is None:blockers.append('Technical evidence or an entry setup is incomplete.')
    if news['score'] is None:blockers.append('News coverage/full-article review is incomplete; sentiment is unknown.')
    reasons.append('Valuation uses '+valuation_method+'.')
    supplement=sections.get('financial_supplement',{})
    if supplement.get('status')=='available' and 0<=intel.cache_age(supplement)<86400:reasons.append('Supplementary statement fields are reconciled to the selected accounting basis and year.')
    if negative:reasons.append('Verified material adverse or conflicting news requires investigation.')
    financial_risk=bool(not financial and (num(ocf.get('value')) is not None and num(ocf.get('value'))<=0 or ratio('Debt/Equity','Debt to Equity','Debt/Equity Ratio','D/E') is not None and ratio('Debt/Equity','Debt to Equity','Debt/Equity Ratio','D/E')>2)) or relative_value is not None and relative_value>2
    if financial_risk:reasons.append('Cash generation, leverage or valuation exceeds the pilot buy-risk limits.')
    if holding and not row.get('thesis'):blockers.append('Holding thesis has not been recorded.')
    equity=m.get('balance_equity') or {}
    insolvent=fresh and equity.get('period')==m.get('net_profit',{}).get('period') and num(equity.get('value')) is not None and num(equity['value'])<=0
    if insolvent:reasons.append('Non-positive reported equity is a hard solvency-risk veto; no favourable debt ratio inferred.')
    loss=bool(fresh and (profit is not None and profit<=0 or num(quarter.get('value')) is not None and num(quarter.get('value'))<0))
    if details.get('statement_basis')=='standalone':
        from core.research.investor_details import history as statement_history
        consolidated=details.get('statement_alternatives',{}).get('consolidated',{})
        for name,limit in [('annual_income',550),('quarterly_income',210)]:
            section=consolidated.get(name,{})
            rows=statement_history(section.get('data',{}),'income_statement','net_profit')
            if section.get('status')=='available' and 0<=intel.cache_age(section)<86400 and rows and fresh_period(rows[0].get('period'),limit) and num(rows[0].get('value')) is not None and num(rows[0]['value'])<=0:
                loss=True;reasons.append('Current consolidated losses remain a risk despite the standalone fallback.')
    liquidity=num(b.get('turnover20_rupees'))
    stop=num(row.get('stop_price')) or num(row.get('invalidation_reference'))
    target=num(row.get('target_price'))
    quote=details.get('quote') or {};trade_time=num(quote.get('last_trade_time'))
    quote_age=(intel.company.utcnow().timestamp()*1000-trade_time)/1000 if trade_time else None
    entry_price=num(quote.get('last_price')) if quote_age is not None and 0<=quote_age<=300 else close
    risk=(entry_price-stop)/entry_price*100 if entry_price and stop is not None and 0<stop<entry_price else None
    reward_risk=(target-entry_price)/(entry_price-stop) if entry_price and stop is not None and target is not None and 0<stop<entry_price<target else None
    live_distance=(entry_price/pivot-1)*100 if entry_price and pivot else None
    entry=bool(not holding and row.get('stage')=='early_breakout' and row.get('price_date')==t.get('price_date') and trend==100 and distance is not None and 0<distance<=5 and live_distance is not None and 0<live_distance<=5 and num(t.get('volume_ratio')) is not None and num(t['volume_ratio'])>=1.05)
    prior=store.read('investor/assessments/score-latest-'+row.get('isin',row.get('company',{}).get('isin','unknown'))+'-'+('holding' if holding else 'candidate'),{})
    comparable=prior.get('model',{}).get('implementation_sha256')==MODEL['implementation_sha256']
    delta=round(score-prior['score'],2) if score is not None and prior.get('score') is not None and prior.get('version')==VERSION and comparable else None
    if adverse or challenged or loss or insolvent:decision='exit_candidate' if holding else 'avoid'
    elif blockers or not complete:decision='review' if holding else 'insufficient_evidence'
    elif holding:
        if score<45 and comparable and prior.get('score') is not None and prior['score']<45 and prior.get('technical_date')!=t.get('price_date') and prior.get('confidence',0)>=80:decision='reduce_candidate'
        elif score<55 or negative or financial_risk or delta is not None and delta<=-15:decision='review'
        else:decision='hold'
    elif negative:decision='avoid'
    elif financial_risk:decision='wait'
    elif score>=75 and confidence>=80 and entry and liquidity is not None and liquidity>=5e6 and risk is not None and risk<=8 and reward_risk is not None and reward_risk>=2 and quote_age is not None and 0<=quote_age<=300:decision='buy_candidate'
    else:decision='wait'
    if not holding:
        if not entry:reasons.append('Waiting for a confirmed, unextended completed-session breakout.')
        if risk is None or risk>8 or reward_risk is None or reward_risk<2:reasons.append('Entry needs a valid stop, at most 8% price risk and a planned reward/risk of at least 2.')
        if quote_age is None or not 0<=quote_age<=300:reasons.append('A quote traded within five minutes is required before a buy call.')
        if liquidity is None or liquidity<5e6:reasons.append('Minimum average turnover is not satisfied or is unknown.')
    return dict(as_of=store.now(),version=VERSION,model=MODEL,score=score,range=bounds,confidence=confidence,components=components,decision=decision,
                blockers=blockers,reasons=reasons,score_change=delta,technical_date=t.get('price_date'),news_review_id=review.get('id'),
                statement_basis=f.get('statement_basis'),entry_plan=dict(reference_close=close,proposed_price=entry_price,stop=stop,target=target,risk_pct=risk,reward_risk=reward_risk),
                quote_age_seconds=quote_age,advisory_only=True,notice='Unvalidated pilot; scores are not win probabilities. All new score calls are observations, not orders.')


def save(row,value,details):
    kind='holding' if row.get('kind')=='holding' else 'candidate'
    record=dict(value,company=row['company'],isin=row['isin'],kind=kind,thesis=row.get('thesis',''),entry_date=row.get('entry_date'),
                details_sha256=hashlib.sha256(json.dumps(details,sort_keys=True).encode()).hexdigest(),
                price_evidence_sha256=details.get('technical',{}).get('evidence_sha256'),
                observed_since=store.now(),observation=dict(entry_rule='Next session open after recommendation date',cost_bps=50,horizons=[5,10,20],dividends_included=False))
    identity=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
    record['id']=identity
    store.write('investor/assessments/score-history-'+row['isin']+'-'+identity,record)
    store.write('investor/assessments/score-latest-'+row['isin']+'-'+kind,record)
    return record


def history(isin,limit=50):
    records=[]
    for _,r in store.records('investor/assessments/score-history-'+isin+'-'):
        if r.get('isin')==isin:records.append(r)
    return sorted(records,key=lambda r:r['as_of'],reverse=True)[:limit]


def outcomes(record,technical):
    if record.get('id'):
        frozen=store.read('investor/assessments/score-outcome-'+record['id'])
        if frozen:return frozen
    day=datetime.fromisoformat(record['as_of']).astimezone(intel.company.IST).date().isoformat()
    clock=intel.company.utcnow().astimezone(intel.company.IST)
    from datetime import timedelta
    cutoff=clock.date() if clock.hour>=16 else clock.date()-timedelta(days=1)
    all_bars=[b for b in technical.get('observation_bars',[]) if b['date']<=min(technical.get('price_date',cutoff.isoformat()),cutoff.isoformat())]
    bars=[b for b in all_bars if b['date']>day]
    if technical.get('status')!='available' or not bars:return dict(status='pending',reason='Waiting for subsequent completed sessions.')
    # If the rolling history no longer spans the start, do not silently move entry.
    if not all_bars or all_bars[0]['date']>day:return dict(status='unavailable',reason='Entry period is outside retained validated history.')
    entry=num(bars[0].get('open'))
    if entry is None or entry<=0:return dict(status='unavailable',reason='Invalid next-session opening price.')
    costs=record.get('observation',{}).get('cost_bps',50)/100
    returns={str(n):dict(date=bars[n-1]['date'],gross_return_pct=(bars[n-1]['close']/entry-1)*100,net_return_pct=(bars[n-1]['close']/entry-1)*100-costs) for n in (5,10,20) if len(bars)>=n}
    return dict(status='observing' if len(bars)<20 else 'complete',entry_date=bars[0]['date'],entry_price=entry,returns=returns,
                observation_bars=bars[:20],price_evidence_sha256=technical.get('evidence_sha256'),cost_bps=record.get('observation',{}).get('cost_bps',50),
                notice='Hypothetical price outcomes with 50 bps round-trip assumed costs; excludes dividends, taxes beyond the assumption and fill/liquidity guarantees.')


def observe(settings, *, refresh=False,holdings_only=False,log=lambda m:None):
    from core.research import investor_workflow as workflow,investor_details as details
    rows=workflow.score_targets(settings)
    if holdings_only:rows=[r for r in rows if r['kind']=='holding']
    if refresh:details.refresh([r['company'] for r in rows],log=log)
    saved=[];evaluations=[];evaluated=set();cohorts=set()
    for row in rows:
        snapshot=store.read('investor/stock_details/'+row['isin'],{})
        value=evaluate(row,intel.evidence(settings,row['isin'],item=row['company']),snapshot)
        saved.append(save(row,value,snapshot))
        for past in reversed(history(row['isin'],None)):
            if past.get('model',{}).get('implementation_sha256')!=MODEL['implementation_sha256']:continue
            if past['id'] in evaluated:continue
            evaluated.add(past['id'])
            cohort=(past['isin'],past['kind'],past['decision'],datetime.fromisoformat(past['as_of']).astimezone(intel.company.IST).date().isoformat())
            # Only the first observation of each daily call enters validation.
            # Hourly score history remains available separately.
            if cohort in cohorts:continue
            cohorts.add(cohort)
            result=outcomes(past,snapshot.get('technical',{}))
            if result['status']=='complete' and store.read('investor/assessments/score-outcome-'+past['id']) is None:
                store.write('investor/assessments/score-outcome-'+past['id'],dict(result,as_of=store.now(),recommendation_id=past['id'],model=past['model']))
            evaluations.append({**result,'recommendation_id':past['id'],'recommendation_date':past['as_of'],'company':row['company'],'decision':past['decision']})
    statistics={}
    for n in (5,10,20):
        returns=[r['returns'][str(n)]['net_return_pct'] for r in evaluations if str(n) in r.get('returns',{}) and r['decision']=='buy_candidate']
        statistics[str(n)]=dict(observations=len(returns),mean_net_return_pct=sum(returns)/len(returns) if returns else None,positive_fraction=sum(r>0 for r in returns)/len(returns) if returns else None)
    report=dict(as_of=store.now(),version=VERSION,model=MODEL,recommendations=len(saved),outcomes=sorted(evaluations,key=lambda r:r['recommendation_date'],reverse=True)[:500],outcome_count=len(evaluations),outcomes_truncated=len(evaluations)>500,buy_outcomes=statistics,
                completed=sum(r['status']=='complete' for r in evaluations),pending=sum(r['status']=='pending' for r in evaluations),
                notice='Forward observations only. Historical full-signal backtests are unavailable without publication-time fundamentals and news.')
    identity=hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
    store.write('investor/assessments/score-validation-'+identity,report)
    store.write('investor/assessments/score-validation-latest',report)
    log('Saved '+str(len(saved))+' score observations; '+str(report['completed'])+' have 20-session outcomes.')
    return dict(recommendations=len(saved),completed=report['completed'],pending=report['pending'],partial=any(r['blockers'] for r in saved))
