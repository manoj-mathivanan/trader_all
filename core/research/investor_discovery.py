"""Company-specific news discovery; publisher bodies remain separate evidence."""
import base64
import json
import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit, parse_qs, urljoin
from xml.etree import ElementTree as ET
import httpx
from core.research import investor_intelligence as intel, store

ALIASES={'BHEL':'Bharat Heavy Electricals','AETHER':'Aether Industries','STLTECH':'Sterlite Technologies'}


def merge(articles):
    with store.LOCK:
        news=store.read('investor/news',{})
        by_id={a['id']:a for a in news.get('articles',[])}
        for article in articles:
            previous=by_id.get(article['id'])
            article=dict(article)
            article['first_seen_at']=(previous or article).get('first_seen_at',article['retrieved_at'])
            by_id[article['id']]=article
            intel.archive_article(article)
        originals={intel.normalize(a['title']) for a in by_id.values() if urlsplit(a['url']).hostname!='news.google.com' and a['source_kind']!='exchange'}
        # Keep Google records in the immutable archive but analyse the original URL
        # when the same headline was also discovered at its publisher.
        by_id={k:a for k,a in by_id.items() if not (urlsplit(a['url']).hostname=='news.google.com' and intel.normalize(a['title']) in originals)}
        at=intel.company.utcnow()
        news['articles']=sorted([a for a in by_id.values() if at-timedelta(days=30)<=datetime.fromisoformat(a['published_at'])<=at],key=lambda a:a['published_at'],reverse=True)
        store.write('investor/news',news)


def restore_archive(items, *, force=False, log=lambda m:None):
    """Read only news evidence across namespaces; never restore trading state."""
    items=list({i['isin']:i for i in items}.values())
    previous=store.read('investor/discovery/archive',{})
    identity=sorted(i['isin'] for i in items)
    if not force and previous.get('isins')==identity and 0<=intel.cache_age(previous)<1800:
        return previous
    found={}
    at=intel.company.utcnow()
    def collect(records):
        for a in records:
            try:
                if at-timedelta(days=30)<=datetime.fromisoformat(a['published_at'])<=at and any(intel.matches(i,a) for i in items):
                    old=found.get(a['id'])
                    if old is None or a['retrieved_at']>old['retrieved_at']:found[a['id']]=a
            except (KeyError,TypeError,ValueError):continue
    for _,value in store.records('investor/articles/'):
        collect([value])
    coverage=[]
    from core.research import investor_database
    for environment in ('local','production'):
        try:
            offset=0
            for _ in range(20):
                result=investor_database.read(dict(operation='recent_articles',environment=environment,offset=offset))
                collect(result['articles'])
                offset=result['next_offset']
                if offset is None:break
            coverage.append(dict(environment=environment,status='available' if offset is None else 'incomplete'))
        except ValueError:
            coverage.append(dict(environment=environment,status='unavailable'))
    merge(found.values())
    result=dict(as_of=at.isoformat(),isins=identity,count=len(found),coverage=coverage,
                partial=any(r['status']!='available' for r in coverage))
    store.write('investor/discovery/archive',result)
    log('Restored '+str(len(found))+' matching archived articles; shared archive '+('has gaps.' if result['partial'] else 'checked.'))
    return result


def publisher_link(url):
    """Decode legacy Google RSS URLs; opaque IDs remain explicit discovery gaps."""
    parsed=urlsplit(url)
    if parsed.hostname in ('www.bing.com','bing.com') and parsed.path=='/news/apiclick.aspx':
        return parse_qs(parsed.query).get('url',[url])[0]
    if parsed.hostname=='news.google.com' and '/articles/' in parsed.path:
        token=parsed.path.rsplit('/',1)[-1]
        try:
            raw=base64.urlsafe_b64decode(token+'='*(-len(token)%4))
            match=re.search(rb'https?://[^\x00-\x20\x7f-\xff]+',raw)
            if match:
                candidate=match.group().decode('ascii')
                if urlsplit(candidate).hostname!='news.google.com':return candidate
        except (ValueError,UnicodeError):pass
    return url


