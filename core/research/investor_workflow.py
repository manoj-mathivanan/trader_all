"""Candidate, holding and catalyst queues with optional profitable paper exits."""
import hashlib
import json
import threading
import uuid
from datetime import date,datetime
from typing import Literal
from pydantic import Field
from core.research import company_review as company, investor_intelligence as intel, investor_breakouts as breakouts, store, jobs


class TrackingInput(company.Input):
    isin: str = Field(pattern=r'^IN[A-Z0-9]{10}$')
    kind: Literal['candidate','holding'] = 'candidate'
    thesis: str = Field('',max_length=2000)
    entry_date: date | None = None
    quantity: float | None = Field(None,gt=0)
    stop_price: float | None = Field(None,gt=0)
    target_price: float | None = Field(None,gt=0)


class MonitorSettings(company.Input):
    enabled: bool = False
    interval_minutes: int = Field(60,ge=30,le=1440)
    max_reviews: int = Field(1000,ge=1,le=1000)
    discover: bool = True
    profit_exit_enabled: bool = False


def tracking(settings, value):
    item=intel.selected_company(settings,value.isin)
    if value.entry_date and value.entry_date>company.utcnow().astimezone(company.IST).date():
        raise ValueError('Holding entry date cannot be in the future.')
    with store.LOCK:
        rows=store.read('investor/watchlist',[])
        rows=[r for r in rows if not (r['isin']==value.isin and r['kind']==value.kind)]
        rows.append(dict(value.model_dump(mode='json'),company=item,updated_at=store.now()))
        store.write('investor/watchlist',rows)
    return rows


def untrack(isin,kind):
    if kind not in ('candidate','holding'):
        raise ValueError('Unknown tracking type.')
    with store.LOCK:
        rows=store.read('investor/watchlist',[])
        rows=[r for r in rows if not (r['isin']==isin and r['kind']==kind)]
        store.write('investor/watchlist',rows)
    return rows


def paper_holdings(settings):
    known={i['symbol']:i for i in company.instruments(settings)}
    rows=[]
    names=store.keys('portfolios/')+store.keys('portfolio_scenarios/',recursive=True)
    if store.exists('paper_portfolio'):names.append('paper_portfolio')
    for name in names:
        portfolio=store.read(name)
        for symbol,position in portfolio.get('ledger',{}).get('positions',{}).items():
            item=known.get(symbol)
            if item:
                rows.append(dict(isin=item['isin'],company=item,kind='holding',thesis='',
                                 entry_date=position.get('entry_date',position.get('date')),quantity=position.get('quantity'),
                                 portfolio=portfolio.get('id',name.rsplit('/',1)[-1]),source='local_paper'))
    remote=store.read('investor/portfolio_snapshot',{})
    if 0<=intel.cache_age(remote,field='checked_at' if remote.get('checked_at') else 'as_of')<86400:
        for row in remote.get('holdings',[]):
            item=next((i for i in known.values() if i['isin']==row['isin']),None)
            if item:rows.append(dict(row,company=item,kind='holding',thesis='',source='production_paper'))
    return rows


def news_digest(articles):
    return hashlib.sha256(json.dumps([{k:a[k] for k in ('id','text','published_at')} for a in articles],sort_keys=True).encode()).hexdigest()


def status(review, articles, *, holding=False):
    if not articles:return 'insufficient_coverage'
    if not review or not review.get('full_text'):return 'needs_full_article_review'
    if intel.cache_age(review)>=86400 or review.get('news_input_sha256')!=news_digest(articles):return 'review_outdated'
    if all((company.utcnow()-datetime.fromisoformat(a['published_at'])).days>30 for a in articles):return 'historical_background_only'
    if holding and review.get('thesis_assessment',{}).get('status')=='challenged':return 'exit_review'
    if any(e['direction']=='negative' and e['materiality']=='high' for e in review['events']):return 'material_concern'
    if review.get('failed_batches') or any(c['status']!='available' for c in review.get('article_coverage',[])):return 'insufficient_coverage'
    if any(e['direction'] in ('negative','mixed') for e in review['events']):return 'needs_investigation'
    return 'no_material_adverse_event_found'


