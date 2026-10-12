"""Company-specific news discovery; publisher bodies remain separate evidence."""
import hashlib
import re
from urllib.parse import urlencode, urlsplit, parse_qs
from xml.etree import ElementTree as ET
import httpx
from core.research import investor_intelligence as intel, store

ALIASES={'BHEL':'Bharat Heavy Electricals','AETHER':'Aether Industries','STLTECH':'Sterlite Technologies'}


def refresh(items, *, force=False, transport=None, log=lambda m:None):
    at=intel.company.utcnow();collected=[];coverage=[]
    for item in {i['isin']:i for i in items}.values():
        key='investor/discovery/'+item['isin'];cached=store.read(key,{})
        if not force and 0<=intel.cache_age(cached)<1800:
            collected.extend(cached.get('articles',[]));coverage.append(cached['coverage']);continue
        name=ALIASES.get(item['symbol'],item.get('name',item['symbol']))
        name=re.sub(r'\s+(?:limited|ltd)\.?$','',name,flags=re.I).strip()
        query='"'+name+'" stock company'
        url='https://www.bing.com/news/search?'+urlencode(dict(q=query,format='rss',sortby='Date',mkt='en-IN'))
        source=dict(id='bing',name='Bing News discovery: '+item['symbol'],kind='reporting',url=url)
        row=dict(source,checked_at=at.isoformat(),count=0,skipped=0)
        log('Searching news for '+item['symbol']+'.')
        try:
            with httpx.Client(timeout=20,transport=transport,follow_redirects=False) as client:
                with client.stream('GET',url) as response:
                    response.raise_for_status();body=bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body)>2_000_000:raise ValueError('Oversized search feed')
            if b'<!DOCTYPE' in bytes(body).upper() or b'<!ENTITY' in bytes(body).upper():raise ValueError('Unsupported feed')
            root=ET.fromstring(body)
            for entry in root.findall('.//item'):
                node=entry.find('link')
                if node is None:continue
                link=urlsplit(node.text or '')
                if link.hostname in ('www.bing.com','bing.com') and link.path=='/news/apiclick.aspx':
                    node.text=parse_qs(link.query).get('url',[''])[0]
            found,skipped=intel.parse_feed(ET.tostring(root),source,at,lookback_days=30)
            for article in found:
                article.update(publisher=urlsplit(article['url']).hostname,discovery_query=query,discovery_isin=item['isin'])
            found=[a for a in found if intel.matches(item,a)]
            row.update(status='available' if found else 'empty',count=len(found),skipped=skipped,reason='Search results are discovery evidence; full publisher text is required for interpretation.')
            digest=hashlib.sha256(body).hexdigest()
            store.write('investor/feed_responses/discovery-'+digest,dict(as_of=at.isoformat(),source=source,xml=body.decode('utf-8',errors='replace')))
            store.write(key,dict(as_of=at.isoformat(),articles=found,coverage=row))
            collected.extend(found)
        except (httpx.HTTPError,ValueError,ET.ParseError):
            row.update(status='unavailable',reason='Targeted search unavailable; retained evidence is not complete coverage.')
        coverage.append(row)
    with store.LOCK:
        news=store.read('investor/news',{})
        by_id={a['id']:a for a in news.get('articles',[])}
        for article in collected:
            previous=by_id.get(article['id'])
            article['first_seen_at']=previous.get('first_seen_at',previous['retrieved_at']) if previous else article['retrieved_at']
            by_id[article['id']]=article;intel.archive_article(article)
        news['articles']=sorted(by_id.values(),key=lambda a:a['published_at'],reverse=True)[:3000]
        news['discovery_coverage']=coverage;store.write('investor/news',news)
    return dict(count=len(collected),coverage=coverage,partial=any(r['status']=='unavailable' for r in coverage))
