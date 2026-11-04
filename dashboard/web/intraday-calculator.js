'use strict';

function intradayRunTime(report){
  for(const value of [report.generated_at,report.created_at]){
    if(typeof value!=='string')continue;
    const time=Date.parse(value);if(Number.isFinite(time))return time;
  }
  return null;
}
function intradaySortReports(reports){
  return reports.filter(Boolean).sort((a,b)=>{
    const left=intradayRunTime(a)??-Infinity,right=intradayRunTime(b)??-Infinity;
    return left===right?0:left>right?-1:1;
  });
}
function intradayRunWhen(report){
  const time=intradayRunTime(report);
  return time===null?'Run time unavailable':new Date(time).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+' IST';
}

const intradayScenario={price:1000, movement:1, capital:10000, success:true, symbol:'', direction:'long'};
let intradayBacktest=null, intradaySmallTargetBacktest=null, intradaySmallShortBacktest=null, intradayRelianceLong=null, intradayRelianceShort=null, intradayShortBacktest=null, intradayBacktestLoading=false, intradayBacktestError='';

async function intradayLoadBacktest(){
  intradayBacktestLoading=true;intradayBacktestError='';
  try{[intradayBacktest,intradayShortBacktest,intradaySmallTargetBacktest,intradaySmallShortBacktest,intradayRelianceLong,intradayRelianceShort]=await Promise.all(['hdfcbank-target','hdfcbank-short-target','hdfcbank-target02','hdfcbank-short-target02','reliance-target02','reliance-short-target02'].map(id=>api('intraday/backtests/'+id)));}
  catch(error){intradayBacktestError=error.message;}
  finally{intradayBacktestLoading=false;if(currentView==='intraday'){if(state)render();else intradayPrime();}}
}

function intradayBacktestView(){
  const r=intradayBacktest||(typeof intradayCustomReports==='function'?intradayCustomReports()[0]:null);
  const rows=intradaySortReports([intradayBacktest,intradayShortBacktest,intradaySmallTargetBacktest,intradaySmallShortBacktest,intradayRelianceLong,intradayRelianceShort,...(typeof intradayCustomReports==='function'?intradayCustomReports():[])]).map(r=>`<tr class="intraday-backtest-row" data-intraday-report="${esc(r.id)}" data-run-time="${intradayRunTime(r)??''}" tabindex="0" aria-label="View ${esc(r.stock_name)} ${r.direction==='short'?'short':'long'} daily backtest details"><td><button class="text-button" data-intraday-report="${esc(r.id)}">${esc(r.strategy)}</button><small class="intraday-run-time">Run · ${esc(intradayRunWhen(r))}</small></td><td>${esc(r.stock_name)}<br><small>${esc(r.stock)} · ${r.direction==='short'?'Short':'Long'}</small></td><td>${r.success_days} / ${r.failure_days}${r.outcome_basis==='net_day_pnl'?'<br><small>Net day P&L</small>':''}<br><small>${r.trade_count??r.days.length} trades · ${r.skipped_count??r.skipped.length} skipped</small></td><td>${money(r.total_gross_pnl)}</td><td>${money(r.total_charges)}</td><td class="${r.final_pnl>=0?'positive':'negative'}">${money(r.final_pnl)}</td><td>${money(r.final_capital)}</td></tr>`).join('');
  return `<section class="panel intraday-backtests"><div class="panel-body"><div class="intraday-history-heading"><h2>Historical backtests</h2><button type="button" class="button primary" id="intraday-new-backtest">Backtest</button></div>${typeof intradayBacktestStatus==='function'?intradayBacktestStatus():''}<p class="settings-context">₹5,00,000 starting capital · 5× leverage · daily compounding · Zerodha charges</p>${r?`
    <p>${esc(r.start)} → ${esc(r.end)} · Newest runs first · Trading-day counts are shown per strategy.</p>
    <div class="table-wrap"><table><thead><tr><th>Strategy description</th><th>Stock name</th><th>Success / failure days</th><th>Total profit / loss<br><small>Before charges</small></th><th>Total charges in trade</th><th>Final profit / loss<br><small>After charges</small></th><th>Final capital</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="settings-context">Select the entry for the capital graph and daily ledger. For standard runs, success means target reached; reversal runs classify days by combined net P&L after both trades. Fills and charges are modeled estimates.</p>`:
    `<p role="status">${intradayBacktestLoading?'Loading backtest…':esc(intradayBacktestError||'Backtest unavailable.')}</p>${intradayBacktestError?'<button class="button" id="intraday-backtest-retry">Retry backtest</button>':''}`}</div></section>`;
}

