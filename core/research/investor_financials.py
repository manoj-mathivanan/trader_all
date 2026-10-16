"""Public supplementary statements. Cross-source discrepancies fail closed."""
import hashlib,json,re,time
from urllib.parse import quote
import httpx
from lxml import html
from lxml.etree import ParserError
from core.research import store,investor_intelligence as intel


def parse(raw,item,basis,sections):
    from core.research.investor_details import number,period_date,history
    doc=html.fromstring(raw)
    links=[' '.join(a.text_content().split()) for a in doc.xpath('//a')]
    if not any(re.fullmatch(r'NSE:\s*'+re.escape(item['symbol']),s) for s in links):raise ValueError('Company identity did not match the NSE symbol.')
    tables={}
    for key in ('balance-sheet','profit-loss','cash-flow'):
        node=doc.get_element_by_id(key)
        label=' '.join(node.text_content().split())
        expected='Consolidated' if basis=='consolidated' else 'Standalone'
        info=doc.xpath('//*[@id="company-info"]')
        standalone_metadata=basis=='standalone' and len(info)==1 and info[0].get('data-company-id') and info[0].get('data-warehouse-id') and info[0].get('data-consolidated')!='true' and 'Consolidated Figures' not in label
        if expected+' Figures in Rs. Crores' not in label and not (standalone_metadata and 'Figures in Rs. Crores' in label):raise ValueError('Statement basis or units do not match.')
        table=node.xpath('.//table')[0];headers=[' '.join(c.text_content().split()) for c in table.xpath('.//thead/tr')[0]]
        values={}
        for row in table.xpath('.//tbody/tr'):
            cells=row.xpath('./td');text=[' '.join(c.text_content().split()) for c in cells]
            if not text:continue
            name=text[0].replace('+','').strip()
            values[name]={date:number(value) for date,value in zip(headers[1:],text[1:]) if period_date(date)}
        tables[key]=values
    annual=history(sections['annual_income']['data'],'income_statement','net_profit')
    if not annual:raise ValueError('No current annual profit to reconcile.')
    period=annual[0]['period'];profit=number(annual[0]['value'])
    def get(table,name):return tables[table].get(name,{}).get(period)
    sheet=sections.get('balance_sheet',{}).get('data') or {}
    equity=next((number(r['value']) for f in sheet.get('full_statement',[]) if f.get('particular')=='Equity Capital' for r in f.get('history',[]) if r.get('period')==period),None)
    capital,reserves,debt=get('balance-sheet','Equity Capital'),get('balance-sheet','Reserves'),get('balance-sheet','Borrowings')
    total_equity=capital+reserves if capital is not None and reserves is not None else None
    def matches(a,b):return a is not None and b is not None and abs(a-b)<=max(1,abs(b)*.02)
    profit_ok=matches(get('profit-loss','Net Profit'),profit)
    equity_ok=matches(total_equity,equity)
    official=store.read('investor/assessments/verified-financials-'+item.get('isin',''),{})
    source=None
    if (official.get('status')=='visually_verified' and official.get('company',{}).get('symbol')==item['symbol']
        and official.get('period')==period and official.get('statement_basis')==basis and official.get('units')=='crore'
        and official.get('source_sha256') and official.get('source_pages') and matches(official.get('total_equity'),equity)):
        total_equity=official['total_equity'];debt=official.get('debt_including_leases');equity_ok=True;source=official
    return dict(period=period,statement_basis=basis,units='crore',borrowings=debt,equity=total_equity,official_reconciliation=source,
                debt_equity=debt/total_equity if equity_ok and profit_ok and debt is not None and debt>=0 and total_equity>0 else None,
                operating_cash_flow=get('cash-flow','Cash from Operating Activity') if profit_ok else None,
                reconciliation=dict(equity=equity_ok,annual_profit=profit_ok),
                notice='Supplementary Screener statement; rounded values must reconcile within 2% (minimum Rs 1 crore). Not an exchange filing.')


def fetch(item,basis,sections,*,force=False,transport=None):
    name='investor/financial_supplements/'+item['isin']+'-'+basis
    old=store.read(name,{})
    if not force and 0<=intel.cache_age(old)<(86400 if old.get('status')=='available' else 3600):
        # Reconcile again against the currently selected statements.
        if old.get('raw_html'):
            try:return dict({k:v for k,v in old.items() if k!='reason'},status='available',data=parse(old['raw_html'].encode(),item,basis,sections))
            except (ValueError,KeyError,IndexError,ParserError):pass
        else:return old
    url='https://www.screener.in/company/'+quote(item['symbol'],safe='')+('/consolidated/' if basis=='consolidated' else '/')
    result=dict(as_of=store.now(),url=url,provider='Screener',status='unavailable',statement_basis=basis)
    try:
        with httpx.Client(timeout=20,follow_redirects=False,transport=transport) as client:
            with client.stream('GET',url,headers={'User-Agent':'InvestorResearch/1.0'}) as response:
                if response.status_code!=200:raise ValueError('Public statement returned HTTP '+str(response.status_code))
                raw=b''
                for chunk in response.iter_bytes():
                    raw+=chunk
                    if len(raw)>2_000_000:raise ValueError('Statement response exceeds size limit.')
        result.update(raw_html=raw.decode('utf-8'),response_sha256=hashlib.sha256(raw).hexdigest())
        result.update(status='available',data=parse(raw,item,basis,sections))
    except (httpx.HTTPError,ValueError,KeyError,IndexError,ParserError) as exc:result['reason']=str(exc)
    store.write(name,result)
    identity=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    store.write('investor/feed_responses/financial-supplement-'+identity,result)
    return result
