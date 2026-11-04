'use strict';
let intradayUserReports=[], intradayCustomLoaded=false, intradayCustomLoading=false, intradayCustomError='';
let intradayCustomPending=null, intradayCustomTimer=null, intradayCustomPollError='';
let intradayCustomSubmitting=false, intradayCustomPolling=false, intradayCustomDetailRequest=0;
let intradayBacktestDraft={stock:'HDFCBANK',target_pct:.2,entry_time:'09:30',direction:'long',stop_loss_enabled:false,stop_loss_delay_minutes:30,stop_loss_pct:.2};
try{const saved=JSON.parse(sessionStorage.getItem('trader-intraday-pending')||'null');if(saved&&/^[a-f0-9]{12}$/.test(saved.id))intradayCustomPending=saved;}catch{}

function intradayCustomReports(){return intradayUserReports;}
function intradayCustomRedraw(){if(currentView==='intraday'){if(state)render();else if(typeof accountSession==='undefined'||accountSession)intradayPrime();}}
function intradayRememberPending(){try{if(intradayCustomPending)sessionStorage.setItem('trader-intraday-pending',JSON.stringify(intradayCustomPending));else sessionStorage.removeItem('trader-intraday-pending');}catch{}}

function intradayBacktestStatus(){
  if(intradayCustomPending)return `<div class="notice intraday-run-status" role="status">${esc(intradayCustomPending.message||'Backtest running…')} <a class="text-button" href="#jobs">View in Jobs & logs →</a> ${intradayCustomPollError?`${esc(intradayCustomPollError)} <button class="text-button" id="intraday-check-progress">Check progress</button>`:''}</div>`;
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
function intradayStopMax(time){return Math.max(0,intradayMinutes('15:14')-intradayMinutes(time));}
function intradayStopLabel(time,delay){return `${delay} min after entry · checks from ${intradayTime(intradayMinutes(time)+delay)} IST`;}

function intradaySyncStop(){
  const time=$('#intraday-trigger-time'),delay=$('#intraday-stop-delay'),slider=$('#intraday-stop-slider');
  if(!time?.value||!delay||!slider)return;
  const max=intradayStopMax(time.value);delay.max=max;slider.max=max;
  if(delay.value==='')return;
  const value=Math.max(0,Math.min(max,Math.floor(Number(delay.value))));
  delay.value=value;slider.value=value;
  const label=intradayStopLabel(time.value,value);
  $('#intraday-stop-label').textContent=label;slider.setAttribute('aria-valuetext',label);
}

function intradayBacktestFormHtml(options){
  const d=intradayBacktestDraft;
  const stopEnabled=Boolean(d.stop_loss_enabled), stopMax=intradayStopMax(d.entry_time), stopDelay=Math.min(d.stop_loss_delay_minutes??30,stopMax);
  return `<form id="intraday-backtest-form"><div class="intraday-backtest-fields">
    <label class="field"><span>Stock</span><select name="stock" required>${options.stocks.map(s=>`<option value="${esc(s.symbol)}" ${s.symbol===d.stock?'selected':''}>${esc(s.symbol)} · ${esc(s.name)}</option>`).join('')}</select></label>
    <label class="field"><span>Target movement (%)</span><input name="target_pct" type="number" min="0.0001" max="99.9999" step="any" required value="${d.target_pct}"></label>
    <label class="field"><span>Buy / sell</span><select name="direction"><option value="long" ${d.direction==='long'?'selected':''}>Buy · long</option><option value="short" ${d.direction==='short'?'selected':''}>Sell · short</option></select></label>
    <label class="field"><span>Trigger time (IST)</span><input name="entry_time" id="intraday-trigger-time" type="time" min="${options.entry_min}" max="${options.entry_max}" step="60" required value="${esc(d.entry_time)}"></label>
    <div class="field intraday-time-control"><label for="intraday-trigger-slider">Market entry time · <output id="intraday-trigger-label">${esc(d.entry_time)} IST</output></label><input id="intraday-trigger-slider" type="range" min="${intradayMinutes(options.entry_min)}" max="${intradayMinutes(options.entry_max)}" step="1" value="${intradayMinutes(d.entry_time)}"><div class="intraday-time-labels"><span>${options.entry_min}</span><span>12:15</span><span>${options.entry_max}</span></div></div>
    ${options.stop_loss_supported?`<label class="field checkbox intraday-stop-toggle"><input type="checkbox" name="stop_loss_enabled" id="intraday-stop-enabled" aria-controls="intraday-stop-controls" ${stopEnabled?'checked':''}><span>Enable delayed stop loss</span></label>
    <fieldset id="intraday-stop-controls" class="intraday-stop-controls" ${stopEnabled?'':'disabled hidden'}><legend>Stop loss after entry</legend>
      <label class="field"><span>Delay after entry (minutes)</span><input type="number" name="stop_loss_delay_minutes" id="intraday-stop-delay" min="0" max="${stopMax}" step="1" value="${stopDelay}" required></label>
      <label class="field"><span>Reverse move from entry (%)</span><input type="number" name="stop_loss_pct" min="0.0001" max="99.9999" step="any" value="${d.stop_loss_pct??.2}" required></label>
      <div class="field intraday-time-control"><label for="intraday-stop-slider">Stop-loss delay</label><input type="range" id="intraday-stop-slider" min="0" max="${stopMax}" step="1" value="${stopDelay}" aria-valuetext="${esc(intradayStopLabel(d.entry_time,stopDelay))}"><output id="intraday-stop-label">${esc(intradayStopLabel(d.entry_time,stopDelay))}</output></div>
      <p class="settings-context intraday-time-control">If the trade remains open, start checking the fixed stop after this delay: below entry for Buy, above entry for Sell. A delay of 0 activates it immediately.</p>
    </fieldset>`:''}
    </div><p class="settings-context">${esc(options.start)} → ${esc(options.end)} · ${money(options.capital)} starting capital · ${options.leverage}× leverage, compounded daily. Enter at the selected minute’s opening price. Exit at the target, an enabled stop, or ${esc(options.exit_time)} IST. Includes Zerodha charges; excludes slippage. Uses saved, audited one-minute data.</p>
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
  const stopEnabled=Boolean(form.elements.stop_loss_enabled?.checked);
  if(stopEnabled){config.stop_loss_enabled=true;config.stop_loss_delay_minutes=Number(form.elements.stop_loss_delay_minutes.value);config.stop_loss_pct=Number(form.elements.stop_loss_pct.value);}
  intradayBacktestDraft={...intradayBacktestDraft,...config,stop_loss_enabled:stopEnabled,stop_loss_delay_minutes:Number(form.elements.stop_loss_delay_minutes?.value??intradayBacktestDraft.stop_loss_delay_minutes),stop_loss_pct:Number(form.elements.stop_loss_pct?.value??intradayBacktestDraft.stop_loss_pct)};
  intradayCustomSubmitting=true;submit.disabled=true;error.textContent='';
  try{
    const job=await api('intraday/backtests','POST',config);
    if(state?.jobs)state.jobs=[job,...state.jobs.filter(j=>j.id!==job.id)];
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
    if(currentView==='intraday'&&state?.jobs)state.jobs=state.jobs.map(j=>j.id===job.id?job:j);
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
  if(['intraday-stop-slider','intraday-stop-delay'].includes(event.target.id)){
    if(event.target.id==='intraday-stop-slider')$('#intraday-stop-delay').value=event.target.value;
    intradaySyncStop();return;
  }
  if(!['intraday-trigger-slider','intraday-trigger-time'].includes(event.target.id))return;
  const slider=$('#intraday-trigger-slider'),time=$('#intraday-trigger-time');
  if(event.target===slider)time.value=intradayTime(Number(slider.value));
  else if(time.value)slider.value=intradayMinutes(time.value);
  $('#intraday-trigger-label').textContent=(time.value||'Choose time')+' IST';
  intradaySyncStop();
});
document.addEventListener('change',event=>{
  if(event.target.id!=='intraday-stop-enabled')return;
  const controls=$('#intraday-stop-controls');controls.disabled=!event.target.checked;controls.hidden=!event.target.checked;
  intradaySyncStop();
});