function intradayBacktestDetails(id){
  const r=intradaySortReports([intradayBacktest,intradayShortBacktest,intradaySmallTargetBacktest,intradaySmallShortBacktest,intradayRelianceLong,intradayRelianceShort,...(typeof intradayCustomReports==='function'?intradayCustomReports():[])]).find(r=>r&&(!id||r.id===id));if(!r)return;
  if(r.custom&&!r.days){void intradayOpenCustomReport(r.id);return;}
  const short=r.direction==='short';
  const ledger=r.reverse_once_on_stop&&r.trades?r.trades:r.days;
  const labels=[r.reverse_once_on_stop?'Date / trade':'Date','Target result','Opening capital',r.reverse_once_on_stop?'Entry / side':short?'Sell · '+(r.entry_time||'09:30'):'Buy · '+(r.entry_time||'09:30'),'Target / stop',r.reverse_once_on_stop?'Exit / minute':short?'Buy back / minute':'Sell / minute','Shares','Gross P&L','Charges','Net P&L','Closing capital'];
  const cells=ledger.map(d=>{const values=[`${esc(d.date)}${r.reverse_once_on_stop?`<br><small>Trade ${d.leg_number} · ${d.direction==='short'?'Sell':'Buy'}</small>`:''}`,d.outcome==='success'?'Success':'Failure',money(d.opening_capital),`${money(d.entry_price)}${r.reverse_once_on_stop?`<br><small>${esc(d.entry_time)} IST · ${d.direction==='short'?'Sell':'Buy'}</small>`:''}`,`${money(d.target_price)}${d.stop_price?`<br><small>Stop ${money(d.stop_price)}${d.stop_active_from?`<br>from ${esc(d.stop_active_from)}`:''}</small>`:''}`,`${money(d.exit_price)}<br><small>${esc(d.exit_time)} IST${d.exit_reason?'<br>'+esc(d.exit_reason)+(d.ambiguous_exit?' *':''):''}</small>`,number(d.quantity,0),money(d.gross_pnl),`<details><summary>${money(d.charges)}</summary>${Object.entries(d.fees).filter(([,v])=>v).map(([k,v])=>`<div>${esc(k.toUpperCase())}: ${money(v)}</div>`).join('')}</details>`,money(d.net_pnl),money(d.closing_capital)];return `<tr>${values.map((value,i)=>`<td data-label="${esc(labels[i])}"${i===9?` class="${d.net_pnl>=0?'positive':'negative'}"`:''}>${value}</td>`).join('')}</tr>`;}).join('');
  modal(`${r.stock_name} · ${short?'Short':'Long'} · ${r.entry_time||'09:30'} target backtest`,`<p>${esc(r.strategy)}</p><p>${esc(r.start)} → ${esc(r.end)} · ${r.outcome_basis==='net_day_pnl'?`${r.success_days} profitable / ${r.failure_days} non-profitable days`:`${r.success_days} target successes / ${r.failure_days} failures`} · ${r.net_profitable_days} net profitable days${r.reverse_once_on_stop?` · ${r.reversal_count} reversals`:''}${r.stop_loss_enabled?` · ${r.stop_loss_exits??r.stop_loss_days} stop-loss exits`:''}</p>
    <div class="intraday-summary"><div>Starting capital<br><b>${money(r.starting_capital)}</b></div><div>Gross P&L<br><b>${money(r.total_gross_pnl)}</b></div><div>Total charges<br><b>${money(r.total_charges)}</b></div><div>Net P&L<br><b>${money(r.final_pnl)}</b></div><div>Final capital<br><b>${money(r.final_capital)}</b></div><div>Net return<br><b>${pct(r.return_pct)}</b></div></div>
    <h3>Capital after each trading day</h3>${equitySvg(r.curve)}
    <details class="intraday-fees"><summary>Execution assumptions & data coverage</summary><ul>${r.assumptions.map(a=>`<li>${esc(a)}</li>`).join('')}</ul><p>${esc(r.data_source)} · ${r.expected_sessions} verified sessions. Generated ${esc(r.generated_at)}.</p><p>${r.fee_sources.map((url,i)=>`<a href="${esc(url)}" target="_blank" rel="noopener">Fee source ${i+1}</a>`).join(' · ')}</p><p>Input SHA-256: <code style="overflow-wrap:anywhere">${esc(r.input_sha256)}</code></p>${(r.skipped_count??r.skipped.length)?`<p>Skipped: ${r.skipped.map(d=>`${esc(d.date)} — ${esc(d.reason)}`).join('; ')}</p>`:''}</details>
    <h3>Daily trades</h3><div class="table-wrap intraday-daily-ledger"><table><thead><tr>${labels.map(label=>`<th scope="col">${esc(label)}</th>`).join('')}</tr></thead><tbody>${cells}</tbody></table></div>`);
}

