'use strict';
let intradayUserReports=[], intradayCustomLoaded=false, intradayCustomLoading=false, intradayCustomError='';
let intradayCustomPending=null, intradayCustomTimer=null, intradayCustomPollError='';
let intradayCustomSubmitting=false, intradayCustomPolling=false, intradayCustomDetailRequest=0;
let intradayBacktestDraft={stock:'HDFCBANK',target_pct:.2,entry_time:'09:30',direction:'long'};
try{const saved=JSON.parse(sessionStorage.getItem('trader-intraday-pending')||'null');if(saved&&/^[a-f0-9]{12}$/.test(saved.id))intradayCustomPending=saved;}catch{}

function intradayCustomReports(){return intradayUserReports;}
function intradayCustomRedraw(){if(currentView==='intraday'){if(state)render();else if(typeof accountSession==='undefined'||accountSession)intradayPrime();}}
function intradayRememberPending(){try{if(intradayCustomPending)sessionStorage.setItem('trader-intraday-pending',JSON.stringify(intradayCustomPending));else sessionStorage.removeItem('trader-intraday-pending');}catch{}}

function intradayBacktestStatus(){
  if(intradayCustomPending)return `<div class="notice intraday-run-status" role="status">${esc(intradayCustomPending.message||'Backtest running…')} ${intradayCustomPollError?`${esc(intradayCustomPollError)} <button class="text-button" id="intraday-check-progress">Check progress</button>`:''}</div>`;
  if(intradayCustomError)return `<div class="notice warn" role="status">${esc(intradayCustomError)} <button class="text-button" id="intraday-custom-retry">Reload saved results</button></div>`;
  return '';
}

function intradayEnsureCustom(){
  if(!intradayCustomLoaded&&!intradayCustomLoading&&!intradayCustomError)void intradayLoadCustomReports();
  if(intradayCustomPending&&!intradayCustomTimer&&!intradayCustomPolling&&!intradayCustomPollError)intradayCustomTimer=setTimeout(intradayPollCustom,500);
}

async function intradayLoadCustomReports(){
  intradayCustomLoading=true;intradayCustomError='';
  try{
    const result=await api('intraday/backtests');
    const previous=new Map(intradayUserReports.map(r=>[r.id,r]));
    intradayUserReports=result.reports.map(r=>previous.get(r.id)?.days?previous.get(r.id):r);
    intradayCustomLoaded=true;
  }catch(error){intradayCustomError=error.message;}
  finally{intradayCustomLoading=false;intradayCustomRedraw();}
}