def score_targets(settings):
    tracked=store.read('investor/watchlist',[])
    overrides={r['isin']:r for r in tracked if r['kind']=='holding'}
    holdings=paper_holdings(settings)
    existing={r['isin'] for r in holdings}
    for isin,pos in store.read('investor/assessments/composite-paper-state',{}).get('positions',{}).items():
        if isin not in existing:holdings.append(dict(isin=isin,company=pos['company'],kind='holding',thesis=pos['thesis'],entry_date=pos['entry_date'],quantity=pos['quantity'],source='composite_paper',portfolio='composite-paper'))
    present={r['isin'] for r in holdings}
    holdings += [dict(r,source='manual',portfolio='manual') for r in overrides.values() if r['isin'] not in present]
    for row in holdings:
        if row['isin'] in overrides:
            row.update({k:overrides[row['isin']][k] for k in ('thesis','entry_date','quantity')})
            row.update({k:overrides[row['isin']].get(k) for k in ('stop_price','target_price')})
    scan=store.read('investor/scan',{})
    candidates=[dict(r,isin=r['company']['isin'],thesis='Early breakout with a tightening base',source='early_breakout') for r in scan.get('matches',[])]
    seen={r['isin'] for r in candidates}
    candidates += [dict(r,source='manual') for r in tracked if r['kind']=='candidate' and r['isin'] not in seen]
    candidate_theses={r['isin']:r['thesis'] for r in tracked if r['kind']=='candidate'}
    for row in candidates:
        if row['isin'] in candidate_theses:row['thesis']=candidate_theses[row['isin']]
        override=next((r for r in tracked if r['isin']==row['isin'] and r['kind']=='candidate'),{})
        row.update(kind='candidate',stop_price=override.get('stop_price'),target_price=override.get('target_price'))
        from core.research import investor_paper
        row.update(investor_paper.plan(row,store.read('investor/stock_details/'+row['isin'],{}).get('technical',{})))
    return holdings+candidates


def queues(settings):
    targets=score_targets(settings)
    holdings=[r for r in targets if r['kind']=='holding'];candidates=[r for r in targets if r['kind']=='candidate']
    scan=store.read('investor/scan',{})
    cache={}
    news=store.read('investor/news',{})
    def decorate(row,holding=False):
        isin=row['isin']
        if isin not in cache:cache[isin]=intel.evidence(settings,isin,item=row['company'],news=news)
        value=cache[isin]
        review=value['review']
        from core.research import investor_details
        details=store.read('investor/stock_details/'+isin,{})
        return dict(row,news_count=len(value['articles']),news_coverage=value['news_coverage'],review_status=status(review,value['articles'],holding=holding),
                    details={k:details.get(k) for k in ('as_of','fundamentals','technical','quote')},assessment=investor_details.assessment(row,value,details),
                    outlook=review.get('outlook') if review else None,last_review=review.get('as_of') if review else None,
                    thesis_assessment=review.get('thesis_assessment') if review else None)
    candidates=[decorate(r) for r in candidates]
    candidates.sort(key=lambda r:(r['assessment'].get('scoring',{}).get('decision')!='avoid',r['assessment'].get('scoring',{}).get('range',[0])[0],r['assessment'].get('scoring',{}).get('confidence',0)),reverse=True)
    holdings=[decorate(r,True) for r in holdings]
    held={r['isin'] for r in holdings}
    catalysts=[]
    for item in company.instruments(settings):
        value=cache.get(item['isin']) or intel.evidence(settings,item['isin'],item=item,news=news)
        review=value['review']
        if not value['articles']:continue
        material=[e for e in (review or {}).get('events',[]) if e['materiality'] in ('high','medium')]
        if material or any(any(w in a['text'].lower() for w in ('order','acquisition','guidance','regulator','expansion','results','debt','fraud')) for a in value['articles']):
            catalysts.append(dict(company=item,isin=item['isin'],news_count=len(value['articles']),
                                  review_status=status(review,value['articles']),outlook=(review or {}).get('outlook'),
                                  last_review=(review or {}).get('as_of'),events=material,held=item['isin'] in held,
                                  discovery_basis='interpreted_event' if material else 'headline_triage'))
    catalysts.sort(key=lambda r:(r['discovery_basis']!='interpreted_event',r['last_review'] or '',-r['news_count'],r['company']['symbol']))
    alerts=[]
    for _,value in store.records('investor/alerts/'):
        alerts.append(value)
    alerts.sort(key=lambda x:x['as_of'],reverse=True)
    return dict(candidates=candidates,holdings=holdings,catalysts=catalysts[:30],alerts=alerts[:100],scan=scan,
                monitoring=store.read('investor/settings',MonitorSettings().model_dump()),
                last_cycle=store.read('investor/monitor',{}),
                portfolio_snapshot=store.read('investor/portfolio_snapshot',{}).get('checked_at'))