document.addEventListener('click',event=>{
  const report=event.target.closest('[data-intraday-report]');if(report)intradayBacktestDetails(report.dataset.intradayReport);
  if(event.target.id==='intraday-backtest-retry')void intradayLoadBacktest();
});
document.addEventListener('keydown',event=>{
  if(event.target.matches('tr[data-intraday-report]')&&['Enter',' '].includes(event.key)){event.preventDefault();intradayBacktestDetails(event.target.dataset.intradayReport);}
});
let intradayStocks=null, intradayStockError='', intradayStockLoading=false, intradayQuoteVersion=0, intradayPriceNote='Manual entry price', intradayQuoteLoading=false;
try{
  const cached=JSON.parse(sessionStorage.getItem('trader-intraday-members')||'null');
  if(cached&&Date.now()-cached.saved_at<3600000&&Array.isArray(cached.data?.stocks)&&cached.data.stocks.length>=45)intradayStocks=cached.data;
}catch{/* A blocked browser cache does not prevent manual calculations. */}

function intradayPrime(){
  if(location.hash!=='#intraday')return;
  currentView='intraday';$('#view').innerHTML=intradayCalculatorView();
}

function intradayCalculate({price,movement,capital,success,direction='long'}){
  if(![price,movement,capital].every(Number.isFinite)||price<=0||capital<0||movement<0||movement>=100) return null;
  const quantity=Math.floor(capital*5/price), sign=success?1:-1;
  const exit=price*(1+(direction==='short'?-1:1)*sign*movement/100);
  const entryValue=quantity*price, exitValue=quantity*exit;
  const buy=direction==='short'?exitValue:entryValue, sell=direction==='short'?entryValue:exitValue;
  const turnover=buy+sell;
  const fees={brokerage:Math.min(20,buy*.0003)+Math.min(20,sell*.0003), stt:sell*.00025,
    exchange:turnover*.000030699, ipft:turnover*.000000001, sebi:turnover*.000001, stamp:buy*.00003};
  fees.gst=.18*(fees.brokerage+fees.exchange+fees.ipft+fees.sebi);
  const charges=Object.values(fees).reduce((a,b)=>a+b,0), gross=sell-buy, net=gross-charges;
  return {quantity,exit,entryValue,margin:entryValue/5,gross,fees,charges,net,balance:capital+net,returnPct:capital?net/capital*100:0};
}

