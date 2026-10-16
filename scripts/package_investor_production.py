"""Prepare selective overlays against inspected production baselines."""
from pathlib import Path
import tarfile,io,json,hashlib
from core.research.investor_breakouts import Rules
from core.research.investor_workflow import MonitorSettings
root=Path(__file__).resolve().parents[1]
base=root/'data/private/investor-deploy/base'
payload={}
files=['core/research/jobs.py','core/research/investor_database.py','deploy/market-data/export_investor_data.py','core/research/company_review.py','core/research/investor_details.py','core/research/investor_upstox.py','core/research/investor_intelligence.py','core/research/investor_articles.py','core/research/investor_breakouts.py','core/research/investor_workflow.py','core/research/investor_discovery.py','core/research/investor_exits.py','dashboard/api/investor_intelligence.py','dashboard/web/investor-intelligence.js','scripts/sync_investor_data.py','deploy/market-data/import_investor_data.py','deploy/market-data/investor_schema.sql','deploy/market-data/archive_investor_server.py','deploy/market-data/investor-archive.service','deploy/market-data/investor-archive.timer']
for p in files:payload[p]=(root/p).read_bytes()
def change(text,old,new):
    if text.count(old)!=1:raise ValueError('Production patch anchor missing or ambiguous: '+old[:50])
    return text.replace(old,new)
p='dashboard/api/main.py';s=(base/p).read_text(encoding='utf-8')
s=change(s,'from dashboard.api.company_review import router as company_review_router','from dashboard.api.company_review import router as company_review_router\nfrom dashboard.api.investor_intelligence import router as investor_intelligence_router')
s=change(s,'    stop, thread = None, None','    stop, thread = None, None\n    from core.research import investor_workflow\n    investor_stop, investor_thread = investor_workflow.start()')
s=change(s,'    finally:\n        if stop is not None:','    finally:\n        investor_stop.set()\n        investor_thread.join(timeout=2)\n        if stop is not None:')
s=change(s,'app.include_router(company_review_router)','app.include_router(company_review_router)\napp.include_router(investor_intelligence_router)');payload[p]=s.encode()
p='dashboard/web/app.js';s=(base/p).read_text(encoding='utf-8')
s=change(s,"['backtests','Backtests'","['investor','Investor intelligence','◈'],['backtests','Backtests'")
s=change(s,'company:()=>companyReviewView(),','company:()=>companyReviewView(),investor:()=>investorView(),');payload[p]=s.encode()
p='dashboard/web/index.html';s=(base/p).read_text(encoding='utf-8')
s=change(s,'  <script defer src="/static/company-review.js"></script>','  <script defer src="/static/company-review.js"></script>\n  <script defer src="/static/investor-intelligence.js"></script>');payload[p]=s.encode()
p='dashboard/web/style.css';s=(base/p).read_text(encoding='utf-8')
s+='\n.investor-article-text'+(root/p).read_text(encoding='utf-8').split('.investor-article-text')[1];payload[p]=s.encode()
p='core/portfolio/paper.py';s=(base/p).read_text(encoding='utf-8')
s=change(s,'    def entry_check(symbol,day):\n        check=',"    def entry_check(symbol,day):\n        if any(e.get('symbol')==symbol and e.get('date','')>=day for e in portfolio.get('investor_exits',[])):\n            return False\n        check=");payload[p]=s.encode()
p='core/portfolio/midday.py';s=(base/p).read_text(encoding='utf-8')
s=change(s,"        if portfolio['status'] != 'active':\n            denial = 'Entries paused'","        if portfolio['status'] != 'active':\n            denial = 'Entries paused'\n        elif any(e.get('symbol')==s and e.get('date','')>=day for e in portfolio.get('investor_exits',[])):\n            denial = 'Investor news exit; no same-day reentry'");payload[p]=s.encode()
p='requirements-lock.txt';s=(base/p).read_text(encoding='utf-8');existing={x.split('==')[0] for x in s.splitlines()}
extra=[x for x in (root/p).read_text().splitlines() if x.split('==')[0] not in existing];payload[p]=(s.rstrip()+'\n'+'\n'.join(extra)+'\n').encode()
manifest={p:hashlib.sha256((base/p).read_text(encoding='utf-8').encode()).hexdigest() for p in ['dashboard/api/main.py','dashboard/web/app.js','dashboard/web/index.html','dashboard/web/style.css','core/portfolio/paper.py','core/portfolio/midday.py','requirements-lock.txt']}
payload['investor-deploy-manifest.json']=json.dumps(manifest).encode()
package=root/'data/private/investor-deploy/investor-code.tar.gz'
with tarfile.open(package,'w:gz') as t:
    for p,body in payload.items():
        info=tarfile.TarInfo(p);info.size=len(body);t.addfile(info,io.BytesIO(body))
seed=root/'data/private/investor-deploy/investor-data.tar.gz'
with tarfile.open(seed,'w:gz') as t:
    for p in (root/'data/investor').rglob('*.json'):
        if p.name in ('portfolio_snapshot.json','database_sync.json','settings.json','rules.json','monitor.json','monitor_scheduler.json','execution.json'):continue
        t.add(p,arcname=str(p.relative_to(root/'data')).replace('\\','/'))
    for p,value in [('investor/settings.json',MonitorSettings(enabled=True,profit_exit_enabled=True).model_dump()),('investor/rules.json',Rules().model_dump())]:
        body=json.dumps(value).encode();info=tarfile.TarInfo(p);info.size=len(body);t.addfile(info,io.BytesIO(body))
print('Prepared production package',len(payload),'files; archive seed bytes',seed.stat().st_size)
