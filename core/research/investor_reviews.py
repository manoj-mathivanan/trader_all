"""Review every accessible body in bounded batches; retain incomplete coverage."""
import hashlib,json
from concurrent.futures import ThreadPoolExecutor
from core.research import store,investor_intelligence as intel,investor_articles as articles


def interpret(settings,isin,*,context=None,force=False,transport=None,article_transport=None,log=lambda m:None):
    value=intel.evidence(settings,isin);coverage=[];ready=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        docs=list(pool.map(lambda a:articles.read(a,force=force,transport=article_transport),value['articles']))
    for a,d in zip(value['articles'],docs):
        status=d['status'];reason=d.get('reason','')
        if status=='available' and len(d['text'])<=170000:ready.append((a,d))
        elif status=='available':status='pending_analysis';reason='Full body exceeds an individual review budget; no truncated text supplied.'
        coverage.append(dict(article_id=a['id'],title=a['title'],status=status,reason=reason))
    store.write('investor/article_coverage/'+isin,dict(as_of=store.now(),articles=coverage))
    identity=hashlib.sha256(json.dumps(dict(context=context or {},model=intel.os.environ.get('TRADER_NEWS_MODEL'),prompt=intel.FULL_PROMPT,
        articles=[(a['id'],a['sha256'],d.get('response_sha256'),d['status']) for a,d in zip(value['articles'],docs)]),sort_keys=True).encode()).hexdigest()
    cached=store.read('investor/latest/'+isin,{})
    if not force and not cached.get('failed_batches') and cached.get('batch_cache_key')==identity and 0<=intel.cache_age(cached)<86400:
        from core.research.investor_workflow import news_digest
        cached['news_input_sha256']=news_digest(value['articles'])
        store.write('investor/latest/'+isin,cached);store.write('investor/reviews/'+cached['id'],cached)
        return dict(isin=isin,review_id=cached['id'],cached=True,reviewed_articles=len(cached.get('article_summaries',[])),batches=len(cached.get('batch_review_ids',[])),failed_batches=cached.get('failed_batches',[]),partial=bool(cached.get('failed_batches')) or any(c['status']!='available' for c in coverage))
    batches=[];current=[];size=0
    for a,d in ready:
        if current and (len(current)>=10 or size+len(d['text'])>170000):batches.append(current);current=[];size=0
        current.append(a['id']);size+=len(d['text'])
    if current:batches.append(current)
    reviews=[];failed=[]
    original=value.get('review')
    for n,batch in enumerate(batches):
        log('Reviewing '+value['company']['symbol']+' batch '+str(n+1)+'/'+str(len(batches))+'; '+str(len(batch))+' full articles.')
        try:
            cache_name='investor/assessments/article-batch-cache-'+hashlib.sha256(json.dumps([identity,batch]).encode()).hexdigest()
            prior=store.read(cache_name,{})
            saved=store.read('investor/reviews/'+prior.get('review_id',''),{}) if prior else {}
            if not force and saved and 0<=intel.cache_age(saved)<86400:
                reviews.append(saved);continue
            result=intel.interpret(settings,isin,full_text=True,force=force,context=context,transport=transport,article_transport=article_transport,article_ids=batch,log=log)
            reviews.append(store.read('investor/reviews/'+result['review_id']))
            store.write(cache_name,dict(as_of=store.now(),review_id=result['review_id']))
        except ValueError as exc:failed.append(dict(batch=n+1,reason=str(exc)))
    if not reviews:
        if original:store.write('investor/latest/'+isin,original)
        return dict(isin=isin,status='unavailable',reviewed_articles=0,failed_batches=failed,partial=True)
    from uuid import uuid4
    from core.research.investor_workflow import news_digest
    events=[e for r in reviews for e in r['events']];directions={e['direction'] for e in events}-{'neutral'}
    thesis=next((r['thesis_assessment'] for r in reviews if r['thesis_assessment']['status']=='challenged'),None)
    if thesis is None:
        statuses={r['thesis_assessment']['status'] for r in reviews}
        thesis=dict(status='unknown' if failed or any(c['status']!='available' for c in coverage) or 'unknown' in statuses else 'unchanged',
                    reason='Combined full-article batches; incomplete evidence requires review.' if failed or any(c['status']!='available' for c in coverage) else 'No cited thesis challenge found across the reviewed batches.',citations=[])
    review=dict(id=uuid4().hex,version='investor-full-batches-v1',as_of=store.now(),company=value['company'],full_text=True,
        batch_cache_key=identity,batch_review_ids=[r['id'] for r in reviews],failed_batches=failed,context=context or {},
        news_input_sha256=news_digest(value['articles']),article_coverage=coverage,articles=[a for r in reviews for a in r['articles']],
        events=events,article_summaries=[a for r in reviews for a in r['article_summaries']],thesis_assessment=thesis,
        unknowns=list(dict.fromkeys(x for r in reviews for x in r['unknowns']))+['Unreadable articles are not evidence.'] if any(c['status']!='available' for c in coverage) else list(dict.fromkeys(x for r in reviews for x in r['unknowns'])),
        outlook='insufficient_evidence' if not events else 'neutral' if not directions else next(iter(directions)) if len(directions)==1 else 'mixed',
        model=intel.os.environ.get('TRADER_NEWS_MODEL'),coverage=value['coverage'],news_as_of=value['as_of'],
        notice='All accessible bodies reviewed in bounded batches. Citations validated in each batch. Aggregation uses no new inferred facts; unreadable/failed coverage remains explicit.')
    store.write('investor/reviews/'+review['id'],review);store.write('investor/latest/'+isin,review)
    store.write('investor/article_coverage/'+isin,dict(as_of=store.now(),articles=coverage))
    return dict(isin=isin,review_id=review['id'],reviewed_articles=len(review['article_summaries']),batches=len(reviews),failed_batches=failed,partial=bool(failed) or any(c['status']!='available' for c in coverage))


def run(settings,log=lambda m:None):
    from core.research import investor_workflow as w,investor_scores as scores
    rows=w.score_targets(settings);seen=set();results=[]
    for row in sorted(rows,key=lambda r:r['kind']!='holding'):
        if row['isin'] in seen:continue
        seen.add(row['isin'])
        log('Checking complete news coverage for '+row['company']['symbol']+'.')
        context=dict(thesis=row.get('thesis','') if row['kind']=='holding' else '',entry_date=row.get('entry_date'),holding=row['kind']=='holding')
        results.append(interpret(settings,row['isin'],context=context,log=log))
    observations=scores.observe(settings,log=log)
    from core.research import investor_paper
    report=dict(as_of=store.now(),companies=len(results),reviews=results,scores=observations,paper=investor_paper.run(settings,log=log),partial=any(r.get('partial') for r in results))
    store.write('investor/assessments/full-review-run-'+hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest(),report)
    return report
