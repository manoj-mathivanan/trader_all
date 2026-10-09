"""Direct NSE Ind-AS filing retrieval and deterministic, conservative calculations."""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx
from core.research import store

IST = timezone(timedelta(hours=5, minutes=30))
FILING = re.compile(r'^/corporate/ixbrl/INTEGRATED_FILING_(?:INDAS|BANKING|NBFC_INDAS)_\d+_(\d{14})_iXBRL_WEB\.html$')
MAX_BYTES = 2_000_000
UNIT_FACTORS = {'lakhs': Decimal(100000), 'crores': Decimal(10000000), 'millions': Decimal(1000000),
                'actual': Decimal(1), 'actuals': Decimal(1), 'units': Decimal(1)}


def filing_date(value):
    for pattern in ('%d-%m-%Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError('Unsupported filing date.')


def filing_url(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname != 'nsearchives.nseindia.com'
                or parts.username or parts.password or parts.port not in (None, 443) or not FILING.fullmatch(parts.path)):
            return None
        datetime.strptime(FILING.fullmatch(parts.path)[1], '%d%m%Y%H%M%S')
    except ValueError:
        return None
    return urlunsplit(('https', parts.hostname, parts.path, '', ''))


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.stack, self.cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.stack.append([])
        elif tag in ('td', 'th') and self.stack:
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.stack and self.cell is not None:
            self.stack[-1].append(' '.join(' '.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.stack:
            row = self.stack.pop()
            if row:
                self.rows.append(row)


def number(text):
    value = text.strip().replace(',', '')
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    try:
        parsed = Decimal(value)
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def parse(html, url, item, at):
    url = filing_url(url)
    if not url:
        raise ValueError('Unsupported official filing URL.')
    company_type = 'bank' if '_BANKING_' in url else 'nbfc' if '_NBFC_INDAS_' in url else 'non_financial'
    parser = Rows()
    parser.feed(html)
    rows = parser.rows

    def values(label, source_rows=None):
        result = []
        for row in rows if source_rows is None else source_rows:
            for index, cell in enumerate(row):
                if cell.casefold() == label.casefold():
                    result.append(row[index + 1:])
        return result

    def unique(label):
        entries = {r[0] for r in values(label) if r and r[0]}
        if len(entries) != 1:
            raise ValueError('Missing or conflicting filing field: ' + label)
        return entries.pop()

    if unique('ISIN') != item['isin'] or unique('NSE Symbol').upper() != item['symbol'].upper():
        raise ValueError('Official filing identity does not match the selected company.')
    currency = unique('Description of presentation currency')
    if currency not in ('INR', 'INR (in Actuals)'):
        raise ValueError('Unsupported filing currency.')
    unit = 'actuals' if currency == 'INR (in Actuals)' else unique('Level of rounding used in financial results').casefold()
    if unit not in UNIT_FACTORS:
        raise ValueError('Unsupported financial unit.')
    # Annual documents contain both fourth-quarter and full-year cash-flow dates.
    # The first reporting-date rows belong to the primary financial-results table.
    reporting_start = values('Date of start of reporting period')
    reporting_end = values('Date of end of reporting period')
    if not reporting_start or not reporting_start[0] or not reporting_end or not reporting_end[0]:
        raise ValueError('Missing reporting dates.')
    start = filing_date(reporting_start[0][0])
    end = filing_date(reporting_end[0][0])
    basis = unique('Nature of report standalone or consolidated').casefold()
    if basis not in ('consolidated', 'standalone'):
        raise ValueError('Unsupported accounting basis.')
    approved = filing_date(unique('Date of board meeting when results were approved'))
    filed = datetime.strptime(FILING.fullmatch(urlsplit(url).path)[1], '%d%m%Y%H%M%S').replace(tzinfo=IST)
    if not start <= end <= approved <= filed.date() or filed > at:
        raise ValueError('Invalid or future filing dates.')
    # The segment table repeats revenue labels, sometimes with total income or
    # template zeroes. Conflicts within the primary P&L remain invalid, but a
    # different segment disclosure must not override the issuer's main results.
    period_rows = [i for i, row in enumerate(rows) if 'Date of start of reporting period' in row]
    pnl_start = period_rows[0]
    boundaries = period_rows[1:2] + [i for i, row in enumerate(rows) if i > pnl_start
                                   and any(cell.casefold().startswith('segment revenue') for cell in row)]
    pnl_rows = rows[pnl_start:min(boundaries) if boundaries else len(rows)]
    # Extract only the first reporting-period column; the next is usually YTD.
    def amount(label):
        entries = {number(r[0]) for r in values(label, pnl_rows) if r}
        entries.discard(None)
        return entries.pop() if len(entries) == 1 else None

    revenue_label = 'Total income' if company_type == 'bank' else 'Total Revenue From Operations' if company_type == 'nbfc' else 'Revenue from operations'
    profit_label = 'Net profit (loss) for the period' if company_type == 'bank' else 'Total profit (loss) for period'
    pbt_label = 'Total profit (loss) from ordinary activities before tax' if company_type == 'bank' else 'Total profit before tax'
    amounts = dict(revenue=amount(revenue_label), profit=amount(profit_label),
                   profit_before_tax=amount(pbt_label), finance_cost=amount('Finance costs'))
    if amounts['revenue'] is None or amounts['profit'] is None:
        raise ValueError('Filing lacks unambiguous revenue and profit rows.')
    opinion = values('Declaration of unmodified opinion or statement on impact of audit qualification')
    clean_opinion = bool(opinion and opinion[0] and opinion[0][0].casefold() == 'declaration of unmodified opinion')
    annual = None
    years = values('Date of start of financial year'), values('Date of end of financial year')
    if all(part and part[0] for part in years) and end == filing_date(years[1][0][0]):
        year_start = filing_date(years[0][0][0])
        if 350 <= (end-year_start).days <= 370:
            def first_column(label, column=0):
                candidates = values(label)
                return number(candidates[0][column]) if candidates and len(candidates[0]) > column else None
            # Annual P&L is the YTD column; balance sheet/cash flow are year-end/full-year.
            leases = values('Lease liabilities')
            lease_values = [number(r[0]) for r in leases if r]
            lease_total = sum(lease_values) if len(lease_values) == 2 and all(v is not None for v in lease_values) else None
            facts = dict(profit=first_column(profit_label, 1),
                         profit_before_tax=first_column(pbt_label, 1),
                         finance_cost=first_column('Finance costs', 1), equity=first_column('Total equity'),
                         assets=first_column('Total assets'), current_liabilities=first_column('Total current liabilities'),
                         borrowings_current=first_column('Borrowings, current'),
                         borrowings_non_current=first_column('Borrowings, non-current'), lease_liabilities=lease_total,
                         operating_cash_flow=first_column('Net cash flows from (used in) operating activities'))
            annual = dict(start=year_start.isoformat(), end=end.isoformat(),
                          amounts={k: str(v) if v is not None else None for k,v in facts.items()})
    return dict(url=url, isin=item['isin'], symbol=item['symbol'], basis=basis, unit=unit, company_type=company_type,
                start=start.isoformat(), end=end.isoformat(), filed_at=filed.isoformat(),
                approved_on=approved.isoformat(), amounts={k: str(v) if v is not None else None for k, v in amounts.items()},
                auditor_concern=False if clean_opinion else None, annual=annual, rows=rows)


def calculate(filings, item):
    if not filings:
        return None
    # Consolidated is preferred; never mix accounting bases or quarterly/YTD columns.
    consolidated = [f for f in filings if f['basis'] == 'consolidated']
    selected = consolidated or filings
    latest = max(selected, key=lambda f: (f['end'], f['filed_at']))
    company_type = latest.get('company_type', 'non_financial')
    end = datetime.fromisoformat(latest['end']).date()
    start = datetime.fromisoformat(latest['start']).date()
    if not 70 <= (end-start).days <= 100:
        return None  # Annual/YTD growth is not substituted for quarterly growth.
    matches = [f for f in selected if f.get('company_type','non_financial') == company_type
               and f['unit'] in UNIT_FACTORS and f['end'][:4] == str(end.year-1)
               and f['end'][4:] == latest['end'][4:] and f['start'][4:] == latest['start'][4:]]
    previous = max(matches, key=lambda f: f['filed_at'], default=None)
    # Ambiguous competing revisions cannot safely establish growth.
    if previous and any(f['amounts'] != previous['amounts'] for f in matches):
        previous = None
    metrics, citations, calculations = {}, [], []
    for field, raw in [('revenue_growth_pct', 'revenue'), ('profit_growth_pct', 'profit')]:
        if previous:
            current = Decimal(latest['amounts'][raw]) * UNIT_FACTORS[latest['unit']]
            prior = Decimal(previous['amounts'][raw]) * UNIT_FACTORS[previous['unit']]
            if prior > 0:
                value = (current/prior-1)*100
                if -100 <= value <= 10000:
                    metrics[field] = float(value)
                    calculations.append(dict(key=field, formula='(current / prior - 1) * 100',
                                             current=str(current), prior=str(prior), value=float(value), unit='INR'))
                    for f in (latest, previous):
                        citations.append(dict(key=field, url=f['url'], measurement_period=f['start']+' to '+f['end']))
    if latest['auditor_concern'] is False:
        metrics['auditor_concern'] = False
        citations.append(dict(key='auditor_concern', url=latest['url'], measurement_period=latest['end']))
    annuals = [f for f in selected if f.get('company_type','non_financial') == company_type
               and f.get('annual') and f['end'] <= latest['end']]
    annual = max(annuals, key=lambda f:(f['end'],f['filed_at']), default=None)
    if annual and (end-datetime.fromisoformat(annual['end']).date()).days <= 450:
        last_year = str(int(annual['end'][:4])-1)+annual['end'][4:]
        prior_annual = max((f for f in annuals if f['end']==last_year), key=lambda f:f['filed_at'], default=None)
        def annual_value(document, key):
            raw = document['annual']['amounts'].get(key) if document else None
            return Decimal(raw)*UNIT_FACTORS[document['unit']] if raw is not None else None
        def ratio(key, numerator, denominator, percentage=False, prior_document=None):
            if numerator is None or denominator is None or denominator <= 0:
                return
            value = numerator/denominator*(100 if percentage else 1)
            limits = {'roe_pct':(-1000,1000), 'roce_pct':(-1000,1000), 'debt_equity':(0,1000),
                      'interest_coverage':(-1000,10000), 'cash_profit_ratio':(-1000,1000)}
            if not limits[key][0] <= value <= limits[key][1]:
                return
            metrics[key]=float(value)
            calculations.append(dict(key=key, formula='numerator / denominator'+(' * 100' if percentage else ''),
                                     current=str(numerator), prior=str(denominator), value=float(value), unit='INR',
                                     percentage=percentage))
            for document in [annual]+([prior_document] if prior_document else []):
                citations.append(dict(key=key,url=document['url'],measurement_period=document['annual']['start']+' to '+document['end']))
        pat=annual_value(annual,'profit'); pbt=annual_value(annual,'profit_before_tax'); finance=annual_value(annual,'finance_cost')
        equity=annual_value(annual,'equity'); previous_equity=annual_value(prior_annual,'equity')
        if equity is not None and previous_equity is not None and equity > 0 and previous_equity > 0:
            ratio('roe_pct',pat,(equity+previous_equity)/2,True,prior_annual)
        if company_type == 'non_financial':
            ebit=pbt+finance if pbt is not None and finance is not None else None
            assets=annual_value(annual,'assets'); liabilities=annual_value(annual,'current_liabilities')
            previous_assets=annual_value(prior_annual,'assets'); previous_liabilities=annual_value(prior_annual,'current_liabilities')
            if all(v is not None for v in (assets,liabilities,previous_assets,previous_liabilities)):
                capital=assets-liabilities; previous_capital=previous_assets-previous_liabilities
                if capital > 0 and previous_capital > 0:
                    ratio('roce_pct',ebit,(capital+previous_capital)/2,True,prior_annual)
            debt=[annual_value(annual,k) for k in ('borrowings_current','borrowings_non_current','lease_liabilities')]
            if all(v is not None and v >= 0 for v in debt):
                ratio('debt_equity',sum(debt),equity)
            ratio('interest_coverage',ebit,finance)
            if pat is not None and pat > 0:
                ratio('cash_profit_ratio',annual_value(annual,'operating_cash_flow'),pat)
    if not metrics:
        return None
    return dict(isin=item['isin'], company_type=company_type, period_end=latest['end'], basis=latest['basis'],
                source=dict(title='NSE integrated financial filing · '+item['symbol'], url=latest['url'], published_at=latest['filed_at']),
                **metrics, notes='Quarterly growth calculated from matching periods, units and accounting basis. '
                'Annual ROE uses total PAT / average total equity; ROCE uses (PBT + finance costs) / average '
                '(assets - current liabilities), debt, interest coverage and cash/profit are calculated only '
                'for ordinary Ind-AS issuers, not banks or NBFCs. Debt includes borrowings and lease liabilities. Interest coverage '
                'uses (PBT + finance costs) / finance costs; cash conversion uses annual operating cash flow / PAT. '
                'Annual calculations use the full-year YTD column, never fourth-quarter profit. '
                'Filing timestamp is encoded in the NSE filename; board approval date is checked against it. '
                'Unmodified opinion covers this financial filing, not all governance or auditor risks.',
                provenance='official_nse_filing', metric_sources=citations, calculations=calculations,
                extraction_notice='Downloaded official NSE filing; numeric rows parsed and growth calculated in code. '
                'Unsupported ratios and missing comparable periods remain unknown.')


def discover(item, at, *, transport=None, history=False):
    """Use the NSE website's own filing index, independently of LLM link selection."""
    url = 'https://www.nseindia.com/api/integrated-filing-results'
    params = dict(symbol=item['symbol'], index='equities', page=1, size=100,
                  type='Integrated Filing- Financials', from_date=(at-timedelta(days=800)).strftime('%d-%m-%Y'),
                  to_date=at.astimezone(IST).strftime('%d-%m-%Y'))
    try:
        with httpx.Client(headers={'User-Agent':'TraderCompanyResearch/1.0'}, timeout=httpx.Timeout(20, connect=5),
                          follow_redirects=False, transport=transport) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            rows = response.json()['data']
        valid = [row for row in rows if row.get('symbol') == item['symbol'] and filing_url(row.get('ixbrl',''))]
        valid.sort(key=lambda row: (filing_date(row['qe_Date']), row.get('consolidated') == 'Consolidated'), reverse=True)
        if valid:
            latest = filing_date(valid[0]['qe_Date'])
            prior = latest.replace(year=latest.year-1)
            annual_end = datetime(latest.year if latest.month >= 3 else latest.year-1,3,31).date()
            if annual_end > latest:
                annual_end = annual_end.replace(year=annual_end.year-1)
            wanted = (latest,prior,annual_end,annual_end.replace(year=annual_end.year-1))
            if not history:
                valid = [row for row in valid if filing_date(row['qe_Date']) in wanted]
            # Retain latest revision per period/basis, avoiding duplicate filings crowding out comparables.
            unique = {}
            for row in valid:
                key=(row['qe_Date'],row.get('consolidated'))
                if key not in unique or datetime.strptime(FILING.fullmatch(urlsplit(row['ixbrl']).path)[1],'%d%m%Y%H%M%S') > datetime.strptime(FILING.fullmatch(urlsplit(unique[key]['ixbrl']).path)[1],'%d%m%Y%H%M%S'):
                    unique[key]=row
            valid=list(unique.values())
        return dict(status='available', url=str(response.url),
                    sources=[dict(url=row['ixbrl'], title=item['symbol']+' · NSE financial filing',
                                  period_end=filing_date(row['qe_Date']).isoformat(),
                                  basis='consolidated' if row.get('consolidated') == 'Consolidated' else 'standalone')
                             for row in valid[:64 if history else 8]])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return dict(status='unavailable', url=url, sources=[])


def retrieve(item, sources, at, *, transport=None, log=lambda message: None, discover_index=False):
    index = discover(item, at, transport=transport) if discover_index else dict(status='not_requested', sources=[])
    sources = index['sources'] or sources
    urls = sorted({u for source in sources for u in [filing_url(source['url'])] if u},
                  key=lambda u: datetime.strptime(FILING.fullmatch(urlsplit(u).path)[1], '%d%m%Y%H%M%S'), reverse=True)[:8]
    result = dict(status='no_supported_filings', documents=[], failures=[], snapshot=None, index=index)
    if not urls:
        return result
    log(f'Retrieving {len(urls)} official NSE financial filing(s).')
    filings = []
    # NSE's edge stalls the default python-httpx user agent. Identify this reader
    # explicitly; increasing the timeout alone does not fix those stalled requests.
    with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, transport=transport,
                      headers={'User-Agent': 'TraderCompanyResearch/1.0', 'Accept': 'text/html'}) as client:
        for url in urls:
            log('Downloading official NSE filing: '+urlsplit(url).path.rsplit('/', 1)[-1])
            try:
                with client.stream('GET', url) as response:
                    response.raise_for_status()
                    if 'html' not in response.headers.get('content-type', '').lower():
                        raise ValueError('Unsupported document type.')
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError('Filing exceeded size limit.')
                parsed = parse(data.decode('utf-8'), url, item, at)
                digest = hashlib.sha256(data).hexdigest()
                artifact = 'company/filings/'+digest
                path = store.DATA / (artifact+'.html')
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_bytes(data)
                parsed.update(sha256=digest, artifact=artifact+'.html')
                store.write(artifact, parsed)
                filings.append(parsed)
                result['documents'].append({k: parsed[k] for k in ('url','sha256','artifact','start','end','basis','unit','filed_at','approved_on')})
            except httpx.HTTPStatusError as exc:
                result['failures'].append(dict(url=url, reason=f'HTTP {exc.response.status_code}; download unavailable.'))
            except httpx.HTTPError:
                result['failures'].append(dict(url=url, reason='Connection failed or timed out.'))
            except (ValueError, UnicodeError):
                result['failures'].append(dict(url=url, reason='Document identity, dates or structure could not be validated.'))
    result['snapshot'] = calculate(filings, item)
    result['status'] = 'available' if result['snapshot'] else 'incomplete' if filings else 'unavailable'
    log(f'Official filings: {len(filings)} validated, {len(result["failures"])} unavailable.')
    return result
