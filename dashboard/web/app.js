'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Keep persisted experiment identities intact while using current product terminology.
const uiCopy = value => String(value??'').replace(/Independent fixed-window proxies, not [^:]*detector parity:/gi,'Fixed-window rules:').replace(/Screens use independent research approximations inspired by [^;]*; detector parity is unverified and historical /gi,'Historical ').replace(/banana(?:[ _-]patterns)?(?:[ _-]proxy(?:_v1)?)?/gi,'Technical').replace(/\bscreens\b/gi,'strategies').replace(/\bscreen\b/gi,'strategy');
function cleanWorkspaceCopy(root){
  if(!root||!document.createTreeWalker)return;
  const walk=document.createTreeWalker(root,4);
  while(walk.nextNode()){
    const node=walk.currentNode;
    if(['SCRIPT','STYLE','TEXTAREA'].includes(node.parentElement?.tagName))continue;
    const value=uiCopy(node.nodeValue);if(value!==node.nodeValue)node.nodeValue=value;
  }
  root.querySelectorAll('[title],[aria-label],[placeholder]').forEach(node=>{
    for(const key of ['title','aria-label','placeholder'])if(node.hasAttribute(key)){
      const value=uiCopy(node.getAttribute(key));if(value!==node.getAttribute(key))node.setAttribute(key,value);
    }
  });
}
const money = n => n == null ? '—' : '₹' + Number(n).toLocaleString('en-IN',{maximumFractionDigits:2});
const number = (n, digits=2) => n == null ? '—' : Number(n).toLocaleString('en-IN',{maximumFractionDigits:digits});
const pct = n => n == null ? '—' : `${n>0?'+':''}${number(n)}%`;
const when = s => s ? new Date(s).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})+' IST' : 'Not yet';
const universeName = () => 'Nifty Total Market (750)';
let state, chart, observer, selectedRun, toastTimer, polling = false;
let tradeSort = {key:'exit_date', direction:'desc'};
let currentView = 'overview';
let selectedPaperStrategy = 'swing_patterns';
let selectedPaperScenario = null;
const paperPortfolio = () => selectedPaperStrategy==='scalping' ? state.scalping_paper??state.paper_portfolios?.scalping??null : selectedPaperStrategy==='swing_patterns'&&selectedPaperScenario ? (state.paper_scenarios||[]).find(p=>p.id===selectedPaperScenario)||null : state.paper_portfolios?.[selectedPaperStrategy] ?? (selectedPaperStrategy==='swing_patterns'?state.paper_portfolio:null);
const paperSchema = () => state.paper_schemas?.[selectedPaperStrategy] ?? (selectedPaperStrategy==='swing_patterns'?state.paper_schema:null);
const paperPath = action => `strategies/${encodeURIComponent(selectedPaperStrategy)}/paper/${action}${selectedPaperStrategy==='swing_patterns'&&selectedPaperScenario?'?portfolio_id='+encodeURIComponent(selectedPaperScenario):''}`;
const nav = [['overview','Home','⌂'],['data','Market data','⌁'],['backtests','Backtest','↗'],['paper','Paper trade','◎'],['live','Live trade','●'],['settings','Settings','⚙'],['jobs','Jobs & logs','≡'],['company','Fundamental','◇'],['news','News','◷']];
const workspaceViews = ['overview','data','company','investor','backtests','momentum','scalping','paper','live','jobs','settings','news'];

async function api(path, method='GET', body) {
  const response = await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Trader-Request':'local-ui'},...(body === undefined ? {} : {body:JSON.stringify(body)})});
  if(!response.ok) {
    let data; try {data=await response.json();} catch {throw new Error('The server could not complete this request.');}
    const message=Array.isArray(data.detail) ? data.detail.map(x=>`${x.loc?.slice(1).join('.')}: ${x.msg}`).join('; ') : data.detail;
    throw new Error(message || 'Request failed.');
  }
  return response.json();
}
function toast(message){$('#toast').textContent=uiCopy(message);$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),5500);}
function badge(status){return `<span class="badge ${esc(status)}">${esc(status==='warning'?'Completed with warnings':status)}</span>`;}
function priceGapWarnings(quality){return (quality?.warnings||[]).map(message=>`<div class="notice warn" role="status">${esc(message)}</div>`).join('');}
function disposeChart(){observer?.disconnect();observer=null;if(chart){klinecharts.dispose('stock-chart');chart=null;}}
function modal(title, body){disposeChart();delete $('#modal-content').dataset.paperDetails;$('#modal-content').innerHTML=`<div class="dialog-head"><h2>${esc(title)}</h2><button class="icon-button" data-action="close" aria-label="Close dialog">×</button></div><div class="dialog-body">${body}</div>`;cleanWorkspaceCopy($('#modal-content'));if(!$('#modal').open)$('#modal').showModal();}
function empty(title, copy, action='', label='Get started', symbol='⌁'){return `<div class="empty"><div class="empty-symbol">${symbol}</div><h3>${esc(title)}</h3><p>${esc(copy)}</p>${action?`<a class="button primary" href="#${action}">${esc(label)} <span>↗</span></a>`:''}</div>`;}
function heading(title, subtitle, actions='', context){return `<div class="page-heading"><div><div class="eyebrow">${esc(context||'RESEARCH WORKSPACE / '+universeName().toUpperCase())}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></div>`;}
function stat(label,value,hint,positive=false){return `<div class="stat"><div class="label">${esc(label)}<span>↗</span></div><div class="value ${positive?'positive':''}">${esc(value)}</div><div class="hint">${esc(hint)}</div></div>`;}
function activeJob(){return state.jobs.find(j=>['running','queued'].includes(j.status));}
function pending(){const job=activeJob();return job?`<div class="pending" role="status"><i></i>${esc(job.type)} · ${esc(job.status)} <a href="#jobs" class="text-button">View progress →</a></div>`:'';}
function jobRows(jobs){return jobs.map(j=>`<div class="job-card"><div><strong>${esc(j.type)}</strong><small>${when(j.created_at)} · ${esc(j.id)}</small></div><div class="actions">${badge(j.status)}<button class="text-button" data-action="logs" data-id="${esc(j.id)}">View logs ↗</button></div></div>`).join('');}
function overview(){
  const loaded=state.instruments.filter(x=>x.count), count=state.instruments.reduce((sum,x)=>sum+x.count,0), latest=state.runs[0];
  return heading('Home','Your rules, your research, your trading workspace.',`<a class="button" href="#data">⌁ &nbsp; Manage data</a><button class="button primary" data-action="new-backtest">＋ New backtest</button>`)+pending()+
  `<div class="stats">${stat('Universe',universeName(),`${state.instruments.length || 'No'} constituents loaded`)}${stat('Historical coverage',`${loaded.length} / ${state.instruments.length || '—'}`,`${number(count,0)} daily candles`,true)}${stat('Backtest runs',state.runs.length,latest?'Latest: '+latest.config.name:'Your first experiment starts here')}${stat('Execution mode',state.paper_portfolio?'Paper':'Research',state.paper_portfolio?`${Object.keys(state.paper_portfolio.ledger.positions||{}).length} simulated positions · no live orders`:(state.paper_enabled?'Create a portfolio in Paper trading':'Paper trading runs in production'))}</div>
  <div class="grid-main"><section class="panel"><div class="panel-head"><div><h2>Your research, at a glance</h2><p>Every result starts with a traceable dataset.</p></div><span class="badge">End of day</span></div>${latest?`<div class="panel-body"><span class="intro-label">LATEST EXPERIMENT · ${esc(latest.config.name)}</span><div class="stats">${stat('Net return',pct(latest.metrics.return_pct),'After modeled costs',latest.metrics.return_pct>0)}${stat('Trades',latest.metrics.trade_count,'Winners and losers included')}</div><button class="button" data-action="result" data-id="${latest.id}">Open complete report ↗</button></div>`:empty('A clean slate. Real data first.','Connect Upstox, fetch your universe, and test an idea. Results will appear here when your first backtest finishes.','settings','Connect your data','↗')}</section>
  <section class="panel"><div class="panel-head"><div><h2>Build your first experiment</h2><p>Three steps from data to a trade ledger.</p></div></div><div class="onboarding">
  ${step(1,'Connect Upstox','Save your access token on the server.',state.token_saved,'settings','Connection settings')}
  ${step(2,'Load market history',`Fetch daily and five-minute history for all 750 stocks; older candles are retained.`,loaded.length>0,'data','Open market data')}
  ${step(3,'Put your rules to the test','Choose entries, exits and costs. Keep every result.',state.runs.length>0,'backtests','Open backtests')}
  </div></section></div>
  <div class="method-strip"><div class="method-art">↗</div><div><div class="eyebrow">THE METHOD, BEFORE THE METRICS</div><h3>Wait for the base. Test the breakout. Define the risk.</h3><p>Signals at the close. Entries at the next open. Losses, costs and drawdowns are part of the record.</p></div><button class="text-button" data-action="method">How it works ↗</button></div>
  <section class="panel"><div class="panel-head"><h2>Recent activity</h2><a class="text-button" href="#jobs">All jobs →</a></div>${state.jobs.length?jobRows(state.jobs.slice(0,3)):empty('No jobs yet','Data fetches and backtests will leave a status and an inspectable log here.','','','≡')}</section>`;
}
function step(n,title,copy,done,target,label){return `<div class="step ${done?'done':''}"><span class="step-no">${done?'✓':n}</span><div><h3>${title}</h3><p>${copy}</p><a class="text-button" href="#${target}">${label} →</a></div></div>`;}
function marketRefreshActions(){
  const busy=Boolean(activeJob()),hasStocks=Boolean(state.instruments.length),disabled=value=>value?'disabled':'';
  return `<div class="market-refresh-actions"><section><span class="eyebrow">01 / STOCKS</span><h2>Stocks & prices</h2><p>Refresh the stock list and daily and five-minute candles. Older history is retained.</p><div class="actions"><button class="button primary" data-action="refresh-stocks" ${disabled(busy||!state.token_saved)}>Refresh stocks</button><button class="text-button" data-action="refresh-universe" ${disabled(busy)}>Refresh stock list only</button></div></section><section><span class="eyebrow">02 / FUNDAMENTALS</span><h2>Quarterly fundamentals</h2><p>Check official filings for the loaded Total Market stocks. Prices are refreshed separately.</p><div class="actions"><button class="button primary" data-action="refresh-fundamentals" ${disabled(busy||!hasStocks)}>Refresh fundamentals</button><a class="text-button" href="#company">View fundamentals ↗</a></div></section><section><span class="eyebrow">03 / NEWS</span><h2>News & company feeds</h2><p>Refresh broad feeds and news for tracked companies, portfolio holdings and scanner candidates.</p><div class="actions"><button class="button primary" data-action="refresh-market-news" ${disabled(busy)}>Refresh news</button><a class="text-button" href="#news">Read news ↗</a></div></section></div>${!state.token_saved?'<div class="notice">Save your Upstox access token using Connection settings before refreshing stock prices.</div>':''}${!hasStocks?'<div class="notice">Refresh the stock list before requesting quarterly fundamentals.</div>':''}`;
}
function dataView(){return heading('Market data','Refresh stocks, fundamentals and news, and inspect the data behind your strategies.',`<a class="button" href="#jobs">Jobs & logs ↗</a>`)+pending()+marketRefreshActions()+
 `<div class="actions market-data-tools"><button class="button" data-action="sector-audit">Sector coverage</button><button class="button" data-action="fetch-sectors" ${!state.token_saved||activeJob()?'disabled':''}>Refresh sector data</button><button class="button" data-action="audit-data">Audit price history</button></div>`+
 `<div class="notice">Every fetch covers <strong>Nifty Total Market (750 stocks)</strong>: daily candles for the last calendar year and five-minute candles for the last 10 calendar days, ending on the latest completed trading day available from Upstox. Older candles are retained. Research uses the saved Nifty Total Market universe.</div>
 ${state.sector_fetch?`<div class="notice">Sector mapping: ${state.sector_fetch.mapped}/${state.sector_fetch.total} stocks mapped. Index fetch through ${esc(state.sector_fetch.end)}; ${state.sector_fetch.failures.length} failed ranges. <button class="text-button" data-action="sector-audit">Inspect sector coverage ↗</button></div>`:''}
 ${state.market_fetch?`<div class="notice">Latest fetch: <strong>${esc(state.market_fetch.daily_start)} → ${esc(state.market_fetch.end)}</strong> daily; <strong>${esc(state.market_fetch.minute_start)} → ${esc(state.market_fetch.end)}</strong> five-minute. Daily: ${state.market_fetch.daily_symbols}/${state.market_fetch.total_symbols} stocks; five-minute: ${state.market_fetch.minute_symbols}/${state.market_fetch.total_symbols}. ${state.market_fetch.failures.length} download failures. ${state.market_fetch.completed_at?'Completed '+when(state.market_fetch.completed_at):'In progress'} · <a href="#jobs">Inspect progress and failures</a>.</div>`:''}
 ${state.market_fetch?.fundamentals&&state.market_fetch.fundamentals.status!=='not_requested'?`<div class="notice">Fundamentals: ${state.market_fetch.fundamentals.coverage?`<strong>${state.market_fetch.fundamentals.coverage.validated_symbols}/${state.market_fetch.total_symbols}</strong> stocks with validated snapshots`:'Quarterly check completed'} · ${state.market_fetch.fundamentals.counts?.updated||0} updated · ${state.market_fetch.fundamentals.counts?.failed||0} failed · ${state.market_fetch.fundamentals.counts?.unsupported||0} unsupported. <a href="#company">Inspect financial evidence and historical coverage</a>.</div>`:''}
 ${priceGapWarnings(state.market_fetch?.data_quality)}
 <div class="notice warn">This is today's constituent list. Historical membership, delisted stocks and corporate-action adjustments are not yet verified. Coverage is reported honestly; exploratory results do not establish an edge.</div>
 <div class="toolbar"><label class="search"><span class="sr-only">Search instruments</span><input id="instrument-search" placeholder="Search by symbol, company or sector…" autocomplete="off"></label><span class="status-line">${state.instruments.length} instruments · Upstox daily OHLCV</span></div>
 <section class="panel"><div id="instrument-table">${instrumentTable('')}</div></section>`;}
