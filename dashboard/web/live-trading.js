'use strict';
let liveState = null, liveBusy = false, liveError = '', liveHistory = null, livePlan = null;

function liveField(key,schema,value){
  const spec=schema.properties[key],v=value??spec.default??'';
  const required=(schema.required||[]).includes(key)?'required':'';
  const names={breakout:'Price and volume breakout',vcp:'VCP',blue_sky:'Blue sky',multiyear:'Multi-year breakout',ipo:'IPO base',take_8:'Take profit at +8%',take_15:'Take profit at +15%',take_25:'Take profit at +25%',trail_pct:'Trail below best observed price',trail_50d:'Completed close below SMA50',trail_30w:'Completed close below SMA150 (30 weeks)'};
  const help={capital:'Maximum cost of managed positions and pending buys. This does not transfer money.',risk_pct:'Buy size uses allocated capital × risk % ÷ stop %. Cash and order limits also apply.',stop_pct:'Recalculated below the actual average buy fill; changing this can tighten or loosen existing stops.',max_daily_loss:'Gross managed daily P/L pauses new buys at this loss. Exits continue. Charges are excluded.',breakeven_r:'Move the stop to the average buy fill after this many risk units of observed price improvement.',protection_bps:'50 bps = 0.5%. Buys use a protected maximum price; sells use a protected minimum. A limit order can remain unfilled.',order_ttl_seconds:'Unfilled orders are cancelled on the first cycle after this age. Cancellation needs broker confirmation.',static_ip_confirmed:'Register the server’s public static IP in Upstox before enabling this.',delivery_sell_authorized:'Without applicable delivery authorization, Upstox may reject automated sells.'};
  if(spec.type==='boolean')return `<label class="field checkbox"><input type="checkbox" name="${esc(key)}" ${v?'checked':''}><span>${esc(spec.title||key)}${help[key]?`<small>${esc(help[key])}</small>`:''}</span></label>`;
  const control=spec.enum?`<select name="${esc(key)}" ${required}>${spec.enum.map(x=>`<option value="${esc(x)}" ${x===v?'selected':''}>${esc(names[x]||x)}</option>`).join('')}</select>`:
    `<input name="${esc(key)}" type="${['number','integer'].includes(spec.type)?'number':'text'}" value="${esc(v)}" ${required} ${spec.type==='integer'?'step="1"':spec.type==='number'?'step="any"':''} ${spec.minimum!=null?`min="${spec.minimum}"`:spec.exclusiveMinimum!=null?`min="${spec.exclusiveMinimum+.0001}"`:''} ${spec.maximum!=null?`max="${spec.maximum}"`:''} ${spec.maxLength?`maxlength="${spec.maxLength}"`:''}>`;
  return `<label class="field"><span>${esc(spec.title||key)}</span>${control}${help[key]?`<span class="help">${esc(help[key])}</span>`:''}</label>`;
}