function intradayMinutes(time){const [h,m]=time.split(':').map(Number);return h*60+m;}
function intradayTime(minutes){return String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');}

function intradayBacktestFormHtml(options){
  const d=intradayBacktestDraft;
  return `<form id="intraday-backtest-form"><div class="intraday-backtest-fields">
    <label class="field"><span>Stock</span><select name="stock" required>${options.stocks.map(s=>`<option value="${esc(s.symbol)}" ${s.symbol===d.stock?'selected':''}>${esc(s.symbol)} · ${esc(s.name)}</option>`).join('')}</select></label>
    <label class="field"><span>Target movement (%)</span><input name="target_pct" type="number" min="0.0001" max="99.9999" step="any" required value="${d.target_pct}"></label>
    <label class="field"><span>Buy / sell</span><select name="direction"><option value="long" ${d.direction==='long'?'selected':''}>Buy · long</option><option value="short" ${d.direction==='short'?'selected':''}>Sell · short</option></select></label>
    <label class="field"><span>Trigger time (IST)</span><input name="entry_time" id="intraday-trigger-time" type="time" min="${options.entry_min}" max="${options.entry_max}" step="60" required value="${esc(d.entry_time)}"></label>
    <div class="field intraday-time-control"><label for="intraday-trigger-slider">Market entry time · <output id="intraday-trigger-label">${esc(d.entry_time)} IST</output></label><input id="intraday-trigger-slider" type="range" min="${intradayMinutes(options.entry_min)}" max="${intradayMinutes(options.entry_max)}" step="1" value="${intradayMinutes(d.entry_time)}"><div class="intraday-time-labels"><span>${options.entry_min}</span><span>12:15</span><span>${options.entry_max}</span></div></div>
    </div><p class="settings-context">${esc(options.start)} → ${esc(options.end)} · ${money(options.capital)} starting capital · ${options.leverage}× leverage, compounded daily. Enter at the selected minute’s opening price. Exit at the target or ${esc(options.exit_time)} IST. Includes Zerodha charges; excludes slippage. Uses saved, audited one-minute data.</p>
    <div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button class="button primary" type="submit">Run backtest</button></div></form>`;
}

async function intradayNewBacktest(){
  if(intradayCustomPending||intradayCustomSubmitting){toast('A backtest is already running.');return;}
  modal('Intraday backtest','<p id="intraday-form-loading" role="status">Loading available stocks…</p>');
  try{
    const options=await api('intraday/backtest-options');
    if(!$('#modal').open||!$('#intraday-form-loading'))return;
    if(!options.stocks.length)throw new Error('No audited stock history is available.');
    if(!options.stocks.some(s=>s.symbol===intradayBacktestDraft.stock))intradayBacktestDraft.stock=options.stocks[0].symbol;
    modal('Intraday backtest',intradayBacktestFormHtml(options));
  }catch(error){if($('#modal').open&&$('#intraday-form-loading'))modal('Intraday backtest',`<p role="alert">${esc(error.message)}</p>`);}
}

async function intradaySubmitCustom(form){
  if(intradayCustomPending||intradayCustomSubmitting)return;
  const submit=form.querySelector('[type="submit"]'), error=form.querySelector('.form-error');
  const config={stock:form.elements.stock.value,target_pct:Number(form.elements.target_pct.value),entry_time:form.elements.entry_time.value,direction:form.elements.direction.value};
  intradayBacktestDraft=config;intradayCustomSubmitting=true;submit.disabled=true;error.textContent='';
  try{
    const job=await api('intraday/backtests','POST',config);
    intradayCustomPending={id:job.id,message:'Backtest queued. Validating saved market data…'};
    intradayCustomPollError='';intradayRememberPending();
    if($('#intraday-backtest-form')===form)$('#modal').close();
    intradayCustomRedraw();
    if(!intradayCustomTimer)intradayCustomTimer=setTimeout(intradayPollCustom,500);
  }catch(cause){error.textContent=cause.message;submit.disabled=false;}
  finally{intradayCustomSubmitting=false;}
}

async function intradayPollCustom(){
  intradayCustomTimer=null;
  if(!intradayCustomPending||intradayCustomPolling)return;
  intradayCustomPolling=true;
  try{
    const job=await api('jobs/'+encodeURIComponent(intradayCustomPending.id));
    if(['queued','running'].includes(job.status)){
      intradayCustomPending.message=job.logs?.at(-1)?.message||'Backtest running…';
      intradayCustomPollError='';intradayRememberPending();intradayCustomRedraw();
      intradayCustomTimer=setTimeout(intradayPollCustom,2000);return;
    }
    intradayCustomPending=null;intradayCustomPollError='';intradayRememberPending();
    if(!['success','warning'].includes(job.status)||!job.result?.report_id){intradayCustomError=job.logs?.at(-1)?.message||'Backtest failed. Review Jobs & logs.';intradayCustomRedraw();return;}
    await intradayLoadCustomReports();
    if(currentView==='intraday'&&state&&!$('#modal').open)await intradayOpenCustomReport(job.result.report_id);
    else toast('Intraday backtest complete. Result saved in Intraday.');
  }catch(error){intradayCustomPollError=error.message;intradayCustomRedraw();}
  finally{intradayCustomPolling=false;}
}

async function intradayOpenCustomReport(id){
  if(!/^custom-[a-f0-9]{12}$/.test(id))return;
  const request=++intradayCustomDetailRequest;
  modal('Intraday backtest','<p id="intraday-report-loading" role="status">Loading daily trades…</p>');
  try{
    const report=await api('intraday/backtests/'+id);
    intradayUserReports=intradayUserReports.map(r=>r.id===id?report:r);
    if(!intradayUserReports.some(r=>r.id===id))intradayUserReports.unshift(report);
    if(request===intradayCustomDetailRequest&&$('#modal').open&&$('#intraday-report-loading'))intradayBacktestDetails(id);
  }catch(error){if(request===intradayCustomDetailRequest&&$('#modal').open&&$('#intraday-report-loading'))modal('Intraday backtest',`<p role="alert">${esc(error.message)}</p>`);}
}

document.addEventListener('click',event=>{
  if(event.target.closest('#intraday-new-backtest'))void intradayNewBacktest();
  if(event.target.id==='intraday-custom-retry')void intradayLoadCustomReports();
  if(event.target.id==='intraday-check-progress'&&intradayCustomPending&&!intradayCustomTimer&&!intradayCustomPolling){intradayCustomPollError='';void intradayPollCustom();}
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='intraday-backtest-form')return;
  event.preventDefault();event.stopImmediatePropagation();void intradaySubmitCustom(event.target);
});
document.addEventListener('input',event=>{
  if(!['intraday-trigger-slider','intraday-trigger-time'].includes(event.target.id))return;
  const slider=$('#intraday-trigger-slider'),time=$('#intraday-trigger-time');
  if(event.target===slider)time.value=intradayTime(Number(slider.value));
  else if(time.value)slider.value=intradayMinutes(time.value);
  $('#intraday-trigger-label').textContent=(time.value||'Choose time')+' IST';
});