def refresh_news(settings, *, force=False, isin=None, holdings_only=False, log=lambda message:None):
    from core.research import investor_upstox, investor_discovery
    tracked=store.read('investor/watchlist',[])
    targets=paper_holdings(settings)+[r for r in tracked if not holdings_only or r['kind']=='holding']
    if not holdings_only:
        targets += [dict(company=r['company']) for r in store.read('investor/scan',{}).get('matches',[])]
    items=[r['company'] for r in targets]
    if isin:
        items.append(intel.selected_company(settings,isin))
    archive=investor_discovery.restore_archive(items,force=force,log=log)
    try:
        feeds=intel.refresh_feeds(force=force,log=log)
    except ValueError:
        feeds=dict(partial=True,coverage=store.read('investor/news',{}).get('coverage',[]))
        log('Broad feeds unavailable; continuing with company-specific sources.')
    upstox=investor_upstox.refresh(items,force=force,log=log)
    discovery=investor_discovery.refresh(items,force=force,log=log)
    return dict(feeds=feeds,upstox=upstox,discovery=discovery,archive=archive,
                partial=feeds['partial'] or upstox['partial'] or discovery['partial'] or archive['partial'])


def cycle(settings, *, holdings_only=False, log=lambda message:None):
    cfg=MonitorSettings(**store.read('investor/settings',{}))
    log('Refreshing news and scanning completed daily bars.')
    scan=store.read('investor/scan',dict(price_date=None,matches=[])) if holdings_only else breakouts.scan(settings)
    from core.research import investor_exits,investor_details
    news=refresh_news(settings,holdings_only=holdings_only,log=log)
    discovery=news['discovery']
    view=queues(settings)
    target_rows=view['holdings']+([] if holdings_only else view['candidates'])
    previous_details={r['isin']:store.read('investor/stock_details/'+r['isin'],{}) for r in view['holdings']}
    details=investor_details.refresh([r['company'] for r in target_rows],log=log)
    for row in view['holdings']:
        current=store.read('investor/stock_details/'+row['isin'],{})
        changes=investor_details.holding_changes(previous_details[row['isin']],current)
        if not changes:continue
        identity=hashlib.sha256(json.dumps(dict(isin=row['isin'],changes=changes),sort_keys=True).encode()).hexdigest()
        if store.read('investor/alerts/'+identity) is None:
            store.write('investor/alerts/'+identity,dict(id=identity,as_of=store.now(),isin=row['isin'],company=row['company'],
                status='open',kind='holding_data_review',reason=' '.join(changes),citations=[],
                previous_data_as_of=previous_details[row['isin']].get('as_of'),current_data_as_of=current.get('as_of'),
                notice='Measured financial or technical deterioration. Review company data; this alert does not execute an exit.'))
    from core.research import investor_articles
    from concurrent.futures import ThreadPoolExecutor
    articles={a['id']:a for r in target_rows for a in intel.evidence(settings,r['isin'],item=r['company'])['articles']}
    log('Retrieving complete bodies for '+str(len(articles))+' unique matching articles.')
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Download each shared URL once; failed bodies remain explicit coverage gaps.
        list(pool.map(investor_articles.read,articles.values()))
    work=[]
    for kind,rows in [('holding',view['holdings']),('candidate',view['candidates']),('catalyst',view['catalysts'] if cfg.discover else [])]:
        if holdings_only and kind!='holding':continue
        rows=sorted(rows,key=lambda r:r['last_review'] or '')
        for row in rows:
            if row['isin'] not in {r['isin'] for r in work} and row['news_count']:
                context=dict(thesis=row.get('thesis','') if kind=='holding' else '',entry_date=row.get('entry_date') if kind=='holding' else None,holding=kind=='holding')
                review=store.read('investor/latest/'+row['isin'],{})
                if row['review_status'] not in ('needs_full_article_review','review_outdated') and review.get('full_text') and review.get('context')==context:
                    continue
                work.append(dict(row,queue=kind))
    completed=[]
    for row in work[:cfg.max_reviews]:
        log('Reviewing '+row['company']['symbol']+' ('+row['queue']+').')
        try:
            context=dict(thesis=row.get('thesis','') if row['queue']=='holding' else '',entry_date=row.get('entry_date') if row['queue']=='holding' else None,holding=row['queue']=='holding')
            result=__import__('core.research.investor_reviews',fromlist=['interpret']).interpret(settings,row['isin'],context=context,log=log)
            if result.get('status')=='unavailable':
                completed.append(dict(result,status='unavailable'));continue
            review=store.read('investor/latest/'+row['isin'])
            negative=[e for e in review.get('events',[]) if e['direction']=='negative' and e['materiality']=='high']
            challenged=review['thesis_assessment']['status']=='challenged'
            if row['queue']=='holding' and (challenged or negative):
                assessment=review['thesis_assessment'] if challenged else dict(
                    reason='Material adverse news: '+'; '.join(e['event'] for e in negative),
                    citations=[c for e in negative for c in e['citations']])
                identity=hashlib.sha256(json.dumps(dict(isin=row['isin'],assessment=assessment),sort_keys=True).encode()).hexdigest()
                if store.read('investor/alerts/'+identity) is None:
                    store.write('investor/alerts/'+identity,dict(id=identity,as_of=store.now(),isin=row['isin'],company=row['company'],
                        status='open',kind='exit_review' if challenged else 'material_news_review',portfolio=row.get('portfolio'),review_id=review['id'],
                        reason=assessment['reason'],citations=assessment['citations'],
                        notice='Automatic profitable swing paper exit checks are enabled; execution outcomes are recorded separately.' if cfg.profit_exit_enabled else 'Review whether to exit. No portfolio orders or accounting were changed.'))
            completed.append(dict(result,status='reviewed'))
        except ValueError as exc:
            completed.append(dict(isin=row['isin'],status='unavailable',reason=str(exc)))
    execution=investor_exits.execute(log=log) if __import__('os').environ.get('TRADER_ENV','local')=='production' else dict(exits=0)
    for row in target_rows:
        assessment=investor_details.assessment(row,intel.evidence(settings,row['isin'],item=row['company']),store.read('investor/stock_details/'+row['isin'],{}))
        snapshot=dict(company=row['company'],**assessment)
        identity=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()
        store.write('investor/assessments/'+identity,snapshot)
    result=dict(id=uuid.uuid4().hex,as_of=store.now(),price_date=scan['price_date'],candidate_count=len(scan['matches']),
                execution=execution,discovery=discovery,upstox=news['upstox'],details=details,holdings_only=holdings_only,reviews=completed,pending=max(0,len(work)-len(completed)),partial=news['partial'] or details['partial'] or any(r['status']=='unavailable' for r in completed))
    from core.research import investor_scores
    result['scores']=investor_scores.observe(settings,log=log,holdings_only=holdings_only)
    result['paper']=__import__('core.research.investor_paper',fromlist=['run']).run(settings,log=log)
    store.write('investor/monitor_runs/'+result['id'],result)
    store.write('investor/monitor',result)
    return result


