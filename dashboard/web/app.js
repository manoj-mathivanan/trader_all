'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => n == null ? '—' : '₹' + Number(n).toLocaleString('en-IN',{maximumFractionDigits:2});
const number = (n, digits=2) => n == null ? '—' : Number(n).toLocaleString('en-IN',{maximumFractionDigits:digits});
const pct = n => n == null ? '—' : `${n>0?'+':''}${number(n)}%`;
const when = s => s ? new Date(s).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})+' IST' : 'Not yet';
const universeName = () => state.settings.universe === 'nifty50' ? 'Nifty 50' : 'Nifty 500';
let state, chart, observer, selectedRun, toastTimer, polling = false;
let tradeSort = {key:'exit_date', direction:'desc'};
let currentView = 'overview';
let selectedPaperStrategy = 'swing_patterns';
const paperPortfolio = () => state.paper_portfolios?.[selectedPaperStrategy] ?? (selectedPaperStrategy==='swing_patterns'?state.paper_portfolio:null);
const paperSchema = () => state.paper_schemas?.[selectedPaperStrategy] ?? (selectedPaperStrategy==='swing_patterns'?state.paper_schema:null);
const paperPath = action => `strategies/${encodeURIComponent(selectedPaperStrategy)}/paper/${action}`;
const nav = [['overview','Overview','▦'],['data','Market data','⌁'],['backtests','Backtests','↗'],['paper','Paper trading','◎'],['jobs','Jobs & logs','≡'],['settings','Settings','⚙']];

async function api(path, method='GET', body) {
  const response = await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Trader-Request':'local-ui'},...(body === undefined ? {} : {body:JSON.stringify(body)})});
  if(!response.ok) {
    let data; try {data=await response.json();} catch {throw new Error('The server could not complete this request.');}
    const message=Array.isArray(data.detail) ? data.detail.map(x=>`${x.loc?.slice(1).join('.')}: ${x.msg}`).join('; ') : data.detail;
    throw new Error(message || 'Request failed.');
  }
  return response.json();
}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),5500);}
function badge(status){return `<span class="badge ${esc(status)}">${esc(status)}</span>`;}
function disposeChart(){observer?.disconnect();observer=null;if(chart){klinecharts.dispose('stock-chart');chart=null;}}
function modal(title, body){disposeChart();$('#modal-content').innerHTML=`<div class="dialog-head"><h2>${esc(title)}</h2><button class="icon-button" data-action="close" aria-label="Close dialog">×</button></div><div class="dialog-body">${body}</div>`;if(!$('#modal').open)$('#modal').showModal();}
function empty(title, copy, action='', label='Get started', symbol='⌁'){return `<div class="empty"><div class="empty-symbol">${symbol}</div><h3>${esc(title)}</h3><p>${esc(copy)}</p>${action?`<a class="button primary" href="#${action}">${esc(label)} <span>↗</span></a>`:''}</div>`;}
function heading(title, subtitle, actions='', context){return `<div class="page-heading"><div><div class="eyebrow">${esc(context||'SWING PATTERNS / '+universeName().toUpperCase())}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></div>`;}
function stat(label,value,hint,positive=false){return `<div class="stat"><div class="label">${esc(label)}<span>↗</span></div><div class="value ${positive?'positive':''}">${esc(value)}</div><div class="hint">${esc(hint)}</div></div>`;}
function activeJob(){return state.jobs.find(j=>['running','queued'].includes(j.status));}
function pending(){const job=activeJob();return job?`<div class="pending" role="status"><i></i>${esc(job.type)} · ${esc(job.status)} <a href="#jobs" class="text-button">View progress →</a></div>`:'';}
function jobRows(jobs){return jobs.map(j=>`<div class="job-card"><div><strong>${esc(j.type)}</strong><small>${when(j.created_at)} · ${esc(j.id)}</small></div><div class="actions">${badge(j.status)}<button class="text-button" data-action="logs" data-id="${esc(j.id)}">View logs ↗</button></div></div>`).join('');}
function overview(){
  const loaded=state.instruments.filter(x=>x.count), count=state.instruments.reduce((sum,x)=>sum+x.count,0), latest=state.runs[0];
  return heading('A clearer view of your next trade.','Your rules, your research, your trading workspace.',`<a class="button" href="#data">⌁ &nbsp; Manage data</a><button class="button primary" data-action="new-backtest">＋ New backtest</button>`)+pending()+
  `<div class="stats">${stat('Universe',universeName(),`${state.instruments.length || 'No'} constituents loaded`)}${stat('Historical coverage',`${loaded.length} / ${state.instruments.length || '—'}`,`${number(count,0)} daily candles`,true)}${stat('Backtest runs',state.runs.length,latest?'Latest: '+latest.config.name:'Your first experiment starts here')}${stat('Execution mode',state.paper_portfolio?'Paper':'Research',state.paper_portfolio?`${Object.keys(state.paper_portfolio.ledger.positions||{}).length} simulated positions · no live orders`:(state.paper_enabled?'Create a portfolio in Paper trading':'Paper trading runs in production'))}</div>
  <div class="grid-main"><section class="panel"><div class="panel-head"><div><h2>Your research, at a glance</h2><p>Every result starts with a traceable dataset.</p></div><span class="badge">End of day</span></div>${latest?`<div class="panel-body"><span class="intro-label">LATEST EXPERIMENT · ${esc(latest.config.name)}</span><div class="stats">${stat('Net return',pct(latest.metrics.return_pct),'After modeled costs',latest.metrics.return_pct>0)}${stat('Trades',latest.metrics.trade_count,'Winners and losers included')}</div><button class="button" data-action="result" data-id="${latest.id}">Open complete report ↗</button></div>`:empty('A clean slate. Real data first.','Connect Upstox, fetch your universe, and test an idea. Results will appear here when your first backtest finishes.','settings','Connect your data','↗')}</section>
  <section class="panel"><div class="panel-head"><div><h2>Build your first experiment</h2><p>Three steps from data to a trade ledger.</p></div></div><div class="onboarding">
  ${step(1,'Connect Upstox','Save your access token on the server.',state.token_saved,'settings','Connection settings')}
  ${step(2,'Load market history',`Fetch daily OHLCV for ${universeName()}; later runs fetch only missing boundaries.`,loaded.length>0,'data','Open market data')}
  ${step(3,'Put your rules to the test','Choose entries, exits and costs. Keep every result.',state.runs.length>0,'backtests','Open backtests')}
  </div></section></div>
  <div class="method-strip"><div class="method-art">↗</div><div><div class="eyebrow">THE METHOD, BEFORE THE METRICS</div><h3>Wait for the base. Test the breakout. Define the risk.</h3><p>Signals at the close. Entries at the next open. Losses, costs and drawdowns are part of the record.</p></div><button class="text-button" data-action="method">How it works ↗</button></div>
  <section class="panel"><div class="panel-head"><h2>Recent activity</h2><a class="text-button" href="#jobs">All jobs →</a></div>${state.jobs.length?jobRows(state.jobs.slice(0,3)):empty('No jobs yet','Data fetches and backtests will leave a status and an inspectable log here.','','','≡')}</section>`;
}
function step(n,title,copy,done,target,label){return `<div class="step ${done?'done':''}"><span class="step-no">${done?'✓':n}</span><div><h3>${title}</h3><p>${copy}</p><a class="text-button" href="#${target}">${label} →</a></div></div>`;}
function dataView(){return heading('Know the data behind the signal.','Inspect your universe, daily candles and historical coverage.',`<button class="button" data-action="audit-data">Audit price history</button><button class="button" data-action="refresh-universe" ${activeJob()?'disabled':''}>↻ Refresh universe</button><button class="button primary" data-action="fetch-data" ${!state.token_saved||activeJob()?'disabled':''}>↓ Fetch missing data</button>`)+pending()+
 `<div class="notice">${esc(universeName())} · Requested history: <strong>${esc(state.settings.start)} → ${esc(state.settings.end)}</strong>. <a href="#settings">Change universe or dates</a>. Universe refreshed: ${when(state.universe_updated)}.</div>
 <div class="notice warn">This is today's constituent list. Historical membership, delisted stocks and corporate-action adjustments are not yet verified. Coverage is reported honestly; exploratory results do not establish an edge.</div>
 <div class="toolbar"><label class="search"><span class="sr-only">Search instruments</span><input id="instrument-search" placeholder="Search by symbol, company or sector…" autocomplete="off"></label><span class="status-line">${state.instruments.length} instruments · Upstox daily OHLCV</span></div>
 <section class="panel"><div id="instrument-table">${instrumentTable('')}</div></section>`;}
