const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

async function main(){
  const listeners={},elements={},saved=new Map(),calls=[],timers=[];
  const dialog={open:false,close(){this.open=false;}};
  elements['#modal']=dialog;
  let handler=async()=>{throw Error('Unexpected API call');};
  const context=vm.createContext({
    document:{addEventListener(type,fn){(listeners[type]||=[]).push(fn);}},
    sessionStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
    setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){},
    currentView:'jobs',state:{user:{username:'tester'},jobs:[]},
    $:selector=>elements[selector]||null,
    esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    money:v=>Number(v).toFixed(2),number:v=>String(v),pct:v=>v+'%',equitySvg:()=>'<svg></svg>',
    toast:()=>{},modal(title,body){context.detail={title,body};dialog.open=true;elements['#intraday-report-loading']=body.includes('intraday-report-loading')?{}:null;},
    api:async(path,method='GET',body)=>{calls.push({path,method,body});return handler(path,method,body);}
  });
  vm.runInContext(fs.readFileSync('dashboard/web/intraday-calculator.js','utf8'),context);
  vm.runInContext(fs.readFileSync('dashboard/web/intraday-backtests.js','utf8'),context);
  const runs=[{id:'missing'}, {id:'old',generated_at:'2026-11-03T18:30:00Z'},
    {id:'latest',generated_at:'2026-11-04T23:00:00+05:30'},
    {id:'morning',generated_at:'2026-11-04T09:00:00+05:30'},
    {id:'fallback',generated_at:'invalid',created_at:'2026-11-04T13:00:00Z'}];
  assert.deepEqual(Array.from(context.intradaySortReports(runs),r=>r.id),['latest','fallback','morning','old','missing']);
  assert.equal(runs[0].id,'missing','Sorting must not mutate stored report arrays');
  assert.ok(context.intradayRunWhen({generated_at:'2026-11-04T03:30:00Z'}).includes('09:00:00'));
  assert.equal(context.intradayRunWhen({}),'Run time unavailable');
  const options={stocks:[{symbol:'HDFCBANK',name:'HDFC Bank'},{symbol:'RELIANCE',name:'Reliance'}],start:'2024-11-04',end:'2026-11-03',capital:500000,leverage:5,entry_min:'09:15',entry_max:'15:14',exit_time:'15:15',stop_loss_supported:true,reversal_supported:true};
  const formHtml=context.intradayBacktestFormHtml(options);
  for(const field of ['stock','target_pct','entry_time','direction'])assert.ok(formHtml.includes(`name="${field}"`));
  assert.ok(formHtml.includes('min="555" max="914" step="1"'));
  assert.ok(formHtml.includes('RELIANCE'));
  assert.ok(formHtml.includes('15:15 IST'));
  assert.ok(formHtml.includes('name="stop_loss_enabled"'));
  assert.ok(formHtml.includes('name="reverse_once_on_stop"'));
  assert.ok(formHtml.includes('disabled hidden'));
  assert.ok(!context.intradayBacktestFormHtml({...options,stop_loss_supported:false}).includes('name="stop_loss_enabled"'));
  for(const minute of [555,570,660,899,914])assert.equal(context.intradayMinutes(context.intradayTime(minute)),minute);
  const slider={id:'intraday-trigger-slider',value:'661'},time={id:'intraday-trigger-time',value:'09:30'},label={};
  elements['#intraday-trigger-slider']=slider;elements['#intraday-trigger-time']=time;elements['#intraday-trigger-label']=label;
  listeners.input.at(-1)({target:slider});assert.equal(time.value,'11:01');assert.equal(label.textContent,'11:01 IST');
  time.value='14:59';listeners.input.at(-1)({target:time});assert.equal(Number(slider.value),899);
  const stopDelay={id:'intraday-stop-delay',value:'30'},stopSlider={id:'intraday-stop-slider',value:'30',setAttribute(){}},stopControls={},stopLabel={};
  elements['#intraday-stop-delay']=stopDelay;elements['#intraday-stop-slider']=stopSlider;
  elements['#intraday-stop-controls']=stopControls;elements['#intraday-stop-label']=stopLabel;
  listeners.change.at(-1)({target:{id:'intraday-stop-enabled',checked:true}});
  assert.equal(stopControls.hidden,false);assert.equal(stopControls.disabled,false);
  assert.equal(Number(stopDelay.value),15);assert.ok(stopLabel.textContent.includes('15:14 IST'));
  time.value='09:30';stopDelay.value='30';listeners.input.at(-1)({target:stopDelay});
  assert.ok(stopLabel.textContent.includes('10:00 IST'));
  stopSlider.value='0';listeners.input.at(-1)({target:stopSlider});
  assert.equal(Number(stopDelay.value),0);assert.ok(stopLabel.textContent.includes('09:30 IST'));
  listeners.change.at(-1)({target:{id:'intraday-stop-enabled',checked:false}});
  assert.equal(stopControls.hidden,true);assert.equal(stopControls.disabled,true);

  const submit={disabled:false},error={textContent:''};
  const form={elements:{stock:{value:'RELIANCE'},target_pct:{value:'0.3'},entry_time:{value:'11:45'},direction:{value:'short'},stop_loss_enabled:{checked:false},stop_loss_delay_minutes:{value:'30'},stop_loss_pct:{value:'0.2'},reverse_once_on_stop:{checked:false}},querySelector:selector=>selector==='[type="submit"]'?submit:error};
  elements['#intraday-backtest-form']=form;
  let resolveCreate;handler=()=>new Promise(resolve=>resolveCreate=resolve);
  const first=context.intradaySubmitCustom(form);await context.intradaySubmitCustom(form);
  assert.equal(calls.length,1,'Double submit must create only one job');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].body)),{stock:'RELIANCE',target_pct:.3,entry_time:'11:45',direction:'short'});
  resolveCreate({id:'abcdef123456'});await first;
  assert.equal(dialog.open,false);assert.ok(saved.has('trader-intraday-pending'));
  assert.equal(context.state.jobs[0].id,'abcdef123456');

  handler=async()=>({status:'running',logs:[{message:'Validated 100/495 stock sessions.'}]});
  await context.intradayPollCustom();assert.ok(context.intradayBacktestStatus().includes('Validated 100/495'));
  assert.ok(context.intradayBacktestStatus().includes('href="#jobs"'));
  const report={...JSON.parse(fs.readFileSync('dashboard/reports/reliance-short-target02.json','utf8')),id:'custom-abcdef123456',custom:true,entry_time:'11:45'};
  const {days,curve,skipped,assumptions,fee_sources,...summary}=report;
  summary.trade_count=days.length;summary.skipped_count=skipped.length;
  handler=async path=>path.startsWith('jobs/')?{status:'success',result:{report_id:report.id}}:{reports:[summary]};
  await context.intradayPollCustom();assert.ok(!saved.has('trader-intraday-pending'));
  assert.equal(context.intradayCustomReports()[0].id,report.id);
  assert.ok(context.intradayBacktestView().includes('RELIANCE'));
  assert.ok(context.intradayBacktestView().includes('Backtest</button>'));
  context.oldStatic={...summary,id:'older-static',generated_at:'2024-11-04T00:00:00Z'};
  vm.runInContext('intradayBacktest=oldStatic;',context);
  const sortedTable=context.intradayBacktestView();
  assert.ok(sortedTable.indexOf('data-intraday-report="custom-abcdef123456"')<sortedTable.indexOf('data-intraday-report="older-static"'));
  assert.ok(sortedTable.includes('class="intraday-run-time"'));
  handler=async()=>report;
  await context.intradayOpenCustomReport(report.id);
  assert.ok(context.detail.title.includes('11:45'));
  assert.ok(context.detail.body.includes('Sell · 11:45'));
  assert.ok(context.detail.body.includes('142296.96'));
  report.stop_loss_enabled=true;report.stop_loss_days=1;
  report.days[0]={...report.days[0],stop_price:report.days[0].entry_price*1.0025,stop_active_from:'12:30',exit_reason:'Stop loss',ambiguous_exit:true};
  context.intradayBacktestDetails(report.id);
  assert.ok(context.detail.body.includes('Stop '));
  assert.ok(context.detail.body.includes('from 12:30'));
  assert.ok(context.detail.body.includes('Stop loss *'));
  assert.ok(context.detail.body.includes('1 stop-loss exits'));
  report.reverse_once_on_stop=true;report.outcome_basis='net_day_pnl';report.reversal_count=1;
  report.success_days=0;report.failure_days=1;
  report.trades=[{...report.days[0],leg_number:1,direction:'long'},{...report.days[0],leg_number:2,direction:'short'}];
  context.intradayBacktestDetails(report.id);
  assert.ok(context.detail.body.includes('Trade 2 · Sell'));
  assert.ok(context.detail.body.includes('Entry / side'));
  assert.ok(context.detail.body.includes('0 profitable / 1 non-profitable days'));

  handler=async()=>{throw Error('Another job is active.');};
  form.elements.stop_loss_enabled.checked=true;
  form.elements.reverse_once_on_stop.checked=true;
  form.elements.stop_loss_delay_minutes.value='45';form.elements.stop_loss_pct.value='0.25';
  await context.intradaySubmitCustom(form);
  assert.equal(calls.at(-1).body.stop_loss_enabled,true);
  assert.equal(calls.at(-1).body.stop_loss_delay_minutes,45);
  assert.equal(calls.at(-1).body.stop_loss_pct,.25);
  assert.equal(calls.at(-1).body.reverse_once_on_stop,true);
  assert.equal(error.textContent,'Another job is active.');assert.equal(submit.disabled,false);
  assert.ok(!saved.has('trader-intraday-pending'));
  console.log('Custom backtest inputs, minute slider, duplicate prevention, queued progress, persisted results, correct trigger labels and failure recovery passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