function intradayResults(){
  const r=intradayCalculate(intradayScenario);
  if(!r)return '<div class="notice warn" role="alert">Enter a price above zero, capital of zero or more, and movement below 100%.</div>';
  const labels={brokerage:'Brokerage · 0.03% per order, capped at ₹20',stt:'STT · 0.025% of sell value',exchange:'NSE transaction charge · 0.0030699%',ipft:'NSE IPFT · ₹0.01 / crore',sebi:'SEBI · ₹10 / crore',stamp:'Stamp duty · 0.003% of buy value',gst:'GST · 18% on brokerage, exchange, IPFT & SEBI'};
  return `<div class="intraday-net ${r.net>=0?'positive':'negative'}"><span>Final ${r.net>=0?'profit':'loss'} after charges</span><strong>${money(r.net)}</strong><small>${pct(r.returnPct)} on your capital</small></div>
    ${!r.quantity?'<div class="notice warn">Capital × 5 is below one share. No trade; no charges.</div>':''}
    <dl class="intraday-summary"><div><dt>Entry price</dt><dd>${money(intradayScenario.price)}</dd></div><div><dt>Exit price</dt><dd>${money(r.exit)}</dd></div><div><dt>Gross ${r.gross>=0?'profit':'loss'}</dt><dd>${money(r.gross)}</dd></div><div><dt>Charges</dt><dd>${money(r.charges)}</dd></div></dl>
    <details class="intraday-fees"><summary>${number(r.quantity,0)} shares ${intradayScenario.direction==='short'?'sold':'purchased'} · Details & charges</summary>
    <p class="intraday-equation">${number(r.quantity,0)} shares × ${money(intradayScenario.price)} × ${intradayScenario.success?'+':'−'}${number(intradayScenario.movement)}% − ${money(r.charges)} = <b>${money(r.net)}</b></p>
    <dl class="intraday-totals"><div><dt>Final capital</dt><dd>${money(r.balance)}</dd></div><div><dt>Position value</dt><dd>${money(r.entryValue)}</dd></div><div><dt>Margin used / unused</dt><dd>${money(r.margin)} / ${money(intradayScenario.capital-r.margin)}</dd></div>${Object.entries(labels).map(([key,label])=>`<div><dt>${label}</dt><dd>${money(r.fees[key])}</dd></div>`).join('')}</dl>
    <p class="settings-context">Shares = floor(capital × 5 ÷ entry price). Success means a move in your trade’s favour; a small gross profit can become a net loss after charges. Assumes one entry and one manual exit, with 5× leverage and whole shares. Keep cash for fees. Leverage and contract-note rounding can vary. Excludes slippage, dealer/auto-square-off fees, AMC and income tax. <a href="https://zerodha.com/charges/" target="_blank" rel="noopener">Zerodha rates</a> · checked 4 Nov 2026.</p>
    ${intradayStocks?`<p class="settings-context">${intradayStocks.cached?'Saved':'Official'} Nifty 50 membership · ${esc(intradayStocks.as_of||'date unavailable')}</p>`:''}</details>`;
}

function intradayLever(key,label,min,max,step,prefix=''){
  const value=intradayScenario[key];
  const rangeMax=Math.max(key==='movement'?5:key==='capital'?100000:max,value);
  return `<div class="intraday-lever"><div class="intraday-lever-row"><label for="intraday-${key}">${label}</label><div class="intraday-number"><span>${prefix}</span><input id="intraday-${key}" data-intraday="${key}" type="number" min="${min}" step="${step}" value="${value}"></div></div><input aria-label="${label} slider" data-intraday="${key}" type="range" min="${min}" max="${rangeMax}" step="${step}" value="${value}"></div>`;
}

function intradayCalculatorView(){
  if(typeof intradayEnsureCustom==='function')intradayEnsureCustom();
  if(!intradayStocks&&!intradayStockLoading&&!intradayStockError)void intradayLoadStocks();
  if(!intradayBacktest&&!intradayBacktestLoading&&!intradayBacktestError)void intradayLoadBacktest();
  return `<div class="intraday-page"><div class="intraday-heading"><h1>Intraday equation</h1><span class="badge" title="Zerodha NSE equity intraday">5× leverage</span></div>
    <section class="panel"><div class="panel-body intraday-stock"><label class="field"><span>Nifty 50 stock</span><select id="intraday-stock"><option value="">Manual price</option>${(intradayStocks?.stocks||[]).map(s=>`<option value="${esc(s.symbol)}" ${s.symbol===intradayScenario.symbol?'selected':''}>${esc(s.symbol)} · ${esc(s.name)}</option>`).join('')}</select></label><button class="button" id="intraday-reset-price" aria-label="Reset to stock price" ${!intradayScenario.symbol||intradayQuoteLoading?'disabled':''}>Reset price</button><p id="intraday-price-note" role="status">${esc(intradayQuoteLoading?'Loading stock price…':intradayPriceNote)}</p>${intradayStockLoading||intradayStockError?`<p class="intraday-membership" role="status">${intradayStockLoading?'Loading Nifty 50 stocks…':esc(intradayStockError)+' <button class="text-button" id="intraday-retry">Retry</button>'}</p>`:''}</div></section>
    <div class="intraday-grid"><section class="panel"><div class="panel-body">
    ${intradayLever('price','Stock price',.01,10000,.01,'₹')}${intradayLever('movement','Movement (%)',0,99.99,.01)}${intradayLever('capital','Capital',0,1000000,1,'₹')}
    <div class="intraday-trade-options"><fieldset class="intraday-outcome"><legend class="intraday-sr-only">Trade outcome</legend><label><input type="radio" name="intraday-outcome" value="success" ${intradayScenario.success?'checked':''}> Success</label><label><input type="radio" name="intraday-outcome" value="failure" ${!intradayScenario.success?'checked':''}> Failure</label></fieldset>
    <select id="intraday-direction" aria-label="Trade direction"><option value="long" ${intradayScenario.direction==='long'?'selected':''}>Long</option><option value="short" ${intradayScenario.direction==='short'?'selected':''}>Short</option></select></div></div></section>
    <section class="panel"><div id="intraday-result" class="panel-body" aria-live="polite">${intradayResults()}</div></section></div>${intradayBacktestView()}</div>`;
}