function instrumentTable(query){const rows=state.instruments.filter(x=>`${x.symbol} ${x.name} ${x.sector}`.toLowerCase().includes(query.toLowerCase()));
  if(!state.instruments.length)return empty('Load your investable universe','Refresh the universe to download the official constituents and match their Upstox instrument keys.');
  if(!rows.length)return empty('No matching instruments','Try a symbol, company name or another sector.');
  return `<div class="table-wrap"><table><thead><tr><th>COMPANY / SYMBOL</th><th>SECTOR</th><th class="right">LAST CLOSE</th><th class="right">CHANGE</th><th class="right">BARS</th><th>HISTORY AVAILABLE</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td><button class="symbol-button" data-action="chart" data-isin="${esc(x.isin)}" ${x.count?'':'disabled'}>${esc(x.symbol)}</button><small>${esc(x.name)}</small></td><td>${esc(x.sector)}</td><td class="right">${money(x.close)}</td><td class="right ${x.change>=0?'positive':'negative'}">${pct(x.change)}</td><td class="right">${number(x.count,0)}</td><td>${x.first?`${x.first}<small>through ${x.last}</small>`:'Awaiting data'}</td><td><button class="text-button" data-action="chart" data-isin="${esc(x.isin)}" ${x.count?'':'disabled'}>Chart ↗</button></td></tr>`).join('')}</tbody></table></div>`;}
function backtestsView(){return heading('An idea is only the beginning.','Test the rules. Read the losses. Compare every iteration.',`<button class="button primary" data-action="new-backtest">＋ New backtest</button>`)+pending()+
 `<div class="notice">Swing screens follow the Banana Patterns set: <strong>VCP, Blue sky, Multi-year breakouts and IPO base</strong>. Entry, risk, winner-exit and market-regime dials are recorded with every run.</div>
 ${state.runs.length?`<div class="run-list">${state.runs.map(r=>`<section class="panel run-card"><div><button class="run-name" data-action="result" data-id="${r.id}"><h3>${esc(r.config.name)} ↗</h3></button><p>${esc(r.universe)} · ${r.config.start} — ${r.config.end} · ${when(r.created_at)}</p><span class="badge warn">Exploratory · current constituents</span></div><div class="run-metrics"><div><small>NET RETURN</small><strong class="${r.metrics.return_pct>=0?'positive':'negative'}">${pct(r.metrics.return_pct)}</strong></div><div><small>MAX DRAWDOWN</small>${number(r.metrics.max_drawdown_pct)}%</div><div><small>TRADES</small>${r.metrics.trade_count}</div></div></section>`).join('')}</div>`:`<section class="panel">${empty('Your first backtest belongs here.','Once daily candles are available, run a reproducible experiment with your entry and exit rules. Every result keeps its own data and parameter snapshot.','data','Prepare market data','↗')}</section>`}
 <div class="method-strip"><div><div class="eyebrow">MAKE EACH EXPERIMENT COUNT</div><h3>Change one idea. Keep an untouched test period.</h3><p>A better historical curve can come from overfitting. Tune on an earlier period, then check the rules on later data you have not used to tune them.</p></div></div>`;}
function paperForm(){
  if(!paperSchema())throw new Error('Restart the local server or select an implemented paper strategy.');
  const p=paperPortfolio(), schema=paperSchema(), seed={...p?.config,acknowledge_limitations:false};
  const swing=selectedPaperStrategy==='swing_patterns';
  const keys=Object.keys(schema.properties).filter(k=>!swing||k!=='pattern');
  modal(p?'Configure paper portfolio':'Create paper portfolio',`<div class="notice">Completed-session signals enter at the next open. Capital and the universe are fixed after creation. Changed risk and exit rules apply to new positions; existing positions retain their exit rules.</div><form id="paper-form">${swing?`<input type="hidden" name="pattern" value="${esc(p?.config.pattern||'vcp')}">`:""}<div class="form-section"><div class="fields">${swing?field('screen',schema,p?`builtin:${p.config.pattern}`:'builtin:vcp'):''}${keys.map(k=>field(k,schema,seed[k])).join('')}</div></div><div class="notice">Use all-in charges that include your brokerage, taxes and exchange fees. Rates are estimates. Automatic cycles run after the configured IST time while the production server is running, with one scheduled attempt per weekday. Failed attempts can be retried manually.</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">${p?'Save configuration':'Create paper portfolio'}</button></div></form>`);
  if(p)$('#paper-form').elements.capital.readOnly=true;
  else if(swing)applyScreenPreset($('#paper-form'),'builtin:vcp');
}
function paperView(){
  const p=paperPortfolio();
  const strategy=state.strategies.find(s=>s.id===selectedPaperStrategy);
  const selector=`<div class="toolbar"><label class="field">Strategy portfolio<select id="paper-strategy-picker">${state.strategies.map(s=>`<option value="${esc(s.id)}" ${s.id===selectedPaperStrategy?'selected':''} ${state.paper_schemas?.[s.id]||(s.id==='swing_patterns'&&state.paper_schema)?'':'disabled'}>${esc(s.name)}${state.paper_schemas?.[s.id]||(s.id==='swing_patterns'&&state.paper_schema)?'':' · planned'}</option>`).join('')}</select></label><span class="status-line">Each strategy has its own capital, settings, positions and history.</span></div>`;
  const notice=`<div class="notice warn">Simulated execution using real daily candles. Current membership and corporate-action adjustments remain unverified; the strategy has not passed the edge-validation gate. Fills do not model circuits or liquidity constraints. No real broker orders are placed.</div>`;
  const actions=`<button class="button" data-action="configure-paper" ${activeJob()?'disabled':''}>${p?'Configure portfolio':'＋ Create portfolio'}</button>${p?`<button class="button" data-action="paper-status" ${activeJob()?'disabled':''}>${p.status==='active'?'Pause new entries':'Resume entries'}</button><button class="button primary" data-action="paper-cycle" ${activeJob()||!state.token_saved?'disabled':''}>Run daily cycle</button>`:''}`;
  const head=heading('Practice the rules. Keep the record.','Persistent paper positions, one cash balance per strategy, and every modeled cost.',actions,`${strategy?.name.toUpperCase()||'PAPER'} / ${p?.universe||universeName()}`)+pending()+selector+notice;
  if(!p)return head+`<section class="panel">${empty('Start a forward paper portfolio',`Load real history, choose allocated capital and risk settings, then create the ${strategy?.name||'strategy'} portfolio. Trading begins with sessions after creation; earlier history supplies indicator context.`,'','','◎')}</section>`;
  const l=p.ledger||{}, positions=Object.entries(l.positions||{}), equity=p.metrics?.final_equity??p.config.capital, cash=l.cash??p.config.capital;
  const realized=(l.trades||[]).reduce((sum,t)=>sum+t.pnl,0), unrealized=positions.reduce((sum,[symbol,t])=>sum+(l.marks[symbol]*t.quantity-t.entry_cost),0);
  return head+`<div class="notice">${badge(p.status)} · ${esc(p.universe)} · ${esc(p.config.pattern)} · Begins ${esc(p.start_session)} · Last processed: <strong>${esc(l.last_session||'Awaiting new sessions')}</strong><br>${p.config.auto_run?`Automatic cycle at ${String(p.config.run_hour).padStart(2,'0')}:${String(p.config.run_minute).padStart(2,'0')} IST on weekdays; keep the server running.`:'Automatic cycles are off. Run a daily cycle manually or enable scheduling in Configure portfolio.'} Pausing blocks new entries; cycles continue protective exits. Missed completed sessions are processed in order when the next cycle runs.</div>
  <div class="stats">${stat('Portfolio equity',money(equity),'Includes marked open positions')}${stat('Available cash',money(cash),'No leverage')}${stat('Realized P&L',money(realized),'After modeled charges',realized>0)}${stat('Unrealized P&L',money(unrealized),'Entry fees included; exit fees pending',unrealized>0)}</div>
  <section class="panel"><div class="panel-head"><h2>Open positions · ${positions.length}</h2><span class="badge">Paper only</span></div>${positions.length?`<div class="table-wrap"><table><thead><tr><th>SYMBOL</th><th>ENTRY DATE</th><th class="right">QUANTITY</th><th class="right">ENTRY</th><th class="right">LAST CLOSE</th><th class="right">STOP</th><th class="right">OPEN P&L</th></tr></thead><tbody>${positions.map(([s,t])=>`<tr><td>${esc(s)}</td><td>${esc(t.entry_date)}</td><td class="right">${t.quantity}</td><td class="right">${money(t.entry)}</td><td class="right">${money(l.marks[s])}</td><td class="right">${money(t.stop)}</td><td class="right">${money(l.marks[s]*t.quantity-t.entry_cost)}</td></tr>`).join('')}</tbody></table></div>`:empty('No open positions','Positions appear when completed-session signals qualify and the next session provides an entry.')}</section>
  <section class="panel"><div class="panel-head"><h2>Paper equity</h2><button class="text-button" data-action="paper-export">Export complete ledger ↓</button></div><div class="panel-body">${l.curve?.length?equitySvg(l.curve):'<p>No completed paper sessions yet.</p>'}<p>Modeled fees: ${money(l.total_fees||0)} · Slippage: ${money(l.total_slippage||0)} · Maximum drawdown: ${number(p.metrics?.max_drawdown_pct||0)}%</p></div></section>
  <section class="panel"><div class="panel-head"><h2>Closed trades</h2></div>${paperTrades(l.trades||[])}</section>
  <section class="panel"><div class="panel-head"><h2>Simulated fills</h2></div>${paperOrders(l.orders||[])}</section>`;
}
function paperTrades(trades){return trades.length?`<div class="table-wrap"><table><thead><tr><th>SYMBOL</th><th>ENTRY</th><th>EXIT</th><th class="right">QUANTITY</th><th class="right">BUY / SELL</th><th class="right">FEES</th><th class="right">NET P&L</th><th>REASON</th></tr></thead><tbody>${[...trades].reverse().map(t=>`<tr><td>${esc(t.symbol)}</td><td>${esc(t.entry_date)}</td><td>${esc(t.exit_date)}</td><td class="right">${t.quantity}</td><td class="right">${money(t.entry)} / ${money(t.exit)}</td><td class="right">${money(t.fees)}</td><td class="right">${money(t.pnl)}</td><td>${esc(t.reason)}</td></tr>`).join('')}</tbody></table></div>`:empty('No closed trades','Both winners and losses will be recorded with execution costs.');}
function paperOrders(orders){return orders.length?`<div class="table-wrap"><table><thead><tr><th>SESSION</th><th>SYMBOL</th><th>SIDE</th><th class="right">QUANTITY</th><th class="right">FILL</th><th class="right">FEES</th><th>STATUS</th><th>JOB</th></tr></thead><tbody>${[...orders].reverse().map(o=>`<tr><td>${esc(o.date)}</td><td>${esc(o.symbol)}</td><td>${esc(o.side)}</td><td class="right">${o.quantity}</td><td class="right">${money(o.price)}</td><td class="right">${money(o.fees)}</td><td>${esc(o.status)}</td><td><button class="text-button" data-action="logs" data-id="${esc(o.job_id)}">${esc(o.job_id)}</button></td></tr>`).join('')}</tbody></table></div>`:empty('No fills yet','Every simulated buy and sell will link to its daily-cycle job.');}
function jobsView(){return heading('Nothing happens in the dark.','Every data refresh, backtest and paper cycle has a status and a readable record.',`<button class="button" data-action="reload">↻ Refresh</button>`)+pending()+`<section class="panel"><div class="panel-head"><h2>Job history</h2><span class="badge">Local worker</span></div>${state.jobs.length?jobRows(state.jobs):empty('No jobs yet','Start a universe refresh or a data fetch. Its progress and errors will appear here.','data','Open market data','≡')}</section>`;}
const fieldHelp={
  strategy:'The strategy family that interprets the bars and generates signals. Swing Pattern is the active daily end-of-day strategy; other families will be added when their data and execution modules are ready.',
  screen:'A reusable preset of screen filters. Built-in Banana screens or saved custom screens populate the filter values below.',
  name:'A descriptive name stored with the run or saved screen so you can identify the assumptions later.',
  pattern:'The signal family: VCP looks for contraction and volume dry-up; Blue sky tests a long-history high; Multi-year uses a long base; IPO base targets young listings.',
  start:'First date included in the reported simulation. Earlier bars may still be used for indicator warmup.',
  end:'Last date included in the reported simulation. Open positions are closed using the last available test-bar price.',
  capital:'Starting cash for the simulated portfolio. All positions share this one cash pool.',
  base_days:'Minimum base length in trading sessions used to measure the prior price structure.',
  max_depth_pct:'Maximum percentage drawdown from the base high to the base low. Lower values require shallower bases.',
  volume_multiple:'Breakout volume divided by the prior 50-session average volume. Values above 1 require confirmation.',
  sma_days:'Moving-average length used as the trend filter. The close must be above this average where the screen requires it.',
  min_rs_rating:'Percentile of prior 126-session price return among eligible members of this run’s universe. Zero disables this local RS filter; it is not Banana’s proprietary rating.',
  candidate_rank:'When cash or position slots bind, prioritize alphabetically or by completed-session 126-day strength. Ties use the symbol.',
  require_long_trend:'Require the completed close above the 200-session average as well as the selected trend average.',
  require_rising_long_trend:'Also require the 200-session average to exceed its value 20 sessions earlier. Requires 220 warmup sessions.',
  market_min_coverage_pct:'Minimum fraction of the simulation universe with a dated 200-session average. Insufficient coverage blocks new entries when the market gate is enabled.',
  ipo_max_age_days:'Maximum calendar days since a verified listing date. Missing listing evidence blocks IPO signals; this does not prove first-base identity.',
  market_breadth_pct:'Minimum percentage of eligible universe members above their 200-session average when Skip weak markets is enabled.',
  min_turnover:'Minimum average traded rupee value per day. This filters out illiquid symbols.',
  vcp_window_days:'Length of the most recent VCP contraction window used to compare range tightening.',
  vcp_volume_multiple:'Latest VCP-window volume divided by the prior 50-session average. Lower values require volume dry-up.',
  blue_sky_lookback_days:'Maximum number of prior sessions searched for the all-time or long-history high before the signal.',
  multiyear_base_days:'Minimum sessions in the long base used by the Multi-year screen.',
  multiyear_max_depth_pct:'Maximum depth allowed for the Multi-year base.',
  entry_mode:'Pivot enters at the prior base ceiling when the breakout is reached; close enters at the signal-bar close.',
  risk_pct:'Percentage of current portfolio equity risked if the initial stop is hit. Cash and position limits still apply.',
  stop_pct:'Initial stop distance below the simulated entry price. It defines the first unit of risk.',
  winner_exit:'How profitable positions are managed: 50-day average trail, 30-week average trail, or a fixed +25% target.',
  skip_weak_markets:'When enabled, skip new entries when the percentage of eligible symbols above their 200-session average is below Minimum market breadth. Existing positions continue.',
  breakeven_r:'Profit threshold, measured in initial risk units, after which the stop may move to the cost-adjusted breakeven level.',
  trail_pct:'Fallback percentage below the best close when a moving-average or target exit does not set the stop.',
  max_positions:'Maximum number of simultaneous open positions. New signals are skipped when the limit is full.',
  max_hold_days:'Safety limit on holding sessions. A position is closed when it reaches this age.',
  slippage_bps:'Estimated execution slippage per side in basis points; 100 basis points equals 1%.',
  buy_cost_bps:'All-in modeled charges on buys, expressed in basis points.',
  sell_cost_bps:'All-in modeled charges on sells, expressed in basis points.',
  acknowledge_limitations:'Confirms that this is exploratory research with current-constituent bias, unverified adjustments and hypothetical fills.'
};
function infoLabel(title,key){const help=fieldHelp[key]||'This parameter is recorded with the experiment and controls one part of the selected strategy.';return `<span class="field-label">${esc(title)}<button type="button" class="info-button" aria-label="Explain ${esc(title)}">i<span class="field-tooltip" role="tooltip">${esc(help)}</span></button></span>`;}
function field(key,schema,value,dateBounds=null){
  if(key==='strategy')return `<label class="field">${infoLabel('Strategy',key)}<select name="strategy"><option value="swing_patterns" selected>Swing Pattern</option></select><span class="help">The active daily-bar strategy. Intraday and scalping strategies will appear here when their data and execution modules are ready.</span></label>`;
  if(key==='screen'){const options=[['builtin:vcp','VCP'],['builtin:blue_sky','Blue sky'],['builtin:multiyear','Multi-year breakouts'],['builtin:ipo','IPO base'],...(state?.screens||[]).map(x=>[x.id,`${x.name} · saved`])];return `<label class="field">${infoLabel('Screen',key)}<select name="screen" id="screen-picker">${options.map(([id,label])=>`<option value="${esc(id)}" ${value===id?'selected':''}>${esc(label)}</option>`).join('')}</select><span class="help">Choose a built-in Banana screen or one of your saved custom screens.</span></label>`;}
  const s=schema.properties[key], v=value??s.default??'', req=(schema.required||[]).includes(key)?'required':'';
  const dateAttrs=s.format==='date'&&dateBounds?`${dateBounds.min?`min="${esc(dateBounds.min)}"`:''} ${dateBounds.max?`max="${esc(dateBounds.max)}"`:''} ${dateBounds.min&&dateBounds.max?'':'disabled'}`:'';
  if(s.type==='boolean')return `<label class="field checkbox"><input name="${key}" type="checkbox" ${v?'checked':''} ${req}>${infoLabel(key==='pattern'?'Base screen':s.title,key)}</label>`;
  const options=key==='pattern'?s.enum?.filter(x=>x!=='breakout'):s.enum||(s.const?[s.const]:null);
  const labels={alphabetical:'Symbol order',rs_126:'Highest 126-day strength first',vcp:'VCP',blue_sky:'Blue sky',multiyear:'Multi-year breakouts',ipo:'IPO base',pivot:'Pivot breakout',close:'Close breakout',next_open:'Next session open',trail_50d:'50-day trailing exit',trail_30w:'30-week trailing exit',take_25:'Take profit at +25%'};
  return `<label class="field">${infoLabel(key==='pattern'?'Base screen':s.title,key)}${options?`<select name="${key}" ${req}>${options.map(x=>`<option value="${esc(x)}" ${v===x?'selected':''}>${labels[x]|| (x==='nifty50'?'Nifty 50':x==='nifty500'?'Nifty 500':esc(x))}</option>`).join('')}</select>`:`<input name="${key}" type="${s.format==='date'?'date':s.type==='number'||s.type==='integer'?'number':'text'}" value="${esc(v)}" ${s.type==='integer'?'step="1"':s.type==='number'?'step="any"':''} ${s.minimum!=null?`min="${s.minimum}"`:s.exclusiveMinimum!=null?`min="${s.exclusiveMinimum+.0001}"`:''} ${s.maximum!=null?`max="${s.maximum}"`:''} ${s.maxLength?`maxlength="${s.maxLength}"`:''} ${dateAttrs} ${req} ${s.type==='number'&&v===''?'placeholder="Enter your assumption"':''}>`}${dateBounds&&dateBounds.min&&dateBounds.max?`<span class="help">Available dates: ${esc(dateBounds.min)} → ${esc(dateBounds.max)}</span>`:''}</label>`;
}
function settingsView(){return heading('Your workspace. Your assumptions.','Configure the data source and universe without changing code.')+
 `<div class="split-settings"><section class="panel"><div class="panel-head"><div><h2>Market data</h2><p>Shared history for your strategy experiments.</p></div><span class="badge">Upstox V3</span></div><form id="settings-form"><div class="form-section"><div class="fields">${Object.keys(state.settings_schema.properties).map(k=>field(k,state.settings_schema,state.settings[k])).join('')}</div><p style="margin:16px 0 0">Fetch earlier than your backtest start to provide at least 50 sessions of indicator warmup. Saving settings does not automatically fetch data.</p></div><div class="form-actions"><button class="button primary" type="submit">Save data settings</button></div><div class="form-error" role="alert"></div></form></section>
 <section class="panel"><div class="panel-head"><div><h2>Upstox connection</h2><p>Historical market data access only.</p></div>${badge(state.token_saved?'Token saved':'Not connected')}</div><form id="token-form"><div class="form-section"><label class="field"><span>${state.token_saved?'Replace access token':'Access token'}</span><input type="password" name="access_token" minlength="20" maxlength="10000" autocomplete="off" required placeholder="Paste your Upstox access token"><span class="help">Saved in a private server file. Never returned to the browser or written to job logs. A saved token is checked when data is fetched.</span></label><p style="margin:16px 0 0"><a href="https://account.upstox.com/developer/apps" target="_blank" rel="noreferrer" class="text-button">Open Upstox developer apps ↗</a></p></div><div class="form-actions"><button class="button primary" type="submit">Save token</button></div><div class="form-error" role="alert"></div></form></section></div>
 <div class="notice">${state.remote_enabled?'Remote research workspace.':'Local research workspace.'} ${state.auth_enabled?'Basic authentication is enabled.':'No website login is configured.'} Paper trading uses simulated fills. Live broker orders remain unavailable.</div>
 <section class="panel"><div class="panel-head"><h2>Strategy settings</h2><span class="badge">Per experiment</span></div><div class="panel-body"><p>Entry filters, capital, stops, trailing exits and transaction costs are recorded separately for each backtest. Run settings never overwrite earlier results.</p><button class="button" style="margin-top:16px" data-action="new-backtest">Configure a backtest ↗</button></div></section>`;}
