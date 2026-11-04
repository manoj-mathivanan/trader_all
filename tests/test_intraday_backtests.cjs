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
  const options={stocks:[{symbol:'HDFCBANK',name:'HDFC Bank'},{symbol:'RELIANCE',name:'Reliance'}],start:'2024-11-04',end:'2026-11-03',capital:500000,leverage:5,entry_min:'09:15',entry_max:'15:14',exit_time:'15:15'};
  const formHtml=context.intradayBacktestFormHtml(options);
  for(const field of ['stock','target_pct','entry_time','direction'])assert.ok(formHtml.includes(`name="${field}"`));
  assert.ok(formHtml.includes('min="555" max="914" step="1"'));
  assert.ok(formHtml.includes('RELIANCE'));
  assert.ok(formHtml.includes('15:15 IST'));
  for(const minute of [555,570,660,899,914])assert.equal(context.intradayMinutes(context.intradayTime(minute)),minute);
  const slider={id:'intraday-trigger-slider',value:'661'},time={id:'intraday-trigger-time',value:'09:30'},label={};
  elements['#intraday-trigger-slider']=slider;elements['#intraday-trigger-time']=time;elements['#intraday-trigger-label']=label;
  listeners.input.at(-1)({target:slider});assert.equal(time.value,'11:01');assert.equal(label.textContent,'11:01 IST');
  time.value='14:59';listeners.input.at(-1)({target:time});assert.equal(Number(slider.value),899);

  const submit={disabled:false},error={textContent:''};
  const form={elements:{stock:{value:'RELIANCE'},target_pct:{value:'0.3'},entry_time:{value:'11:45'},direction:{value:'short'}},querySelector:selector=>selector==='[type="submit"]'?submit:error};
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
  handler=async()=>report;
  await context.intradayOpenCustomReport(report.id);
  assert.ok(context.detail.title.includes('11:45'));
  assert.ok(context.detail.body.includes('Sell · 11:45'));
  assert.ok(context.detail.body.includes('142296.96'));

  handler=async()=>{throw Error('Another job is active.');};
  await context.intradaySubmitCustom(form);
  assert.equal(error.textContent,'Another job is active.');assert.equal(submit.disabled,false);
  assert.ok(!saved.has('trader-intraday-pending'));
  console.log('Custom backtest inputs, minute slider, duplicate prevention, queued progress, persisted results, correct trigger labels and failure recovery passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