def resolve_google(url, *, transport=None, force=False):
    """Best-effort public redirect resolution; publisher access is checked separately.

    Google's page protocol is undocumented and may change. Never bypass a
    consent/login/CAPTCHA page or treat its HTML as the original news article.
    """
    decoded=publisher_link(url)
    if urlsplit(decoded).hostname!='news.google.com':return decoded
    key='investor/discovery/google-'+hashlib.sha256(url.encode()).hexdigest()
    cached=store.read(key,{})
    if not force and 0<=intel.cache_age(cached)<(86400 if cached.get('publisher_url') else 3600):
        return cached.get('publisher_url',url)
    result=dict(as_of=store.now(),url=url,status='unresolved')
    try:
        with httpx.Client(timeout=15,transport=transport,follow_redirects=False) as client:
            page_url=url
            for _ in range(4):
                if urlsplit(page_url).scheme!='https' or urlsplit(page_url).hostname!='news.google.com':raise ValueError('Unexpected redirect')
                with client.stream('GET',page_url) as response:
                    if response.is_redirect:
                        page_url=urljoin(page_url,response.headers.get('location',''));continue
                    response.raise_for_status();body=bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body)>2_000_000:raise ValueError('Oversized redirect page')
                break
            else:raise ValueError('Redirect limit')
            page=body.decode('utf-8',errors='replace')
            signature=re.search(r'data-n-a-sg="([^"]+)"',page)
            timestamp=re.search(r'data-n-a-ts="(\d+)"',page)
            if not signature or not timestamp:raise ValueError('Original link unavailable')
            token=urlsplit(url).path.rsplit('/',1)[-1]
            context=[["X","X",["X","X"],None,None,1,1,"IN:en",None,1,None,None,None,None,None,0,1],"X","X",1,[1,1,1],1,1,None,0,0,None,0]
            request=json.dumps(['garturlreq',context,token,int(timestamp.group(1)),signature.group(1)])
            with client.stream('POST','https://news.google.com/_/DotsSplashUi/data/batchexecute',data={'f.req':json.dumps([[['Fbv4je',request]]])}) as response:
                response.raise_for_status();body=bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>1_000_000:raise ValueError('Oversized redirect response')
            for line in body.decode('utf-8').splitlines():
                if not line.startswith('['):continue
                records=json.loads(line)
                if not isinstance(records,list):continue
                for record in records:
                    if isinstance(record,list) and len(record)>2 and record[0]=='wrb.fr' and record[1]=='Fbv4je':
                        data=json.loads(record[2])
                        if isinstance(data,list) and len(data)>1 and data[0]=='garturlres' and isinstance(data[1],str) and urlsplit(data[1]).scheme=='https' and urlsplit(data[1]).hostname!='news.google.com':
                            result.update(status='resolved',publisher_url=data[1])
                            break
    except (httpx.HTTPError,ValueError,TypeError,IndexError,UnicodeError):pass
    store.write(key,result)
    return result.get('publisher_url',url)


