"""Incrementally mirror investor evidence to the existing shared PostgreSQL archive."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

try:
    from sync_market_refresh import lock
except ImportError:
    from scripts.sync_market_refresh import lock


def bundle(source, environment='local'):
    root = source/'investor'
    articles, documents = {}, []
    def add_article(value):
        # Retrieval times are observation metadata, not new content versions.
        record = {k:v for k,v in value.items() if k not in ('copies', 'retrieved_at', 'version_sha256')}
        record['retrieved_at'] = value.get('first_seen_at', value['retrieved_at'])
        sha = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        articles[(record['id'], sha)] = dict(sha256=sha, record=record)
    singles={'news','watchlist','settings','rules','portfolio_snapshot','scan','monitor','execution'}
    for kind in ('articles', 'refreshes', 'reviews', 'llm_responses', 'feed_responses', 'article_documents',
                 'article_summaries','scans','monitor_runs','alerts','article_coverage','discovery','stock_details','assessments','latest','full_articles',*sorted(singles)):
        if kind=='news' and any(d['kind']=='news' for d in documents):continue
        paths = [root/(kind+'.json')] if kind in singles else sorted((root/kind).glob('*.json'))
        for path in paths:
            if not path.exists():
                continue
            record = json.loads(path.read_text(encoding='utf-8'))
            if kind == 'articles':
                add_article(record)
                continue
            for article in record.get('articles', []) if isinstance(record,dict) else []:
                if 'text' not in article or 'source_id' not in article:continue
                add_article(article)
            if kind=='portfolio_snapshot':record={k:v for k,v in record.items() if k!='checked_at'}
            sha = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            documents.append(dict(kind=kind, id=path.stem, sha256=sha, record=record))
    for record in json.loads((source/'jobs.json').read_text(encoding='utf-8')) if (source/'jobs.json').exists() else []:
        if record.get('type','').startswith(('Investor ', 'Early breakout')):
            documents.append(dict(kind='analysis_jobs',id=record['id'],sha256=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest(),record=record))
    for path in sorted((source/'private').glob('investor-local-validation-*.json')):
        record=json.loads(path.read_text(encoding='utf-8'))
        documents.append(dict(kind='validation_reports',id=path.stem,sha256=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest(),record=record))
    return dict(version=1, environment=environment, articles=[articles[k] for k in sorted(articles)], documents=documents)


def run(source, target, key):
    state = source/'private/investor-db-sync'
    state.mkdir(parents=True, exist_ok=True)
    with lock(state/'worker.lock'):
        command=['ssh','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10',target]
        snapshot=subprocess.run(command+['/opt/market-data/venv/bin/python /opt/market-data/export_investor_holdings.py'],capture_output=True,timeout=30)
        if snapshot.returncode==0:
            remote=json.loads(snapshot.stdout)
            path=source/'investor/portfolio_snapshot.json'
            old=json.loads(path.read_text()) if path.exists() else {}
            if old.get('holdings')==remote['holdings']:remote['as_of']=old['as_of']
            from datetime import datetime,timezone
            remote['checked_at']=datetime.now(timezone.utc).isoformat()
            path.parent.mkdir(parents=True,exist_ok=True)
            pending=path.with_suffix('.tmp');pending.write_text(json.dumps(remote));pending.replace(path)
        full=bundle(source)
        archive_digest=hashlib.sha256(json.dumps(full,sort_keys=True).encode()).hexdigest()
        receipt = source/'investor/database_sync.json'
        previous = json.loads(receipt.read_text()) if receipt.exists() else {}
        if previous.get('archive_sha256') == archive_digest and previous.get('status') == 'complete':
            (state/'last-error.json').unlink(missing_ok=True)
            return dict(previous, cached=True)
        manifest_path=state/'objects.json'
        known=set(json.loads(manifest_path.read_text())) if manifest_path.exists() else set()
        def identity(row,kind):return kind+':'+(row.get('id') or row['record']['id'])+':'+row['sha256']
        batch=dict(version=1,environment='local',articles=[],documents=[])
        identities=set()
        for kind in ('articles','documents'):
            for row in full[kind]:
                token=identity(row,row.get('kind',kind));identities.add(token)
                if token not in known:batch[kind].append(row)
        value=dict(previous,status='complete',environment='local')
        inserted_articles=inserted_documents=0
        for part in batches(batch):
            data=json.dumps(part,sort_keys=True).encode()
            digest=hashlib.sha256(data).hexdigest()
            result = subprocess.run(command+['/opt/market-data/venv/bin/python /opt/market-data/import_investor_data.py'],
                                    input=data,capture_output=True,timeout=180)
            if result.returncode:raise RuntimeError('Investor database sync failed; local evidence retained for retry.')
            value=json.loads(result.stdout)
            if value.get('sha256')!=digest or value.get('status')!='complete':raise ValueError('Invalid investor database receipt')
            inserted_articles+=value.get('articles_inserted',0);inserted_documents+=value.get('documents_inserted',0)
            for kind in ('articles','documents'):
                known.update(identity(row,row.get('kind',kind)) for row in part[kind])
            pending=manifest_path.with_suffix('.tmp');pending.write_text(json.dumps(sorted(known)));pending.replace(manifest_path)
        value.update(articles_inserted=inserted_articles,documents_inserted=inserted_documents)
        from datetime import datetime, timezone
        value['synced_at'] = datetime.now(timezone.utc).isoformat()
        value['archive_sha256']=archive_digest
        pending = receipt.with_suffix('.tmp')
        pending.write_text(json.dumps(value, indent=2))
        pending.replace(receipt)
        pending=manifest_path.with_suffix('.tmp');pending.write_text(json.dumps(sorted(known|identities)));pending.replace(manifest_path)
        (state/'last-error.json').unlink(missing_ok=True)
        return value


def batches(bundle, max_bytes=40_000_000):
    """Bound imports and preserve acknowledged chunks when a later upload fails."""
    part=dict(version=1,environment=bundle['environment'],articles=[],documents=[])
    size=1000
    for kind in ('articles','documents'):
        for row in bundle[kind]:
            row_size=len(json.dumps(row,sort_keys=True).encode())+2
            if row_size+1000>max_bytes:raise ValueError('A single archive record exceeds the upload limit')
            if size+row_size>max_bytes:
                yield part
                part=dict(version=1,environment=bundle['environment'],articles=[],documents=[]);size=1000
            part[kind].append(row);size+=row_size
    if part['articles'] or part['documents']:yield part


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--ssh-target', required=True)
    parser.add_argument('--ssh-key', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.source, args.ssh_target, args.ssh_key)))
    except Exception as exc:
        from datetime import datetime, timezone
        path = args.source/'private/investor-db-sync/last-error.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), error_type=type(exc).__name__, retry=True)))
        receipt = args.source/'investor/database_sync.json'
        previous = json.loads(receipt.read_text()) if receipt.exists() else {}
        receipt.parent.mkdir(parents=True, exist_ok=True)
        pending = receipt.with_suffix('.tmp')
        pending.write_text(json.dumps(dict(previous, status='retry_pending', error_type=type(exc).__name__)))
        pending.replace(receipt)
        raise


if __name__ == '__main__':
    main()