def acknowledge(alert_id):
    if not __import__('re').fullmatch('[a-f0-9]{64}',alert_id):raise ValueError('Invalid alert.')
    with store.LOCK:
        alert=store.read('investor/alerts/'+alert_id)
        if not alert:raise ValueError('Alert not found.')
        alert.update(status='acknowledged',acknowledged_at=store.now())
        store.write('investor/alerts/'+alert_id,alert)
    return alert


def start():
    stop=threading.Event()
    def loop():
        if __import__('os').environ.get('TRADER_ENV','local')!='production':return
        while not stop.wait(60):
            try:
                cfg=MonitorSettings(**store.read('investor/settings',{}))
                if __import__('os').environ.get('TRADER_ENV','local')!='production':continue
                if not cfg.enabled:continue
                from core.research import investor_exits,investor_details
                clock=investor_exits.paper.local_now()
                if not investor_details.market_open(clock):continue
                if cfg.profit_exit_enabled and clock.weekday()<5 and (9,15)<=(clock.hour,clock.minute)<(15,30) and intel.cache_age(store.read('investor/execution',{}))>=300:
                    if not any(j['status'] in ('queued','running') for j in store.read('jobs',[])):
                        jobs.submit('Investor profit exits',lambda log,job_id:investor_exits.execute(log=log))
                    continue
                if intel.cache_age(store.read('investor/monitor',{}))<cfg.interval_minutes*60:continue
                if intel.cache_age(store.read('investor/monitor_scheduler',{}))<cfg.interval_minutes*60:continue
                if any(j['status'] in ('queued','running') for j in store.read('jobs',[])):continue
                from core.research.config import current_settings
                settings=current_settings()
                jobs.submit('Investor monitoring',lambda log,job_id:cycle(settings,holdings_only=True,log=log))
                store.write('investor/monitor_scheduler',dict(as_of=store.now(),status='submitted'))
            except Exception:
                store.write('investor/monitor_scheduler',dict(as_of=store.now(),status='retry_pending'))
    thread=threading.Thread(target=loop,name='investor-monitor',daemon=True)
    thread.start()
    return stop,thread