function instrumentTable(query){const rows=state.instruments.filter(x=>`${x.symbol} ${x.name} ${x.sector}`.toLowerCase().includes(query.toLowerCase()));
  if(!state.instruments.length)return empty('Load your investable universe','Refresh the universe to download the official constituents and match their Upstox instrument keys.');
  if(!rows.length)return empty('No matching instruments','Try a symbol, company name or another sector.');
  return `<div class="table-wrap"><table><thead><tr><th>COMPANY / SYMBOL</th><th>SECTOR</th><th class="right">LAST CLOSE</th><th class="right">CHANGE</th><th class="right">BARS</th><th>HISTORY AVAILABLE</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td><button class="symbol-button" data-action="chart" data-isin="${esc(x.isin)}" ${x.count?'':'disabled'}>${esc(x.symbol)}</button><small>${esc(x.name)}</small></td><td>${esc(x.sector)}</td><td class="right">${money(x.close)}</td><td class="right ${x.change>=0?'positive':'negative'}">${pct(x.change)}</td><td class="right">${number(x.count,0)}</td><td>${x.first?`${x.first}<small>through ${x.last}</small>`:'Awaiting data'}</td><td><button class="text-button" data-action="chart" data-isin="${esc(x.isin)}" ${x.count?'':'disabled'}>Chart ↗</button></td></tr>`).join('')}</tbody></table></div>`;}

function referenceAuditPanel(r){
  const rows=r.candidate_audit||[];if(!rows.length)return '';
  const counts=r.audit_summary||rows.reduce((out,a)=>(out[a.reason]=(out[a.reason]||0)+1,out),{});
  return `<section class="panel"><div class="panel-head"><h2>Opportunity audit</h2>${r.candidate_audit_reference?`<button class="text-button" data-action="paper-opportunities-export" data-cycle="${esc(r.job_id)}">Export complete opportunity audit ↓</button>`:""}</div><div class="panel-body"><p>Breakouts are recorded before account limits. A technical opportunity is separate from an executed trade. Financial checks are evaluated only when an entry reaches that gate.</p><p>${Object.entries(counts).map(([reason,count])=>`${esc(reason)}: ${number(count,0)}`).join(' · ')}</p><details><summary>View latest ${Math.min(rows.length,100)} opportunities</summary><div class="table-wrap"><table><thead><tr><th>Date</th><th>Stock</th><th>Decision date</th><th>Pivot</th><th>RS / population</th><th>Median turnover</th><th>Cash before</th><th>Positions before</th><th>Quantity</th><th>Decision</th><th>Sizing constraint</th></tr></thead><tbody>${rows.slice(-100).reverse().map(a=>`<tr><td>${esc(a.date)}</td><td>${esc(a.symbol)}</td><td>${esc(a.decision_date)}</td><td>${money(a.pivot)}</td><td>${number(a.rs)} / ${number(a.rs_population,0)}</td><td>${money(a.median_turnover)}</td><td>${a.cash_before==null?'—':money(a.cash_before)}</td><td>${a.positions_before??'—'}</td><td>${a.quantity}</td><td>${esc(a.reason)}</td><td>${esc(a.sizing_constraint||'—')}</td></tr>`).join('')}</tbody></table></div></details><p>The full research trace is retained with the run; full paper traces are retained per cycle. Older cycles have no retrospective audit.</p></div></section>`;
}
function referenceAuditPanel(r){
  const rows=r.candidate_audit||[];if(!rows.length)return '';
  const counts=r.audit_summary||rows.reduce((out,a)=>(out[a.reason]=(out[a.reason]||0)+1,out),{});
  return `<section class="panel"><div class="panel-head"><h2>Opportunity audit</h2>${r.candidate_audit_reference?`<button class="text-button" data-action="paper-opportunities-export" data-cycle="${esc(r.job_id)}">Export complete opportunity audit ↓</button>`:""}</div><div class="panel-body"><p>Breakouts are recorded before account limits. A technical opportunity is separate from an executed trade. Financial checks are evaluated only when an entry reaches that gate.</p><p>${Object.entries(counts).map(([reason,count])=>`${esc(reason)}: ${number(count,0)}`).join(' · ')}</p><details><summary>View latest ${Math.min(rows.length,100)} opportunities</summary><div class="table-wrap"><table><thead><tr><th>Date</th><th>Stock</th><th>Decision date</th><th>Pivot</th><th>RS / population</th><th>Median turnover</th><th>Cash before</th><th>Positions before</th><th>Quantity</th><th>Decision</th><th>Sizing constraint</th></tr></thead><tbody>${rows.slice(-100).reverse().map(a=>`<tr><td>${esc(a.date)}</td><td>${esc(a.symbol)}</td><td>${esc(a.decision_date)}</td><td>${money(a.pivot)}</td><td>${number(a.rs)} / ${number(a.rs_population,0)}</td><td>${money(a.median_turnover)}</td><td>${a.cash_before==null?'—':money(a.cash_before)}</td><td>${a.positions_before??'—'}</td><td>${a.quantity}</td><td>${esc(a.reason)}</td><td>${esc(a.sizing_constraint||'—')}</td></tr>`).join('')}</tbody></table></div></details><p>The full research trace is retained with the run; full paper traces are retained per cycle. Older cycles have no retrospective audit.</p></div></section>`;
}
function sectorReport(r){
  if(r.config?.skip_weak_markets&&r.config.market_breadth_scope==='sector'){
    const checks=(r.sector_checks||[]).filter(c=>c.mapping_method==='frozen_current_sector_label');
    return `<h3>Sector breadth decisions</h3><p>At least ${number(r.config.market_breadth_pct)}% of eligible sector peers above SMA200, with ${number(r.config.market_min_coverage_pct)}% history coverage. ${checks.length} signals checked; ${checks.filter(c=>!c.allowed).length} blocked. Current sector labels and small groups remain limitations.</p><details><summary>View all sector breadth decisions</summary><div class="table-wrap"><table><thead><tr><th>Stock</th><th>Signal session</th><th>Sector</th><th>Breadth</th><th>Coverage</th><th>Eligible peers</th><th>Decision</th></tr></thead><tbody>${checks.map(c=>`<tr><td>${esc(c.symbol)}</td><td>${esc(c.day)}</td><td>${esc(c.sector||'Unmapped')}</td><td>${number(c.breadth_pct)}%</td><td>${number(c.coverage_pct)}%</td><td>${c.eligible_peers} / ${c.sector_size}</td><td>${esc(c.reason)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  if(!r.sector_reference)return referenceAuditPanel(r);
  const checks=r.sector_checks||[];
  return `<h3>Sector decisions</h3><p>${esc(r.sector_reference.notice)} ${checks.length} candidate signals checked; ${checks.filter(x=>!x.allowed&&x.enforced!==false).length} blocked; ${checks.filter(x=>!x.allowed&&x.enforced===false).length} observed failures.</p><details><summary>View all sector entry decisions</summary><div class="table-wrap"><table><thead><tr><th>Stock</th><th>Signal session</th><th>Sector</th><th>Close / SMA50</th><th>Relative strength</th><th>Decision</th></tr></thead><tbody>${checks.map(c=>`<tr><td>${esc(c.symbol)}</td><td>${esc(c.date)}</td><td>${esc(c.index||'Unmapped')}</td><td>${number(c.close)} / ${number(c.sma50)}</td><td>${c.relative_strength_pp==null?'—':number(c.relative_strength_pp)+' pp'}</td><td>${esc(c.reason)}</td></tr>`).join('')}</tbody></table></div></details>`;
}
async function showSectorAudit(){
  const d=await api('sectors');
  modal('Sector coverage',`<p>${esc(d.notice)}</p><p>Mapping captured: ${esc(d.mapping_captured_at||'Not fetched')} · Latest benchmark session: ${esc(d.as_of||'Unavailable')}</p>${d.fetch?.partial?'<div class="notice warn">The last fetch had failures. Inspect Jobs & logs; retained history may be stale.</div>':''}<div class="table-wrap"><table><thead><tr><th>Index</th><th>Bars</th><th>History</th></tr></thead><tbody>${d.indices.map(x=>`<tr><td>${esc(x.id)}</td><td>${x.bars}</td><td>${esc(x.first||'—')} → ${esc(x.last||'—')}</td></tr>`).join('')}</tbody></table></div><h3>Stock mappings</h3><div class="table-wrap"><table><thead><tr><th>Stock</th><th>Industry</th><th>Index</th><th>Mapping method</th><th>Current decision</th></tr></thead><tbody>${d.mappings.map(m=>`<tr><td>${esc(m.symbol)}</td><td>${esc(m.industry)}</td><td>${esc(m.index||'Unmapped')}</td><td>${esc(m.method)}</td><td>${esc(d.decisions.find(c=>c.symbol===m.symbol)?.reason||'History unavailable')}</td></tr>`).join('')}</tbody></table></div><p>Missing mappings: ${esc(d.missing_symbols.join(', ')||'None')}</p>`);
}
function referenceScreenDetails(screen,showAction=true){
  if(!screen?.source_filters)return '';
  return `<section class="panel"><div class="panel-head"><h2>${esc(screen.name)}</h2><span class="badge">Fixed-rule screen</span></div><div class="panel-body"><p>Saved qualification thresholds and execution settings are recorded with each experiment.</p><div class="detail-grid">${Object.entries(screen.source_filters).filter(([key])=>!['url','observed_on'].includes(key)).map(([key,value])=>`<div><span>${esc(key.replaceAll('_',' '))}</span>${esc(value)}</div>`).join('')}</div>${showAction?`<button class="button" data-action="new-backtest" data-screen="${esc(screen.id)}">Configure backtest ↗</button>`:''}</div></section>`;
}
function strategyOptions(paper=false){
  if(state.reference_only)return (state.screens||[]).filter(p=>!paper||p.paper_defaults).map(p=>[p.id,p.name]);
  const options=[['builtin:vcp','VCP'],['builtin:blue_sky','Blue sky'],['builtin:multiyear','Multi-year breakouts'],['builtin:ipo','IPO base'],...(state.screens||[]).filter(p=>!paper||!p.backtest_defaults||p.paper_defaults).map(p=>[p.id,p.name])];
  if(!paper)options.push(...(state.bearish_screens||[]).map(([id,label])=>['bearish:'+id,label]),['intraday_momentum','Intraday momentum']);
  if(!paper&&state.backtest_schema?.$defs?.Rules)options.push(['investor_early_breakout','Early breakout']);
  options.push(['scalping','Scalping']);
  return options.filter(([id])=>!(state.retired_strategy_choices||[]).includes(id));
}
function strategyPicker(value='builtin:vcp',id='backtest-strategy-picker',paper=false){
  if(value==='swing_patterns')value='builtin:vcp';
  if(state.reference_only&&!strategyOptions(paper).some(([key])=>key===value))value=strategyOptions(paper)[0]?.[0]||'';
  return `<label class="field"><span>Strategy</span><select name="${id==='screen-picker'?'screen':'strategy'}" id="${esc(id)}">${(strategyOptions(paper).some(([id])=>id===value)?strategyOptions(paper):[[value,'Historical strategy'],...strategyOptions(paper)]).map(([key,label])=>`<option value="${esc(key)}" ${key===value?'selected':''} ${paper&&key!=='scalping'&&!state.paper_enabled?'disabled':''}>${esc(uiCopy(label))}</option>`).join('')}</select></label>`;
}
function researchTabs(){return '';}
function chooseBacktestStrategy(){modal('Start backtest',`<div class="form-section">${strategyPicker('builtin:vcp','launcher-strategy-picker')}<p style="margin-top:16px">Choose a strategy, then review its dates, capital, risk and execution settings.</p></div><div class="form-actions"><button class="button primary" data-action="launch-backtest">Configure backtest ↗</button></div>`);}
function backtestsView(){return heading('Backtest','Select a strategy, configure an experiment, and inspect the results.',`<a class="text-button" href="#data">Market data ↗</a>${state.reference_only?'':'<button class="button" data-action="new-screen">＋ New strategy</button>'}<button class="button primary" data-action="choose-backtest">＋ New backtest</button>`)+pending()+
 `${state.runs.length?`<div class="run-list">${state.runs.map(r=>`<button type="button" class="panel run-card" data-action="result" data-id="${esc(r.id)}" aria-label="Open backtest: ${esc(r.config.name)}"><span class="run-description"><strong class="run-title">${esc(r.config.name)} ↗</strong><span class="run-subtitle">${esc(r.universe)} · ${r.config.start} — ${r.config.end} · ${when(r.created_at)}</span><span class="badge warn">Exploratory · current constituents</span></span><span class="run-metrics"><span><small>NET RETURN</small><strong class="${r.metrics.return_pct>=0?'positive':'negative'}">${pct(r.metrics.return_pct)}</strong></span><span><small>MAX DRAWDOWN</small>${number(r.metrics.max_drawdown_pct)}%</span><span><small>TRADES</small>${r.metrics.trade_count}</span></span></button>`).join('')}</div>`:`<section class="panel">${empty('Your first backtest belongs here.','Once daily candles are available, run a reproducible experiment with your entry and exit rules. Every result keeps its own data and parameter snapshot.','data','Prepare market data','↗')}</section>`}`;}

function paperForm(screenId){
  if(selectedPaperStrategy==='scalping')return scalpingPaperForm();
  if(!paperSchema())throw new Error('Restart the local server or select an implemented paper strategy.');
  const p=paperPortfolio(), schema=paperSchema(), seed={candidate_rank:'fundamental_score',max_positions:5,execution_time:'midday',run_hour:12,run_minute:30,...p?.config,...(screenId?screenPreset(screenId,true):{}),acknowledge_limitations:false};
  const swing=selectedPaperStrategy==='swing_patterns';
  if(p)seed.capital=p.config.capital;
  const screenValue=screenId||p?.config.screen_id||(p?`builtin:${p.config.pattern}`:'builtin:vcp');
  const reference=seed.simulation_model==='banana_proxy_v1';
  const visibleReference=['name','capital','risk_pct','stop_pct','max_positions','reference_same_day','reference_cap_pct','reference_turnover_pct','fundamental_mode','slippage_bps','buy_cost_bps','sell_cost_bps','auto_run','run_hour','run_minute','acknowledge_limitations'];
  const keys=Object.keys(schema.properties).filter(k=>(!swing||!['pattern','screen_id'].includes(k))&&(!reference||visibleReference.includes(k)));
  const fixed=reference?Object.keys(schema.properties).filter(k=>!keys.includes(k)&&!['pattern','screen_id'].includes(k)).map(k=>`<input type="hidden" name="${k}" value="${esc(seed[k]??schema.properties[k].default??'')}">`).join(''):'';
  modal(p?'Configure paper portfolio':'Create paper scenario',`<div class="notice">Each scenario has separate capital, positions and history. Midday mode uses completed-session signals and fresh bid/ask quotes; stops and exits are checked at cycle time, without continuous monitoring. Next-open mode reconstructs daily fills after the close. Capital and universe remain fixed after creation.</div><form id="paper-form">${fixed}${swing?`<input type="hidden" name="pattern" value="${esc(seed.pattern||'vcp')}">`:""}<div class="form-section"><div class="fields">${swing?field('screen',schema,screenValue):''}${keys.map(k=>field(k,schema,seed[k])).join('')}</div></div><div class="notice">${reference?'Reference strategy: entries reconstructed from daily bars, equal fees per side plus modeled slippage, SMA50 next-open exits. Fundamentals are required unless you explicitly select observation; news does not block entries or force exits. Rules freeze per scenario.':'Use all-in charges that include your brokerage, taxes and exchange fees.'} Automatic cycles require the server to remain running. Midday execution records the actual quote time; missed sessions are never backfilled as trades.</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">${p?'Save configuration':'Create paper scenario'}</button></div></form>`);
  if(p)$('#paper-form').elements.capital.readOnly=true;
  if(swing&&screenId)applyScreenPreset($('#paper-form'),screenId);
  else if(!p&&swing&&!screenId)applyScreenPreset($('#paper-form'),'builtin:vcp');
}
function paperStrategyPicker(inForm=false){return `<label class="field"><span>Strategy</span><select id="${inForm?'paper-form-strategy-picker':'paper-strategy-picker'}">${(state.strategies||[]).map(s=>`<option value="${esc(s.id)}" ${s.id===selectedPaperStrategy?'selected':''} ${(s.id==='scalping'&&state.scalping_paper_schema)||(state.paper_enabled&&(state.paper_schemas?.[s.id]||(s.id==='swing_patterns'&&state.paper_schema)))?'':'disabled'}>${esc(s.name)}${s.id==='intraday_momentum'?' · paper execution pending':s.id==='swing_patterns'&&!state.paper_enabled?' · production only':''}</option>`).join('')}</select></label>`;}
function paperPortfolioCards(){
  const swing=[...new Map([...(state.paper_scenarios||[]),...(state.paper_portfolios?.swing_patterns?[state.paper_portfolios.swing_patterns]:[])].map(p=>[p.id,p])).values()];
  const portfolios=[...swing,...(state.scalping_paper?[state.scalping_paper]:[])];
  if(!portfolios.length)return empty('No paper portfolios yet','Create a portfolio to start tracking a strategy with simulated capital.');
  return `<div class="paper-tiles">${portfolios.map(p=>{const config=p.config,l=p.ledger||{},strategy=p.strategy_name||'scalping',equity=p.metrics?.final_equity??config.capital,pnl=equity-config.capital,positions=Object.keys(l.positions||{}).length,trades=l.full_trade_count??l.trades?.length??0;return `<button class="paper-tile" data-action="open-paper-portfolio" data-strategy="${esc(strategy)}" data-id="${esc(p.id)}"><span class="tile-title"><strong>${esc(uiCopy(config.name))}</strong><span>${esc(uiCopy((state.screens||[]).find(s=>s.id===config.screen_id)?.name||({vcp:'VCP',blue_sky:'Blue sky',multiyear:'Multi-year',ipo:'IPO base'})[config.pattern]||'Scalping'))} · ${esc(({niftytotalmarket:'Nifty Total Market',nifty500:'Nifty 500',nifty50:'Nifty 50'})[p.universe]||p.universe||universeName())}</span></span><span class="tile-value"><small>Equity / capital</small><strong>${money(equity)}</strong><span>${money(config.capital)} allocated</span></span><span class="tile-value ${pnl>=0?'positive':'negative'}"><small>Net P&L</small><strong>${money(pnl)}</strong><span>${pct(pnl/config.capital*100)}</span></span><span class="tile-value"><small>Cash / exposure</small><strong>${money(l.cash??config.capital)}</strong><span>${positions} open · ${trades} closed trades</span></span><span class="tile-value"><small>Risk / schedule</small><strong>${number(config.risk_pct)}% risk · ${config.max_positions??'—'} positions</strong><span>${config.auto_run?`${String(config.run_hour??9).padStart(2,'0')}:${String(config.run_minute??15).padStart(2,'0')} IST`:'Manual'} · ${number(config.stop_pct)}% stop</span></span><span class="tile-status">${badge(p.status)}<small>${l.last_session?'Processed '+esc(l.last_session):'Awaiting first session'}</small><span>View trades ↗</span></span></button>`;}).join('')}</div>`;
}
function paperView(){return heading('Paper trade','Independent strategies, settings and trade records.',`<button class="button primary" data-action="choose-paper">＋ New paper portfolio</button>`)+pending()+paperPortfolioCards();}
function settingsTable(config,schema={}){
  const rows=[];
  function add(values,properties,prefix=''){
    for(const [key,value] of Object.entries(values||{})){
      const title=uiCopy(properties?.[key]?.title||key.replaceAll('_',' '));
      const label=prefix?prefix+' / '+title:title;
      if(value&&typeof value==='object'&&!Array.isArray(value)){add(value,{},label);continue;}
      const text=value==null?'Not set':typeof value==='boolean'?(value?'Yes':'No'):Array.isArray(value)?JSON.stringify(value):key==='simulation_model'?(value==='legacy'?'Configurable rules':'Fixed rules'):String(value);
      rows.push(`<tr><th scope="row">${esc(label)}</th><td>${esc(uiCopy(text))}</td></tr>`);
    }
  }
  add(config,schema?.properties);
  return `<div class="table-wrap settings-table"><table><tbody>${rows.join('')||'<tr><td>No settings were recorded.</td></tr>'}</tbody></table></div>`;
}
function detailTabs(kind,label,content,settings){return `<div class="detail-view"><div class="detail-tabs" role="tablist" aria-label="${kind==='paper'?'Paper portfolio':'Backtest'} details"><button type="button" role="tab" id="${kind}-main-tab" aria-selected="true" aria-controls="${kind}-main" tabindex="0" data-action="detail-tab">${label}</button><button type="button" role="tab" id="${kind}-settings-tab" aria-selected="false" aria-controls="${kind}-settings" tabindex="-1" data-action="detail-tab">Settings</button></div><section role="tabpanel" id="${kind}-main" aria-labelledby="${kind}-main-tab">${content}</section><section role="tabpanel" id="${kind}-settings" aria-labelledby="${kind}-settings-tab" hidden>${settings}</section></div>`;}
function activateDetailTab(button){
  const root=button.closest('.detail-view'),target=button.getAttribute('aria-controls');
  if(!root)return;
  root.querySelectorAll('[role="tab"]').forEach(tab=>{const active=tab===button;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;});
  root.querySelectorAll('[role="tabpanel"]').forEach(panel=>{panel.hidden=panel.id!==target;});
}
function paperSettingsView(p){
  if(!p)return '<p>No portfolio settings recorded.</p>';
  const cycle=(p.cycles||[]).filter(c=>c.config).at(-1),session=p.stream_session?.config?p.stream_session:null;
  const execution=session||cycle,schema=selectedPaperStrategy==='scalping'?state.scalping_paper_schema:paperSchema();
  return `<h3>${execution?'Latest execution settings':'Configured portfolio settings'}</h3><p class="settings-context">${execution?`Recorded for ${esc(session?.day||cycle?.end||'the latest cycle')}${cycle?.at?' · '+when(cycle.at):''}. These settings were saved with that execution.`:'No executed cycle has been recorded yet. These are the settings saved for this portfolio.'}</p>${settingsTable(execution?.config||p.config,schema)}${execution?`<details class="paper-trade-more"><summary>Current portfolio configuration</summary><p>Configuration changes apply according to the portfolio execution rules; earlier positions retain their saved exit rules.</p>${settingsTable(p.config,schema)}</details>`:''}`;
}
function openPaperDetails(){const p=paperPortfolio();modal(p?.config.name||'Paper portfolio',detailTabs('paper','Trades',paperDetailView(),paperSettingsView(p)));$('#modal-content').dataset.paperDetails='true';}

function choosePaperStrategy(){modal('New paper portfolio',`<div class="form-section">${strategyPicker('builtin:vcp','new-paper-strategy',true)}<p style="margin-top:16px">Each portfolio keeps its own strategy, capital, settings and trades.</p></div><div class="form-actions"><button class="button primary" data-action="start-paper">Configure portfolio ↗</button></div>`);}
function paperDetailView(){
  if(selectedPaperStrategy==='scalping')return scalpingPaperView();
  const p=paperPortfolio();if(!p)return empty('Portfolio unavailable','Reload the page to refresh your portfolios.');
  const l=p.ledger||{},positions=Object.entries(l.positions||{}),config=p.config;
  return `<div class="actions paper-detail-actions"><button class="button" data-action="configure-paper" ${activeJob()?'disabled':''}>Configure portfolio</button><button class="button" data-action="paper-status" ${activeJob()?'disabled':''}>${p.status==='active'?'Pause new entries':'Resume entries'}</button><button class="button primary" data-action="paper-cycle" ${activeJob()||!state.token_saved?'disabled':''}>Run daily cycle</button><button class="text-button" data-action="paper-export">Export ledger ↓</button></div><p class="paper-detail-summary">${badge(p.status)} · ${money(config.capital)} allocated · ${number(config.risk_pct)}% risk · ${number(config.stop_pct)}% stop · ${config.max_positions} positions maximum<br>Last processed: ${esc(l.last_session||'Awaiting first session')} · Fees ${money(l.total_fees||0)} · Slippage ${money(l.total_slippage||0)} · ${config.auto_run?`${String(config.run_hour).padStart(2,'0')}:${String(config.run_minute).padStart(2,'0')} IST weekdays`:'Manual cycles'}. Simulated fills only; pausing entries keeps exits active.</p>${priceGapWarnings(p.data_quality)}${referenceAuditPanel((p.cycles||[]).filter(c=>c.candidate_audit?.length).at(-1)||{})}<h3>Closed trades · ${l.trades?.length||0}</h3>${paperTrades(l.trades||[])}<h3>Open positions · ${positions.length}</h3>${positions.length?`<div class="table-wrap"><table><thead><tr><th>Stock</th><th>Entry date</th><th>Shares</th><th>Entry</th><th>Mark</th><th>Stop</th><th>Open P&L</th></tr></thead><tbody>${positions.map(([symbol,t])=>`<tr><td>${esc(symbol)}</td><td>${esc(t.entry_date)}</td><td>${t.quantity}</td><td>${money(t.entry)}</td><td>${money(l.marks?.[symbol])}</td><td>${money(t.stop)}</td><td>${money(l.marks?.[symbol]*t.quantity-t.entry_cost)}</td></tr>`).join('')}</tbody></table></div>`:'<p>No open positions.</p>'}<details class="paper-trade-more"><summary>Simulated fills · ${l.orders?.length||0}</summary>${paperOrders(l.orders||[])}</details><details class="paper-trade-more"><summary>Equity history</summary>${l.curve?.length?equitySvg(l.curve):'<p>No completed equity observations yet.</p>'}</details>`;
}

function paperTrades(trades){return trades.length?`<div class="table-wrap"><table><thead><tr><th>SYMBOL</th><th>ENTRY</th><th>EXIT</th><th class="right">QUANTITY</th><th class="right">BUY / SELL</th><th class="right">FEES</th><th class="right">NET P&L</th><th>REASON</th></tr></thead><tbody>${[...trades].reverse().map(t=>`<tr><td>${esc(t.symbol)}</td><td>${esc(t.entry_date)}</td><td>${esc(t.exit_date)}</td><td class="right">${t.quantity}</td><td class="right">${money(t.entry)} / ${money(t.exit)}</td><td class="right">${money(t.fees)}</td><td class="right">${money(t.pnl)}</td><td>${esc(t.reason)}</td></tr>`).join('')}</tbody></table></div>`:empty('No closed trades','Both winners and losses will be recorded with execution costs.');}
function paperOrders(orders){return orders.length?`<div class="table-wrap"><table><thead><tr><th>SESSION</th><th>SYMBOL</th><th>SIDE</th><th class="right">QUANTITY</th><th class="right">FILL</th><th class="right">FEES</th><th>STATUS</th><th>JOB</th></tr></thead><tbody>${[...orders].reverse().map(o=>`<tr><td>${esc(o.date)}</td><td>${esc(o.symbol)}</td><td>${esc(o.side)}</td><td class="right">${o.quantity}</td><td class="right">${money(o.price)}</td><td class="right">${money(o.fees)}</td><td>${esc(o.status)}</td><td><button class="text-button" data-action="logs" data-id="${esc(o.job_id)}">${esc(o.job_id)}</button></td></tr>`).join('')}</tbody></table></div>`:empty('No fills yet','Every simulated buy and sell will link to its daily-cycle job.');}
function jobsView(){return heading('Nothing happens in the dark.','Every data refresh, backtest and paper cycle has a status and a readable record.',`<button class="button" data-action="reload">↻ Refresh</button>`)+pending()+`<section class="panel"><div class="panel-head"><h2>Job history</h2><span class="badge">Local worker</span></div>${state.jobs.length?jobRows(state.jobs):empty('No jobs yet','Start a universe refresh or a data fetch. Its progress and errors will appear here.','data','Open market data','≡')}</section>`;}
const fieldHelp={
  require_fundamentals:'Block both long and short entries unless verified archived filings published by entry time pass the quality screen. Missing historical evidence blocks entry.',
  fundamental_min_score:'Minimum score from the existing transparent fundamentals rules. Frozen per run; no current score substitution.',
  fundamental_min_coverage_pct:'Minimum percentage of scored evidence available in the historical filing snapshot.',
  fundamental_max_age_days:'Maximum financial period age at entry. This experiment threshold replaces the scorer’s default 180-day freshness warning; other risk flags still block entry.',
  entry_pattern:'Breakout alone, or a fixed impulse / two-candle pullback / completed resumption beyond the range. Rules are research adaptations.',
  stop_reference:'Prior ATR stop, or the known pullback extreme for flag entries. A gap leaving nonpositive fill-to-stop distance cancels the trade.',
  execution_mode:'Follow trades in the signal direction. Reverse sells buy signals and buys sell signals at the same next-bar open. Stops, targets and costs use the actual position side; direction selection still filters original signals.',
  exclude_symbols:'Optional comma-separated symbols omitted before daily stock selection. Recorded in each report; exclusions chosen after reviewing data can bias results.',
  exclude_stock_sessions:'Comma-separated SYMBOL:YYYY-MM-DD entries for unavailable regular-opening candles. Also skips candidates whose opening-volume history includes those sessions. Recorded exclusions can bias results.',
  indicator_filter:'Optional EMA9/20 trend, MACD12/26/9 directional rising histogram, or both. Uses completed candles and prior-session warmup.',
  indicator_minutes:'10-minute or hourly indicators, aligned to 09:15 IST. Separate from breakout confirmation. Corporate-action warmup crossings halt pending price-basis verification.',
  require_vwap:'Require the signal close above cumulative session VWAP for longs or below it for shorts. Uses completed five-minute typical prices and volume.',
  breakout_buffer_atr:'Move the opening-range trigger farther by this multiple of prior daily ATR. Zero keeps the original high/low trigger.',
  min_close_strength:'Position of the completed confirmation close within its full high-low range: 0.7 requires the top 30% for longs or bottom 30% for shorts. Zero disables.',
  min_confirmation_body_atr:'Directional close-minus-open movement of the entire completed confirmation candle, divided by prior daily ATR. 0.1 requires a body of at least 10% of ATR. Zero disables.',
  breakeven_after_r:'After a completed close reaches this initial R gain, tighten the next bar’s stop to estimated cost breakeven. Zero disables; gaps can still lose money.',
  opening_minutes:'Build the opening high/low and volume from the first 5, 10, 15 or 30 minutes starting 09:15 IST.',
  confirmation_minutes:'Wait for a completed 5, 10, 15, 30 or 60-minute breakout close, aligned to 09:15 IST. Fills and stops still use five-minute bars. This is close confirmation, not an hourly EMA/ADX filter.',
  volume_lookback:'Number of prior observed sessions used to average volume in the same opening interval.',
  min_relative_volume:'Opening volume divided by prior same-interval average. 1.5 means 50% above that average.',
  liquid_universe_size:'Prior-turnover ranking limits how many stocks need five-minute input each day.',
  stop_atr:'Initial stop distance as a multiple of prior arithmetic-mean daily true range.',
  target_r:'Optional target in multiples of initial price-stop risk. Zero keeps the stop and mandatory exit only.',

  strategy:'The strategy family that interprets the bars and generates signals. Swing Pattern is the active daily end-of-day strategy; other families will be added when their data and execution modules are ready.',
  screen:'Saved strategies populate signals, ranking, position limits, risk, exits and costs. Saved screens populate signal filters only. All settings remain editable before submission.',
  name:'A descriptive name stored with the run or saved screen so you can identify the assumptions later.',
  pattern:'Bullish patterns test breaks above resistance. Bearish patterns test breaks below support: VCP breakdown follows contraction and volume dry-up, 52-week low uses prior lows, Multi-year uses a long base, and IPO base breakdown requires a verified young listing.',
  require_falling_long_trend:'Require the close below the 200-session SMA and that average below its value 20 sessions earlier.',
  max_rs_rating:'Maximum percentile of the 126-session return among eligible symbols in the selected universe. Lower values select weaker stocks.',
  require_weak_market:'Allow bearish candidates only when market breadth is at or below its maximum and history coverage meets its minimum.',
  max_market_breadth_pct:'Maximum percentage of eligible symbols above their 200-session SMA. Lower breadth indicates fewer stocks in long-term uptrends.',
  low_lookback_days:'Sessions preceding the signal bar used to find the prior low. A bearish signal must close below that low.',
  execution_horizon:'Intraday closes every position on its entry date using five-minute candles. Swing allows overnight holdings; swing shorts require borrowing.',
  square_off_time:'Hard exit cutoff in IST. Intraday execution closes at the open of this five-minute candle. Must precede your broker’s auto-square-off.',
  borrow_cost_bps_year:'Annual stock-borrow cost in basis points, accrued on calendar days using the prior marked short liability. Zero excludes borrow costs; availability is not modeled.',
  start:'First date included in the reported simulation. Earlier bars may still be used for indicator warmup.',
  end:'Last date included in the reported simulation. Open positions are closed using the last available test-bar price.',
  capital:'Starting cash for the simulated portfolio. All positions share this one cash pool.',
  base_days:'Minimum base length in trading sessions used to measure the prior price structure.',
  max_depth_pct:'Maximum percentage drawdown from the base high to the base low. Lower values require shallower bases.',
  volume_multiple:'Breakout volume divided by the prior 50-session average volume. Values above 1 require confirmation.',
  sma_days:'Moving-average length used as the trend filter. Bullish signals require a close above it; bearish signals require a close below it.',
  min_rs_rating:'Percentile of prior 126-session price return among eligible members of this run’s universe. Zero disables this local relative-strength filter.',
  rs_short_lookback:'Return lookback used to rank emerging leadership among stocks with history on each completed signal date.',
  min_short_rs_rating:'Minimum emerging RS percentile. Zero disables this filter; the existing 126-session filter remains separate.',
  rs_improvement_sessions:'Compare emerging RS with its percentile this many stock sessions earlier, using the universe available on that earlier date.',
  min_rs_improvement:'Required rise in emerging RS percentile points. Zero disables improvement filtering. Swing research and paper only.',
  candidate_rank:'Prioritize the highest fundamental score when the five position slots or cash bind. Historical scores use filing publication times. Missing/stale scores rank last; ties prefer coverage then symbol. Alphabetical and relative-strength comparisons remain available.',
  require_long_trend:'Require the completed close above the 200-session average as well as the selected trend average.',
  require_rising_long_trend:'Also require the 200-session average to exceed its value 20 sessions earlier. Requires 220 warmup sessions.',
  market_min_coverage_pct:'Minimum fraction of the simulation universe with a dated 200-session average. Insufficient coverage blocks new entries when the market gate is enabled.',
  ipo_max_age_days:'Maximum calendar days since a verified listing date. Missing listing evidence blocks IPO signals; this does not prove first-base identity.',
  market_breadth_pct:'Minimum percentage of eligible stocks above their 200-session average in the selected breadth universe when Skip weak markets is enabled.',
  market_breadth_scope:'Full market measures all eligible stocks. Candidate sector measures eligible peers in the stock’s captured sector. Sector breadth requires swing next-open entries; current classifications and small groups remain limitations.',
  min_turnover:'Minimum average traded rupee value per day. This filters out illiquid symbols.',
  vcp_window_days:'Length of the most recent VCP contraction window used to compare range tightening.',
  vcp_volume_multiple:'Latest VCP-window volume divided by the prior 50-session average. Lower values require volume dry-up.',
  blue_sky_lookback_days:'Maximum number of prior sessions searched for the all-time or long-history high before the signal.',
  multiyear_base_days:'Minimum sessions in the long base used by the Multi-year screen.',
  multiyear_max_depth_pct:'Maximum depth allowed for the Multi-year base.',
  entry_mode:'Pivot triggers at resistance for bullish entries or support for bearish entries. Close uses the signal close; next-open uses the following session open.',
  risk_pct:'Percentage of current portfolio equity risked if the initial stop is hit. Cash and position limits still apply.',
  stop_pct:'Initial stop distance below a long entry or above a short entry. It defines the first unit of risk.',
  winner_exit:'How profitable positions are managed: moving-average trail, percentage below best close, or a fixed +8% / +15% / +25% target. Close-based stops activate next session.',
  fee_model:'Zerodha NSE resident-individual cash-equity tariff includes taxes, exchange fees and delivery DP charges; same-day exits use intraday brokerage. Custom buy/sell bps are ignored in Zerodha mode. AMC and personal income tax are excluded.',
  max_open_gap_pct:'Skip an upward opening gap above this percentage of the prior close. Zero disables. Execution assumes the open can be observed and the order filled at open plus slippage.',
  require_open_above_pivot:'Skip entries opening below the completed setup’s breakout level.',
  max_extension_pct:'Skip setups whose signal close is too far above its 50-session moving average. Zero disables.',
  reentry_cooldown_sessions:'Wait this many stock sessions after an exit before allowing a new entry. Zero disables.',
  stalled_exit_sessions:'If the best closing gain has not reached stalled_min_r times the initial percentage stop after this many sessions, sell at the next available open. Zero disables.',
  stalled_min_r:'Required best closing gain for avoiding a stalled exit; 0.5R with an 8% stop means 4% progress.',
  failed_breakout_sessions:'During these first holding sessions, a close below the original breakout level schedules a next-open exit. Zero disables.',
  market_risk_scale:'With the hard breadth gate off, multiply position risk by this number when breadth is weak. One leaves risk unchanged.',
  market_breadth_trend_sessions:'Strong breadth must also be at least its value this many sessions ago. Zero disables the trend condition.',
  sector_observe_only:'Paper only: when checked, record sector decisions but keep entries unchanged. Uncheck to enforce the selected sector filter. Existing exits continue in both modes.',
  sector_filter:'Off preserves the original strategy. Trend requires sector close above SMA50 and SMA50 rising over 20 sessions. Trend + relative strength also requires its 63-session return above Nifty 500. Long swing next-open entries only; missing or stale inputs block entries. Fetch sector data in Market data.',
  skip_weak_markets:'When enabled, skip new entries when the percentage of eligible symbols above their 200-session average is below Minimum market breadth. Existing positions continue.',
  breakeven_r:'Profit threshold, measured in initial risk units, after which the stop may move to the cost-adjusted breakeven level.',
  trail_pct:'Fallback stop below the highest close for longs or above the lowest close for shorts.',
  max_positions:'Maximum number of simultaneous open positions. New signals are skipped when the limit is full.',
  max_hold_days:'Safety limit on holding sessions. A position is closed when it reaches this age.',
  slippage_bps:'Estimated execution slippage per side in basis points; 100 basis points equals 1%.',
  buy_cost_bps:'All-in modeled charges on buys, expressed in basis points.',
  sell_cost_bps:'All-in modeled charges on sells, expressed in basis points.',
  acknowledge_limitations:'Confirms that this is exploratory research with current-constituent bias, unverified adjustments and hypothetical fills.'
};
// Effects describe the engine's thresholds, not a prediction of profitability.
const fieldEffects={
  capital:['Smaller cash pool and smaller affordable positions.','Larger cash pool; the same percentage risk represents more rupees.','₹1,00,000 at 1% risk budgets ₹1,000 before position limits.'],
  base_days:['Measures a shorter price base.','Measures a longer price base and needs more history.','25 sessions is roughly five trading weeks.'],
  max_depth_pct:['Requires shallower, tighter bases.','Allows deeper price swings in the base.','A ₹100 high and ₹80 low give 20% depth.'],
  multiyear_max_depth_pct:['Requires a shallower long base.','Allows deeper long bases.','A 30% limit rejects a base with 40% depth.'],
  volume_multiple:['Allows breakouts or breakdowns with less volume confirmation.','Requires stronger volume confirmation.','1.5 requires 150,000 shares when the prior mean is 100,000.'],
  sma_days:['The trend average responds faster to recent prices.','The trend average changes more slowly and needs more history.','50 averages the last 50 completed closes.'],
  min_rs_rating:['Includes weaker relative performers; 0 disables.','Restricts entries to stronger relative performers.','80 selects the top roughly 20% of eligible stocks.'],
  max_rs_rating:['Restricts bearish entries to weaker performers.','Allows relatively stronger stocks into bearish setups.','20 admits roughly the weakest fifth of eligible stocks.'],
  rs_short_lookback:['Ranks more recent price performance.','Ranks performance over a longer period.','63 sessions is roughly three trading months.'],
  min_short_rs_rating:['Includes more emerging leaders; 0 disables.','Requires a higher emerging-strength percentile.','80 requires an emerging RS rating of at least 80.'],
  rs_improvement_sessions:['Compares RS with a more recent observation.','Measures RS improvement over a longer interval.','20 compares today’s percentile with 20 stock sessions ago.'],
  min_rs_improvement:['Allows less improvement; 0 disables.','Requires a larger rise in RS percentile.','10 requires a rise from 60 to at least 70.'],
  min_turnover:['Includes less liquid stocks.','Requires more daily traded value.','₹5,00,00,000 means ₹5 crore of average daily turnover.'],
  vcp_window_days:['Measures tightening over fewer recent sessions.','Measures tightening over a longer recent window.','10 examines about two trading weeks.'],
  vcp_volume_multiple:['Requires stronger volume dry-up.','Allows more volume in the final contraction.','0.8 allows at most 80,000 shares against a 100,000-share mean.'],
  blue_sky_lookback_days:['Tests against a more recent prior high.','Tests against highs from a longer history.','252 searches roughly one trading year.'],
  low_lookback_days:['Tests a more recent support low.','Requires breaking a low from a longer history.','252 tests the prior roughly one-year low.'],
  multiyear_base_days:['Uses a shorter long-term base.','Uses a longer base and needs more history.','260 sessions is roughly one trading year.'],
  ipo_max_age_days:['Limits the screen to younger listings.','Includes older listings.','730 permits listings up to about two calendar years old.'],
  risk_pct:['Budgets less equity at risk per trade.','Budgets more equity at risk, subject to cash and position limits.','1% of ₹10 lakh budgets ₹10,000 of initial stop risk.'],
  stop_pct:['Tighter initial stop; more shares for the same risk budget.','Wider initial stop; fewer shares for the same risk budget.','8% at ₹100 sets a long stop at ₹92 or short stop at ₹108.'],
  market_breadth_pct:['Allows entries in weaker markets when the gate is on.','Requires more eligible stocks above their SMA200.','40 requires at least 40% above SMA200.'],
  max_market_breadth_pct:['Requires weaker breadth for bearish entries.','Allows bearish entries in broader market conditions.','30 permits at most 30% above SMA200.'],
  market_min_coverage_pct:['Accepts a breadth reading based on fewer stocks.','Requires more stocks to have enough dated history.','80 requires coverage of at least 80% of the universe.'],
  breakeven_r:['Moves the stop toward breakeven sooner.','Waits for a larger favorable move.','1R with an 8% initial stop means an 8% favorable price move.'],
  trail_pct:['Keeps the trailing stop closer to the best close.','Allows larger reversals before the trailing stop.','8% below a best long close of ₹120 gives ₹110.40.'],
  max_positions:['Concentrates the portfolio in fewer positions.','Allows more positions, subject to cash; skipped signals may change.','5 permits up to five positions; momentum uses five selected stocks per session.'],
  max_sector_positions:['Caps sector concentration more tightly; 0 disables.','Allows more positions in each captured sector.','2 allows at most two open positions from the same sector.'],
  max_hold_days:['Forces an earlier holding-age exit.','Gives trades more sessions to develop.','20 is roughly four trading weeks.'],
  max_open_gap_pct:['Rejects smaller upward gaps; 0 disables.','Allows larger upward gaps.','3 rejects an open above ₹103 after a ₹100 prior close.'],
  max_extension_pct:['Requires the signal nearer SMA50; 0 disables.','Allows signals farther above SMA50.','10 allows a signal close up to ₹110 when SMA50 is ₹100.'],
  reentry_cooldown_sessions:['Allows earlier re-entry; 0 disables.','Waits longer after an exit.','5 waits five stock sessions.'],
  stalled_exit_sessions:['Checks for inadequate progress sooner; 0 disables.','Gives the trade more time before checking.','10 checks progress after ten holding sessions.'],
  stalled_min_r:['Less progress is needed to avoid a stalled exit.','More progress is needed to avoid a stalled exit.','0.5R with an 8% stop requires a best closing gain of 4%.'],
  failed_breakout_sessions:['Monitors failures for a shorter initial period; 0 disables.','Keeps the failure exit active for more early sessions.','5 monitors closes below the original breakout level in the first five holding sessions.'],
  market_risk_scale:['Reduces position risk more in weak markets.','Preserves more normal risk; 1 leaves risk unchanged.','0.5 turns a 1% risk budget into 0.5% when breadth is weak and the hard gate is off.'],
  market_breadth_trend_sessions:['Compares breadth over a shorter interval; 0 disables.','Compares breadth with a more distant observation.','20 requires breadth at least as high as 20 sessions ago.'],
  slippage_bps:['Models less adverse execution; 0 removes slippage.','Models worse execution prices on each side.','10 bps is 0.1%, or ₹0.10 on a ₹100 price.'],
  buy_cost_bps:['Models lower buy charges; 0 removes custom charges.','Models higher buy charges.','25 bps charges ₹250 on a ₹1 lakh buy.'],
  sell_cost_bps:['Models lower sell charges; 0 removes custom charges.','Models higher sell charges.','25 bps charges ₹250 on a ₹1 lakh sale.'],
  borrow_cost_bps_year:['Models lower overnight borrowing cost; 0 excludes it.','Models higher borrowing cost on short liabilities.','1,000 bps is 10% annually, prorated by calendar days.'],
  minimum_warmup_sessions:['Requires less pre-test history; indicator requirements still apply.','Requires more pre-test history and may exclude more stocks.','250 requires at least 250 sessions before the test starts.'],
  reference_cap_pct:['Caps each reference position at a smaller share of equity.','Allows a larger position, subject to risk and liquidity limits.','30 caps a position at ₹3 lakh on ₹10 lakh equity.'],
  reference_turnover_pct:['Limits orders to a smaller share of median turnover.','Allows larger orders relative to liquidity.','10 caps notional at ₹1 lakh when median turnover is ₹10 lakh.'],
  opening_minutes:['Builds the opening range sooner from fewer bars.','Waits longer and includes more early-session prices.','15 uses the 09:15–09:30 IST opening interval.'],
  confirmation_minutes:['Confirms sooner with shorter completed candles.','Waits for longer completed candles.','60 waits for a completed hourly candle; fills still use five-minute bars.'],
  indicator_minutes:['Uses faster indicator candles.','Uses slower indicator candles.','60 uses hourly EMA/MACD rather than 10-minute candles.'],
  volume_lookback:['The opening-volume baseline adapts faster.','The baseline averages more prior sessions.','14 compares opening volume with 14 prior same-interval observations.'],
  min_relative_volume:['Allows less opening-volume activity; 0 removes the threshold.','Requires stronger opening-volume activity.','1.5 requires volume 50% above the same-interval average.'],
  liquid_universe_size:['Scans fewer liquid stocks.','Scans more stocks and may require more data.','20 scans at most 20 selected stocks each day.'],
  liquidity_days:['Turnover ranking responds faster to recent activity.','Turnover ranking averages more sessions.','20 uses the prior 20 sessions.'],
  atr_days:['ATR responds faster to recent daily volatility.','ATR smooths volatility over more sessions.','14 is the arithmetic mean of 14 prior daily true ranges.'],
  min_atr_pct:['Includes quieter stocks.','Requires more daily price movement relative to price.','1 requires ATR of at least ₹1 for a ₹100 prior close.'],
  stop_atr:['Sets a tighter ATR stop and increases risk-sized shares.','Sets a wider ATR stop and reduces risk-sized shares.','0.5 with ₹4 ATR gives a ₹2 initial stop distance.'],
  target_r:['Takes profit after a smaller favorable move; momentum allows 0 to disable.','Targets a larger favorable move.','2R with ₹2 initial risk targets ₹4 of favorable movement.'],
  breakout_buffer_atr:['Triggers closer to the opening-range boundary; 0 removes the buffer.','Requires a move farther beyond the boundary.','0.1 with ₹4 ATR adds a ₹0.40 trigger buffer.'],
  min_close_strength:['Allows closes farther from the trend-side extreme; 0 disables.','Requires closes nearer the high for longs or low for shorts.','0.7 requires the top 30% for longs or bottom 30% for shorts.'],
  min_confirmation_body_atr:['Allows smaller directional candle bodies; 0 disables.','Requires larger directional candle bodies.','0.1 with ₹4 ATR requires a ₹0.40 directional body.'],
  breakeven_after_r:['Tightens toward cost breakeven sooner; 0 disables.','Waits for more favorable progress.','1R with ₹2 initial risk activates after a ₹2 favorable completed close.'],
  fundamental_min_score:['Accepts lower-scoring financial evidence.','Requires a higher fundamentals score.','60 requires at least 60 out of 100 when the filter is enabled.'],
  fundamental_min_coverage_pct:['Accepts less complete historical evidence.','Requires more complete historical evidence.','80 requires at least 80% evidence coverage.'],
  fundamental_max_age_days:['Requires fresher financial periods.','Accepts older financial periods.','180 rejects periods older than 180 days at entry.'],
  trend_fast:['Fast EMA responds sooner to price changes.','Fast EMA smooths more five-minute bars.','9 uses a nine-bar EMA; it must stay below the slow EMA length.'],
  trend_slow:['Slow EMA responds sooner to price changes.','Slow EMA smooths more five-minute bars.','20 uses a 20-bar five-minute EMA.'],
  pullback_ema:['Pullback reference follows one-minute prices faster.','Pullback reference smooths more one-minute bars.','9 uses a nine-bar one-minute EMA.'],
  pullback_bars:['Needs fewer adverse candles before a resumption.','Requires a longer consecutive pullback.','2 requires two adverse one-minute candles.'],
  ema_touch_bps:['Requires the pullback nearer its EMA.','Allows a touch farther from the EMA.','5 bps gives ₹0.05 tolerance around a ₹100 EMA.'],
  entry_buffer_bps:['Adds less distance to breakout and stop levels.','Adds more distance to breakout and stop levels.','10 bps adds 0.1% of the reference price.'],
  min_stop_pct:['Allows trades with very tight stops.','Rejects trades whose computed stops are too tight.','0.05 rejects stop distances below ₹0.05 at a ₹100 entry.'],
  max_stop_pct:['Rejects more trades with wide stops.','Allows wider computed stops.','0.5 rejects a stop distance above ₹0.50 at a ₹100 entry.'],
  min_stock_score:['Includes lower suitability scores; 0 admits all scores.','Requires stronger suitability scores under score ranking.','60 requires at least 60 out of 100; it is not a win probability.'],
  max_holding_minutes:['Closes scalps sooner.','Allows longer scalps, subject to square-off.','15 limits holding to 15 minutes.'],
  cooldown_minutes:['Allows another trade in the stock sooner.','Waits longer after an exit.','5 waits five minutes before another entry.'],
  max_trades_per_symbol:['Allows fewer trades per stock each day.','Allows more repeated entries per stock each day.','3 caps a stock at three trades per session.'],
  daily_loss_pct:['Pauses new entries after a smaller daily loss.','Allows a larger daily loss before pausing entries.','1% of ₹10 lakh is ₹10,000; existing exits continue.'],
  participation_pct:['Caps fills at a smaller share of signal-minute volume.','Allows larger fills relative to that volume.','1% of 10,000 shares permits at most 100 shares.'],
  resistance_sessions:['Tests against a more recent resistance high.','Uses a longer resistance history.','40 takes the highest high of the preceding 40 sessions.'],
  max_distance_pct:['Keeps approaching candidates closer below the pivot.','Includes candidates farther below the pivot.','10 allows an approaching close from ₹90 to ₹100 for a ₹100 pivot; watchlist only.'],
  max_base_range_pct:['Requires a tighter recent base.','Allows a wider recent base.','30 allows a high/low ratio of at most 1.30 over the prior 20 sessions.'],
  max_contraction_ratio:['Requires more recent range compression.','Allows less compression or some expansion.','0.8 requires recent average range at most 80% of the earlier average.'],
  max_dry_volume_ratio:['Requires quieter volume near resistance.','Allows more near-resistance volume.','0.5 requires the prior five-session average at most half the prior 20-session mean; watchlist only.'],
  min_breakout_volume_ratio:['Allows lighter breakout volume.','Requires stronger breakout volume.','1.5 requires today’s volume at least 150% of the prior 20-session mean.'],
  min_turnover_rupees:['Includes less liquid candidates.','Requires more daily traded value.','₹50 lakh requires at least that 20-session average of close × volume.']
};
Object.assign(fieldHelp,{
  name:'A name saved with this run, screen or portfolio so you can recognize its assumptions later. Example: “VCP · 1% risk · 2025”.',
  pattern:'VCP looks for contraction and volume dry-up before a breakout; Blue sky tests a long-history high; Multi-year tests a long base; IPO base restricts listing age. Bearish variants look for support breaks, and 52-week low tests prior lows. Example: choose VCP to test tightening bases.',
  candidate_rank:'When cash or position limits bind, Symbol order prioritizes alphabetically; RS prioritizes stronger stocks for longs or weaker stocks for shorts; Fundamental score prioritizes verified historical financial quality, with missing or stale scores last. Example: RS priority can select a different stock than alphabetical order from simultaneous signals.',
  universe:'The stock universe used for research. New runs use Nifty Total Market (750); a larger universe would scan more stocks.',
  direction:'Both evaluates buy and sell signals; Long evaluates buy signals; Short evaluates sell signals. In momentum, execution reversal can change the actual position side.',
  entry_filter:'Candles only uses candle direction; EMA adds moving-average alignment and a pullback EMA touch; EMA + VWAP also requires the trend side of session VWAP. Added confirmations can reject signals.',
  stock_selection:'Turnover ranks by prior traded rupee value. Score ranks by liquidity, movement, trend consistency and volume activity, then applies the minimum score.',
  min_stock_score:'Minimum experimental suitability score when score ranking is selected; ignored under turnover ranking.',
  trend_fast:'Length of the fast five-minute exponential moving average used to confirm trend.',
  trend_slow:'Length of the slow five-minute exponential moving average used to confirm trend; must exceed the fast length.',
  pullback_ema:'One-minute exponential moving average that the pullback must touch in EMA confirmation modes.',
  pullback_bars:'Number of consecutive adverse one-minute candles needed to form a pullback.',
  ema_touch_bps:'Allowed distance from the pullback EMA for a qualifying touch. Relevant in EMA confirmation modes.',
  entry_buffer_bps:'Price buffer applied beyond the pullback breakout level and protective stop extreme.',
  min_stop_pct:'Rejects a scalping entry when its computed initial stop distance is below this percentage.',
  max_stop_pct:'Rejects a scalping entry when its computed initial stop distance exceeds this percentage.',
  liquidity_days:'Prior completed sessions used to average daily traded rupee value for stock selection.',
  atr_days:'Prior completed daily sessions used for arithmetic-mean true range (ATR).',
  min_atr_pct:'Minimum prior daily ATR divided by prior close, as a percentage; filters for stocks with sufficient movement.',
  max_holding_minutes:'Maximum duration of a scalp before a time exit, subject to the mandatory session cutoff.',
  cooldown_minutes:'Minimum time after exiting a stock before another entry in that stock.',
  max_trades_per_symbol:'Per-stock daily trade limit; other risk and portfolio limits also apply.',
  daily_loss_pct:'Daily loss threshold that pauses new scalping entries; protective exits remain active.',
  participation_pct:'Caps simulated quantity as a percentage of the signal minute’s traded volume.',
  first_entry_time:'Earliest allowed entry open in IST. Earlier permits earlier-session trades; later skips more opening activity. Example: 09:45 waits until 09:45.',
  last_entry_time:'Latest allowed entry open in IST. Earlier ends entries sooner; later permits more afternoon entries. Example: 11:30 rejects subsequent entry opens.',
  square_off_time:'Mandatory exit open in IST. Earlier shortens the possible holding period; later allows more session time. Example: 15:00 exits at the 15:00 bar open; valid boundaries depend on the strategy.',
  start:'First reported simulation date. Earlier includes more past sessions; later shortens the period with the same end date. Example: 2025-01-01 excludes earlier trades but can use earlier bars for warmup.',
  end:'Last reported simulation date. Earlier ends the experiment sooner; later adds sessions. Legacy simulations close remaining positions; reference simulations keep end-date holdings marked.',
  max_sector_positions:'Maximum simultaneous positions in one captured sector. Applies to supported long swing strategies.',
  minimum_warmup_sessions:'Minimum history required before the test window. Warmup bars prepare indicators and are excluded from reported returns.',
  simulation_model:'Configurable filters or a fixed-rule model with saved thresholds and execution assumptions.',
  reference_same_day:'Conservative checks an entry-day stop whenever the daily low touches it. Reference can exempt a qualifying bullish pivot-entry candle. Daily OHLC does not establish which price came first.',
  reference_cap_pct:'Reference simulation cap on each position’s notional value as a percentage of portfolio equity.',
  reference_turnover_pct:'Reference simulation cap on position notional as a percentage of prior median daily turnover.',
  comparison_run_id:'Optional saved run ID for reusing frozen input evidence. Blank uses available data for a new experiment.',
  resistance_sessions:'Prior sessions searched for the resistance pivot; excludes the signal session.',
  max_distance_pct:'Maximum distance below resistance for approaching-breakout watchlist candidates. Does not trigger backtest trades.',
  max_base_range_pct:'Maximum high/low range over the last 20 sessions of the prior base, calculated as (high / low − 1) × 100.',
  max_contraction_ratio:'Maximum average daily range in the prior five sessions divided by the earlier 15-session average.',
  max_dry_volume_ratio:'Maximum prior five-session average volume divided by prior 20-session average volume for approaching-breakout candidates. Watchlist only.',
  min_breakout_volume_ratio:'Minimum signal-session volume divided by prior 20-session average for a confirmed early breakout.',
  min_turnover_rupees:'Minimum 20-session average of close × volume in rupees for investor technical setups.',
  strict_trend:'On requires close ≥ SMA20 ≥ SMA50 ≥ SMA100 and rising SMA50. Off requires close ≥ SMA50 ≥ SMA100 and rising SMA50.',
  max_spread_bps:'Maximum bid/ask spread allowed before a simulated paper entry. Exits continue even when entry conditions fail.',
  quote_max_age_seconds:'Maximum age of a quote used by the paper runner before it is considered stale.',
  max_entry_delay_seconds:'Time available after a completed signal to obtain a qualifying fresh quote for entry.',
  auto_run:'On enables automatic startup or weekday cycles for this paper strategy. Off requires manual startup; the configuration is saved with the portfolio.',
  execution_time:'Next open reconstructs that session’s opening execution from the preceding completed setup; schedule its cycle at or after 16:00 IST. Midday uses observed quotes during a cycle within the regular session before 15:15 IST.',
  run_hour:'Hour in IST at which the weekday paper cycle runs when automatic cycling is enabled.',
  run_minute:'Minute within the configured IST cycle hour when automatic cycling is enabled.'
});
Object.assign(fieldEffects,{
  max_spread_bps:['Requires a tighter quoted spread.','Accepts a wider quoted spread.','15 bps permits a ₹0.15 spread around a ₹100 price.'],
  quote_max_age_seconds:['Requires fresher quotes.','Accepts older quotes.','3 rejects quotes older than three seconds.'],
  max_entry_delay_seconds:['Abandons unfilled signals sooner.','Allows more time to find a qualifying quote.','8 allows entry within eight seconds after the signal close.'],
  run_hour:['Schedules the cycle earlier in the day.','Schedules the cycle later in the day.','16 with minute 15 schedules 16:15 IST.'],
  run_minute:['Schedules earlier within the selected hour.','Schedules later within the selected hour.','15 with hour 16 schedules 16:15 IST.']
});
let fieldHelpId=0;
function parameterGuidance(key,schema){
  const investor=Boolean(schema.properties.resistance_sessions);
  let effect=investor&&key==='max_extension_pct'
    ? ['Requires a breakout close nearer the pivot; 0 permits no confirmed breakout.','Allows more extension above the pivot.','5 allows a confirmed close above ₹100 and up to ₹105 for a ₹100 pivot.'] : fieldEffects[key];
  let description=investor&&key==='max_extension_pct'?'Maximum close extension above resistance for confirmed investor early breakouts. Zero does not disable this rule.':fieldHelp[key]||schema.properties[key]?.description||'';
  const s=schema.properties[key];
  if(['slippage_bps','buy_cost_bps','sell_cost_bps'].includes(key)&&(s?.exclusiveMinimum===0||schema.properties.execution_time&&key!=='slippage_bps')){
    description+=' This paper form requires a positive custom cost; zero is unavailable.';
    effect=[effect[0].split(';')[0]+'.',effect[1],effect[2]];
  }
  if(s?.type==='boolean'&&!['acknowledge_limitations','sector_observe_only','auto_run','enabled','strict_trend'].includes(key))description+=' On applies this requirement; off removes this requirement.';
  return {description,effect};
}
function parameterHelp(key,schema,id){const {description,effect}=parameterGuidance(key,schema);return `<span class="help parameter-help" id="${id}">${esc(description)}${effect?`<span><b>Lower:</b> ${esc(effect[0])}</span><span><b>Higher:</b> ${esc(effect[1])}</span><span><b>Example:</b> ${esc(effect[2])}</span>`:''}</span>`;}
function infoLabel(title,key){return `<span class="field-label">${esc(title)}</span>`;}
function sliderBounds(s,key){
  // Monetary bounds are validation limits, too wide for a useful linear slider.
  if(!['number','integer'].includes(s.type)||['capital','min_turnover','min_turnover_rupees','borrow_cost_bps_year'].includes(key)||s.maximum==null)return null;
  const step=s.type==='integer'?1:s.multipleOf||0.01;
  const min=s.minimum??(s.exclusiveMinimum!=null?Number((s.exclusiveMinimum+step).toFixed(8)):null);
  return min==null||min>=s.maximum?null:{min,max:s.maximum,step};
}
function syncParameterSliders(root){
  root?.querySelectorAll?.('[data-parameter-slider]').forEach(slider=>{
    const input=slider.closest('.parameter-control').querySelector('input[type="number"]');
    slider.disabled=input.disabled||input.readOnly||input.value===''||!input.validity.valid||Number(input.value)<Number(slider.min)||Number(input.value)>Number(slider.max);
    if(!slider.disabled)slider.value=input.value;
  });
}
function updateParameterControl(target){
  const control=target.closest?.('.parameter-control');if(!control)return;
  if(target.matches?.('[data-parameter-slider]')){
    const input=control.querySelector('input[type="number"]');
    if(input.disabled||input.readOnly)return;
    input.value=target.value;
  }
  syncParameterSliders(control);
}
function parameterInput(key,s,v,req,dateAttrs,helpId){
  const bounds=sliderBounds(s,key),title=s.title||key;
  const input=`<input name="${key}" type="${s.format==='date'?'date':['number','integer'].includes(s.type)?'number':'text'}" value="${esc(v)}" ${s.type==='integer'?'step="1"':s.type==='number'?'step="any"':''} ${s.minimum!=null?`min="${s.minimum}"`:s.exclusiveMinimum!=null?`min="${s.exclusiveMinimum+.0001}"`:''} ${s.maximum!=null?`max="${s.maximum}"`:''} ${s.maxLength?`maxlength="${s.maxLength}"`:''} ${dateAttrs} ${req} aria-label="${esc(title)}" aria-describedby="${helpId}" ${s.type==='number'&&v===''?'placeholder="Enter your assumption"':''}>`;
  const lower=s.exclusiveMinimum!=null?`greater than ${s.exclusiveMinimum}`:s.minimum??'no minimum';
  const range=['number','integer'].includes(s.type)&&(s.maximum!=null||s.minimum!=null||s.exclusiveMinimum!=null)?`<span class="help parameter-range">Allowed: ${lower}${s.maximum!=null?` – ${s.maximum}`:s.exclusiveMinimum!=null?'':' or higher'}${bounds?' · Drag or enter an exact value.':''}</span>`:'';
  if(!bounds)return input+range;
  return `<span class="parameter-control"><input type="range" data-parameter-slider min="${bounds.min}" max="${bounds.max}" step="${bounds.step}" value="${esc(v)}" ${v===''||Number(v)<bounds.min||Number(v)>bounds.max?'disabled':''} aria-label="${esc(title)} slider" aria-describedby="${helpId}">${input}</span>${range}`;
}
function field(key,schema,value,dateBounds=null){
  if(key==='strategy')return '';
  if(key==='screen')return strategyPicker(value||'builtin:vcp','screen-picker',Boolean(schema.properties.execution_time));
  const s=schema.properties[key];if(!s)return '';const v=key==='name'?uiCopy(value??s.default??''):value??s.default??'', req=(schema.required||[]).includes(key)?'required':'',helpId=`parameter-help-${++fieldHelpId}`,help=parameterHelp(key,schema,helpId);
  const dateAttrs=s.format==='date'&&dateBounds?`${dateBounds.min?`min="${esc(dateBounds.min)}"`:''} ${dateBounds.max?`max="${esc(dateBounds.max)}"`:''} ${dateBounds.min&&dateBounds.max?'':'disabled'}`:'';
  if(s.type==='boolean')return `<label class="field checkbox"><input name="${key}" type="checkbox" ${v?'checked':''} ${req} aria-describedby="${helpId}"><span class="checkbox-guidance">${infoLabel(s.title,key)}${help}</span></label>`;
  let options=key==='universe'?['niftytotalmarket']:key==='pattern'?s.enum?.filter(x=>!['breakout','investor_early_breakout'].includes(x)):s.enum||(s.const?[s.const]:null);
  if(key==='winner_exit'&&schema===state.bearish_backtest_schema)options=options?.filter(x=>x!=='trail_pct');
  const labels={legacy:'Configurable rules',banana_proxy_v1:'Fixed rules',niftytotalmarket:'Nifty Total Market (750)',off:'Off',trend:'Sector trend',trend_rs:'Sector trend + relative strength',candles:'Candles only',ema:'EMA confirmation',ema_vwap:'EMA + VWAP',intraday:'Intraday: mandatory same-day exit',swing:'Swing: overnight holdings',vcp_breakdown:'VCP breakdown',new_lows:'52-week low',multiyear_breakdown:'Multi-year breakdown',ipo_breakdown:'IPO base breakdown',alphabetical:'Symbol order',rs_126:'Highest 126-day strength first',vcp:'VCP',blue_sky:'Blue sky',multiyear:'Multi-year breakouts',ipo:'IPO base',pivot:'Pivot breakout',close:'Close breakout',next_open:'Next session open',trail_50d:'50-day trailing exit',trail_30w:'30-week trailing exit',take_8:'Take profit at +8%',take_15:'Take profit at +15%',take_25:'Take profit at +25%'};
  labels.custom_bps='Custom buy/sell bps';labels.zerodha_equity='Zerodha NSE cash equity';labels.trail_pct='Percentage trail below best close';labels.market='Full market';labels.sector='Candidate sector';
  if(schema===state.bearish_backtest_schema){labels.rs_126='Weakest 126-day strength first';labels.pivot='Pivot breakdown';labels.close='Signal close';for(const pct of [8,15,25])labels[`take_${pct}`]=`Take profit after ${pct}% decline`;}
  return `<div class="field">${infoLabel(key==='pattern'?'Base screen':key==='trail_pct'&&schema===state.bearish_backtest_schema?'Trail above lowest close (%)':s.title,key)}${options?`<select name="${key}" ${req} aria-label="${esc(s.title||key)}" aria-describedby="${helpId}">${options.map(x=>`<option value="${esc(x)}" ${v===x?'selected':''}>${labels[x]||esc(x)}</option>`).join('')}</select>`:parameterInput(key,s,v,req,dateAttrs,helpId)}${dateBounds&&dateBounds.min&&dateBounds.max?`<span class="help">Available dates: ${esc(dateBounds.min)} → ${esc(dateBounds.max)}</span>`:''}${help}</div>`;
}
function settingsView(){return heading('Settings','Connect Upstox for market data and live execution.')+
 `<section class="panel connection-panel"><div class="panel-head"><div><h2>Upstox access token</h2><p>Your market data connection.</p></div>${badge(state.token_saved?'Token saved':'Not connected')}</div><form id="token-form"><div class="form-section"><label class="field"><span>${state.token_saved?'Replace access token':'Access token'}</span><input type="password" name="access_token" minlength="20" maxlength="10000" autocomplete="off" required placeholder="Paste your Upstox access token"><span class="help">The saved token is never returned to the browser. Access is validated when data is fetched.</span></label><p style="margin-top:18px"><a href="https://account.upstox.com/developer/apps" target="_blank" rel="noreferrer" class="text-button">Open Upstox developer apps ↗</a></p></div><div class="form-actions"><button class="button primary" type="submit">Save token</button></div><div class="form-error" role="alert"></div></form></section>`;}

const screenKeys=['base_days','max_depth_pct','volume_multiple','sma_days','require_long_trend','require_rising_long_trend','min_rs_rating','rs_short_lookback','min_short_rs_rating','rs_improvement_sessions','min_rs_improvement','min_turnover','vcp_window_days','vcp_volume_multiple','blue_sky_lookback_days','multiyear_base_days','multiyear_max_depth_pct','ipo_max_age_days'];
// Current technical screen defaults; keep legacy API defaults for saved experiments.
const builtinScreenFilters={base_days:15,max_depth_pct:35,volume_multiple:1,sma_days:50,require_long_trend:false,require_rising_long_trend:false,min_rs_rating:0,rs_short_lookback:63,min_short_rs_rating:0,rs_improvement_sessions:20,min_rs_improvement:0,min_turnover:50000000,vcp_window_days:10,vcp_volume_multiple:0.9,blue_sky_lookback_days:5000,multiyear_base_days:260,multiyear_max_depth_pct:50,ipo_max_age_days:730};
function isBearishPattern(pattern){return ['vcp_breakdown','new_lows','multiyear_breakdown','ipo_breakdown'].includes(pattern);}
function screenPreset(id,paper=false){
  if(id.startsWith('bearish:'))return {...Object.fromEntries(Object.entries(state.bearish_schema.properties).filter(([,v])=>v.default!==undefined).map(([k,v])=>[k,v.default])),pattern:id.slice(8)};
  const custom=(state.screens||[]).find(x=>x.id===id);
  if(custom)return {pattern:custom.pattern,...Object.fromEntries(screenKeys.map(k=>[k,custom[k]??builtinScreenFilters[k]])),...(custom.trading_defaults||{}),...(paper?(custom.paper_defaults||{}):(custom.backtest_defaults||{})),...(custom.minimum_warmup_sessions!=null?{minimum_warmup_sessions:custom.minimum_warmup_sessions}:{})};
  const pattern=id.replace('builtin:','');
  if(!['vcp','blue_sky','multiyear','ipo'].includes(pattern))return {};
  return {pattern,...builtinScreenFilters};
}
function applyScreenPreset(form,id){
  const values=screenPreset(id,form.id==='paper-form');
  for(const key of Object.keys(values)){
    if(form.id==='paper-form'&&key==='capital'&&form.elements.capital?.readOnly)continue;
    if(form.elements[key]&&values[key]!=null){if(form.elements[key].type==='checkbox')form.elements[key].checked=Boolean(values[key]);else form.elements[key].value=values[key];}
  }
  if(form.elements.screen)form.elements.screen.value=id;
  syncParameterSliders(form);
}
function screenForm(){const schema=state.backtest_schema;return `<form id="screen-form"><div class="notice">Save a reusable Swing Pattern screen. These values control pattern qualification; entry, risk, exits and costs remain configurable for each backtest.</div><div class="form-section"><div class="fields">${field('name',{properties:{name:{title:'Screen name',type:'string',maxLength:80}},required:['name']},'My screen')}${field('pattern',schema,'vcp')}</div></div><div class="form-section"><h3>Screen filters</h3><p>Adjust every measurable filter used by the daily-bar pattern engine.</p><div class="fields">${screenKeys.map(k=>field(k,schema)).join('')}</div></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">Save screen →</button></div></form>`;}
function newScreen(){modal('Add a new screen',screenForm());applyScreenPreset($('#screen-form'),'builtin:vcp');}
let bearishScanRequest=0;
function newBearishScreen(pattern='vcp_breakdown'){
  bearishScanRequest++;
  const schema=state.bearish_schema;
  modal('Bearish market screen',`<div class="notice">Scan downloaded daily history for downside setups. This screen uses completed sessions before today (IST). It produces a watchlist. Intraday short backtests use five-minute candles and compulsory same-day buyback; paper trading supports long positions only.</div><form id="bearish-form"><div class="form-section"><div class="fields">${Object.keys(schema.properties).map(k=>field(k,schema,k==='pattern'?pattern:undefined)).join('')}</div></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Close</button><button class="button" type="button" data-action="bearish-backtest">Backtest this screen</button><button class="button primary" type="submit">Scan bearish setups →</button></div></form><div id="bearish-results" aria-live="polite"></div>`);
}
function bearishResults(data){
  const summary=`Session: ${esc(data.as_of||'No completed history')} · ${data.scanned_symbols} / ${data.total_symbols} symbols current · Above 200-day SMA: ${data.market_breadth_pct==null?'Unavailable':number(data.market_breadth_pct)+'%'} · Breadth coverage: ${number(data.market_coverage_pct)}%`;
  return `<div class="notice">${summary}</div>${!data.market_gate_passed?'<div class="notice warn">The weak-market gate did not pass. No candidates qualify with these settings.</div>':''}${data.matches.length?`<div class="table-wrap"><table><thead><tr><th>SYMBOL</th><th>SESSION</th><th>CLOSE</th><th>BROKEN SUPPORT</th><th>VOLUME ×</th><th>RS PERCENTILE</th></tr></thead><tbody>${data.matches.map(x=>`<tr><td><button class="symbol-button" data-action="chart" data-isin="${esc(x.isin)}">${esc(x.symbol)}</button><small>${esc(x.name)}</small></td><td>${esc(x.date)}</td><td>${money(x.close)}</td><td>${money(x.breakdown_level)}</td><td>${number(x.volume_multiple)}</td><td>${number(x.rs_rating)}</td></tr>`).join('')}</tbody></table></div>`:empty('No bearish setups qualify','Try another breakdown pattern or review the filters and downloaded history.')}<div class="notice">Thresholds are editable research assumptions. Relative strength compares eligible symbols in the selected universe. No profitability or short-sale execution is assumed.</div>${data.excluded.length?`<details><summary>${data.excluded.length} excluded symbols</summary><ul>${data.excluded.map(x=>`<li>${esc(x.symbol)}: ${esc(x.reason)}</li>`).join('')}</ul></details>`:''}`;
}
async function submitBearishScreen(form){
  const request=++bearishScanRequest, submit=form.querySelector('[type="submit"]'), errorBox=form.querySelector('.form-error');
  submit.disabled=true;errorBox.textContent='';$('#bearish-results').innerHTML='<p role="status">Scanning completed daily history…</p>';
  try{
    const result=await api('bearish/scan','POST',readForm(form,state.bearish_schema));
    if(request===bearishScanRequest&&$('#modal').open&&$('#bearish-form')===form)$('#bearish-results').innerHTML=bearishResults(result);
  }catch(error){if(request===bearishScanRequest&&$('#bearish-form')===form){errorBox.textContent=error.message;$('#bearish-results').innerHTML='';}}
  finally{submit.disabled=false;}
}
function render(){
  if(!state)return;
  $('.local-status').innerHTML='<i></i> '+(state.environment==='production'?'Production workspace':'Local workspace');
  currentView=location.hash.slice(1)||'overview';if(!workspaceViews.includes(currentView))currentView='overview';
  const activeNav=['momentum','scalping'].includes(currentView)?'backtests':currentView==='investor'?'news':currentView;
  $('#top-navigation').innerHTML=nav.map(([id,label,icon])=>`<a class="nav-link ${id===activeNav?'active':''}" href="#${id}" ${id===activeNav?'aria-current="page"':''}><span class="nav-icon">${icon}</span>${label}</a>`).join('');
  $('#view').innerHTML=({overview,data:()=>researchTabs()+dataView(),news:()=>newsView(),company:()=>companyReviewView(),investor:()=>investorView(),backtests:backtestsView,momentum:momentumView,scalping:scalpingView,paper:paperView,live:()=>liveView(),jobs:jobsView,settings:()=>settingsView()+(typeof liveConnectionView==='function'?liveConnectionView():'')}[currentView])();
  cleanWorkspaceCopy($('#view'));
}
async function refresh(redraw=true){state=await api('bootstrap');if(redraw){render();if($('#modal')?.open&&$('#modal-content')?.dataset.paperDetails==='true')openPaperDetails();}updateBacktestAvailability();for(const id of ['momentum-form','scalping-form']){const form=$('#'+id);if(form)form.querySelector('[type="submit"]').disabled=Boolean(activeJob())||form.dataset.submitting==='true';}}
function momentumComparisonTable(c){
  return `<section class="panel"><div class="panel-head"><div><h2>Refinement comparison</h2><p>${esc(c.start)} → ${esc(c.end)} · Same frozen data and costs</p></div><span class="badge">${c.trials.length} trials</span></div><div class="panel-body"><div class="table-wrap"><table><thead><tr><th>Trial</th><th>Net return</th><th>Δ vs replay</th><th>Drawdown</th><th>Trades</th><th>Earlier / later</th><th></th></tr></thead><tbody>${c.trials.map(t=>`<tr><td>${esc(t.label)}</td><td class="${t.metrics.return_pct>=0?'positive':'negative'}">${pct(t.metrics.return_pct)}</td><td>${t.delta_return_pct>0?'+':''}${number(t.delta_return_pct)} pp</td><td>${number(t.metrics.max_drawdown_pct)}%</td><td>${t.metrics.trade_count??'—'}</td><td>${t.evaluation.segments.map(v=>pct(v.return_pct)).join(' / ')}</td><td>${t.status==='failed'?`<span class="negative">Failed: ${esc(t.error)}</span>`:`<button class="text-button" data-action="result" data-id="${esc(t.run_id)}">Report ↗</button>`}</td></tr>`).join('')}</tbody></table></div><div class="notice">${esc(c.notice)} The earlier/later split is a diagnostic on an already known sample.</div></div></section>`;
}
function momentumView(){
  const runs=state.runs.filter(r=>r.strategy_id==='intraday_momentum'), latest=runs[0], comparison=state.momentum_comparisons?.[0];
  return researchTabs()+heading('Momentum research. Clearer evidence.','Test opening breakouts, see cost drag, and compare changes on identical candles.',`<a class="button" href="#company">Fundamental buy screen</a><button class="button primary" data-action="new-momentum">＋ Momentum backtest</button>`,'INTRADAY MOMENTUM / '+universeName().toUpperCase())+pending()+
    (latest?`<div class="stats">${stat('Latest net return',pct(latest.metrics.return_pct),latest.config.name,latest.metrics.return_pct>0)}${stat('Max drawdown',number(latest.metrics.max_drawdown_pct)+'%','Session-end equity')}${stat('Trade count',latest.metrics.trade_count,`${latest.metrics.long_trades??'—'} long · ${latest.metrics.short_trades??'—'} short`)}${stat('Modeled cost drag',money(latest.metrics.modeled_fees+latest.metrics.modeled_slippage),'Fees + slippage on recorded fills')}</div>`:'')+
    `<section class="panel momentum-method"><div class="panel-body"><div class="momentum-steps"><div><span>01 · SELECT</span><h3>Liquid stocks in play</h3><p>Prior turnover and ATR; opening relative volume.</p></div><div><span>02 · CONFIRM</span><h3>Completed breakout</h3><p>5–60 minute confirmation; five-minute fills. Optional VWAP and ATR buffer.</p></div><div><span>03 · PROTECT</span><h3>Risk and same-day exit</h3><p>ATR stop, optional breakeven/target, fixed cutoff.</p></div></div><div class="notice">Compare refinements runs six trials. Research ideas runs twelve declared tests of confirmation timeframes, opening ranges, volume, timing and direction. Test stronger entries runs seven trials of hourly confirmation, VWAP, buffer and candle quality. All use frozen inputs and matched costs; every trial is kept and defaults stay unchanged.</div><details><summary>Research sources and data assumptions</summary><p>US research informs this India adaptation. Cached five-minute history is shared; missing inputs can be fetched for new experiments. Short samples and current-constituent bias do not establish an edge.</p><div class="actions">${(state.momentum_sources||[]).map(s=>`<a class="text-button" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)} ↗</a>`).join('')}</div></details></div></section>`+
    (comparison?momentumComparisonTable(comparison):'')+`<section class="panel momentum-experiments"><div class="panel-head"><h2>Momentum experiments</h2><span class="badge">${runs.length} reports</span></div><div class="panel-body">${runs.map(r=>`<div class="job-card"><div><strong>${esc(r.config.name)}</strong><small>${esc(r.config.start)} → ${esc(r.config.end)} · ${r.metrics.trade_count} trades · ${pct(r.metrics.return_pct)}</small></div><div class="actions"><button class="button small" data-action="momentum-compare" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Compare refinements</button><button class="button small" data-action="momentum-research" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Research ideas</button><button class="button small" data-action="momentum-fundamentals" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Test fundamentals filter</button><button class="button small" data-action="momentum-pullbacks" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Test pullback entries</button><button class="button small" data-action="momentum-indicators" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Test EMA / MACD</button><button class="button small" data-action="momentum-stronger" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Test stronger entries</button><button class="button" data-action="result" data-id="${esc(r.id)}">Open report ↗</button></div></div>`).join('')||'<p>No momentum experiments yet. Start with a short window to verify data and execution.</p>'}</div></section>`;
}
function scalpingView(){
  const runs=state.runs.filter(r=>r.strategy_id==='scalping'), latest=runs[0], comparison=state.scalping_comparisons?.[0];
  return researchTabs()+heading('Scalping research. Minute by minute.','Test pullback entries with candles, moving averages and optional VWAP.',`<button class="button primary" data-action="new-scalping">＋ Scalping backtest</button>`,'SCALPING / '+universeName().toUpperCase())+pending()+
    `<div class="stats">${stat('Experiments',runs.length,'Saved one-minute backtests')}${stat('Latest net return',latest?pct(latest.metrics.return_pct):'—','After fees and slippage')}${stat('Latest trades',latest?.metrics.trade_count??'—','Long and short pullbacks')}</div>`+
    `<section class="panel"><div class="panel-body"><h3>Trend → pullback → continuation</h3><p>Completed five-minute EMAs establish direction. Consecutive adverse one-minute candles pull back to a short EMA; a completed breakout close triggers entry at the next minute’s open. Optional VWAP confirms direction.</p><p>Pullback stops, R targets, holding limits, cooldowns and a daily loss pause manage risk. Capital is shared across stocks and reused after exits.</p><div class="notice">Research uses candle intervals and modeled fills. Start with a short date window. Compare confirmations runs all three declared versions on identical frozen data and costs; results do not automatically change defaults.</div></div></section>`+
    scalpingPaperView()+(comparison?momentumComparisonTable(comparison):'')+
    `<section class="panel"><div class="panel-head"><h2>Scalping experiments</h2><span class="badge">${runs.length} reports</span></div><div class="panel-body">${runs.map(r=>`<div class="job-card"><div><strong>${esc(r.config.name)}</strong><small>${esc(r.config.start)} → ${esc(r.config.end)} · ${esc(r.config.entry_filter)} · ${r.metrics.trade_count} trades · ${pct(r.metrics.return_pct)}</small></div><div class="actions"><button class="button small" data-action="scalping-compare" data-id="${esc(r.id)}" ${activeJob()?'disabled':''}>Compare confirmations</button><button class="button" data-action="result" data-id="${esc(r.id)}">Open report ↗</button></div></div>`).join('')||'<p>No scalping experiments yet. Fetch daily history, then check one-minute coverage.</p>'}</div></section>`;
}
function scalpingPaperView(){
  if(!state.scalping_paper_schema)return '';
  const p=state.scalping_paper,r=state.scalping_runner||{},l=p?.ledger||{},positions=Object.entries(l.positions||{});
  const controls=p?`<button class="button small" data-action="scalping-paper-config">Configure</button><button class="button small" data-action="scalping-paper-status">${p.status==='active'?'Pause entries':'Resume entries'}</button><button class="button small" data-action="scalping-paper-export">Export full ledger</button>${r.running?'<button class="button small" data-action="scalping-paper-stop">Flatten & stop runner</button>':'<button class="button primary small" data-action="scalping-paper-start">Start quote runner</button>'}`:'<button class="button primary" data-action="scalping-paper-config">Create paper portfolio</button>';
  return `<section class="panel"><div class="panel-head"><div><h2>Forward scalping paper</h2><p>Observed bid/ask fills · separate cash and durable ledger</p></div><div class="actions">${controls}</div></div><div class="panel-body"><div class="notice">${p?badge(p.status)+' · Begins '+esc(p.start_session)+' · ':''}${badge(r.status||'stopped')} ${esc(r.message||'Create a portfolio with allocated capital, then start the quote runner.')} ${r.stale_symbols?.length?'Stale held stocks: '+esc(r.stale_symbols.join(', ')):''}</div>${priceGapWarnings(p?.data_quality)}<p>Signals use completed one-minute candles; fills use fresh streamed quotes. A stop request waits for fresh quotes to liquidate before stopping. Settings changes apply when the next session is frozen. ${p?.config.auto_run?'The standalone runner starts automatically with the app.':'Automatic startup is off.'}</p>${p?`<div class="stats">${stat('Paper equity',money(p.metrics?.final_equity??p.config.capital),'Marked at observed bid/ask')}${stat('Available cash',money(l.cash??p.config.capital),'Full notional reserved for both directions')}${stat('Realized P&L',money(p.metrics?.realized_pnl??0),'After modeled fees and slippage')}${stat('Open positions',positions.length,'Quotes required for protective exits')}</div><h3>Open positions</h3><div class="table-wrap"><table><thead><tr><th>Stock</th><th>Side</th><th>Entry</th><th>Shares</th><th>Stop / target</th></tr></thead><tbody>${positions.map(([s,t])=>`<tr><td>${esc(s)}</td><td>${esc(t.direction)}</td><td>${money(t.entry)}<small>${esc(t.entry_date)} ${esc(t.entry_time)}</small></td><td>${t.quantity}</td><td>${money(t.stop)} / ${money(t.target)}${t.pending_exit?`<small>${esc(t.pending_exit)}</small>`:''}</td></tr>`).join('')||'<tr><td colspan="5">No open positions.</td></tr>'}</tbody></table></div><h3>Closed trades · ${l.full_trade_count??l.trades?.length??0}</h3><div class="table-wrap"><table><thead><tr><th>Stock / side</th><th>Entry</th><th>Exit</th><th>Shares</th><th>Net P&L</th><th>Reason</th></tr></thead><tbody>${[...(l.trades||[])].reverse().map(t=>`<tr><td>${esc(t.symbol)}<small>${esc(t.direction)}</small></td><td>${esc(t.entry_date)} ${esc(t.entry_time)}<small>${money(t.entry)}</small></td><td>${esc(t.exit_date)} ${esc(t.exit_time)}<small>${money(t.exit)}</small></td><td>${t.quantity}</td><td class="${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</td><td>${esc(t.reason)}${t.partial_exit?' · partial':''}</td></tr>`).join('')||'<tr><td colspan="6">No closed forward trades yet.</td></tr>'}</tbody></table></div><p>Latest 100 closed trade portions shown. Export preserves all trades, quotes, fills and checkpoints.</p><h3>Observed simulated fills · ${l.full_order_count??l.orders?.length??0}</h3><div class="table-wrap"><table><thead><tr><th>Time</th><th>Stock / side</th><th>Shares</th><th>Fill</th><th>Observed bid / ask</th><th>Fees</th></tr></thead><tbody>${[...(l.orders||[])].reverse().map(o=>`<tr><td>${esc(o.date)} ${esc(o.time)}</td><td>${esc(o.symbol)} · ${esc(o.side)}</td><td>${o.quantity}</td><td>${money(o.price)}</td><td>${money(o.quote.bid)} / ${money(o.quote.ask)}</td><td>${money(o.fees)}</td></tr>`).join('')||'<tr><td colspan="6">No quote fills yet.</td></tr>'}</tbody></table></div>${Object.keys(p.stream_session?.data_issues||{}).length?`<div class="notice warn">Entry data issues: ${Object.entries(p.stream_session.data_issues).map(([s,v])=>esc(s)+': '+esc(v)).join('; ')}. Quote exits continue.</div>`:''}`:'<p>Capital is required. Trading starts with sessions after portfolio creation; past candles provide indicator context only.</p>'}<div class="notice">Simulated fills include quoted spread, configured charges and slippage. Displayed depth caps each fill but does not establish queue position, short-sale eligibility or actual execution.</div></div></section>`;
}
function scalpingPaperForm(){
  const p=state.scalping_paper,schema=state.scalping_paper_schema;
  if(!schema)throw new Error('The scalping paper backend is not loaded.');
  const seed={...p?.config,acknowledge_limitations:false};
  const keys=Object.keys(schema.properties).filter(k=>k!=='strategy_id'&&k!=='acknowledge_limitations');
  modal(p?'Configure scalping paper':'Create scalping paper portfolio',`<form id="scalping-paper-form"><div class="form-section">${strategyPicker('scalping','paper-config-strategy-picker',true)}</div><input type="hidden" name="strategy_id" value="scalping"><div class="notice">One portfolio per strategy. Capital and universe are fixed after creation. Signals and risk settings freeze at session preparation; changes apply next session. Pause entries immediately while exits continue.</div><div class="form-section"><div class="fields">${keys.map(k=>field(k,schema,seed[k])).join('')}</div></div><div class="form-section">${field('acknowledge_limitations',schema,false)}</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">${p?'Save configuration':'Create paper portfolio'}</button></div></form>`);
  if(p)$('#scalping-paper-form').elements.capital.readOnly=true;
}
function readScalpingForm(form){const cfg=readForm(form,state.scalping_schema);if(!cfg.comparison_run_id)delete cfg.comparison_run_id;return cfg;}
async function newScalping(seed={}){
  const request=++backtestDialogRequest;
  modal('Scalping backtest','<p role="status">Checking daily history…</p>');
  let window;
  try{if(seed.comparison_run_id){const reference=await api('runs/'+encodeURIComponent(seed.comparison_run_id));window={start:reference.config.start,end:reference.config.end};}else window=await api('backtest/window?warmup=52');}
  catch(e){if(request===backtestDialogRequest&&$('#modal').open)modal('Scalping backtest',`<div class="form-error">${esc(e.message)}</div>`);return;}
  if(request!==backtestDialogRequest||!$('#modal').open)return;
  if(!window.start){modal('Scalping backtest',`<form><div class="form-section">${strategyPicker('scalping')}</div></form><div class="notice">Fetch daily history in Market data before running scalping research.</div>`);return;}
  const min=window.start>'2022-04-01'?window.start:'2022-04-01',max=window.end;
  const from=new Date(max+'T00:00:00Z');from.setUTCDate(from.getUTCDate()-7);
  const values={start:from.toISOString().slice(0,10)<min?min:from.toISOString().slice(0,10),end:max,...seed},schema=state.scalping_schema;
  const sections=[
    ['Experiment',['name','start','end','capital','direction'],'Use completed sessions. An initial one-week window keeps downloads manageable.'],
    ['Stock selection',['liquidity_days','min_turnover','liquid_universe_size','stock_selection','min_stock_score'],'Scan size caps the selected stocks. Turnover ranks liquidity. Experimental score (0–100) combines prior daily liquidity (20), movement (35), trend consistency (30), and volume activity (15), then applies the minimum score. Scores are not win probabilities; all inputs precede the session.'],
    ['Trend and pullback',['entry_filter','trend_fast','trend_slow','pullback_ema','pullback_bars','ema_touch_bps','entry_buffer_bps'],'EMA mode requires completed five-minute alignment and slope, a one-minute EMA touch and a completed pullback breakout. Candle-only mode uses consecutive five-minute closes for direction.'],
    ['Risk and exits',['min_stop_pct','max_stop_pct','risk_pct','max_positions','target_r','max_holding_minutes','cooldown_minutes','max_trades_per_symbol','daily_loss_pct','participation_pct','first_entry_time','last_entry_time','square_off_time'],'Full notional reserved for both directions. The daily loss limit pauses new entries; existing exits continue. Participation uses signal-minute volume.'],
    ['Execution costs',['slippage_bps','buy_cost_bps','sell_cost_bps'],'Editable assumptions affect sizing and both sides of every trade.']
  ];
  modal('Scalping backtest',`<form id="scalping-form"><div class="form-section">${strategyPicker('scalping')}</div><input type="hidden" name="strategy_id" value="scalping"><input type="hidden" name="comparison_run_id" value="${esc(seed.comparison_run_id||'')}"><div class="notice">One-minute execution; completed five-minute trend context. ${seed.comparison_run_id?'Replay uses frozen inputs and cannot fetch substitutes.':'Missing one-minute sessions and EMA warmup are fetched automatically.'}</div>${sections.map(([title,keys,help])=>`<div class="form-section"><h3>${title}</h3><p>${help}</p><div class="fields">${keys.map(k=>field(k,schema,values[k],['start','end'].includes(k)?{min,max}:null)).join('')}</div></div>`).join('')}<div class="form-section">${field('acknowledge_limitations',schema,false)}</div><div id="scalping-coverage" aria-live="polite"></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="scalping-coverage">Check minute coverage</button><button class="button primary" type="submit" ${activeJob()?'disabled':''}>${seed.comparison_run_id?'Replay frozen & backtest':'Fetch missing & backtest'} →</button></div></form>`);
}
async function scalpingCoverage(){
  const form=$('#scalping-form');if(!form)return;
  const box=$('#scalping-coverage'),error=form.querySelector('.form-error');error.textContent='';box.textContent='Checking one-minute sessions and EMA warmup…';
  try{const cfg=readScalpingForm(form);cfg.acknowledge_limitations=true;const result=await api('scalping/coverage','POST',cfg);if($('#scalping-form')===form)box.textContent=`${result.stock_sessions} stock-sessions · ${result.cached} cached · ${result.missing} ${cfg.comparison_run_id?'unavailable in frozen inputs':'to download'} · approximately ${number(result.estimated_candles,0)} candles including warmup.`;}
  catch(e){if($('#scalping-form')===form){box.textContent='';error.textContent=e.message;}}
}
function scalpingReportDetails(r){
  const d=r.diagnostics;
  const rows=[...['long','short'].map(k=>({name:k,...d[k]})),...(d.time_of_day||[])];
  return `<h3>Scalping execution</h3><div class="stats">${stat('Fees + slippage',money(d.cost_impact),'Modeled total cost drag')}${stat('Average hold',number(d.average_holding_minutes)+' min','Minute intervals')}${stat('Loss-limit sessions',d.daily_loss_halt_sessions,'New entries paused')}${stat('Turnover',money(d.turnover),'Entry plus exit notional')}</div><div class="table-wrap"><table><thead><tr><th>Direction / entry time</th><th>Trades</th><th>Net P&L</th><th>Expectancy</th></tr></thead><tbody>${rows.map(v=>`<tr><td>${esc(v.name)}</td><td>${v.trade_count}</td><td>${money(v.pnl)}</td><td>${number(v.expectancy_r)} R</td></tr>`).join('')}</tbody></table></div>${d.fundamental_checks?.length?`<details><summary>Fundamental entry decisions (${d.fundamental_checks.length})</summary><div class="table-wrap"><table><thead><tr><th>Stock / entry</th><th>Side</th><th>Score</th><th>Coverage</th><th>Financial period / available</th><th>Decision</th></tr></thead><tbody>${d.fundamental_checks.map(v=>`<tr><td>${esc(v.symbol)}<small>${esc(v.date)} ${esc(v.time)}</small></td><td>${esc(v.direction)}</td><td>${v.score??'—'}</td><td>${v.coverage_pct??0}%</td><td>${esc(v.period_end||'Missing')}<small>${esc(v.available_at||'No historical filing')}</small></td><td>${v.allowed?'Passed':'Blocked'}<small>${esc(v.block_reasons.join(' · '))}</small></td></tr>`).join('')}</tbody></table></div></details>`:''}${r.evaluation?`<h3>Earlier versus later sessions</h3><div class="table-wrap"><table><thead><tr><th>Sample</th><th>Dates</th><th>Return</th><th>Drawdown</th><th>Trades</th></tr></thead><tbody>${r.evaluation.segments.map(v=>`<tr><td>${esc(v.name)}</td><td>${esc(v.start)} → ${esc(v.end)}</td><td>${pct(v.return_pct)}</td><td>${number(v.max_drawdown_pct)}%</td><td>${v.trade_count}</td></tr>`).join('')}</tbody></table></div><div class="notice">${esc(r.evaluation.notice)}</div>`:''}`;
}
function readMomentumForm(form){const cfg=readForm(form,state.momentum_schema);if(!cfg.comparison_run_id)delete cfg.comparison_run_id;return cfg;}
function momentumReportDetails(r){
  const d=r.diagnostics;if(!d)return '';
  const rows=[['Long',d.long],['Short',d.short]];
  return `<section class="momentum-diagnostics"><h3>What drove this result</h3><div class="stats">${stat('Before-cost attribution',money(d.pnl_before_modeled_cost_impact),'Same executed trades; sizing still includes costs')}${stat('Fees + slippage',money(d.cost_impact),'Total modeled impact')}${stat('No breakout',d.no_breakout,'Selected stocks without an eligible confirmed entry')}${stat('VWAP rejections',d.vwap_rejected_signals,'Signal candles failing optional confirmation')}${stat('Fundamental blocks',d.fundamental_rejected_entries||0,`${d.fundamental_missing_entries||0} missing historical evidence`)}${stat('Indicator rejections',d.indicator_rejected_signals||0,'Breakout candles failing EMA / MACD gates')}${stat('Candle-quality rejections',d.quality_rejected_signals||0,'Completed candles failing close position or directional body')}</div><div class="table-wrap"><table><thead><tr><th>Direction</th><th>Trades</th><th>Net P&L</th><th>Win rate</th><th>Expectancy</th></tr></thead><tbody>${rows.map(([label,v])=>`<tr><td>${label}</td><td>${v.trade_count}</td><td>${money(v.pnl)}</td><td>${pct(v.win_rate)}</td><td>${number(v.expectancy_r)} R</td></tr>`).join('')}</tbody></table></div>${r.evaluation?`<h3>Earlier versus later sessions</h3><div class="table-wrap"><table><thead><tr><th>Sample</th><th>Dates</th><th>Sessions</th><th>Return</th><th>Drawdown</th></tr></thead><tbody>${r.evaluation.segments.map(v=>`<tr><td>${esc(v.name)}</td><td>${esc(v.start)} → ${esc(v.end)}</td><td>${v.sessions}</td><td>${pct(v.return_pct)}</td><td>${number(v.max_drawdown_pct)}%</td></tr>`).join('')}</tbody></table></div><div class="notice">${esc(r.evaluation.notice)}</div>`:''}</section>`;
}
async function newMomentum(seed={}){
  const request=++backtestDialogRequest;
  modal('Momentum backtest','<p role="status">Checking daily history…</p>');
  let window;
  try{if(seed.comparison_run_id){const reference=await api('runs/'+encodeURIComponent(seed.comparison_run_id));window={start:reference.config.start,end:reference.config.end};}else window=await api('backtest/window?warmup=50');}
  catch(e){if(request===backtestDialogRequest&&$('#modal').open)modal('Momentum backtest',`<div class="form-error">${esc(e.message)}</div>`);return;}
  if(request!==backtestDialogRequest||!$('#modal').open)return;
  if(!window.start){modal('Momentum backtest',`<form><div class="form-section">${strategyPicker('intraday_momentum')}</div></form><div class="notice">Fetch daily history in Market data before running momentum research.</div>`);return;}
  const min=window.start>'2022-04-01'?window.start:'2022-04-01', max=window.end;
  const from=new Date(max+'T00:00:00Z');from.setUTCDate(from.getUTCDate()-30);
  const proposed=from.toISOString().slice(0,10);
  const values={start:proposed<min?min:proposed,end:max,require_fundamentals:!seed.comparison_run_id,...seed};
  const schema=state.momentum_schema;
  modal('Momentum backtest',`<form id="momentum-form"><div class="form-section">${strategyPicker('intraday_momentum')}</div><input type="hidden" name="strategy_id" value="intraday_momentum"><div class="notice">Completed-session research using five-minute candles. ${seed.comparison_run_id?'Frozen test window':'Daily history'}: ${esc(min)} → ${esc(max)}. ${seed.comparison_run_id?'Replay preserves the reference inputs; unavailable sessions cannot be fetched.':'Missing minute sessions are fetched automatically; choose a short initial window.'} Fees and slippage are editable assumptions.</div><input type="hidden" name="comparison_run_id" value="${esc(seed.comparison_run_id||'')}">${seed.comparison_run_id?'<div class="notice">Uses the reference experiment’s frozen inputs. Changes requiring unavailable stock-sessions will fail instead of fetching replacements.</div>':''}${[
    ['Experiment',['name','start','end','capital','direction','execution_mode'],'Choose a date window, modeled starting capital and whether to follow or reverse the original signals.'],
    ['Stock selection',['opening_minutes','volume_lookback','min_relative_volume','liquidity_days','min_turnover','liquid_universe_size','atr_days','min_atr_pct','exclude_symbols','exclude_stock_sessions'],'Daily filters use prior sessions; relative volume compares the same opening interval.'],
    ['Fundamentals before entry',['require_fundamentals','fundamental_min_score','fundamental_min_coverage_pct','fundamental_max_age_days'],'Historical filing publication times determine availability. Missing or stale evidence blocks entry for both sides; blocked slots are not replaced.'],
    ['Entry and protection',['confirmation_minutes','require_vwap','indicator_filter','indicator_minutes','entry_pattern','stop_reference','breakout_buffer_atr','min_close_strength','min_confirmation_body_atr','stop_atr','target_r','breakeven_after_r','risk_pct','max_positions','last_entry_time','square_off_time'],'Choose the completed signal timeframe independently of the opening range. Candle-quality checks use its full range and directional body. Stops update after completed closes and activate next bar.'],
    ['Execution costs',['slippage_bps','buy_cost_bps','sell_cost_bps'],'Costs affect sizing and both sides of every trade.']
  ].map(([title,keys,help])=>`<div class="form-section"><h3>${title}</h3><p>${help}</p><div class="fields">${keys.map(k=>field(k,schema,values[k],['start','end'].includes(k)?{min,max}:null)).join('')}</div></div>`).join('')}<div class="form-section">${field('acknowledge_limitations',schema,false)}</div><div id="momentum-coverage" aria-live="polite"></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="momentum-coverage">Check minute coverage</button><button class="button primary" type="submit" ${activeJob()?'disabled':''}>${seed.comparison_run_id?'Replay frozen & backtest':'Fetch missing & backtest'} →</button></div></form>`);
}
async function momentumCoverage(){
  const form=$('#momentum-form');if(!form)return;
  const box=$('#momentum-coverage'), error=form.querySelector('.form-error');error.textContent='';box.textContent='Checking required five-minute sessions…';
  try{const cfg=readMomentumForm(form);cfg.acknowledge_limitations=true;const result=await api('momentum/coverage','POST',cfg);if($('#momentum-form')===form)box.textContent=`${result.stock_sessions} stock-sessions required · ${result.cached} available in ${result.source||'shared cache'} · ${result.missing} ${cfg.comparison_run_id?'unavailable in frozen inputs (comparison cannot fetch substitutes)':'to download'} · ${result.excluded.length} daily symbols excluded.`;}
  catch(e){if($('#momentum-form')===form){box.textContent='';error.textContent=e.message;}}
}
function readForm(form,schema){const values=new FormData(form), result={};for(const [key,s] of Object.entries(schema.properties)){if(!form.elements[key]){if(s.default!==undefined)result[key]=s.default;continue;}if(s.type==='boolean')result[key]=form.elements[key].type==='hidden'?values.get(key)==='true':values.has(key);else if(s.type==='number'||s.type==='integer')result[key]=Number(values.get(key));else if(s.type==='array')result[key]=String(values.get(key)||'').split(',').map(x=>x.trim()).filter(Boolean);else result[key]=values.get(key);}return result;}
let backtestDialogRequest=0, backtestWindow=null;
function backtestDateBounds(window){return {min:window?.history_start||window?.start||'',max:window?.history_end||window?.end||''};}
function backtestFeeDateIssue(config){
  return config.fee_model==='zerodha_equity'&&config.start&&config.start<'2024-10-01'
    ? 'Zerodha tariff supports tests from 2024-10-01. Choose a start date on or after 2024-10-01, or select Custom buy/sell bps for earlier tests.' : '';
}
function validateBacktestDates(config,window){
  const feeIssue=backtestFeeDateIssue(config);if(feeIssue)throw new Error(feeIssue);
  const bounds=backtestDateBounds(window);
  for(const key of ['start','end']){
    if(bounds.min&&config[key]<bounds.min)throw new Error(`${key==='start'?'Start':'End'} date cannot be earlier than available price history (${bounds.min}). Fetch earlier history in Market data to extend this range.`);
    if(bounds.max&&config[key]>bounds.max)throw new Error(`${key==='start'?'Start':'End'} date cannot be later than the last available test date (${bounds.max}). Fetch newer history in Market data to extend this range.`);
  }
  if(config.start>=config.end)throw new Error('End date must be after start date.');
}

