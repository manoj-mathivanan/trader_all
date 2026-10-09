'use strict';
let companyState=null, companyLoading=false, companyUniverse=null, companyScan=null, companySelectedReview=null;
let companyFilters={query:'', minimum:0, complete:false, candidates:false};
let companyPendingJob=null, companyLastCompletedMarketFetch=null;
const companyMetricLabels={revenue_growth_pct:'Latest quarter revenue growth YoY (%)',profit_growth_pct:'Latest quarter PAT growth YoY (%)',roe_pct:'Trailing annual ROE (%)',roce_pct:'Trailing annual ROCE (%)',debt_equity:'Latest debt / equity',interest_coverage:'Trailing annual interest coverage',cash_profit_ratio:'Annual operating cash flow / PAT',promoter_pledge_pct:'Promoter shares pledged (%)',net_npa_pct:'Net NPA (%)',capital_adequacy_pct:'Capital adequacy (%)'};

async function loadCompany(){
  if(companyLoading)return;
  companyLoading=true;
  try{companyState=await api('company');companyUniverse=state.settings.universe;if(currentView==='company')render();}
  catch(e){if(currentView==='company')$('#view').innerHTML=heading('Company research','Review business quality and recent evidence.')+empty('Company research could not load',e.message);}
  finally{companyLoading=false;}
}
function companyReviewView(){
  if(companyUniverse!==state.settings.universe){companyState=null;companyScan=null;companyFilters.candidates=false;}
  if(!companyState){loadCompany();return heading('Company research','Review business quality and recent evidence.')+'<p role="status">Loading company evidence…</p>';}
  const rows=companyState.rows, available=rows.filter(r=>r.score!=null), reviewed=companyState.reviews;
  return heading('Business quality behind the breakout.','The LLM finds company filings and recent news, then challenges the buy thesis.',`<button class="button" data-company-action="reload">↻ Refresh</button>`)+pending()+
    `<div class="notice">Choose a stock and select <strong>Research stock</strong>. The LLM searches websites itself and returns cited financial evidence, catalysts, risks and unknowns. No articles or source links are required from you. Stored fundamentals support the candidate quality checks; LLM news reviews remain advisory.</div>`+
    `<div class="stats">${stat('Financial coverage',`${available.length} / ${rows.length}`,'Financial evidence found')}${stat('Complete snapshots',rows.filter(r=>r.coverage_pct===100).length,'Missing metrics earn no points')}${stat('Saved reviews',reviewed.length,'Latest 100 shown')}${stat('Web researcher',companyState.llm.enabled?'Connected':'Not connected',companyState.llm.enabled?'Finds filings and multiple news sources':companyState.llm.reason)}</div>`+
    `${companyHistoryCoverage()}${companyBuyScreens()}<section class="panel"><div class="panel-head"><div><h2>Find candidates from your strategy</h2><p>Scan completed daily history, then inspect company quality.</p></div></div><div class="panel-body"><div class="actions"><label class="field"><span>Technical screen</span><select id="company-screen">${['vcp','blue_sky','multiyear','ipo'].map(p=>`<option value="builtin:${p}" ${companyScan?.config?.pattern===p?'selected':''}>${esc(p.replaceAll('_',' '))}</option>`).join('')}${(state.screens||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}</select></label><button class="button" data-company-action="scan">Scan technical candidates</button></div><div id="company-scan-status" aria-live="polite">${companyScan?companyScanSummary():''}</div></div></section>`+
    `<div class="toolbar company-toolbar"><label class="search"><span class="sr-only">Search companies</span><input id="company-search" value="${esc(companyFilters.query)}" placeholder="Symbol, company or sector…"></label><label class="field"><span>Minimum score</span><input id="company-minimum" type="number" min="0" max="100" value="${companyFilters.minimum}"></label><label><input id="company-complete" type="checkbox" ${companyFilters.complete?'checked':''}> Complete evidence only</label><label><input id="company-candidates" type="checkbox" ${companyFilters.candidates?'checked':''} ${companyScan?'':'disabled'}> Technical matches only</label></div>`+
    `<section class="panel"><div id="company-table">${companyTable()}</div></section>`+
    `<section class="panel"><div class="panel-head"><div><h2>Prospective review journal</h2><p>Retain rejected candidates as well as accepted ones.</p></div></div>${reviewed.length?`<div class="table-wrap"><table><thead><tr><th>Company</th><th>Reviewed</th><th>Score</th><th>News evidence</th><th>Your disposition</th><th></th></tr></thead><tbody>${reviewed.map(r=>`<tr><td>${esc(r.symbol)}</td><td>${when(r.as_of)}</td><td>${r.score??'—'}</td><td>${esc(r.verdict.replaceAll('_',' '))}</td><td>${esc(r.disposition.replaceAll('_',' '))}</td><td><button class="text-button" data-company-action="saved-review" data-id="${esc(r.id)}">Read review ↗</button></td></tr>`).join('')}</tbody></table></div>`:empty('No reviews saved','Research a stock to collect its financial evidence and news automatically.')}</section>`;
}
function companyHistoryCoverage(){
  const h=companyState.history_coverage;if(!h)return '';
  return `<section class="panel"><div class="panel-head"><h2>Historical financial coverage</h2></div><div class="panel-body"><p>Coverage measured: ${when(h.measured_at)}.</p><p>${h.validated_symbols}/${h.total_symbols} stocks with validated snapshots · ${h.retained_snapshot_versions} retained versions · ${h.companies_with_multiple_snapshot_periods} stocks with multiple snapshot quarters.</p><p>Snapshot periods: ${esc(Object.entries(h.snapshot_periods).map(([day,n])=>day+' ('+n+' stocks)').join(' · ')||'None')}.</p><p>${h.source_filings} comparative source filings. Source periods: ${esc(Object.entries(h.source_periods).map(([day,n])=>day+' ('+n+' filings)').join(' · ')||'None')}.</p><p>${esc(h.notice)}</p></div></section>`;
}
function companyScanSummary(){return `<p>Signal session: <strong>${esc(companyScan.as_of||'No completed history')}</strong> · ${companyScan.matches.length} technical matches · First ${companyScan.config.max_positions||5} by fundamental score: ${esc((companyScan.recommended||companyScan.matches.slice(0,5)).map(x=>x.symbol+' ('+x.fundamental_score+')').join(', ')||'None')} · ${companyScan.excluded.length} exclusions · market gate ${companyScan.market_gate_passed?'passed':'failed'}.</p><p>${esc(companyScan.notice)}</p><details><summary>Excluded history</summary><ul>${companyScan.excluded.map(x=>`<li>${esc(x.symbol)}: ${esc(x.reason)}</li>`).join('')||'<li>None</li>'}</ul></details>`;}
function companyTable(){
  const match=new Set((companyScan?.matches||[]).map(x=>x.isin));
  const rows=companyState.rows.filter(r=>{
    const c=r.company;
    return `${c.symbol} ${c.name} ${c.sector}`.toLowerCase().includes(companyFilters.query.toLowerCase())&&
      (!companyFilters.minimum||(r.score!=null&&r.score>=companyFilters.minimum))&&
      (!companyFilters.complete||(r.coverage_pct===100&&r.status==='available'))&&(!companyFilters.candidates||match.has(c.isin));
  }).sort((a,b)=>(b.score??-1)-(a.score??-1)||b.coverage_pct-a.coverage_pct||a.company.symbol.localeCompare(b.company.symbol));
  if(!rows.length)return empty('No matching companies',companyState.rows.length?'Adjust the score or evidence filters.':'Refresh the market universe first.','data','Open market data');
  return `<div class="table-wrap"><table><thead><tr><th>Company</th><th>Score / 100</th><th>Evidence coverage</th><th>Financial period / last pull</th><th>Status</th><th>News review</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.company.symbol)}</strong><small>${esc(r.company.name)}</small>${match.has(r.company.isin)?'<span class="badge">Technical match</span>':''}</td><td>${r.score??'—'}</td><td>${r.coverage_pct}%</td><td>${esc(r.period_end||'No evidence')}<small>Last pull: ${r.last_pulled_at?when(r.last_pulled_at):'Never'}</small><small>${esc((r.pull_status||'not_pulled').replaceAll('_',' '))}</small></td><td>${esc(r.status.replaceAll('_',' '))}<small>${esc(r.flags.join(' · '))}</small></td><td>${esc(r.latest_review?.verdict?.replaceAll('_',' ')||'Not researched')}<small>${r.latest_review?when(r.latest_review.as_of):'Sources found automatically'}</small></td><td><div class="actions"><button class="button small" data-company-action="buy-check" data-isin="${esc(r.company.isin)}">Check buy</button><button class="button small" data-company-action="auto-research" data-isin="${esc(r.company.isin)}" ${activeJob()?'disabled':''}>Research stock ↗</button>${r.latest_review?`<button class="text-button" data-company-action="saved-review" data-id="${esc(r.latest_review.id)}">Read review</button>`:''}</div></td></tr>`).join('')}</tbody></table></div>`;
}

function companyBuyScreens(){
  if(!companyState.buy_screens)return '';
  const pull=companyState.bulk_pull||{};
  return `<section class="panel"><div class="panel-head"><h2>Fundamental buy screens</h2><button class="button" data-company-action="pull-fundamentals" ${activeJob()?'disabled':''}>Pull quarterly fundamentals</button></div><div class="panel-body"><p>Candidate quality checks use the saved score and coverage thresholds, fresh evidence and no flagged concerns. Missing evidence fails the check. Current scores are not applied to historical backtests.</p><p>Latest bulk pull: ${pull.started_at?when(pull.started_at):'Not started'} · ${esc(JSON.stringify(pull.counts||{}))}${pull.completed_at?' · completed':''}</p>${Object.entries(companyState.buy_screens).map(([strategy,cfg])=>`<form id="company-buy-screen-form-${strategy}" data-strategy="${strategy}"><h3>${strategy==='swing_patterns'?'Swing':'Intraday momentum'}</h3><div class="fields">${companyInput('min_score','Minimum score',cfg.min_score,'number','min="0" max="100" required')}${companyInput('min_coverage_pct','Minimum evidence coverage (%)',cfg.min_coverage_pct,'number','min="0" max="100" required')}${companyInput('max_age_days','Maximum financial period age (days)',cfg.max_age_days,'number','min="1" max="730" required')}</div><div class="form-error" role="alert"></div><button class="button" type="submit">Save buy screen</button></form>`).join('')}</div></section>`;
}

function companyItem(isin){return state.instruments.find(x=>x.isin===isin);}
function companySelect(name, label, options, value=''){return `<label class="field"><span>${esc(label)}</span><select name="${esc(name)}" required>${options.map(([key,text])=>`<option value="${esc(key)}" ${key===value?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;}
function companyInput(name,label,value='',type='text',extra=''){return `<label class="field"><span>${esc(label)}</span><input name="${esc(name)}" type="${type}" value="${esc(value)}" ${extra}></label>`;}
function companyFormFooter(label){return `<div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">${label}</button></div>`;}
function companyAutoForm(isin){
  modal(companyItem(isin).symbol+' · automatic web research',`<form id="company-auto-form" data-isin="${esc(isin)}"><div class="notice">The LLM will search for company filings and multiple recent news articles, compare the evidence and save a cited review. You do not need to provide websites or article text.</div><div class="form-section"><label class="field"><span>Your technical setup or thesis (optional)</span><textarea name="thesis" rows="3" maxlength="2000"></textarea></label>${companySelect('disposition','Your provisional decision',[['undecided','Undecided'],['watch','Watch'],['would_take','Would take'],['would_skip','Would skip']],'undecided')}<p>Searches prioritize company/exchange disclosures for financial figures and compare recent reporting for support, risks and contradictions. Missing evidence stays unknown.</p>${companyState.llm.enabled?'':`<div class="notice warn">${esc(companyState.llm.reason)}</div>`}</div>${companyFormFooter('Search websites & save review')}</form>`);
  $('#company-auto-form').querySelector('[type="submit"]').disabled=!companyState.llm.enabled||Boolean(activeJob());
}
function companyOfficialEvidence(review){
  const official=review.retrieval?.official_filings;if(!official)return '';
  return `<div class="notice">Official filing retrieval: <strong>${esc(official.status.replaceAll('_',' '))}</strong> · ${(official.documents||[]).length} validated document(s). Financial scores use downloaded filings and calculations in code.</div><details><summary>Official financial downloads & calculations</summary><ul>${(official.documents||[]).map(d=>`<li><a href="${esc(d.url)}" target="_blank" rel="noreferrer">NSE filing</a> · ${esc(d.start)} to ${esc(d.end)} · ${esc(d.basis)} · ${esc(d.unit)}<small>SHA-256: ${esc(d.sha256)}</small></li>`).join('')}${(official.failures||[]).map(d=>`<li><a href="${esc(d.url)}" target="_blank" rel="noreferrer">Unavailable filing</a> · ${esc(d.reason)}</li>`).join('')}</ul>${(official.snapshot?.calculations||[]).map(c=>`<p>${esc(companyMetricLabels[c.key]||c.key)}: ${esc(c.formula)} · current ${esc(c.current)}, prior ${esc(c.prior)} (${esc(c.unit)}) = ${esc(Number(c.value).toFixed(2))}${c.key.endsWith("_pct")?"%":""}</p>`).join('')}<p>Quarterly growth and annual ratios use their respective measurement periods. Missing evidence remains unknown. Supports NSE Ind-AS filings for non-financial companies.</p></details>`;
}
function companyWebReview(review){
  const sources=review.retrieval?.sources||[];
  return `<p>${esc(review.news.notice)}</p>${review.news.findings.map(f=>`<section class="company-finding"><strong>${esc(f.kind.toUpperCase())} · ${esc(f.event)}</strong><p>${esc(f.explanation)}</p><ul>${f.citations.map(c=>`<li><a href="${esc(c.url)}" target="_blank" rel="noreferrer">${esc(c.title)}</a> · ${esc(c.source_kind)} · ${esc(c.published_date||'Publication date unknown')}</li>`).join('')}</ul></section>`).join('')}<h3>Unknowns</h3><ul>${review.news.unknowns.map(u=>`<li>${esc(u)}</li>`).join('')||'<li>No further gaps identified by the model; completeness is not guaranteed.</li>'}</ul><details><summary>Web sources discovered (${sources.length})</summary><ul>${sources.map(s=>`<li><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.title)}</a></li>`).join('')}</ul></details><details><summary>Retrieved research report</summary><p class="company-evidence-text">${esc(review.retrieval?.report||'')}</p></details>`;
}
function companyFinancialFields(type, snapshot={}){
  const keys=type==='non_financial'?['revenue_growth_pct','profit_growth_pct','roe_pct','roce_pct','debt_equity','interest_coverage','cash_profit_ratio','promoter_pledge_pct']:['revenue_growth_pct','profit_growth_pct','roe_pct','net_npa_pct','capital_adequacy_pct','promoter_pledge_pct'];
  return keys.map(k=>companyInput(k,companyMetricLabels[k],snapshot[k]??'','number','step="any"')).join('')+
    ['auditor_concern','governance_concern'].map(k=>companySelect(k,k==='auditor_concern'?'Reported auditor concern':'Reported governance concern',[['','Unknown'],['false','No reported concern'],['true','Concern reported']],snapshot[k]==null?'':String(snapshot[k]))).join('');
}
async function companyFinancialForm(isin){
  const evidence=await api('company/evidence/'+encodeURIComponent(isin)), s=evidence.fundamentals.snapshot||{}, item=companyItem(isin);
  modal(item.symbol+' · financial evidence',`<form id="company-financial-form" data-isin="${esc(isin)}"><div class="notice">Enter figures from company filings. Leave unavailable metrics blank. Quarterly growth is year-on-year; ROE, ROCE, interest coverage and cash/PAT use annual or trailing annual figures. Cash/PAT is meaningful only with positive PAT; leave it blank for losses. Pledge is pledged promoter shares / total promoter shares. Note the measurement periods and any differing source documents below.</div><div class="form-section"><div class="fields">${companySelect('company_type','Company type',[['non_financial','Non-financial company'],['bank','Bank'],['nbfc','NBFC']],s.company_type||'non_financial')}${companySelect('basis','Accounting basis',[['consolidated','Consolidated'],['standalone','Standalone']],s.basis||'consolidated')}${companyInput('period_end','Latest financial period end',s.period_end||'','date','required')}${companyInput('source_title','Source document',s.source?.title||'','text','required maxlength="300"')}${companyInput('source_url','Source HTTPS link',s.source?.url||'','url','required maxlength="2000"')}${companyInput('published_at','Source publication time (include timezone)',s.source?.published_at||'','text','required placeholder="2026-10-01T16:30:00+05:30"')}</div></div><div class="form-section"><h3>Company quality metrics</h3><div class="fields" id="company-metrics">${companyFinancialFields(s.company_type||'non_financial',s)}</div><label class="field"><span>Measurement periods, additional sources and notes</span><textarea name="notes" rows="3" maxlength="3000">${esc(s.notes||'')}</textarea></label></div>${companyFormFooter('Save financial snapshot')}</form>`);
}
function companyArticleForm(isin){modal(companyItem(isin).symbol+' · article evidence',`<form id="company-article-form" data-isin="${esc(isin)}"><div class="notice">Paste article text you can access, with its original link and publication time. Articles must refer to this company. The news reviewer uses up to 12 deduplicated articles from the last 30 days; identical text and duplicate links count once.</div><div class="form-section"><div class="fields">${companyInput('title','Article title','','text','required maxlength="300"')}${companyInput('url','Original HTTPS link','','url','required maxlength="2000"')}${companyInput('published_at','Publication time (include timezone)','','text','required placeholder="2026-10-08T09:00:00+05:30"')}${companySelect('source_kind','Source type',[['reporting','News reporting'],['exchange','Exchange disclosure'],['company','Company announcement'],['opinion','Opinion / commentary']],'reporting')}</div><label class="field"><span>Article text</span><textarea name="text" rows="10" required minlength="80" maxlength="20000"></textarea></label></div>${companyFormFooter('Save article evidence')}</form>`);}
function companyChecks(f){return `<div class="notice">Score: <strong>${f.score??'—'} / 100</strong> · coverage ${f.coverage_pct}% · ${esc(f.status.replaceAll('_',' '))}. ${esc(f.flags.join(' · '))}</div>${f.snapshot?`<p>Period ${esc(f.snapshot.period_end)} · ${esc(f.snapshot.basis)} · <a href="${esc(f.snapshot.source.url)}" target="_blank" rel="noreferrer">${esc(f.snapshot.source.title)}</a> · ${when(f.snapshot.source.published_at)}</p><div class="table-wrap"><table><thead><tr><th>Experimental criterion</th><th>Value</th><th>Points available</th><th>Result</th></tr></thead><tbody>${f.checks.map(c=>`<tr><td>${esc(c.label)}</td><td>${c.value==null?'—':esc(c.value)}</td><td>${c.weight}</td><td>${esc(c.result)}</td></tr>`).join('')}</tbody></table></div><p>${esc(f.snapshot.notes)}</p>`:''}`;}
function companyArticles(articles){return articles.length?`<ul>${articles.map(a=>`<li><a href="${esc(a.url)}" target="_blank" rel="noreferrer">${esc(a.title)}</a> · ${esc(a.source_kind)} · ${when(a.published_at)}</li>`).join('')}</ul>`:'<p>No recent article evidence. This does not imply favourable news.</p>';}
async function companyReviewForm(isin){
  const evidence=await api('company/evidence/'+encodeURIComponent(isin));
  modal(companyItem(isin).symbol+' · challenge the thesis',`<form id="company-review-form" data-isin="${esc(isin)}"><div class="form-section">${companyChecks(evidence.fundamentals)}<h3>Available news evidence</h3>${companyArticles(evidence.articles)}<label class="field"><span>Your technical setup and thesis</span><textarea name="thesis" rows="3" maxlength="2000"></textarea></label>${companySelect('disposition','Your provisional decision',[['undecided','Undecided'],['watch','Watch'],['would_take','Would take'],['would_skip','Would skip']],'undecided')}<label><input type="checkbox" name="use_llm" ${!companyState?.llm.enabled||!evidence.articles.length?'disabled':''}> Review articles with the LLM</label><p>${companyState?.llm.enabled?'When selected, company identity and the listed article text are sent to the configured OpenAI model. The response looks for support, risks and contradictions.':esc(companyState?.llm.reason||'LLM is not connected.')}</p></div>${companyFormFooter('Save prospective review')}</form>`);
}
function companyShowReview(review){
  companySelectedReview=review;
  if(review.research_mode==='automatic_web'){
    const snapshot=review.fundamentals.snapshot;
    modal(review.company.symbol+' · automatic web review',`<div class="actions"><button class="button" data-company-action="export-review">Export review JSON ↓</button></div><p>${when(review.as_of)} · ${esc(review.disposition.replaceAll('_',' '))}</p><div class="notice">${esc(review.notice)}</div><h3>Your thesis</h3><p>${esc(review.thesis||'No thesis entered')}</p><h3>Financial evidence</h3>${companyOfficialEvidence(review)}${companyChecks(review.fundamentals)}${snapshot?`<div class="notice warn">${esc(snapshot.extraction_notice)}</div><details><summary>Financial measurement sources</summary><ul>${(snapshot.metric_sources||[]).map(m=>`<li>${esc(companyMetricLabels[m.key]||m.key)} · ${esc(m.measurement_period)} · <a href="${esc(m.url)}" target="_blank" rel="noreferrer">Source</a></li>`).join('')}</ul></details>`:''}<h3>News: ${esc(review.news.verdict.replaceAll('_',' '))}</h3>${companyWebReview(review)}<p>Model: ${esc(review.news.model)}</p>`);return;
  }
  const byId=Object.fromEntries(review.articles.map(a=>[a.id,a]));
  modal(review.company.symbol+' · saved review',`<div class="actions"><button class="button" data-company-action="export-review">Export review JSON ↓</button></div><p>${when(review.as_of)} · ${esc(review.disposition.replaceAll('_',' '))}</p><div class="notice">${esc(review.notice)}</div><h3>Your thesis</h3><p>${esc(review.thesis||'No thesis entered')}</p><h3>Financial evidence</h3>${companyChecks(review.fundamentals)}<h3>News: ${esc(review.news.verdict.replaceAll('_',' '))}</h3><p>${esc(review.news.notice||'No LLM analysis requested.')}</p>${review.news.findings.map(f=>`<section class="company-finding"><strong>${esc(f.kind.toUpperCase())} · ${esc(f.event)}</strong><p>${esc(f.explanation)}</p>${f.citations.map(c=>{const a=byId[c.article_id];return `<blockquote>${esc(c.excerpt)}</blockquote><p><a href="${esc(a.url)}" target="_blank" rel="noreferrer">${esc(a.title)}</a> · ${when(a.published_at)}</p>`;}).join('')}</section>`).join('')}<h3>Unknowns</h3><ul>${review.news.unknowns.map(u=>`<li>${esc(u)}</li>`).join('')||'<li>None identified by the model; completeness is not guaranteed.</li>'}</ul><details><summary>All article evidence (${review.articles.length})</summary>${companyArticles(review.articles)}${review.articles.map(a=>`<details><summary>${esc(a.title)}</summary><p class="company-evidence-text">${esc(a.text)}</p></details>`).join('')}</details>${review.news.model?`<p>Model: ${esc(review.news.model)} · interpretation may be wrong; review the sources.</p>`:''}`);
}
function companyImportForm(){modal('Import source-backed company evidence',`<form id="company-import-form"><div class="notice">Import a JSON document with fundamentals and/or articles arrays. Company ISINs must belong to the current universe. See COMPANY_RESEARCH.md for the fields and measurement definitions.</div><div class="form-section"><label class="field"><span>Choose JSON file</span><input type="file" id="company-json-file" accept=".json,application/json"></label><label class="field"><span>Evidence JSON</span><textarea name="payload" rows="14" required placeholder='{"fundamentals": [], "articles": []}' maxlength="3000000"></textarea></label></div>${companyFormFooter('Import evidence')}</form>`);}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-company-action]');if(!button)return;
  const action=button.dataset.companyAction, isin=button.dataset.isin;
  button.disabled=true;
  try{
    if(action==='buy-check'){const results=await Promise.all(['swing_patterns','intraday_momentum'].map(s=>api('company/buy-check/'+s+'/'+encodeURIComponent(isin))));modal(companyItem(isin).symbol+' · buy eligibility',results.map(r=>`<h3>${r.strategy_id==='swing_patterns'?'Swing':'Intraday momentum'}: ${r.buy_allowed?'Allowed':'Blocked'}</h3><p>Minimum score ${r.screen.min_score}; coverage ${r.screen.min_coverage_pct}%; maximum age ${r.screen.max_age_days} days.</p><p>${esc(r.block_reasons.join(' · ')||'All configured fundamental requirements passed.')}</p><p>Last pull: ${r.last_pulled_at?when(r.last_pulled_at):'Never'} · last check: ${r.last_checked_at?when(r.last_checked_at):'Never'}</p>${companyChecks(r)}`).join(''));return;}
    if(action==='pull-fundamentals'){await api('company/fundamentals-pull','POST');await refresh(false);render();toast('Quarterly fundamentals pull started.');return;}
    if(action==='auto-research'){companyAutoForm(isin);return;}
    if(action==='reload'){await loadCompany();return;}
    if(action==='fundamentals'){await companyFinancialForm(isin);return;}
    if(action==='article'){companyArticleForm(isin);return;}
    if(action==='review'){await companyReviewForm(isin);return;}
    if(action==='import'){companyImportForm();return;}
    if(action==='saved-review'){companyShowReview(await api('company/reviews/'+encodeURIComponent(button.dataset.id)));return;}
    if(action==='export-review'){
      const url=URL.createObjectURL(new Blob([JSON.stringify(companySelectedReview,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download=`company-review-${companySelectedReview.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
    if(action==='scan'){
      const screen=$('#company-screen').value, config={...screenPreset(screen),candidate_rank:'fundamental_score',max_positions:5}, universe=state.settings.universe;
      $('#company-scan-status').textContent='Scanning completed daily history…';
      const result=await api('company/scan','POST',config);
      if(state.settings.universe!==universe)return;
      companyScan=result;companyFilters.candidates=true;if(currentView==='company')render();
    }
  }catch(e){toast(e.message);if(action==='scan'&&$('#company-scan-status'))$('#company-scan-status').textContent=e.message;}
  finally{button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['company-financial-form','company-article-form','company-review-form','company-import-form','company-auto-form'].includes(form.id)&&!form.id.startsWith('company-buy-screen-form-'))return;
  event.preventDefault();const button=form.querySelector('[type="submit"]'), error=form.querySelector('.form-error');button.disabled=true;error.textContent='';
  const values=Object.fromEntries(new FormData(form)), isin=form.dataset.isin;
  try{
    if(form.id.startsWith('company-buy-screen-form-')){await api('company/buy-screen/'+form.dataset.strategy,'PUT',{min_score:Number(values.min_score),min_coverage_pct:Number(values.min_coverage_pct),max_age_days:Number(values.max_age_days)});await loadCompany();toast('Fundamental buy screen saved.');return;}
    if(form.id==='company-auto-form'){
      const job=await api('company/research','POST',{isin,thesis:values.thesis,disposition:values.disposition,technical_config:companyScan?.config||null});
      companyPendingJob=job.id;$('#modal').close();await refresh(false);render();toast('Web research started. Sources will be found automatically; follow progress in Jobs & logs.');return;
    }
    let result=null;
    if(form.id==='company-financial-form'){
      const data={isin,company_type:values.company_type,basis:values.basis,period_end:values.period_end,notes:values.notes,
        source:{title:values.source_title,url:values.source_url,published_at:values.published_at}};
      for(const k of Object.keys(companyMetricLabels))if(values[k]!==undefined)data[k]=values[k]===''?null:Number(values[k]);
      for(const k of ['auditor_concern','governance_concern'])data[k]=values[k]===''?null:values[k]==='true';
      await api('company/evidence','POST',{fundamentals:[data]});
    }
    if(form.id==='company-article-form')await api('company/evidence','POST',{articles:[{isin,...values}]});
    if(form.id==='company-import-form')await api('company/evidence','POST',JSON.parse(values.payload));
    if(form.id==='company-review-form')result=await api('company/reviews','POST',{isin,thesis:values.thesis,disposition:values.disposition,use_llm:form.elements.use_llm.checked});
    await loadCompany();if(result)companyShowReview(result);else $('#modal').close();toast(result?'Prospective review saved.':'Source-backed evidence saved.');
  }catch(e){error.textContent=e.message;}
  finally{button.disabled=false;}
});
setInterval(async()=>{
  if(typeof state==='undefined'||!state)return;
  const completed=state.market_fetch?.completed_at;
  if(completed&&completed!==companyLastCompletedMarketFetch){
    companyLastCompletedMarketFetch=completed;companyState=null;
    if(currentView==='company')await loadCompany();
  }
  if(!companyPendingJob)return;
  const job=state.jobs.find(j=>j.id===companyPendingJob);
  if(!job||!['success','failed'].includes(job.status))return;
  companyPendingJob=null;
  const fundamentalsJob=job.type==='Quarterly fundamentals pull';
  if(job.status==='success'||fundamentalsJob){
    await loadCompany();
    if(currentView==='company'&&!$('#modal').open&&job.result?.review_id){
      try{companyShowReview(await api('company/reviews/'+encodeURIComponent(job.result.review_id)));}catch(e){toast(e.message);}
    }
  }
  if(job.status!=='success')toast(fundamentalsJob?'Fundamentals checked with some failures. Saved evidence is refreshed; inspect Jobs & logs.':'Company web research failed. See Jobs & logs for the reason.');
},3000);
document.addEventListener('input',event=>{
  if(!['company-search','company-minimum','company-complete','company-candidates'].includes(event.target.id))return;
  companyFilters={query:$('#company-search').value,minimum:Number($('#company-minimum').value)||0,complete:$('#company-complete').checked,candidates:$('#company-candidates').checked};
  $('#company-table').innerHTML=companyTable();
});
document.addEventListener('change',async event=>{
  if(event.target.name==='company_type'&&event.target.closest('#company-financial-form'))$('#company-metrics').innerHTML=companyFinancialFields(event.target.value);
  if(event.target.id==='company-json-file'){
    const file=event.target.files[0];if(!file)return;
    if(file.size>3000000){toast('Choose an evidence JSON file below 3 MB.');return;}
    try{event.target.form.elements.payload.value=await file.text();}catch{toast('The evidence file could not be read.');}
  }
});