function liveTable(headers, rows, fallback='No records returned by Upstox.') {
  return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${headers.length}">${esc(fallback)}</td></tr>`}</tbody></table></div>`;
}
function liveButton(action,label,primary=false,extra='') {return `<button type="button" class="button ${primary?'primary':''}" data-live="${action}" ${extra}>${label}</button>`;}
function liveScheduleLoad(){if(typeof setTimeout!=='undefined')setTimeout(()=>loadLive(false),0);}
function liveConnectionView(){
  liveScheduleLoad();
  return `<section class="panel"><div class="panel-head"><div><h2>Upstox live execution</h2><p>The saved access token is shared by market data and this broker connection.</p></div><a class="button" href="#live">Open Live trade ↗</a></div><div class="panel-body" id="live-connection-fields">${liveConnectionFields()}</div></section>`;
}
function liveConnectionFields(){
  if(!liveState)return '<p>Loading broker settings…</p>';
  return `<p>Verified account: <strong id="live-verified-account">${esc(liveState.account?.profile.user_id||'Refresh the account in Live trade to verify')}</strong>.</p><p>Register this server’s static IP in <a href="https://account.upstox.com/developer/apps" target="_blank" rel="noreferrer">Upstox developer apps</a>. If your app uses a registered algo, enter its configured name. API key and secret are not needed when supplying an access token.</p><form id="live-connection-form"><div class="fields">${Object.keys(liveState.connection_schema.properties).map(k=>liveField(k,liveState.connection_schema,liveState.connection[k])).join('')}</div><p>Changing the connection or replacing the token requires stopping the runner. Strategy and risk settings can be changed while running.</p><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">Save live connection</button></div></form>`;
}
function liveView(){
  liveScheduleLoad();
  return heading('Live trade','Long swing strategies · real Upstox delivery orders.',liveButton('refresh','Refresh account'),'UPSTOX / REAL MONEY')+
    `<div class="notice warn">Starting this runner authorizes real buys and sells within your saved limits. Stops are monitored by this app; they require the server, a valid token and fresh market data. Protected limit orders can remain unfilled.</div><div id="live-error" class="form-error" role="alert">${esc(liveError)}</div><div id="live-status">${liveStatusView()}</div>`+
    `<section class="panel"><div class="panel-head"><div><h2>Strategy & risk settings</h2><p>Save changes at any time. The next cycle applies them to new entries and managed exits.</p></div></div><div class="panel-body" id="live-config">${liveConfigView()}</div></section>`+
    `<div id="live-account">${liveAccountView()}</div><section class="panel"><div class="panel-head"><h2>Transaction history</h2></div><div class="panel-body"><form id="live-history-form" class="toolbar"><label class="field">From<input type="date" name="start" required></label><label class="field">Through<input type="date" name="end" required></label><button class="button" type="submit">Load history</button><div class="form-error" role="alert"></div></form><p>Equity trade history from Upstox, 100 records per page. Today’s fills are shown above.</p><div id="live-history">${liveHistoryView()}</div></div></section>`;
}
function liveConfigView(){
  if(!liveState)return '<p>Loading live configuration…</p>';
  const d=liveState,c=d.config;
  return `<form id="live-config-form"><div class="notice">Uses the existing daily swing signal engine with its validated fundamental buy gate. Entries use the latest completed exchange session and fresh prices between 09:16 and 10:00 IST. Exits run until 15:30 IST. Candidates rank by fundamental score. Refresh market data to keep completed candles current.</div><h3>Technical strategy</h3><div class="fields">${liveField('pattern',d.filters_schema,c.filters.pattern)}</div><details><summary>Edit technical filters</summary><div class="fields">${Object.keys(d.filters_schema.properties).filter(k=>k!=='pattern').map(k=>liveField(k,d.filters_schema,c.filters[k])).join('')}</div></details><h3>Capital, risk & exits</h3><div class="fields">${Object.keys(d.schema.properties).filter(k=>k!=='filters').map(k=>liveField(k,d.schema,c[k])).join('')}</div><p>Settings apply to positions opened by this tab. Lowering position or capital limits restricts new buys; it does not force a rebalance. Moving average exits use completed daily closes (30 weeks = 150 sessions); price trailing uses the best price observed by the runner. P/L excludes broker charges and taxes.</p><div class="form-error" role="alert"></div><div class="form-actions">${liveButton('preview','Preview current signals')}<button class="button primary" type="submit">Save strategy & risk</button></div><div id="live-plan">${livePlanView()}</div></form>`;
}
function liveStatusView(){
  const d=liveState;
  if(!d)return '<p>Loading live account…</p>';
  const uncertain=d.ledger.orders.filter(o=>['unknown','submitting'].includes(o.status));
  return `<section class="panel"><div class="panel-head"><div><h2>${d.running?'Live runner active':'Live runner stopped'}</h2><p>${esc(d.runner.message||'Save the broker connection and strategy limits, then explicitly start trading.')} ${d.runner.heartbeat_at?' · '+when(d.runner.heartbeat_at):''}</p></div><div class="actions">${d.running?liveButton('pause',d.paused?'Resume new entries':'Pause new entries')+liveButton('stop','Stop runner'):liveButton('start','Start real trading',true)}</div></div><div class="panel-body"><p>${d.paused?'New buys paused. ':''}Pausing retains exit monitoring. Stopping ends monitoring after the current cycle and leaves holdings and pending broker orders in place. A server restart requires starting the runner again.</p>${uncertain.map(o=>`<div class="notice warn">Unknown order: ${esc(o.symbol)} ${esc(o.side)} × ${o.quantity} · tag ${esc(o.tag)}. Automatic orders are blocked. ${liveButton('resolve','Reconcile order',false,`data-id="${esc(o.id)}"`)}</div>`).join('')}</div></section>`;
}
function liveAccountView(){
  const d=liveState,a=d?.account,l=d?.ledger;
  if(!a)return `<section class="panel"><div class="panel-body">${empty('Connect your Upstox account','Save your token in Settings, then refresh the account here.','settings','Connection settings')}</div></section>`;
  const holdingPnl=a.holdings.every(r=>r.current_unrealized_pnl!=null)?a.holdings.reduce((n,r)=>n+r.current_unrealized_pnl,0):null;
  const managed=Object.values(l.positions);
  const quoteLabel=r=>`${money(r.current_price)}<small>${r.quote_at?when(r.quote_at):'Quote unavailable'}${r.quote_fresh===false?' · stale / market closed':''}</small>`;
  return `<div class="stats">${stat('Holding unrealized P/L',money(holdingPnl),'Broker holdings only; excludes today’s positions',holdingPnl>0)}${stat('Managed realized P/L',money(l.realized_pnl),'Filled strategy exits, before charges',l.realized_pnl>0)}${stat('Managed unrealized P/L',money(l.unrealized_pnl),'Latest broker quotes; before charges',l.unrealized_pnl>0)}${stat('Available margin',money(a.funds.equity?.available_margin),'Upstox equity account')}</div><p>Account ${esc(a.profile.user_id)} · Last successful account refresh ${when(a.fetched_at)}. Holdings and today’s positions can overlap; their P/L is shown separately.</p>`+
    `<section class="panel"><div class="panel-head"><h2>Managed swing holdings</h2><span class="badge">${managed.length} positions</span></div>${liveTable(['Symbol','Quantity','Average fill','Current price','Stop price','Unrealized P/L'],managed.map(p=>[esc(p.symbol),number(p.quantity,0),money(p.average_price),money(p.current_price),money(p.stop_price),(p.current_price!=null?money((p.current_price-p.average_price)*p.quantity):'—')]),'No strategy-owned holdings yet.')}</section>`+
    `<section class="panel"><div class="panel-head"><h2>All Upstox holdings</h2></div>${liveTable(['Symbol','Quantity','T+1 quantity','Average','Current price','Unrealized P/L'],a.holdings.map(r=>[esc(r.trading_symbol||r.tradingsymbol),number(r.quantity,0),number(r.t1_quantity,0),money(r.average_price),quoteLabel(r),money(r.current_unrealized_pnl)]))}</section>`+
    `<section class="panel"><div class="panel-head"><h2>Today’s broker positions</h2></div>${liveTable(['Symbol','Product','Net quantity','Average','Current price','Unrealized P/L','Realized P/L'],a.positions.map(r=>[esc(r.trading_symbol||r.tradingsymbol),esc(r.product),number(r.quantity,0),money(r.average_price),quoteLabel(r),money(r.current_unrealized_pnl),money(r.realised)]))}</section>`+
    `<section class="panel"><div class="panel-head"><h2>Today’s broker orders</h2></div>${liveTable(['Order ID','Symbol','Side','Quantity / filled','Limit','Average fill','Status'],a.orders.map(o=>[esc(o.order_id),esc(o.trading_symbol||o.tradingsymbol),esc(o.transaction_type),`${number(o.quantity,0)} / ${number(o.filled_quantity,0)}`,money(o.price),money(o.average_price),esc(o.status)]))}</section>`+
    `<section class="panel"><div class="panel-head"><h2>Today’s executed transactions</h2></div>${liveTable(['Trade ID','Symbol','Side','Quantity','Fill price','Time'],a.trades.map(t=>[esc(t.trade_id),esc(t.trading_symbol||t.tradingsymbol),esc(t.transaction_type),number(t.quantity,0),money(t.average_price||t.price),esc(t.exchange_timestamp||t.order_timestamp)]))}</section>`+
    `<section class="panel"><div class="panel-head"><h2>Durable strategy order ledger</h2></div>${liveTable(['Requested','Symbol','Side','Quantity / filled','Limit','Status','Broker IDs / reason'],[...l.orders].reverse().map(o=>[when(o.created_at),esc(o.symbol),esc(o.side),`${o.quantity} / ${o.filled_quantity}`,money(o.price),esc(o.status),`${esc((o.order_ids||[]).join(', '))}<small>${esc(o.error||o.reason)}</small>`]))}</section>`;
}
function liveHistoryView(){
  if(!liveHistory)return '<p>Choose dates to retrieve past transactions.</p>';
  return liveTable(['Date','Symbol','Side','Quantity','Price','Amount'],liveHistory.trades.map(t=>[esc(t.trade_date),esc(t.symbol||t.scrip_name),esc(t.transaction_type),number(t.quantity,0),money(t.price),money(t.amount)]))+
    `<div class="actions"><span>Page ${liveHistory.page}</span>${liveHistory.page>1?liveButton('history-prev','Previous page'):''}${liveHistory.has_more?liveButton('history-next','Next page'):''}</div>`;
}
function livePlanView(){return livePlan?`<div class="notice">Signal session ${esc(livePlan.signal_day)} · ${livePlan.matches.length} qualified candidates · ${livePlan.excluded.length} excluded. Preview sends no orders.</div>${liveTable(['Symbol','Signal close','Fundamental score'],livePlan.matches.map(r=>[esc(r.symbol),money(r.close),number(r.score)]))}<details><summary>Excluded stocks</summary>${liveTable(['Symbol','Reason'],livePlan.excluded.map(r=>[esc(r.symbol),esc(r.reason)]))}</details>`:'';}