async function intradayLoadStocks(){
  intradayStockLoading=true;intradayStockError='';
  try{
    intradayStocks=await api('intraday/stocks');
    try{sessionStorage.setItem('trader-intraday-members',JSON.stringify({saved_at:Date.now(),data:intradayStocks}));}catch{/* optional cache */}
  }catch(error){intradayStockError=error.message;}
  finally{intradayStockLoading=false;if(currentView==='intraday'){if(state)render();else intradayPrime();}}
}
async function intradayApplyPrice(){
  const symbol=intradayScenario.symbol, version=++intradayQuoteVersion;
  if(!symbol){intradayQuoteLoading=false;intradayPriceNote='Manual entry price';render();return;}
  intradayQuoteLoading=true;render();
  try{
    const member=intradayStocks?.stocks.find(s=>s.symbol===symbol);
    const saved=intradayStocks?.price_mode==='saved_close'?state?.instruments?.find(s=>s.isin===member?.isin):null;
    const quote=Number.isFinite(saved?.close)&&saved.close>0
      ?{price:saved.close,as_of:saved.last,source:'Saved daily close'}
      :await api('intraday/price/'+encodeURIComponent(symbol));
    if(version!==intradayQuoteVersion)return;
    intradayScenario.price=quote.price;
    const raw=String(quote.as_of||'');
    const stamp=/^\d{13}$/.test(raw)?new Date(Number(raw)):new Date(raw);
    const date=Number.isNaN(stamp.getTime())?'time unavailable':stamp.toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})+' IST';
    intradayPriceNote=`${symbol} · ${quote.source} · ${date}`;
  }catch(error){if(version===intradayQuoteVersion)intradayPriceNote=`${symbol}: ${error.message} Price unchanged.`;}
  finally{if(version===intradayQuoteVersion){intradayQuoteLoading=false;if(currentView==='intraday')render();}}
}
document.addEventListener('input',event=>{
  const key=event.target.dataset?.intraday;if(!key)return;
  intradayScenario[key]=event.target.value===''?NaN:Number(event.target.value);
  document.querySelectorAll(`[data-intraday="${key}"]`).forEach(input=>{if(input!==event.target){if(input.type==='range'&&intradayScenario[key]>Number(input.max))input.max=intradayScenario[key];input.value=event.target.value;}});
  if(key==='price'){++intradayQuoteVersion;intradayQuoteLoading=false;intradayPriceNote='Manual entry price'+(intradayScenario.symbol?' · '+intradayScenario.symbol:'');$('#intraday-price-note').textContent=intradayPriceNote;$('#intraday-reset-price').disabled=!intradayScenario.symbol;}
  $('#intraday-result').innerHTML=intradayResults();
});
document.addEventListener('change',event=>{
  if(event.target.id==='intraday-stock'){intradayScenario.symbol=event.target.value;void intradayApplyPrice();}
  if(event.target.name==='intraday-outcome'){intradayScenario.success=event.target.value==='success';$('#intraday-result').innerHTML=intradayResults();}
  if(event.target.id==='intraday-direction'){intradayScenario.direction=event.target.value;$('#intraday-result').innerHTML=intradayResults();}
});
document.addEventListener('click',event=>{
  if(event.target.id==='intraday-reset-price')void intradayApplyPrice();
  if(event.target.id==='intraday-retry'){void intradayLoadStocks();render();}
});