def refresh(items, *, force=False, transport=None, log=lambda m:None):
    at=intel.company.utcnow();collected=[];coverage=[]
    for item in {i['isin']:i for i in items}.values():
        key='investor/discovery/'+item['isin'];cached=store.read(key,{})
        if not force and cached.get('version')==2 and 0<=intel.cache_age(cached)<1800:
            collected.extend(cached.get('articles',[]));coverage.extend(cached['coverage']);continue
        name=ALIASES.get(item['symbol'],item.get('name',item['symbol']))
        name=re.sub(r'\s+(?:limited|ltd)\.?$','',name,flags=re.I).strip()
        query='("'+name+'" OR "'+item['symbol']+'") (stock OR company)'
        sources=[dict(id='google_news',name='Google News discovery: '+item['symbol'],kind='reporting',
                      url='https://news.google.com/rss/search?'+urlencode(dict(q=query+' when:30d',hl='en-IN',gl='IN',ceid='IN:en'))),
                 dict(id='bing',name='Bing News discovery: '+item['symbol'],kind='reporting',
                      url='https://www.bing.com/news/search?'+urlencode(dict(q=query,format='rss',sortby='Date',mkt='en-IN')))]
        # Try alternative reporting for recent inaccessible articles as well as
        # unresolved search links. Bound extra requests to three per company.
        existing=[a for a in store.read('investor/news',{}).get('articles',[]) if intel.matches(item,a)]
        failed=[a for a in existing if store.read('investor/full_articles/'+a['id'],{}).get('status') not in (None,'available')]
        fallback_titles=[]
        for article in failed[:3]:
            fallback_titles.append(intel.normalize(article['title']))
            sources.append(dict(id='bing_original',name='Alternative reporting lookup: '+item['symbol'],kind='reporting',
                                url='https://www.bing.com/news/search?'+urlencode(dict(q='"'+article['title']+'"',format='rss',mkt='en-IN'))))
        company_articles=[];rows=[]
        for source in sources:
            row=dict(source,isin=item['isin'],checked_at=at.isoformat(),count=0,skipped=0,lookback_days=30)
            log('Searching '+source['name']+'.')
            try:
                with httpx.Client(timeout=20,transport=transport,follow_redirects=False) as client:
                    with client.stream('GET',source['url']) as response:
                        response.raise_for_status();body=bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body)>2_000_000:raise ValueError('Oversized search feed')
                if b'<!DOCTYPE' in bytes(body).upper() or b'<!ENTITY' in bytes(body).upper():raise ValueError('Unsupported feed')
                root=ET.fromstring(body)
                if root.tag!='rss' or root.find('channel') is None:raise ValueError('Invalid search feed')
                for entry in root.findall('.//item'):
                    node=entry.find('link')
                    if node is not None:node.text=publisher_link(node.text or '')
                found,skipped=intel.parse_feed(ET.tostring(root),source,at,lookback_days=30)
                found=[a for a in found if intel.matches(item,a)]
                for article in found:
                    article.update(publisher=urlsplit(article['url']).hostname,discovery_query=query,discovery_isin=item['isin'])
                    if urlsplit(article['url']).hostname=='news.google.com':
                        article['discovery_link_status']='publisher_url_unresolved'
                row.update(status='available' if found else 'empty',count=len(found),skipped=skipped,
                           reason='Discovery only; complete original publisher text is required.')
                digest=hashlib.sha256(body).hexdigest()
                store.write('investor/feed_responses/discovery-'+digest,dict(as_of=at.isoformat(),source=source,xml=body.decode('utf-8',errors='replace')))
                company_articles.extend(found)
                if source['id']=='google_news':
                    unresolved=[a for a in found if a.get('discovery_link_status')=='publisher_url_unresolved']
                    for article in unresolved:
                        if len(fallback_titles)>=3:break
                        if intel.normalize(article['title']) in fallback_titles:continue
                        fallback_titles.append(intel.normalize(article['title']))
                        sources.append(dict(id='bing_original',name='Original article lookup: '+item['symbol'],kind='reporting',
                                            url='https://www.bing.com/news/search?'+urlencode(dict(q='"'+article['title']+'"',format='rss',mkt='en-IN'))))
            except (httpx.HTTPError,ValueError,ET.ParseError):
                row.update(status='unavailable',reason='Targeted search failed; coverage remains incomplete.')
            rows.append(row)
        store.write(key,dict(version=2,as_of=at.isoformat(),articles=company_articles,coverage=rows))
        collected.extend(company_articles);coverage.extend(rows)
    merge(collected)
    with store.LOCK:
        news=store.read('investor/news',{});news['discovery_coverage']=coverage;store.write('investor/news',news)
    return dict(count=len({a['id'] for a in collected}),coverage=coverage,partial=any(r['status']=='unavailable' for r in coverage))


def coverage_status(item,articles,review,news):
    rows=[r for r in news.get('discovery_coverage',[]) if r.get('isin')==item['isin']]
    complete=({r['id'] for r in rows if r['status'] in ('available','empty') and not r.get('skipped') and 0<=intel.cache_age(r,'checked_at')<3600} >= {'google_news','bing'}
              and not any(r.get('status')=='unavailable' for r in news.get('coverage',[]))
              and not any(r.get('status')=='unavailable' and r.get('isin')==item['isin'] for r in news.get('upstox_coverage',[])))
    archive=store.read('investor/discovery/archive',{})
    archive_ok=item['isin'] in archive.get('isins',[]) and not archive.get('partial',True) and 0<=intel.cache_age(archive)<3600
    if not articles:
        return dict(status='no_relevant_news_found' if complete and archive_ok else 'coverage_incomplete',
                    reason='No relevant news found in checked sources within 30 days; this is not proof that no news exists.' if complete and archive_ok else 'Search or archive coverage is missing, failed, stale, or incomplete.')
    bodies=[store.read('investor/full_articles/'+a['id'],{}) for a in articles]
    unavailable=sum(b.get('status') not in (None,'available') for b in bodies)
    pending=sum(not b.get('status') for b in bodies)
    if unavailable:status='full_article_unavailable'
    elif pending:status='needs_full_article_review'
    else:
        reviewed={s['article_id'] for s in (review or {}).get('article_summaries',[])}
        reviewed_articles={r['id']:r for r in (review or {}).get('articles',[])}
        valid=review and review.get('full_text') and 0<=intel.cache_age(review)<86400 and all(a['id'] in reviewed and reviewed_articles.get(a['id'],{}).get('sha256')==a['sha256'] and reviewed_articles.get(a['id'],{}).get('full_document_sha256')==b.get('response_sha256') and b.get('response_sha256') for a,b in zip(articles,bodies))
        status='reviewed' if valid else 'needs_full_article_review'
    return dict(status=status,reason=f'{len(articles)} matching articles; {unavailable} full bodies unavailable; {pending} not retrieved. Search results alone are not decision evidence.',search_complete=complete and archive_ok)