function updateLivePanels(){
  for(const [selector,html] of [['#live-status',liveStatusView()],['#live-account',liveAccountView()]]){const el=$(selector);if(el)el.innerHTML=html;}
  const error=$('#live-error');if(error)error.textContent=liveError;
  const verified=$('#live-verified-account');if(verified)verified.textContent=liveState?.account?.profile.user_id||'Refresh the account in Live trade to verify';
  const config=$('#live-config');if(config&&!$('#live-config-form'))config.innerHTML=liveConfigView();
  const connection=$('#live-connection-fields');if(connection&&!$('#live-connection-form'))connection.innerHTML=liveConnectionFields();
}
async function loadLive(refreshAccount=false){
  if(liveBusy)return;
  if(!['live','settings'].includes(location.hash.slice(1)))return;
  liveBusy=true;
  try{liveState=await api(refreshAccount?'live/refresh':'live',refreshAccount?'POST':'GET');liveError='';}
  catch(error){liveError=error.message;try{liveState=await api('live');}catch{/* Keep the last successful account snapshot. */}}
  finally{liveBusy=false;updateLivePanels();}
}
async function loadLiveHistory(page){
  const form=$('#live-history-form');
  const start=form?.elements.start.value||liveHistory?.start,end=form?.elements.end.value||liveHistory?.end;
  liveHistory=await api(`live/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&page=${page}`);
  const el=$('#live-history');if(el)el.innerHTML=liveHistoryView();
}
document.addEventListener('click',async event=>{
  const button=event.target.closest?.('[data-live]');if(!button)return;
  const action=button.dataset.live;button.disabled=true;
  try{
    if(action==='refresh'){await loadLive(true);return;}
    if(action==='preview'){livePlan=await api('live/preview','POST');const el=$('#live-plan');if(el)el.innerHTML=livePlanView();return;}
    if(action==='start'){
      modal('Start real Upstox trading',`<p>The saved strategy can submit real delivery orders for account <strong>${esc(liveState.connection.expected_user_id||'not configured')}</strong>, with ${money(liveState.config.capital)} allocated capital, ${money(liveState.config.max_order_value)} maximum per buy and ${liveState.config.max_positions} managed positions.</p><form id="live-start-form"><label class="field"><span><input type="checkbox" name="acknowledge" required> I authorize automatic real-money buys and sells under these saved settings.</span></label><p>The app must remain running to monitor exits. Limits and settings can be edited while running.</p><div class="form-error" role="alert"></div><button class="button primary" type="submit">Start real trading</button></form>`);return;
    }
    if(action==='pause')await api('live/pause','PUT',{paused:!liveState.paused});
    if(action==='stop'){await api('live/stop','POST');toast('Runner is stopping. Pending orders and holdings remain in Upstox.');}
    if(action==='history-next'||action==='history-prev'){await loadLiveHistory(liveHistory.page+(action==='history-next'?1:-1));return;}
    if(action==='resolve'){
      modal('Reconcile unknown order',`<p>Stop the runner, then inspect this intent’s tag in Upstox. Link its matching order ID, or confirm after checking broker history that it was never placed.</p><form id="live-resolve-form"><input type="hidden" name="intent_id" value="${esc(button.dataset.id)}"><label class="field">Matching Upstox order ID<input name="order_id" maxlength="80"></label><label class="field"><span><input type="checkbox" name="confirmed_not_placed"> I checked Upstox orders and history and verified no matching order was placed.</span></label><details><summary>Recover an order from an earlier trading day</summary><p>Use this only when the broker detail API can no longer retrieve the order. Enter the exact final status and cumulative fills from Upstox history. The runner must be stopped.</p><label class="field">Final broker status<select name="final_status"><option value="cancelled">Cancelled</option><option value="complete">Complete</option><option value="rejected">Rejected</option></select></label><label class="field">Total filled quantity<input type="number" name="filled_quantity" value="0" min="0" step="1"></label><label class="field">Average fill price<input type="number" name="average_price" value="0" min="0" step="any"></label><label class="field"><span><input type="checkbox" name="confirmed_history_details"> I verified this order ID, symbol, side, final status, quantity and price against Upstox history.</span></label></details><div class="form-error" role="alert"></div><button class="button primary" type="submit">Reconcile saved intent</button></form>`);return;
    }
    await loadLive(false);
  }catch(error){toast(error.message);}finally{button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['live-config-form','live-connection-form','live-history-form','live-start-form','live-resolve-form'].includes(form.id))return;
  event.preventDefault();const button=form.querySelector('[type="submit"]'),errorBox=form.querySelector('.form-error');button.disabled=true;errorBox.textContent='';
  try{
    if(form.id==='live-config-form'){
      const value=readForm(form,liveState.schema);delete value.filters;value.filters=readForm(form,liveState.filters_schema);
      liveState=await api('live/config','PUT',value);toast('Settings saved. The next live cycle will use these rules.');
    }
    if(form.id==='live-connection-form'){liveState=await api('live/connection','PUT',readForm(form,liveState.connection_schema));toast('Live connection settings saved.');}
    if(form.id==='live-history-form')await loadLiveHistory(1);
    if(form.id==='live-start-form'){liveState=await api('live/start','POST',{acknowledge_real_orders:form.elements.acknowledge.checked});$('#modal').close();toast('Real trading runner started.');}
    if(form.id==='live-resolve-form'){liveState=await api('live/resolve','POST',{intent_id:form.elements.intent_id.value,order_id:form.elements.order_id.value.trim(),confirmed_not_placed:form.elements.confirmed_not_placed.checked,confirmed_history_details:form.elements.confirmed_history_details.checked,final_status:form.elements.final_status.value,filled_quantity:Number(form.elements.filled_quantity.value),average_price:Number(form.elements.average_price.value)});$('#modal').close();toast('Order intent reconciled.');}
    updateLivePanels();
  }catch(error){errorBox.textContent=error.message;}finally{button.disabled=false;}
});
setInterval(()=>{if(location.hash==='#live'&&!document.hidden)loadLive(true);},15000);