const screenKeys=['base_days','max_depth_pct','volume_multiple','sma_days','require_long_trend','require_rising_long_trend','min_rs_rating','min_turnover','vcp_window_days','vcp_volume_multiple','blue_sky_lookback_days','multiyear_base_days','multiyear_max_depth_pct','ipo_max_age_days'];
// Current Banana screen defaults; keep legacy API defaults for saved experiments.
const builtinScreenFilters={base_days:15,max_depth_pct:35,volume_multiple:1,sma_days:50,require_long_trend:false,require_rising_long_trend:false,min_rs_rating:0,min_turnover:50000000,vcp_window_days:10,vcp_volume_multiple:0.9,blue_sky_lookback_days:5000,multiyear_base_days:260,multiyear_max_depth_pct:50,ipo_max_age_days:730};
function screenPreset(id){
  const custom=(state.screens||[]).find(x=>x.id===id);
  if(custom)return {pattern:custom.pattern,...Object.fromEntries(screenKeys.map(k=>[k,custom[k]??builtinScreenFilters[k]]))};
  const pattern=id.replace('builtin:','');
  if(!['vcp','blue_sky','multiyear','ipo'].includes(pattern))return {};
  return {pattern,...builtinScreenFilters};
}
function applyScreenPreset(form,id){
  const values=screenPreset(id);
  for(const key of ['pattern',...screenKeys]){
    if(form.elements[key]&&values[key]!=null){if(form.elements[key].type==='checkbox')form.elements[key].checked=Boolean(values[key]);else form.elements[key].value=values[key];}
  }
  if(form.elements.screen)form.elements.screen.value=id;
}
function screenForm(){const schema=state.backtest_schema;return `<form id="screen-form"><div class="notice">Save a reusable Swing Pattern screen. These values control pattern qualification; entry, risk, exits and costs remain configurable for each backtest.</div><div class="form-section"><div class="fields">${field('name',{properties:{name:{title:'Screen name',type:'string',maxLength:80}},required:['name']},'My screen')}${field('pattern',schema,'vcp')}</div></div><div class="form-section"><h3>Screen filters</h3><p>Adjust every measurable filter used by the daily-bar pattern engine.</p><div class="fields">${screenKeys.map(k=>field(k,schema)).join('')}</div></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">Save screen →</button></div></form>`;}
function newScreen(){modal('Add a new screen',screenForm());applyScreenPreset($('#screen-form'),'builtin:vcp');}
function render(){
  if(!state)return;
  $('.local-status').innerHTML='<i></i> '+(state.environment==='production'?'Production workspace':'Local workspace');
  currentView=location.hash.slice(1)||'overview';if(!nav.some(x=>x[0]===currentView)||(currentView==='paper'&&!state.paper_enabled))currentView='overview';
  $('#strategies').innerHTML=state.strategies.map(s=>s.status==='active'
    ? `<a class="strategy" href="#overview"><span>⌁</span><div><strong>${esc(s.name)}</strong><small>${esc(s.description)}</small></div></a>`
    : `<div class="strategy planned" title="${esc(s.name)} is registered but not implemented yet"><span>＋</span><div><strong>${esc(s.name)}</strong><small>${esc(s.description)} · ${esc(s.granularity)}</small></div><em>soon</em></div>`).join('');
  $('#saved-screens').innerHTML=(state.screens||[]).map(s=>`<button class="saved-screen" data-action="new-backtest" data-screen="${esc(s.id)}"><span>◇</span><strong>${esc(s.name)}</strong></button>`).join('');
  $('#top-navigation').innerHTML=nav.filter(([id])=>id!=='paper'||state.paper_enabled).map(([id,label,icon])=>`<a class="nav-link ${id===currentView?'active':''}" href="#${id}" ${id===currentView?'aria-current="page"':''}><span class="nav-icon">${icon}</span>${label}${id==='backtests'?`<span class="count">${state.runs.length}</span>`:''}</a>`).join('');
  $('#view').innerHTML=({overview,data:dataView,backtests:backtestsView,paper:paperView,jobs:jobsView,settings:settingsView}[currentView])();
}
async function refresh(redraw=true){state=await api('bootstrap');if(redraw)render();updateBacktestAvailability();}
function readForm(form,schema){const values=new FormData(form), result={};for(const [key,s] of Object.entries(schema.properties)){if(s.type==='boolean')result[key]=values.has(key);else if(s.type==='number'||s.type==='integer')result[key]=Number(values.get(key));else result[key]=values.get(key);}return result;}
let backtestDialogRequest=0, backtestWindow=null;
function backtestDateBounds(window){return {min:window?.history_start||window?.start||'',max:window?.end||window?.history_end||''};}
function validateBacktestDates(config,window){
  const bounds=backtestDateBounds(window);
  for(const key of ['start','end']){
    if(bounds.min&&config[key]<bounds.min)throw new Error(`${key==='start'?'Start':'End'} date cannot be earlier than available price history (${bounds.min}). Fetch earlier history in Market data to extend this range.`);
    if(bounds.max&&config[key]>bounds.max)throw new Error(`${key==='start'?'Start':'End'} date cannot be later than the last available test date (${bounds.max}). Fetch newer history in Market data to extend this range.`);
  }
  if(config.start>config.end)throw new Error('Start date must be on or before end date.');
}