function updateBacktestAvailability(){
  const form=$('#backtest-form');if(!form)return;
  const job=activeJob();
  const reason=job?`${job.type} is ${job.status}. Wait for it to finish; this button will become available automatically.`
    :!backtestWindow?.start?'Not enough downloaded history for a test window. Fetch more history in Market data.'
    :backtestFeeDateIssue({fee_model:form.elements.fee_model?.value,start:form.elements.start?.value});
  const submit=form.querySelector('[type="submit"]');
  submit.disabled=Boolean(reason)||form.dataset.submitting==='true';
  const notice=$('#backtest-availability');notice.textContent=reason;notice.hidden=!reason;
}
async function selectBacktestStrategy(value){if(value==='investor_early_breakout')return newBacktest({pattern:value});return ['scalping','intraday_momentum'].includes(value)?newBacktest({strategy_id:value}):newBacktest({screen:value});}
async function newBacktest(seed={}){
  if(state.reference_only){
    const preset=(state.screens||[]).find(p=>p.id===(seed.screen||seed.screen_id))||(state.screens||[]).find(p=>p.pattern===(seed.pattern||'vcp'))||state.screens?.[0];
    if(!preset)throw new Error('No strategy is available. Reload the workspace.');
    seed={...screenPreset(preset.id),...seed,screen:preset.id,simulation_model:'banana_proxy_v1'};
    delete seed.strategy_id;
  }
  if(seed.strategy_id==='intraday_momentum')return newMomentum(seed);
  if(seed.strategy_id==='scalping')return newScalping(seed);
  const investor=seed.pattern==='investor_early_breakout';
  const screenValue=seed.pattern==='investor_early_breakout'?'investor_early_breakout':seed.screen||seed.screen_id||`${isBearishPattern(seed.pattern)?'bearish':'builtin'}:${seed.pattern||'vcp'}`;
  seed={candidate_rank:'fundamental_score',max_positions:5,...screenPreset(screenValue),...(isBearishPattern(seed.pattern)||screenValue.startsWith('bearish:')?{candidate_rank:'alphabetical',execution_horizon:'intraday',entry_mode:'next_open',borrow_cost_bps_year:0,square_off_time:'15:00'}:{}),...seed,screen:screenValue};
  if(investor)seed={name:'Investor early breakout · technical baseline',candidate_rank:'alphabetical',entry_mode:'next_open',execution_horizon:'swing',buy_cost_bps:10,sell_cost_bps:10,slippage_bps:10,...seed,candidate_rank:seed.candidate_rank==='fundamental_score'?'alphabetical':seed.candidate_rank,investor_rules:seed.investor_rules||investorState?.queues?.scan?.rules||{}};
  const dialogRequest=++backtestDialogRequest;
  modal('New backtest','<p role="status">Checking downloaded history and available test dates…</p>');
  let window;
  try {window = await api('backtest/window?warmup='+Math.max(investor?100:50,seed.base_days||25,seed.sma_days||50,seed.minimum_warmup_sessions||50,seed.min_rs_rating>0||seed.candidate_rank==='rs_126'?126:50,(seed.min_short_rs_rating>0||seed.min_rs_improvement>0)?(seed.rs_short_lookback||63)+(seed.min_rs_improvement>0?(seed.rs_improvement_sessions||20):0):50,seed.require_rising_long_trend?220:seed.require_long_trend?200:50,['multiyear','multiyear_breakdown'].includes(seed.pattern)?seed.multiyear_base_days||260:50,isBearishPattern(seed.pattern)?Math.max(126,seed.require_falling_long_trend?219:0,seed.pattern==='new_lows'?seed.low_lookback_days||252:0,seed.pattern==='vcp_breakdown'?(seed.vcp_window_days||10)*3:0):50)+(seed.comparison_run_id?'&reference_id='+encodeURIComponent(seed.comparison_run_id):''));}
  catch(error){if(dialogRequest===backtestDialogRequest&&$('#modal').open)modal('New backtest',`<div class="form-error" role="alert">${esc(error.message)}</div><button class="button" data-action="close">Close</button>`);return;}
  if(dialogRequest!==backtestDialogRequest||!$('#modal').open)return;
  seed={start:window.start||'',end:window.end||'',capital:1000000,pattern:'vcp',entry_mode:'pivot',winner_exit:'trail_50d',skip_weak_markets:false,buy_cost_bps:0,sell_cost_bps:0,...seed};
  const coverage=seed.comparison_run_id ? `Frozen test window: ${esc(window.start)} → ${esc(window.end)}. ${window.ready_symbols} eligible stocks; ${window.missing_symbols?.length||0} preserved exclusions. Entries and indicators use the saved price history. No current data is substituted.` : window.start ? `<strong>History loaded:</strong> ${window.history_start} → ${window.history_end}. <strong>Safe test window:</strong> ${window.start} → ${window.end}. The sessions before the safe window are warmup context for indicators and the first signal; they are not included in the reported backtest period. This window is the common overlap across ${window.ready_symbols} of ${window.total_symbols} symbols with enough history. Stocks with missing data, insufficient date coverage or warmup are skipped and listed in the report. <button type="button" class="text-button" data-action="use-dates" data-start="${window.start}" data-end="${window.end}">Use safe test window</button>` : 'Fetch more daily history before running a backtest. There must be enough sessions for indicator warmup and testing.';
  const bearish=isBearishPattern(seed.pattern), schema=investor?structuredClone(state.backtest_schema):bearish?state.bearish_backtest_schema:state.backtest_schema;
  const groups=[['Experiment',['strategy','screen','name','start','end','capital','minimum_warmup_sessions'],'Select a strategy and review the settings saved with this run.'],['Screen filters',['base_days','max_depth_pct','volume_multiple','sma_days','require_long_trend','require_rising_long_trend','min_rs_rating','rs_short_lookback','min_short_rs_rating','rs_improvement_sessions','min_rs_improvement','min_turnover','vcp_window_days','vcp_volume_multiple','blue_sky_lookback_days','multiyear_base_days','multiyear_max_depth_pct','ipo_max_age_days'],'The screen determines which completed daily setups qualify. IPO base is intended for young listings; Blue sky uses long-history highs.'],['Entry, risk & exits',['entry_mode','candidate_rank','risk_pct','stop_pct','winner_exit','sector_filter','skip_weak_markets','market_breadth_scope','market_breadth_pct','market_min_coverage_pct','breakeven_r','trail_pct','max_positions','max_hold_days'],'Entry and winner-exit choices follow the reference workflow. Breakeven, trailing fallback and holding limit remain explicit assumptions for reproducibility.'],['Execution costs',['slippage_bps','buy_cost_bps','sell_cost_bps'],'Record brokerage, taxes and slippage explicitly for each experiment.']];
  if(bearish){groups[1]=['Bearish screen filters',Object.keys(state.bearish_schema.properties).filter(k=>k!=='pattern'),'Downside qualification uses completed sessions, weak relative strength and the configured weak-market gate.'];groups[2][1]=groups[2][1].filter(k=>!['sector_filter','skip_weak_markets','market_breadth_scope','market_breadth_pct','market_min_coverage_pct'].includes(k));groups[3][1].push('borrow_cost_bps_year');}
  if(!bearish){groups[3][1].unshift('fee_model');groups[3][2]='Choose custom bps or the Zerodha NSE equity tariff. Zerodha mode requires a test start on or after 2024-10-01 and includes statutory charges and DP; custom buy/sell bps are ignored. For earlier tests, select Custom buy/sell bps and enter your cost assumptions. Slippage applies separately.';groups.push(['Swing refinements',['max_open_gap_pct','require_open_above_pivot','max_extension_pct','reentry_cooldown_sessions','stalled_exit_sessions','stalled_min_r','failed_breakout_sessions','market_risk_scale','market_breadth_trend_sessions'],'These controls require long swing next-open execution. Zero disables an optional filter or exit. Early exits use the next open after their closing signal.']);}
  groups[2][1].push('execution_horizon','square_off_time');
  if(!bearish)groups[2][1].push('max_sector_positions');
  if(investor){
    groups[0]=['Investor technical experiment',['screen','name','start','end','capital','minimum_warmup_sessions'],'Tests the early-breakout scanner on completed daily bars. Entry is at the next session open. Financial and news assessments are excluded.'];
    const rulesSchema=state.backtest_schema.$defs.Rules;
    groups[1]=['Early-breakout rules',Object.keys(rulesSchema.properties).map(k=>'investor_'+k),'Only confirmed early_breakout setups enter. Approaching-breakout distance and dry-volume rules are watchlist controls and do not trigger trades.'];
    groups[2][1]=groups[2][1].filter(k=>!['entry_mode','execution_horizon','square_off_time'].includes(k));
    schema.properties.candidate_rank.enum=schema.properties.candidate_rank.enum.filter(k=>k!=='fundamental_score');
  }
  const renderBacktestField=k=>{if(investor&&k.startsWith('investor_')){const key=k.slice(9),rulesSchema=state.backtest_schema.$defs.Rules;return field(key,rulesSchema,seed.investor_rules[key]).replaceAll('name="'+key+'"','name="'+k+'"');}return field(k,schema,seed[k],['start','end'].includes(k)?backtestDateBounds(window):null);};
  const reference=seed.simulation_model==='banana_proxy_v1';
  const selectedReference=(state.screens||[]).find(s=>s.id===screenValue);
  if(reference){
    seed.start=seed.start===window.start?'2020-01-01':seed.start;
    seed.end=seed.end===window.end?'2026-09-30':seed.end;
    groups.splice(1,groups.length-1,
      ['Reference execution',['entry_mode','risk_pct','stop_pct','max_positions','reference_same_day','reference_cap_pct','reference_turnover_pct'],'RS priority uses .4/.2/.2/.2 weighted returns ranked in the local universe. Fixed stop; SMA50 close breach exits next open; sale proceeds available next session; end-date holdings stay marked. Reference entry-day ordering is an explicit OHLC assumption.'],
      ['Costs',['buy_cost_bps','sell_cost_bps'],'Equal rates required. Default 25 bps per order. No additional slippage.']);
  }
  backtestWindow=window;
  modal('New backtest',`${seed.comparison_run_id?`<div class="notice">Using frozen prices, membership and financial evidence from run ${esc(seed.comparison_run_id)}.</div>`:''}<div class="notice">${coverage}</div><div class="notice warn">Current-constituent universe; corporate actions and historical membership unverified. This run is for exploring rules, not proving an edge.</div>${reference?referenceScreenDetails(selectedReference,false)+`<div class="notice warn">Historical ₹300 crore market-cap filter and nested base structure cannot be enforced from this dataset. Base windows: VCP/IPO 30 sessions, multi-year 252, Blue sky highest loaded close. All source thresholds are shown above; legacy filters are not used.</div>`:''}<form id="backtest-form">${reference?['simulation_model','candidate_rank','winner_exit','fee_model','slippage_bps','sector_filter'].map(k=>`<input type="hidden" name="${k}" value="${esc(seed[k])}">`).join(''):''}<input type="hidden" name="pattern" value="${esc(seed.pattern)}">${seed.comparison_run_id?`<input type="hidden" name="comparison_run_id" value="${esc(seed.comparison_run_id)}">`:""}${groups.map(([title,keys,help])=>`<div class="form-section"><h3>${title}</h3><p>${help}</p><div class="fields">${keys.map(renderBacktestField).join('')}</div></div>`).join('')}<div class="form-section">${field('acknowledge_limitations',schema,false)}</div><div id="backtest-availability" class="notice warn" role="status"></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">Run backtest →</button></div></form>`);
  if(reference)$('#backtest-form').elements.entry_mode.querySelector('option[value="close"]')?.remove();
  updateBacktestAvailability();
}
async function showChart(isin){const item=state.instruments.find(x=>x.isin===isin);if(!item)return;modal(item.name,`<p>Loading historical candles…</p>`);
  const data=await api('bars/'+encodeURIComponent(isin));if(!$('#modal').open)return;
  modal(item.name,`<div class="actions" style="justify-content:space-between;margin-bottom:18px"><span class="badge">${esc(item.symbol)} · NSE · 1D</span><strong>${money(item.close)} <span class="${item.change>=0?'positive':'negative'}">${pct(item.change)}</span></strong></div><div id="stock-chart" class="chart" aria-label="Daily candlestick chart. Drag to pan, scroll to zoom."></div><div class="chart-info">${data.bars.length} real daily candles · ${data.bars[0].date} — ${data.bars.at(-1).date} · Upstox<br>Corporate-action adjustments unverified. Drag to pan; scroll to zoom.</div>`);
  chart=klinecharts.init('stock-chart',{locale:'en-US',timezone:'Asia/Kolkata',styles:document.documentElement.dataset.theme});
  chart.setStyles({grid:{horizontal:{color:'#e9e2db'},vertical:{show:false}},candle:{bar:{upColor:'#d26624',downColor:'#c77565',upBorderColor:'#d26624',downBorderColor:'#c77565',upWickColor:'#d26624',downWickColor:'#c77565'}}});
  chart.createIndicator('VOL');chart.applyNewData(data.bars);chart.setBarSpace(5);
  observer=new ResizeObserver(()=>chart?.resize());observer.observe($('#stock-chart'));
}
function equitySvg(curve){if(!curve.length)return '';const vals=curve.map(x=>x.equity), min=Math.min(...vals), max=Math.max(...vals), span=max-min||1;const points=vals.map((v,i)=>`${20+i/(vals.length-1||1)*860},${200-(v-min)/span*170}`).join(' ');return `<svg class="equity-chart" viewBox="0 0 900 230" role="img" aria-label="Equity curve from ${money(vals[0])} to ${money(vals.at(-1))}"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#d26624" stop-opacity=".17"/><stop offset="100%" stop-color="#d26624" stop-opacity="0"/></linearGradient></defs>${[30,85,140,200].map(y=>`<line x1="20" y1="${y}" x2="880" y2="${y}" stroke="var(--line)" stroke-dasharray="4 4"/>`).join('')}<polygon points="20,215 ${points} 880,215" fill="url(#area)"/><polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2"/></svg><div class="equity-labels"><span>${curve[0].date} · ${money(vals[0])}</span><span>${curve.at(-1).date} · ${money(vals.at(-1))}</span></div>`;}
let tradeMarkerRegistered=false, tradeChartRequest=0;
function registerTradeMarker(){
  if(tradeMarkerRegistered)return;
  klinecharts.registerOverlay({name:'tradeFill',totalStep:1,needDefaultPointFigure:false,needDefaultXAxisFigure:false,needDefaultYAxisFigure:false,
    createPointFigures:({coordinates,overlay,bounding})=>{
      if(!coordinates.length)return [];
      const {x,y}=coordinates[0], {side,label}=overlay.extendData;
      const color=side==='buy'?'#bd4c13':side==='signal'?'#5879c6':'#b95548', labelY=y+(side==='buy'?24:side==='signal'?-48:-24);
      return [{type:'circle',attrs:{x,y,r:5},styles:{style:'stroke_fill',color,borderColor:'#ffffff',borderSize:2},ignoreEvent:true},
        {type:'line',attrs:{coordinates:[{x,y},{x,y:labelY}]},styles:{color,size:1},ignoreEvent:true},
        {type:'text',attrs:{x:Math.min(x+9,bounding.width-8),y:labelY,text:label,align:x>bounding.width-140?'right':'left',baseline:'middle'},styles:{color:'#ffffff',backgroundColor:color,size:11,paddingLeft:5,paddingRight:5,paddingTop:3,paddingBottom:3,borderRadius:3},ignoreEvent:true}];
    }});
  tradeMarkerRegistered=true;
}
let tradeChartSeries=[];
function tradeIndicatorFigures(series){return series.map(s=>({key:s.id,title:s.label+': ',type:'line',styles:()=>({color:s.color,size:s.id==='protective_stop'?2:1.3})}));}
function tradeExplanation(data){
  const e=data.explanation;if(!e)return '';
  return `<div class="trade-line-controls" aria-label="Chart indicator lines">${e.series.map(s=>`<label><input type="checkbox" class="trade-line-toggle" data-line="${esc(s.id)}" checked><span style="color:${esc(s.color)}">━</span> ${esc(s.label)}</label>`).join('')}</div>`;
}
function tradeSignalDetails(data){
  const e=data.explanation;if(!e)return '';
  return `<section class="trade-signal-details"><h3>Why this trade qualified</h3><p>${esc(({vcp_breakdown:'VCP breakdown',new_lows:'52-week low',multiyear_breakdown:'Multi-year breakdown',ipo_breakdown:'IPO base breakdown',vcp:'VCP',blue_sky:'Blue sky',multiyear:'Multi-year breakout',ipo:'IPO base',investor_early_breakout:'Investor early breakout',breakout:'Legacy breakout'})[e.pattern]||e.pattern)} · Signal ${esc(e.signal?.date||'unavailable')} · Entry ${esc(({pivot:'Pivot breakout',close:'Signal close',next_open:'Next session open'})[e.entry_mode]||e.entry_mode)} · Winner exit ${esc(({trail_50d:'50-day trailing average',trail_30w:'30-week trailing average',take_8:'+8% target',take_15:'+15% target',take_25:'+25% target'})[e.winner_exit]||e.winner_exit)} · Priority ${e.candidate_rank==='fundamental_score'?'Fundamental score':e.candidate_rank==='prior_turnover'?'Prior-session turnover':e.candidate_rank==='opening_relative_volume'?'Opening relative volume':e.candidate_rank==='rs_126'?(isBearishPattern(e.pattern)?'Weakest relative strength first':'Relative strength'):'Alphabetical'}</p><div class="table-wrap"><table><thead><tr><th>Condition</th><th>Signal-session value</th><th>Required</th><th>Check</th></tr></thead><tbody>${e.checks.map(c=>`<tr><td>${esc(c.label)}</td><td>${typeof c.actual==='number'?number(c.actual):esc(c.actual??'Unavailable')}</td><td>${esc(c.required)}</td><td class="${c.passed===true?'positive':c.passed===false?'negative':''}">${c.passed===true?'Passed':c.passed===false?'Failed':c.actual!=null?'Context':'Unavailable'}</td></tr>`).join('')}</tbody></table></div><div class="notice">${e.notices.map(n=>esc(n)).join('<br>')}</div></section>`;
}
function stockTradeMarkers(data){
  return (data.trades||[{...data.trade,trade_index:data.trade_index}]).flatMap((t,i)=>[
    {side:t.direction==='short'?'sell':'buy',date:t.entry_date,timestamp:t.entry_timestamp,price:t.entry,label:`${t.direction==='short'?'SHORT':'BUY'} #${i+1} ${money(t.entry)}`},
    {side:t.direction==='short'?'buy':'sell',date:t.exit_date,timestamp:t.exit_timestamp,price:t.exit,label:`${t.direction==='short'?'COVER':'SELL'} #${i+1} ${money(t.exit)}`}
  ]);
}
function stockTradeList(data){
  const trades=data.trades||[{...data.trade,trade_index:data.trade_index}];
  return `<h3>All ${esc(data.symbol)} trades in this backtest (${trades.length})</h3><p>Indicators and the signal explanation refer to the selected trade. Select another trade below to inspect its setup.</p><div class="table-wrap"><table><thead><tr><th>Trade</th><th>Entry</th><th>Exit</th><th>Shares</th><th>Net P&amp;L</th><th>Exit reason</th></tr></thead><tbody>${trades.map((t,i)=>`<tr><td><button class="text-button" data-action="trade-chart" data-run="${esc(data.run_id)}" data-trade="${t.trade_index}" ${t.trade_index===data.trade_index?'aria-current="true"':''}>#${i+1}${t.trade_index===data.trade_index?' · selected':''}</button></td><td>${esc(t.entry_date)}<small>${money(t.entry)}</small></td><td>${esc(t.exit_date)}<small>${money(t.exit)}</small></td><td>${number(t.quantity,0)}</td><td class="${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</td><td>${esc(t.reason)}</td></tr>`).join('')}</tbody></table></div>`;
}
async function showTradeChart(runId,tradeIndex){
  const request=++tradeChartRequest;
  modal('Trade chart',`<button class="text-button" data-action="back-to-report" data-id="${esc(runId)}">← Back to report</button><p>Loading saved backtest candles…</p>`);
  let data;
  try{data=await api(`runs/${encodeURIComponent(runId)}/trades/${tradeIndex}/chart`);}
  catch(error){if(request===tradeChartRequest&&$('#modal').open)modal('Trade chart',`<button class="text-button" data-action="back-to-report" data-id="${esc(runId)}">← Back to report</button><div class="notice warn">${esc(error.message)}</div>`);return;}
  if(request!==tradeChartRequest||!$('#modal').open||!$('#modal-content [data-action="back-to-report"]'))return;
  const t=data.trade;
  modal(`${data.symbol} · Trade chart`,`<div class="actions" style="justify-content:space-between;margin-bottom:18px"><button class="text-button" data-action="back-to-report" data-id="${esc(runId)}">← Back to report</button><span class="badge">${esc(data.symbol)} · ${data.trades?.length||1} trades · ${data.interval_minutes?data.interval_minutes+'m':'1D'} · Saved backtest data</span></div><div class="trade-chart-summary"><div><span class="${t.direction==='short'?'negative':'positive'}">● ${t.direction==='short'?'Sold short':'Bought'}</span><strong>${money(t.entry)}</strong><small>${esc(t.entry_date)}${t.entry_time?' · '+esc(t.entry_time)+' IST':''}</small></div><div><span class="${t.direction==='short'?'positive':'negative'}">● ${t.direction==='short'?'Bought to cover':'Sold'}</span><strong>${money(t.exit)}</strong><small>${esc(t.exit_date)}${t.exit_time?' · '+esc(t.exit_time)+' IST':''}</small></div><div><span>Net P&L · ${number(t.quantity,0)} shares</span><strong class="${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</strong><small>${esc(t.reason)}</small></div></div>${tradeExplanation(data)}<div id="stock-chart" class="chart trade-chart" aria-label="${data.interval_minutes?data.interval_minutes+'-minute':'Daily'} candles for ${esc(data.symbol)} with bought and sold markers"></div><div class="chart-info">All buys and sells for this stock in this backtest are numbered in matching pairs. Markers show the recorded execution prices, including modeled slippage. Candles come from this run's frozen input snapshot. Drag to pan; scroll to zoom.<br>${data.interval_minutes?'Minute candles identify intervals, not exact tick times for stop/target fills. The mandatory cutoff uses its bar open.':'Daily candles do not show the time of execution within a session.'} Corporate-action adjustments remain unverified.</div>${stockTradeList(data)}${tradeSignalDetails(data)}`);
  chart=klinecharts.init('stock-chart',{locale:'en-US',timezone:'Asia/Kolkata',styles:document.documentElement.dataset.theme});
  chart.setStyles({grid:{horizontal:{color:'#e9e2db'},vertical:{show:false}},candle:{bar:{upColor:'#d26624',downColor:'#c77565',upBorderColor:'#d26624',downBorderColor:'#c77565',upWickColor:'#d26624',downWickColor:'#c77565'}}});
  tradeChartSeries=data.explanation?.series||[];
  if(tradeChartSeries.length){
    klinecharts.registerIndicator({name:'TRADE_CONTEXT',shortName:'Trade',series:'price',precision:2,figures:tradeIndicatorFigures(tradeChartSeries),calc:rows=>rows.map(row=>row.chart_values||{})});
    chart.createIndicator('TRADE_CONTEXT',true,{id:'candle_pane'});
  }
  chart.createIndicator('VOL');chart.applyNewData(data.bars);
  chart.setOffsetRightDistance(20);
  chart.setBarSpace(Math.max(2,Math.min(12,($('#stock-chart').clientWidth-90)/data.bars.length)));
  registerTradeMarker();
  if(data.explanation?.signal&&!data.interval_minutes){const s=data.explanation.signal;chart.createOverlay({name:'tradeFill',lock:true,points:[{timestamp:s.timestamp,value:s.price}],extendData:{side:'signal',label:'SIGNAL'}});}
  for(const marker of stockTradeMarkers(data)){
    const bar=data.bars.find(b=>marker.timestamp?b.timestamp===marker.timestamp:b.date===marker.date);if(!bar)continue;
    chart.createOverlay({name:'tradeFill',lock:true,points:[{timestamp:bar.timestamp,value:marker.price}],extendData:{side:marker.side,label:marker.label}});
  }
  observer=new ResizeObserver(()=>chart?.resize());observer.observe($('#stock-chart'));
}
function tradeTable(r){
  const keys={symbol:'Symbol',entry_date:'Entry date',exit_date:'Exit date',quantity:'Quantity',pnl:'Net P&L',r:'R',reason:'Exit reason'};
  const sorted=[...r.trades].sort((a,b)=>{const av=a[tradeSort.key]??'',bv=b[tradeSort.key]??'';const cmp=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv));return tradeSort.direction==='asc'?cmp:-cmp;});
  const head=key=>{const active=tradeSort.key===key, arrow=active?(tradeSort.direction==='asc'?' ↑':' ↓'):'';return `<th class="${['quantity','pnl','r'].includes(key)?'right':''}" aria-sort="${active?(tradeSort.direction==='asc'?'ascending':'descending'):'none'}"><button class="sort-button" data-action="sort-trades" data-sort="${key}">${keys[key]}${arrow}</button></th>`};
  return `<div class="table-wrap"><table><thead><tr>${head('symbol')}${head('entry_date')}${head('quantity')}${head('pnl')}${head('r')}${head('reason')}</tr></thead><tbody>${sorted.map(t=>`<tr><td><button class="symbol-button" data-action="trade-chart" data-run="${esc(r.id)}" data-trade="${r.trades.indexOf(t)}" aria-label="View ${esc(t.symbol)} buy and sell chart">${esc(t.symbol)} ↗</button></td><td>${t.entry_date}${t.entry_time?` ${esc(t.entry_time)}`:''}<small>→ ${t.exit_date}${t.exit_time?` ${esc(t.exit_time)} IST`:''}</small></td><td class="right">${t.quantity}</td><td class="right ${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</td><td class="right">${number(t.r)}</td><td>${esc(t.reason)}</td></tr>`).join('')||'<tr><td colspan="6">No trades met these rules in this interval.</td></tr>'}</tbody></table></div>`;
}
function swingResearchDetails(r){
  if(!r.cost_model)return '';
  const labels={brokerage:'Brokerage',stt:'STT',exchange:'NSE exchange',ipft:'IPFT',sebi:'SEBI',stamp:'Stamp duty',dp:'DP',gst:'GST'};
  const amounts=Object.fromEntries(Object.keys(labels).map(k=>[k,r.trades.reduce((sum,t)=>sum+(t.charges?.[k]||0),0)]));
  const rejected=Object.entries(r.entry_filter_rejections||{});
  const selection=r.research_selection;
  return `<details><summary>${esc(r.cost_model.name)} · cost breakdown</summary><p>${esc(r.cost_model.notice)}</p><div class="detail-grid">${Object.entries(labels).map(([k,label])=>`<div><span>${label}</span>${money(amounts[k])}</div>`).join('')}</div>${rejected.length?`<p>Refinement rejections: ${rejected.map(([reason,count])=>`${esc(reason)}: ${count}`).join(' · ')}</p>`:''}${selection?`<p>Calibration: ${esc(selection.calibration)} · Validation: ${esc(selection.validation)} · Audit: ${esc(selection.audit)}. ${selection.trials} configurations tested. ${esc(selection.notice)}</p>`:''}</details>`;
}
async function showResult(id){const r=await api('runs/'+id);selectedRun=r;const m=r.metrics;
  modal(r.config.name,detailTabs('backtest','Results',`<div class="actions" style="justify-content:space-between;margin-bottom:20px"><span class="badge">${r.strategy_id==='scalping'?'Scalping':r.strategy_id==='intraday_momentum'?'Intraday momentum':'Swing Pattern'} · ${esc(r.config.pattern||(r.strategy_id==='scalping'?'pullback continuation':'opening range'))} · ${r.config.direction||(isBearishPattern(r.config.pattern)?'short':'long')} · ${r.strategy_id==='scalping'?'intraday 1m':r.strategy_id==='intraday_momentum'||r.config.execution_horizon==='intraday'?'intraday 5m':'daily bars'}</span><div class="actions"><span class="badge warn">Exploratory · ${esc(r.universe)}</span><button class="button small" data-action="clone">Adjust & rerun</button></div></div><div class="stats">${stat('Net return',pct(m.return_pct),'After modeled costs',m.return_pct>0)}${stat('Max drawdown',number(m.max_drawdown_pct)+'%',m.drawdown_basis||'Marked daily')}${stat('Expectancy',number(m.expectancy_r)+' R',m.trade_count+' trades')}${stat('Win rate',m.win_rate==null?'—':number(m.win_rate)+'%','Losses included')}</div><div class="notice warn">Current constituents: survivorship bias remains. Corporate-action adjustment status: unverified. ${r.data_quality?`Gap check: ${esc(r.data_quality.gap_threshold_pct)}% threshold; ${r.data_quality.excluded_symbols?.length?`${r.data_quality.excluded_symbols.length} stocks skipped for unresolved gaps`:`no unresolved gaps in included stocks`}; passing does not establish clean data.`:`This historical report predates the price-gap safeguard.`}</div>${priceGapWarnings(r.data_quality)}${swingResearchDetails(r)}<h3>Portfolio equity</h3>${equitySvg(r.curve)}<div class="notice" style="margin-top:22px">Modeled fees: ${money(m.modeled_fees)} · Slippage impact: ${money(m.modeled_slippage)} · Profit factor: ${number(m.profit_factor)}${m.modeled_borrow_costs!=null?` · Borrow costs: ${money(m.modeled_borrow_costs)}`:''} · Entries skipped by filters or portfolio limits: ${m.skipped_entries}</div><details><summary>Data limitations & run assumptions</summary><ul>${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul><p>Excluded symbols (price gaps, history, warmup or IPO listing evidence): ${esc(r.excluded.join(', ')||'None')}</p><div class="detail-grid">${Object.entries(r.config).filter(([k])=>k!=='acknowledge_limitations').map(([k,v])=>`<div><span>${esc((r.strategy_id==='scalping'?state.scalping_schema:r.strategy_id==='intraday_momentum'?state.momentum_schema:isBearishPattern(r.config.pattern)?state.bearish_backtest_schema:state.backtest_schema)?.properties[k]?.title||k)}</span>${esc(v&&typeof v==='object'?JSON.stringify(v):v)}</div>`).join('')}</div></details>${r.strategy_id==='scalping'?scalpingReportDetails(r):r.strategy_id==='intraday_momentum'?momentumReportDetails(r):''}<h3 style="margin:24px 0 16px">The complete trade record <small>Click a stock for its trade chart; click a column to sort</small></h3>${tradeTable(r)}${sectorReport(r)}`,`<h3>Backtest settings</h3><p class="settings-context">The configuration recorded with this backtest when it was run. Current strategy defaults do not change these values.</p>${settingsTable(r.config,r.strategy_id==='scalping'?state.scalping_schema:r.strategy_id==='intraday_momentum'?state.momentum_schema:isBearishPattern(r.config.pattern)?state.bearish_backtest_schema:state.backtest_schema)}`));
}
function method(){modal('From a base to a complete record',`<p>The first research strategy looks for a close above a prior price base, confirmed by volume, a moving-average trend filter and minimum turnover.</p><ol><li><strong>Wait for a base.</strong> Measure its length and depth using prior completed candles.</li><li><strong>Confirm at the close.</strong> Check breakout, volume and trend conditions.</li><li><strong>Enter at the next open.</strong> Size within the risk budget and cash available, including modeled costs.</li><li><strong>Manage the exit.</strong> Start with a fixed stop; move to cost-adjusted breakeven and trail after the configured R trigger. New stops activate next session.</li><li><strong>Keep the full record.</strong> Preserve every trade, loss, cost assumption and input dataset.</li></ol><div class="notice">This implementation is long-only and uses daily bars. Current constituent bias and unverified adjustments remain. Relative-strength and separate base-formation strategies are planned next.</div>`);}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;const action=button.dataset.action;
  try{
    if(action==='detail-tab'){activateDetailTab(button);return;}
    if(action==='use-dates'){const form=$('#backtest-form');form.elements.start.value=button.dataset.start;form.elements.end.value=button.dataset.end;form.querySelector('.form-error').textContent='';updateBacktestAvailability();return;}
    if(action==='close'){$('#modal').close();return;}
    if(action==='method'){method();return;}
    if(action==='new-momentum'){await newMomentum();return;}
    if(action==='new-scalping'){await newScalping();return;}
    if(action==='scalping-paper-config'){scalpingPaperForm();return;}
    if(action==='scalping-paper-start'){await api('scalping/paper/start','POST');toast('Standalone quote runner requested.');await refresh();return;}
    if(action==='scalping-paper-stop'){await api('scalping/paper/stop','POST');toast('Stop requested. Positions await fresh quotes for liquidation.');await refresh();return;}
    if(action==='scalping-paper-status'){await api('scalping/paper/status','PUT',{status:state.scalping_paper.status==='active'?'paused':'active'});await refresh();return;}
    if(action==='scalping-paper-export'){const p=await api('scalping/paper/export');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}));a.download='scalping-paper.json';a.click();URL.revokeObjectURL(a.href);return;}
    if(action==='scalping-coverage'){await scalpingCoverage();return;}
    if(action==='scalping-compare'){await api('jobs/scalping-comparison','POST',{reference_id:button.dataset.id});toast('Three confirmation variants queued on frozen inputs.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-compare'){await api('jobs/momentum-comparison','POST',{reference_id:button.dataset.id});toast('Six matched-data comparisons queued.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-research'){await api('jobs/momentum-comparison','POST',{reference_id:button.dataset.id,suite:'research'});toast('Twelve declared research comparisons queued.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-fundamentals'){await api('jobs/momentum-comparison','POST',{reference_id:button.dataset.id,suite:'fundamentals'});toast('Matched control and fundamentals-filtered backtests queued.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-pullbacks'){await api('jobs/momentum-comparison','POST',{reference_id:button.dataset.id,suite:'pullbacks'});toast('Seven pullback comparisons queued.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-indicators'){await api('jobs/momentum-comparison','POST',{reference_id:button.dataset.id,suite:'indicators'});toast('Seven indicator comparisons queued.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-stronger'){await api('jobs/momentum-comparison','POST',{reference_id:button.dataset.id,suite:'stronger'});toast('Seven stronger-entry comparisons queued.');location.hash='jobs';await refresh();return;}
    if(action==='momentum-coverage'){await momentumCoverage();return;}
    if(action==='choose-backtest'){chooseBacktestStrategy();return;}
    if(action==='launch-backtest'){await selectBacktestStrategy($('#launcher-strategy-picker').value);return;}
    if(action==='choose-paper'){choosePaperStrategy();return;}
    if(action==='start-paper'){const value=$('#new-paper-strategy').value;selectedPaperStrategy=value==='scalping'?'scalping':'swing_patterns';selectedPaperScenario=selectedPaperStrategy==='swing_patterns'?'scenario_'+Date.now().toString(36):null;paperForm(value==='scalping'?undefined:value);return;}
    if(action==='new-backtest'){if(button.dataset.screen)await newBacktest({screen:button.dataset.screen});else chooseBacktestStrategy();return;}
    if(action==='new-screen'){newScreen();return;}
    if(action==='bearish-screen'){newBearishScreen(button.dataset.pattern);return;}
    if(action==='bearish-backtest'){await newBacktest(readForm($('#bearish-form'),state.bearish_schema));return;}
    if(action==='configure-paper'){paperForm();return;}
    if(action==='paper-preset'){selectedPaperStrategy='swing_patterns';selectedPaperScenario='scenario_'+Date.now().toString(36);paperForm(button.dataset.screen);return;}
    if(action==='open-paper-portfolio'){selectedPaperStrategy=button.dataset.strategy;selectedPaperScenario=button.dataset.id==='swing_patterns'?null:button.dataset.id;openPaperDetails();return;}
    if(action==='new-paper-scenario'){selectedPaperStrategy='swing_patterns';selectedPaperScenario='scenario_'+Date.now().toString(36);paperForm();return;}
    if(action==='paper-opportunities-export'){const path=paperPath('opportunities');const data=await api(path+(path.includes('?')?'&':'?')+'cycle_id='+encodeURIComponent(button.dataset.cycle));const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='paper-opportunities.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    if(action==='paper-export'){const blob=new Blob([JSON.stringify(paperPortfolio(),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`${selectedPaperStrategy}-paper-portfolio.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    if(action==='backfill-history'){button.disabled=true;await api('jobs/backtest-history','POST',selectedRun.config);$('#modal').close();location.hash='jobs';toast('Missing daily history and warmup queued. Rerun the backtest after completion.');await refresh();return;}
    if(action==='frozen-clone'){await newBacktest({...selectedRun.config,comparison_run_id:selectedRun.id,name:selectedRun.config.name+' · frozen comparison'});return;}
    if(action==='clone'){await newBacktest({...selectedRun.config,...(['intraday_momentum','scalping'].includes(selectedRun.strategy_id)||selectedRun.sector_reference?{comparison_run_id:selectedRun.id}:{}),...(isBearishPattern(selectedRun.config.pattern)?{execution_horizon:selectedRun.config.execution_horizon||'swing'}:{}),name:selectedRun.config.name+' · revised'});return;}
    if(action==='sort-trades'){const key=button.dataset.sort;tradeSort=tradeSort.key===key?{key,direction:tradeSort.direction==='asc'?'desc':'asc'}:{key,direction:key==='pnl'||key==='r'||key==='quantity'?'desc':'asc'};if(selectedRun)await showResult(selectedRun.id);return;}
    if(action==='export'){const blob=new Blob([JSON.stringify(selectedRun,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`trader-${selectedRun.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    if(action==='logs'){const job=state.jobs.find(j=>j.id===button.dataset.id)||await api('jobs/'+encodeURIComponent(button.dataset.id));modal(job.type,`<p>${when(job.created_at)} · ${badge(job.status)}</p><div class="log" id="job-log" data-job="${job.id}">${job.logs.map(l=>`${when(l.at)}  ${esc(l.message)}`).join('\n')||'Queued. Waiting for the worker.'}</div>`);return;}
    if(action==='chart'){await showChart(button.dataset.isin);return;}
    if(action==='result'||action==='back-to-report'){tradeChartRequest++;await showResult(button.dataset.id);return;}
    if(action==='trade-chart'){await showTradeChart(button.dataset.run,Number(button.dataset.trade));return;}
    button.disabled=true;
    if(action==='audit-data'){modal('Price-history audit','<p>Checking cached prices and sourced history policies…</p>');const q=await api('data-quality');if(!$('#modal').open)return;modal('Price-history audit',`<div class="notice warn">Adjustment status: unverified. ${esc(q.notice)}</div><p>${number(q.symbols_scanned,0)} symbols scanned · ${number(q.findings.length,0)} unresolved gaps at or above ${esc(q.gap_threshold_pct)}%. Raw cache gaps: ${number(q.raw_findings?.length??q.findings.length,0)}. History policies applied: ${esc((q.history_changes||[]).map(h=>h.symbol+(h.quarantine?' (quarantined)':` (${h.removed_prelisting_bars} prelisting candles excluded${h.candle_repairs?.length?`; ${h.candle_repairs.length} sourced candle repairs`:''})`)).join(', ')||'None')}. Missing history: ${esc(q.missing_symbols.join(', ')||'None')}.</p>${q.listing_evidence?`<p>Verified exchange listing dates: ${number(q.listing_evidence.verified_exchange_listing_symbols.length,0)} / ${number(q.listing_evidence.total_symbols,0)}. Verified initial IPO dates: ${number(q.listing_evidence.verified_ipo_symbols.length,0)} / ${number(q.listing_evidence.total_symbols,0)} (${esc(q.listing_evidence.verified_ipo_symbols.join(', ')||'None')}). ${esc(q.listing_evidence.notice)}</p>`:''}<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Previous session</th><th>Session</th><th>Previous close</th><th>Open</th><th>Gap</th></tr></thead><tbody>${q.findings.map(f=>`<tr><td>${esc(f.symbol)}</td><td>${esc(f.previous_date)}</td><td>${esc(f.date)}</td><td>${money(f.previous_close)}</td><td>${money(f.open)}</td><td>${pct(f.gap_pct)}</td></tr>`).join('')||'<tr><td colspan="6">No large gaps detected; adjustments remain unverified.</td></tr>'}</tbody></table></div><p>This audit reads current cached prices. Historical report inputs may differ. Verify corporate actions and instrument identity before repairing data.</p>`);return;}
    if(action==='refresh-stocks'){await api('jobs/ingest?include_fundamentals=false','POST');toast('Stock list and price refresh started. Follow progress in Jobs & logs.');}
    if(action==='refresh-fundamentals'){await api('company/fundamentals-pull','POST');toast('Quarterly fundamentals refresh started. Follow progress in Jobs & logs.');}
    if(action==='refresh-market-news'){const job=await api('investor/refresh','POST',{force:true});investorPending=job.id;toast('News refresh started. Follow progress in Jobs & logs.');}
    if(action==='refresh-universe'){await api('jobs/universe','POST');toast('Universe refresh started.');}
    if(action==='sector-audit'){await showSectorAudit();return;}
    if(action==='fetch-sectors'){await api('jobs/sectors','POST');toast('Sector mappings and index history queued.');location.hash='jobs';await refresh();return;}
    if(action==='sector-compare'){await api('jobs/sector-comparison','POST',{reference_id:button.dataset.id});toast('Three sector-filter trials queued on shared frozen inputs.');$('#modal').close();location.hash='jobs';await refresh();return;}
    if(action==='fetch-data'){await api('jobs/ingest','POST');toast('Prices, candles and quarterly fundamentals fetch started for all 750 stocks. Follow progress in Jobs & logs.');}
    if(action==='paper-cycle'){await api(paperPath('cycle'),'POST');toast('Paper daily cycle queued. Follow progress in Jobs & logs.');}
    if(action==='paper-status'){await api(paperPath('status'),'PUT',{status:paperPortfolio().status==='active'?'paused':'active'});toast('Portfolio status updated. Pausing blocks new buys; daily cycles still manage exits.');}
    await refresh();
  }catch(error){toast(error.message);}finally{button.disabled=false;}
});
document.addEventListener('keydown',event=>{
  const tab=event.target.closest?.('[role="tab"][data-action="detail-tab"]');
  if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=[...tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]')],index=tabs.indexOf(tab);
  const next=tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];
  event.preventDefault();activateDetailTab(next);next.focus();
});
document.addEventListener('change',event=>{
  updateParameterControl(event.target);
  if(event.target.id==='backtest-strategy-picker'&&event.target.closest('form')){selectBacktestStrategy(event.target.value);return;}
  if(event.target.classList?.contains('trade-line-toggle')){
    if(chart){const enabled=new Set([...document.querySelectorAll('.trade-line-toggle:checked')].map(input=>input.dataset.line));chart.overrideIndicator({name:'TRADE_CONTEXT',figures:tradeIndicatorFigures(tradeChartSeries.filter(s=>enabled.has(s.id)))},'candle_pane');}return;
  }
  if(event.target.id==='paper-config-strategy-picker'){const value=event.target.value;selectedPaperStrategy=value==='scalping'?'scalping':'swing_patterns';selectedPaperScenario=selectedPaperStrategy==='swing_patterns'?'scenario_'+Date.now().toString(36):null;paperForm(value==='scalping'?undefined:value);return;}
  if(event.target.id==='paper-form-strategy-picker'){selectedPaperStrategy=event.target.value;selectedPaperScenario=selectedPaperStrategy==='swing_patterns'?'scenario_'+Date.now().toString(36):null;paperForm();return;}
  if(event.target.id==='paper-strategy-picker'){selectedPaperStrategy=event.target.value;selectedPaperScenario=null;render();return;}
  if(event.target.id==='paper-scenario-picker'){selectedPaperScenario=event.target.value||null;render();return;}
  const form=event.target.closest('form');
  if(!form||!['backtest-form','paper-form','screen-form'].includes(form.id))return;
  if(event.target.id==='screen-picker'){if(form.id==='backtest-form'&&(event.target.value==='investor_early_breakout'||form.elements.pattern.value==='investor_early_breakout')){selectBacktestStrategy(event.target.value);return;}const candidate=screenPreset(event.target.value);if(form.id==='backtest-form'&&isBearishPattern(candidate.pattern)!==isBearishPattern(form.elements.pattern.value)){applyScreenPreset(form,event.target.value);selectBacktestStrategy(event.target.value);return;}if(['scalping','intraday_momentum'].includes(event.target.value)){if(form.id==='paper-form'){selectedPaperStrategy='scalping';selectedPaperScenario=null;paperForm();}else selectBacktestStrategy(event.target.value);return;}const next=screenPreset(event.target.value);if(form.id==='paper-form'&&(screenPreset(event.target.value,true).simulation_model==='banana_proxy_v1'||form.elements.simulation_model?.value==='banana_proxy_v1')){paperForm(event.target.value);return;}if(form.id==='backtest-form'&&(next.simulation_model==='banana_proxy_v1'||form.elements.simulation_model?.value==='banana_proxy_v1')){newBacktest({screen:event.target.value,...next});return;}applyScreenPreset(form,event.target.value);}
  else if(form.id==='screen-form'&&event.target.name==='pattern')applyScreenPreset(form,`builtin:${event.target.value}`);
  if(form.id==='backtest-form')updateBacktestAvailability();
});
document.addEventListener('submit',async event=>{
  if(event.target.id==='bearish-form'){event.preventDefault();await submitBearishScreen(event.target);return;}
  const form=event.target;if(!['settings-form','token-form','backtest-form','screen-form','paper-form','momentum-form','scalping-form','scalping-paper-form'].includes(form.id))return;event.preventDefault();const submit=form.querySelector('[type="submit"]'), errorBox=form.querySelector('.form-error');submit.disabled=true;form.dataset.submitting='true';errorBox.textContent='';
  try{
    if(form.id==='scalping-paper-form'){await api('scalping/paper/portfolio',state.scalping_paper?'PUT':'POST',readForm(form,state.scalping_paper_schema));$('#modal').close();toast('Scalping paper settings saved.');}
    if(form.id==='scalping-form'){const cfg=readScalpingForm(form);await api('jobs/scalping','POST',cfg);$('#modal').close();location.hash='jobs';toast('Scalping backtest queued; missing one-minute data will be fetched.');}
    if(form.id==='momentum-form'){const cfg=readMomentumForm(form);await api('jobs/momentum','POST',cfg);$('#modal').close();location.hash='jobs';toast('Momentum backtest queued; missing five-minute data will be fetched.');}
    if(form.id==='settings-form'){await api('settings','PUT',readForm(form,state.settings_schema));toast('Data settings saved.');}
    if(form.id==='token-form'){const input=form.elements.access_token;const token=input.value.trim();await api('connection','PUT',{access_token:token});input.value='';toast('Token saved on the server. Fetch data to validate access.');}
    if(form.id==='screen-form'){const payload={name:form.elements.name.value.trim(),pattern:form.elements.pattern.value};screenKeys.forEach(k=>{const schema=state.backtest_schema.properties[k];payload[k]=schema.type==='boolean'?form.elements[k].checked:schema.type==='number'||schema.type==='integer'?Number(form.elements[k].value):form.elements[k].value;});await api('screens','POST',payload);$('#modal').close();toast('Screen saved. It is now available in new backtests.');}
    if(form.id==='backtest-form'){const schema=isBearishPattern(form.elements.pattern.value)?state.bearish_backtest_schema:state.backtest_schema;const config=readForm(form,schema);for(const k of Object.keys(config))if(!form.elements[k])delete config[k];if(config.pattern==='investor_early_breakout'){config.entry_mode='next_open';config.execution_horizon='swing';config.investor_rules=Object.fromEntries(Object.entries(state.backtest_schema.$defs.Rules.properties).map(([k,s])=>[k,s.type==='boolean'?form.elements['investor_'+k].checked:Number(form.elements['investor_'+k].value)]));}if(form.elements.screen)config.screen_id=form.elements.screen.value;validateBacktestDates(config,backtestWindow);await api('jobs/backtest','POST',config);$('#modal').close();location.hash='jobs';toast('Backtest queued.');}
    if(form.id==='paper-form'){const config=readForm(form,paperSchema());config.screen_id=form.elements.screen.value;await api(paperPath('portfolio'),paperPortfolio()?'PUT':'POST',config);$('#modal').close();location.hash='paper';toast('Paper portfolio saved.');}
    await refresh();
  }catch(error){errorBox.textContent=error.message;errorBox.scrollIntoView({block:'nearest'});}finally{form.dataset.submitting='false';submit.disabled=false;updateBacktestAvailability();}
});
document.addEventListener('input',event=>{updateParameterControl(event.target);if(event.target.id==='instrument-search')$('#instrument-table').innerHTML=instrumentTable(event.target.value);if(event.target.closest('form')?.id==='backtest-form')updateBacktestAvailability();});
$('#modal').addEventListener('close',()=>{bearishScanRequest++;tradeChartRequest++;disposeChart();});
window.addEventListener('hashchange',()=>{if($('#modal').open)$('#modal').close();render();window.scrollTo(0,0);});
$('#theme-toggle').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=theme;localStorage.setItem('trader-theme',theme);$('#theme-toggle').setAttribute('aria-label',`Switch to ${theme==='light'?'dark':'light'} theme`);chart?.setStyles(theme);});
try{document.documentElement.dataset.theme=localStorage.getItem('trader-theme')||'light';}catch{/* storage unavailable */}
async function poll(){if(polling||!state)return;polling=true;try{const live=()=>currentView==='scalping'||(currentView==='paper'&&selectedPaperStrategy==='scalping')?String(state.scalping_paper?.updated_at||'')+String(state.scalping_runner?.heartbeat_at||''):'';const previous=state.jobs.map(j=>j.id+j.status+j.logs.length).join('|')+live();await refresh(false);const next=state.jobs.map(j=>j.id+j.status+j.logs.length).join('|')+live();if(previous!==next){if(!['settings','live'].includes(currentView)&&!$('#modal').open)render();const log=$('#job-log');if(log){const job=state.jobs.find(j=>j.id===log.dataset.job);if(job)log.textContent=job.logs.map(l=>`${when(l.at)}  ${l.message}`).join('\n');}}}catch{/* keep last state; explicit refresh surfaces an error */}finally{polling=false;}}
if(typeof MutationObserver!=='undefined')new MutationObserver(()=>cleanWorkspaceCopy(document.body)).observe(document.body,{childList:true,subtree:true,characterData:true});
refresh().catch(error=>{$('#view').innerHTML=empty('The workspace could not load',error.message);});
setInterval(poll,3000);
