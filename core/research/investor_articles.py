"""Retrieve complete accessible article bodies; never substitute RSS for full text."""
import base64
import hashlib
import html
import io
import json
import re
import unicodedata
from urllib.parse import urlsplit, urljoin

import httpx
from lxml import html as html_tree
import trafilatura
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from core.research import store

HOSTS = {'nsearchives.nseindia.com', 'archives.nseindia.com', 'www.nseindia.com',
         'economictimes.indiatimes.com', 'www.business-standard.com', 'www.livemint.com',
         'www.moneycontrol.com','www.cnbctv18.com','www.thehindubusinessline.com',
         'www.financialexpress.com','www.reuters.com','www.bhel.com','bhel.com',
         'aether.co.in','www.aether.co.in','stl.tech','www.stl.tech','upstox.com','www.upstox.com',
         'www.businesstoday.in','www.zeebiz.com','www.ndtvprofit.com'}


def canonical_text(text):
    # Keep the original response bytes; normalize presentation characters only.
    text=html.unescape(text)
    text=''.join(c for c in text if unicodedata.category(c)!='Cf')
    text=text.translate(str.maketrans({'\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"','\xa0':' '}))
    return re.sub(r'\s+',' ',text).strip()


def allowed(url):
    p = urlsplit(url)
    return p.scheme == 'https' and p.hostname in HOSTS and not p.username and not p.password and p.port in (None, 443)


def structured_articles(value):
    if isinstance(value, list):
        for child in value:
            yield from structured_articles(child)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if isinstance(types, str):
            types = [types]
        if any(t in ('Article', 'NewsArticle', 'Report', 'BlogPosting') for t in types):
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from structured_articles(child)


def extract(body, content_type):
    if body.startswith(b'%PDF') or 'application/pdf' in content_type:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted or len(reader.pages) > 100:
            return '', 'unreadable_pdf', 'Encrypted or oversized filing.'
        pages = [page.extract_text() or '' for page in reader.pages]
        if any(len(text.strip()) < 20 for text in pages):
            return '\n\n'.join(pages), 'incomplete', 'At least one PDF page has no usable text; OCR is required.'
        return '\n\n'.join(pages), 'available', 'All PDF pages extracted; complex tables may lose structure.'
    root = html_tree.fromstring(body)
    records = []
    for script in root.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            records.extend(structured_articles(json.loads(script)))
        except (ValueError, TypeError):
            continue
    if any(str(r.get('isAccessibleForFree', '')).lower() == 'false' for r in records):
        return '', 'paywalled', 'Publisher marks the article as restricted.'
    for record in records:
        text = record.get('articleBody')
        if isinstance(text, str) and len(text.split()) >= 100:
            text = html.unescape(text).strip()
            if record.get('wordCount') and len(text.split()) < int(record['wordCount']) * .75:
                return text, 'incomplete', 'Extracted body is shorter than the publisher word count.'
            return text, 'available', 'Publisher articleBody extracted in full.'
    for node in root.xpath('//script|//style|//nav|//footer|//aside'):
        node.drop_tree()
    visible = ' '.join(root.itertext()).lower()
    if any(marker in visible for marker in ('subscribe to continue reading', 'subscribe to read the full',
                                            'this article is exclusive', 'unlock this article', 'sign in to continue reading')):
        return '', 'paywalled', 'Page displays a subscription or login wall.'
    text = trafilatura.extract(body, include_comments=False, include_tables=True, favor_recall=True) or ''
    if len(text.split()) < 100:
        return text, 'incomplete', 'Only a teaser or insufficient article text could be extracted.'
    # Full accessible body, not proof that a publisher did not omit content server-side.
    return text, 'available', 'Entire accessible body extracted; publisher completeness cannot be independently guaranteed.'


def read(article, *, force=False, transport=None):
    key = 'investor/full_articles/' + article['id']
    previous = store.read(key)
    from core.research.investor_intelligence import cache_age
    if previous and previous.get('extraction_version')==4 and not force and 0 <= cache_age(previous) < (86400 if previous['status']=='available' else 3600):
        return previous
    result = dict(article_id=article['id'], url=article['url'], title=article['title'],
                  published_at=article['published_at'], source_id=article['source_id'], as_of=store.now(),
                  text='', status='unavailable', reason='Source request failed.',extraction_version=4)
    url = article['url']
    try:
        if urlsplit(url).hostname=='news.google.com':
            from core.research.investor_discovery import resolve_google
            url=resolve_google(url,transport=transport,force=force)
            result['resolved_publisher_url']=url
        if not allowed(url):
            if urlsplit(url).hostname=='news.google.com':
                raise ValueError('Google found this headline, but its original publisher URL could not be resolved. Search summaries cannot replace the full article.')
            raise ValueError('Source host is not supported.')
        with httpx.Client(timeout=15, transport=transport, follow_redirects=False,
                          headers={'User-Agent':'TraderPersonalResearch/1.0'}) as client:
            for _ in range(4):
                if not allowed(url):
                    raise ValueError('Redirect left the supported publisher hosts.')
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 5_000_000:
                            raise ValueError('Article exceeds download limit.')
                    result.update(final_url=url, response_sha256=hashlib.sha256(body).hexdigest(),
                                  raw_base64=base64.b64encode(body).decode(), content_type=response.headers.get('content-type',''))
                    break
            else:
                raise ValueError('Too many redirects.')
        text, status, reason = extract(bytes(body), result['content_type'])
        text=canonical_text(text)
        result.update(text=text, status=status, reason=reason, text_sha256=hashlib.sha256(text.encode()).hexdigest())
        if len(text) > 150_000:
            result.update(status='oversized', reason='Whole article archived; exceeds analysis limit and was not summarized.')
    except (httpx.HTTPError, ValueError, TypeError, OSError, PdfReadError) as exc:
        result['reason'] = str(exc) if isinstance(exc, ValueError) else 'Publisher unavailable or document unreadable.'
    with store.LOCK:
        store.write(key, result)
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        store.write('investor/article_documents/'+article['id']+'-'+digest, result)
    return result