function updateBacktestAvailability(){
  const form=$('#backtest-form');if(!form)return;
  const job=activeJob();
  const missing=backtestWindow?.missing_symbols||[];
  const reason=job?`${job.type} is ${job.status}. Wait for it to finish; this button will become available automatically.`
    :missing.length?`Missing valid candle history for ${missing.join(', ')}. Open Market data and fetch missing data. If ingestion fails, inspect Jobs & logs; invalid provider candles must be resolved before a backtest.`
    :!backtestWindow?.start?'Not enough downloaded history for a test window. Fetch more history in Market data.' : '';
  const submit=form.querySelector('[type="submit"]');
  submit.disabled=Boolean(reason)||form.dataset.submitting==='true';
  const notice=$('#backtest-availability');notice.textContent=reason;notice.hidden=!reason;
}
async function newBacktest(seed={}){
  const screenValue=seed.screen||`builtin:${seed.pattern||'vcp'}`;
  seed={...screenPreset(screenValue),...seed,screen:screenValue};
  const dialogRequest=++backtestDialogRequest;
  modal('New backtest','<p role="status">Checking downloaded history and available test dates…</p>');
  let window;
  try {window = await api('backtest/window?warmup='+Math.max(seed.base_days||25,seed.sma_days||50,seed.minimum_warmup_sessions||50,seed.min_rs_rating>0||seed.candidate_rank==='rs_126'?126:50,seed.require_rising_long_trend?220:seed.require_long_trend?200:50,seed.pattern==='multiyear'?seed.multiyear_base_days||260:50));}
  catch(error){if(dialogRequest===backtestDialogRequest&&$('#modal').open)modal('New backtest',`<div class="form-error" role="alert">${esc(error.message)}</div><button class="button" data-action="close">Close</button>`);return;}
  if(dialogRequest!==backtestDialogRequest||!$('#modal').open)return;
  seed={start:window.start||'',end:window.end||'',capital:1000000,pattern:'vcp',entry_mode:'pivot',winner_exit:'trail_50d',skip_weak_markets:false,buy_cost_bps:0,sell_cost_bps:0,...seed};
  const coverage=window.start ? `<strong>History loaded:</strong> ${window.history_start} → ${window.history_end}. <strong>Safe test window:</strong> ${window.start} → ${window.end}. The sessions before the safe window are warmup context for indicators and the first signal; they are not included in the reported backtest period. This window is the common overlap available across ${window.ready_symbols} of ${window.total_symbols} loaded symbols. <button type="button" class="text-button" data-action="use-dates" data-start="${window.start}" data-end="${window.end}">Use safe test window</button>` : 'Fetch more daily history before running a backtest. There must be enough sessions for indicator warmup and testing.';
  const schema=state.backtest_schema;
  const groups=[['Experiment',['strategy','screen','name','start','end','capital','minimum_warmup_sessions'],'Choose the active Swing Pattern strategy, then select a Banana screen or saved custom screen. Portfolio assumptions remain per run.'],['Banana screen filters',['base_days','max_depth_pct','volume_multiple','sma_days','require_long_trend','require_rising_long_trend','min_rs_rating','min_turnover','vcp_window_days','vcp_volume_multiple','blue_sky_lookback_days','multiyear_base_days','multiyear_max_depth_pct','ipo_max_age_days'],'The screen determines which completed daily setups qualify. IPO base is intended for young listings; Blue sky uses long-history highs.'],['Entry, risk & exits',['entry_mode','candidate_rank','risk_pct','stop_pct','winner_exit','skip_weak_markets','market_breadth_pct','market_min_coverage_pct','breakeven_r','trail_pct','max_positions','max_hold_days'],'Entry and winner-exit choices follow the reference workflow. Breakeven, trailing fallback and holding limit remain explicit assumptions for reproducibility.'],['Execution costs',['slippage_bps','buy_cost_bps','sell_cost_bps'],'Banana-style comparison runs use zero costs; research runs can add brokerage, taxes and slippage explicitly.']];
  backtestWindow=window;
  modal('New backtest',`<div class="notice">${coverage}</div><div class="notice warn">Current-constituent universe; corporate actions and historical membership unverified. This run is for exploring rules, not proving an edge.</div><form id="backtest-form"><input type="hidden" name="pattern" value="${esc(seed.pattern)}">${groups.map(([title,keys,help])=>`<div class="form-section"><h3>${title}</h3><p>${help}</p><div class="fields">${keys.map(k=>field(k,schema,seed[k],['start','end'].includes(k)?backtestDateBounds(window):null)).join('')}</div></div>`).join('')}<div class="form-section">${field('acknowledge_limitations',schema,false)}</div><div id="backtest-availability" class="notice warn" role="status"></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">Run backtest →</button></div></form>`);
  updateBacktestAvailability();
}
async function showChart(isin){const item=state.instruments.find(x=>x.isin===isin);if(!item)return;modal(item.name,`<p>Loading historical candles…</p>`);
  const data=await api('bars/'+encodeURIComponent(isin));if(!$('#modal').open)return;
  modal(item.name,`<div class="actions" style="justify-content:space-between;margin-bottom:18px"><span class="badge">${esc(item.symbol)} · NSE · 1D</span><strong>${money(item.close)} <span class="${item.change>=0?'positive':'negative'}">${pct(item.change)}</span></strong></div><div id="stock-chart" class="chart" aria-label="Daily candlestick chart. Drag to pan, scroll to zoom."></div><div class="chart-info">${data.bars.length} real daily candles · ${data.bars[0].date} — ${data.bars.at(-1).date} · Upstox<br>Corporate-action adjustments unverified. Drag to pan; scroll to zoom.</div>`);
  chart=klinecharts.init('stock-chart',{locale:'en-US',timezone:'Asia/Kolkata',styles:document.documentElement.dataset.theme});
  chart.setStyles({grid:{horizontal:{color:'#e9ede5'},vertical:{show:false}},candle:{bar:{upColor:'#2c8c62',downColor:'#c77565',upBorderColor:'#2c8c62',downBorderColor:'#c77565',upWickColor:'#2c8c62',downWickColor:'#c77565'}}});
  chart.createIndicator('VOL');chart.applyNewData(data.bars);chart.setBarSpace(5);
  observer=new ResizeObserver(()=>chart?.resize());observer.observe($('#stock-chart'));
}
function equitySvg(curve){if(!curve.length)return '';const vals=curve.map(x=>x.equity), min=Math.min(...vals), max=Math.max(...vals), span=max-min||1;const points=vals.map((v,i)=>`${20+i/(vals.length-1||1)*860},${200-(v-min)/span*170}`).join(' ');return `<svg class="equity-chart" viewBox="0 0 900 230" role="img" aria-label="Equity curve from ${money(vals[0])} to ${money(vals.at(-1))}"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#38875d" stop-opacity=".17"/><stop offset="100%" stop-color="#38875d" stop-opacity="0"/></linearGradient></defs>${[30,85,140,200].map(y=>`<line x1="20" y1="${y}" x2="880" y2="${y}" stroke="var(--line)" stroke-dasharray="4 4"/>`).join('')}<polygon points="20,215 ${points} 880,215" fill="url(#area)"/><polyline points="${points}" fill="none" stroke="var(--green)" stroke-width="2"/></svg><div class="equity-labels"><span>${curve[0].date} · ${money(vals[0])}</span><span>${curve.at(-1).date} · ${money(vals.at(-1))}</span></div>`;}
let tradeMarkerRegistered=false, tradeChartRequest=0;
function registerTradeMarker(){
  if(tradeMarkerRegistered)return;
  klinecharts.registerOverlay({name:'tradeFill',totalStep:1,needDefaultPointFigure:false,needDefaultXAxisFigure:false,needDefaultYAxisFigure:false,
    createPointFigures:({coordinates,overlay,bounding})=>{
      if(!coordinates.length)return [];
      const {x,y}=coordinates[0], {side,label}=overlay.extendData;
      const color=side==='buy'?'#24764e':side==='signal'?'#5879c6':'#b95548', labelY=y+(side==='buy'?24:side==='signal'?-48:-24);
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
  return `<section class="trade-signal-details"><h3>Why this trade qualified</h3><p>${esc(({vcp:'VCP',blue_sky:'Blue sky',multiyear:'Multi-year breakout',ipo:'IPO base',breakout:'Legacy breakout'})[e.pattern]||e.pattern)} · Signal ${esc(e.signal?.date||'unavailable')} · Entry ${esc(({pivot:'Pivot breakout',close:'Signal close',next_open:'Next session open'})[e.entry_mode]||e.entry_mode)} · Winner exit ${esc(({trail_50d:'50-day trailing average',trail_30w:'30-week trailing average',take_25:'+25% target'})[e.winner_exit]||e.winner_exit)} · Priority ${e.candidate_rank==='rs_126'?'Relative strength':'Alphabetical'}</p><div class="table-wrap"><table><thead><tr><th>Condition</th><th>Signal-session value</th><th>Required</th><th>Check</th></tr></thead><tbody>${e.checks.map(c=>`<tr><td>${esc(c.label)}</td><td>${typeof c.actual==='number'?number(c.actual):esc(c.actual??'Unavailable')}</td><td>${esc(c.required)}</td><td class="${c.passed===true?'positive':c.passed===false?'negative':''}">${c.passed===true?'Passed':c.passed===false?'Failed':c.actual!=null?'Context':'Unavailable'}</td></tr>`).join('')}</tbody></table></div><div class="notice">${e.notices.map(n=>esc(n)).join('<br>')}</div></section>`;
}
async function showTradeChart(runId,tradeIndex){
  const request=++tradeChartRequest;
  modal('Trade chart',`<button class="text-button" data-action="back-to-report" data-id="${esc(runId)}">← Back to report</button><p>Loading saved backtest candles…</p>`);
  let data;
  try{data=await api(`runs/${encodeURIComponent(runId)}/trades/${tradeIndex}/chart`);}
  catch(error){if(request===tradeChartRequest&&$('#modal').open)modal('Trade chart',`<button class="text-button" data-action="back-to-report" data-id="${esc(runId)}">← Back to report</button><div class="notice warn">${esc(error.message)}</div>`);return;}
  if(request!==tradeChartRequest||!$('#modal').open||!$('#modal-content [data-action="back-to-report"]'))return;
  const t=data.trade;
  modal(`${data.symbol} · Trade chart`,`<div class="actions" style="justify-content:space-between;margin-bottom:18px"><button class="text-button" data-action="back-to-report" data-id="${esc(runId)}">← Back to report</button><span class="badge">${esc(data.symbol)} · 1D · Saved backtest data</span></div><div class="trade-chart-summary"><div><span class="positive">● Bought</span><strong>${money(t.entry)}</strong><small>${esc(t.entry_date)}</small></div><div><span class="negative">● Sold</span><strong>${money(t.exit)}</strong><small>${esc(t.exit_date)}</small></div><div><span>Net P&L · ${number(t.quantity,0)} shares</span><strong class="${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</strong><small>${esc(t.reason)}</small></div></div>${tradeExplanation(data)}<div id="stock-chart" class="chart trade-chart" aria-label="Daily candles for ${esc(data.symbol)} with bought and sold markers"></div><div class="chart-info">Markers show the recorded execution prices, including modeled slippage. Candles come from this run's frozen input snapshot. Drag to pan; scroll to zoom.<br>Daily candles do not show the time of execution within a session. Corporate-action adjustments remain unverified.</div>${tradeSignalDetails(data)}`);
  chart=klinecharts.init('stock-chart',{locale:'en-US',timezone:'Asia/Kolkata',styles:document.documentElement.dataset.theme});
  chart.setStyles({grid:{horizontal:{color:'#e9ede5'},vertical:{show:false}},candle:{bar:{upColor:'#2c8c62',downColor:'#c77565',upBorderColor:'#2c8c62',downBorderColor:'#c77565',upWickColor:'#2c8c62',downWickColor:'#c77565'}}});
  tradeChartSeries=data.explanation?.series||[];
  if(tradeChartSeries.length){
    klinecharts.registerIndicator({name:'TRADE_CONTEXT',shortName:'Trade',series:'price',precision:2,figures:tradeIndicatorFigures(tradeChartSeries),calc:rows=>rows.map(row=>row.chart_values||{})});
    chart.createIndicator('TRADE_CONTEXT',true,{id:'candle_pane'});
  }
  chart.createIndicator('VOL');chart.applyNewData(data.bars);
  chart.setOffsetRightDistance(20);
  chart.setBarSpace(Math.max(2,Math.min(12,($('#stock-chart').clientWidth-90)/data.bars.length)));
  registerTradeMarker();
  if(data.explanation?.signal){const s=data.explanation.signal;chart.createOverlay({name:'tradeFill',lock:true,points:[{timestamp:s.timestamp,value:s.price}],extendData:{side:'signal',label:'SIGNAL'}});}
  for(const [side,day,price] of [['buy',t.entry_date,t.entry],['sell',t.exit_date,t.exit]]){
    const bar=data.bars.find(b=>b.date===day);
    chart.createOverlay({name:'tradeFill',lock:true,points:[{timestamp:bar.timestamp,value:price}],extendData:{side,label:`${side==='buy'?'BUY':'SELL'} ${money(price)}`}});
  }
  observer=new ResizeObserver(()=>chart?.resize());observer.observe($('#stock-chart'));
}
function tradeTable(r){
  const keys={symbol:'Symbol',entry_date:'Entry date',exit_date:'Exit date',quantity:'Quantity',pnl:'Net P&L',r:'R',reason:'Exit reason'};
  const sorted=[...r.trades].sort((a,b)=>{const av=a[tradeSort.key]??'',bv=b[tradeSort.key]??'';const cmp=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv));return tradeSort.direction==='asc'?cmp:-cmp;});
  const head=key=>{const active=tradeSort.key===key, arrow=active?(tradeSort.direction==='asc'?' ↑':' ↓'):'';return `<th class="${['quantity','pnl','r'].includes(key)?'right':''}" aria-sort="${active?(tradeSort.direction==='asc'?'ascending':'descending'):'none'}"><button class="sort-button" data-action="sort-trades" data-sort="${key}">${keys[key]}${arrow}</button></th>`};
  return `<div class="table-wrap"><table><thead><tr>${head('symbol')}${head('entry_date')}${head('quantity')}${head('pnl')}${head('r')}${head('reason')}</tr></thead><tbody>${sorted.map(t=>`<tr><td><button class="symbol-button" data-action="trade-chart" data-run="${esc(r.id)}" data-trade="${r.trades.indexOf(t)}" aria-label="View ${esc(t.symbol)} buy and sell chart">${esc(t.symbol)} ↗</button></td><td>${t.entry_date}<small>→ ${t.exit_date}</small></td><td class="right">${t.quantity}</td><td class="right ${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</td><td class="right">${number(t.r)}</td><td>${esc(t.reason)}</td></tr>`).join('')||'<tr><td colspan="6">No trades met these rules in this interval.</td></tr>'}</tbody></table></div>`;
}
async function showResult(id){const r=await api('runs/'+id);selectedRun=r;const m=r.metrics;
  modal(r.config.name,`<div class="actions" style="justify-content:space-between;margin-bottom:20px"><span class="badge">Swing Pattern · ${esc(r.config.pattern||'breakout')} · daily bars</span><div class="actions"><span class="badge warn">Exploratory · ${esc(r.universe)}</span><button class="button small" data-action="clone">Adjust & rerun</button><button class="button small" data-action="export">Export report JSON ↓</button></div></div><div class="stats">${stat('Net return',pct(m.return_pct),'After modeled costs',m.return_pct>0)}${stat('Max drawdown',number(m.max_drawdown_pct)+'%','Marked daily')}${stat('Expectancy',number(m.expectancy_r)+' R',m.trade_count+' trades')}${stat('Win rate',m.win_rate==null?'—':number(m.win_rate)+'%','Losses included')}</div><div class="notice warn">Current constituents: survivorship bias remains. Corporate-action adjustment status: unverified. ${r.data_quality?`Gap check: ${esc(r.data_quality.gap_threshold_pct)}% threshold; passing does not establish clean data.`:`This historical report predates the price-gap safeguard.`}</div><h3>Portfolio equity</h3>${equitySvg(r.curve)}<div class="notice" style="margin-top:22px">Modeled fees: ${money(m.modeled_fees)} · Slippage impact: ${money(m.modeled_slippage)} · Profit factor: ${number(m.profit_factor)} · Entries skipped by cash/position limits: ${m.skipped_entries}</div><details><summary>Data limitations & run assumptions</summary><ul>${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul><p>Excluded symbols (history, warmup or IPO listing evidence): ${esc(r.excluded.join(', ')||'None')}</p><div class="detail-grid">${Object.entries(r.config).filter(([k])=>k!=='acknowledge_limitations').map(([k,v])=>`<div><span>${esc(state.backtest_schema.properties[k]?.title||k)}</span>${esc(v)}</div>`).join('')}</div></details><h3 style="margin:24px 0 16px">The complete trade record <small>Click a stock for its trade chart; click a column to sort</small></h3>${tradeTable(r)}`);
}
function method(){modal('From a base to a complete record',`<p>The first research strategy looks for a close above a prior price base, confirmed by volume, a moving-average trend filter and minimum turnover.</p><ol><li><strong>Wait for a base.</strong> Measure its length and depth using prior completed candles.</li><li><strong>Confirm at the close.</strong> Check breakout, volume and trend conditions.</li><li><strong>Enter at the next open.</strong> Size within the risk budget and cash available, including modeled costs.</li><li><strong>Manage the exit.</strong> Start with a fixed stop; move to cost-adjusted breakeven and trail after the configured R trigger. New stops activate next session.</li><li><strong>Keep the full record.</strong> Preserve every trade, loss, cost assumption and input dataset.</li></ol><div class="notice">This implementation is long-only and uses daily bars. Current constituent bias and unverified adjustments remain. Relative-strength and separate base-formation strategies are planned next.</div>`);}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;const action=button.dataset.action;
  try{
    if(action==='use-dates'){const form=$('#backtest-form');form.elements.start.value=button.dataset.start;form.elements.end.value=button.dataset.end;form.querySelector('.form-error').textContent='';return;}
    if(action==='close'){$('#modal').close();return;}
    if(action==='method'){method();return;}
    if(action==='new-backtest'){await newBacktest(button.dataset.screen?{screen:button.dataset.screen}:{});return;}
    if(action==='new-screen'){newScreen();return;}
    if(action==='configure-paper'){paperForm();return;}
    if(action==='paper-export'){const blob=new Blob([JSON.stringify(paperPortfolio(),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`${selectedPaperStrategy}-paper-portfolio.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    if(action==='clone'){await newBacktest({...selectedRun.config,name:selectedRun.config.name+' · revised'});return;}
    if(action==='sort-trades'){const key=button.dataset.sort;tradeSort=tradeSort.key===key?{key,direction:tradeSort.direction==='asc'?'desc':'asc'}:{key,direction:key==='pnl'||key==='r'||key==='quantity'?'desc':'asc'};if(selectedRun)await showResult(selectedRun.id);return;}
    if(action==='export'){const blob=new Blob([JSON.stringify(selectedRun,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`trader-${selectedRun.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    if(action==='logs'){const job=state.jobs.find(j=>j.id===button.dataset.id)||await api('jobs/'+encodeURIComponent(button.dataset.id));modal(job.type,`<p>${when(job.created_at)} · ${badge(job.status)}</p><div class="log" id="job-log" data-job="${job.id}">${job.logs.map(l=>`${when(l.at)}  ${esc(l.message)}`).join('\n')||'Queued. Waiting for the worker.'}</div>`);return;}
    if(action==='chart'){await showChart(button.dataset.isin);return;}
    if(action==='result'||action==='back-to-report'){tradeChartRequest++;await showResult(button.dataset.id);return;}
    if(action==='trade-chart'){await showTradeChart(button.dataset.run,Number(button.dataset.trade));return;}
    button.disabled=true;
    if(action==='audit-data'){modal('Price-history audit','<p>Checking cached prices and sourced history policies…</p>');const q=await api('data-quality');if(!$('#modal').open)return;modal('Price-history audit',`<div class="notice warn">Adjustment status: unverified. ${esc(q.notice)}</div><p>${number(q.symbols_scanned,0)} symbols scanned · ${number(q.findings.length,0)} unresolved gaps at or above ${esc(q.gap_threshold_pct)}%. Raw cache gaps: ${number(q.raw_findings?.length??q.findings.length,0)}. History policies applied: ${esc((q.history_changes||[]).map(h=>h.symbol+(h.quarantine?' (quarantined)':` (${h.removed_prelisting_bars} prelisting candles excluded)`)).join(', ')||'None')}. Missing history: ${esc(q.missing_symbols.join(', ')||'None')}.</p>${q.listing_evidence?`<p>Verified exchange listing dates: ${number(q.listing_evidence.verified_exchange_listing_symbols.length,0)} / ${number(q.listing_evidence.total_symbols,0)}. Verified initial IPO dates: ${number(q.listing_evidence.verified_ipo_symbols.length,0)} / ${number(q.listing_evidence.total_symbols,0)} (${esc(q.listing_evidence.verified_ipo_symbols.join(', ')||'None')}). ${esc(q.listing_evidence.notice)}</p>`:''}<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Previous session</th><th>Session</th><th>Previous close</th><th>Open</th><th>Gap</th></tr></thead><tbody>${q.findings.map(f=>`<tr><td>${esc(f.symbol)}</td><td>${esc(f.previous_date)}</td><td>${esc(f.date)}</td><td>${money(f.previous_close)}</td><td>${money(f.open)}</td><td>${pct(f.gap_pct)}</td></tr>`).join('')||'<tr><td colspan="6">No large gaps detected; adjustments remain unverified.</td></tr>'}</tbody></table></div><p>This audit reads current cached prices. Historical report inputs may differ. Verify corporate actions and instrument identity before repairing data.</p>`);return;}
    if(action==='refresh-universe'){await api('jobs/universe','POST');toast('Universe refresh started.');}
    if(action==='fetch-data'){await api('jobs/ingest','POST');toast('Daily data fetch started. Follow progress in Jobs & logs.');}
    if(action==='paper-cycle'){await api(paperPath('cycle'),'POST');toast('Paper daily cycle queued. Follow progress in Jobs & logs.');}
    if(action==='paper-status'){await api(paperPath('status'),'PUT',{status:paperPortfolio().status==='active'?'paused':'active'});toast('Portfolio status updated. Pausing blocks new buys; daily cycles still manage exits.');}
    await refresh();
  }catch(error){toast(error.message);}finally{button.disabled=false;}
});
document.addEventListener('change',event=>{
  if(event.target.classList?.contains('trade-line-toggle')){
    if(chart){const enabled=new Set([...document.querySelectorAll('.trade-line-toggle:checked')].map(input=>input.dataset.line));chart.overrideIndicator({name:'TRADE_CONTEXT',figures:tradeIndicatorFigures(tradeChartSeries.filter(s=>enabled.has(s.id)))},'candle_pane');}return;
  }
  if(event.target.id==='paper-strategy-picker'){selectedPaperStrategy=event.target.value;render();return;}
  const form=event.target.closest('form');
  if(!form||!['backtest-form','paper-form','screen-form'].includes(form.id))return;
  if(event.target.id==='screen-picker')applyScreenPreset(form,event.target.value);
  else if(form.id==='screen-form'&&event.target.name==='pattern')applyScreenPreset(form,`builtin:${event.target.value}`);
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['settings-form','token-form','backtest-form','screen-form','paper-form'].includes(form.id))return;event.preventDefault();const submit=form.querySelector('[type="submit"]'), errorBox=form.querySelector('.form-error');submit.disabled=true;form.dataset.submitting='true';errorBox.textContent='';
  try{
    if(form.id==='settings-form'){await api('settings','PUT',readForm(form,state.settings_schema));toast('Data settings saved.');}
    if(form.id==='token-form'){const input=form.elements.access_token;const token=input.value.trim();await api('connection','PUT',{access_token:token});input.value='';toast('Token saved on the server. Fetch data to validate access.');}
    if(form.id==='screen-form'){const payload={name:form.elements.name.value.trim(),pattern:form.elements.pattern.value};screenKeys.forEach(k=>{const schema=state.backtest_schema.properties[k];payload[k]=schema.type==='boolean'?form.elements[k].checked:schema.type==='number'||schema.type==='integer'?Number(form.elements[k].value):form.elements[k].value;});await api('screens','POST',payload);$('#modal').close();toast('Screen saved. It is now available in new backtests.');}
    if(form.id==='backtest-form'){const config=readForm(form,state.backtest_schema);validateBacktestDates(config,backtestWindow);await api('jobs/backtest','POST',config);$('#modal').close();location.hash='jobs';toast('Backtest queued.');}
    if(form.id==='paper-form'){await api(paperPath('portfolio'),paperPortfolio()?'PUT':'POST',readForm(form,paperSchema()));$('#modal').close();location.hash='paper';toast('Paper portfolio saved.');}
    await refresh();
  }catch(error){errorBox.textContent=error.message;errorBox.scrollIntoView({block:'nearest'});}finally{form.dataset.submitting='false';submit.disabled=false;updateBacktestAvailability();}
});
document.addEventListener('input',event=>{if(event.target.id==='instrument-search')$('#instrument-table').innerHTML=instrumentTable(event.target.value);});
$('#modal').addEventListener('close',()=>{tradeChartRequest++;disposeChart();});
window.addEventListener('hashchange',()=>{if($('#modal').open)$('#modal').close();render();});
$('#theme-toggle').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=theme;localStorage.setItem('trader-theme',theme);$('#theme-toggle').setAttribute('aria-label',`Switch to ${theme==='light'?'dark':'light'} theme`);chart?.setStyles(theme);});
try{document.documentElement.dataset.theme=localStorage.getItem('trader-theme')||'light';}catch{/* storage unavailable */}
async function poll(){if(polling||!state)return;polling=true;try{const previous=state.jobs.map(j=>j.id+j.status+j.logs.length).join('|');await refresh(false);const next=state.jobs.map(j=>j.id+j.status+j.logs.length).join('|');if(previous!==next){if(!['settings'].includes(currentView)&&!$('#modal').open)render();const log=$('#job-log');if(log){const job=state.jobs.find(j=>j.id===log.dataset.job);if(job)log.textContent=job.logs.map(l=>`${when(l.at)}  ${l.message}`).join('\n');}}}catch{/* keep last state; explicit refresh surfaces an error */}finally{polling=false;}}
refresh().catch(error=>{$('#view').innerHTML=empty('The workspace could not load',error.message);});
setInterval(poll,3000);
