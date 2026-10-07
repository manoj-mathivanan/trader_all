// Exercise the real form initialization and dropdown handlers without a server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {};
const context = vm.createContext({
  document: {querySelector: selector => selector==='#modal'?{open:true}:null, addEventListener: (event, handler) => {listeners[event] = handler;}},
  FormData: class {
    constructor(form) {this.form = form;}
    get(key) {return this.form.elements[key]?.value ?? null;}
    has(key) {return Boolean(this.form.elements[key]?.checked);}
  },
});
const source = fs.readFileSync('dashboard/web/app.js', 'utf8');
vm.runInContext(source.slice(0, source.indexOf("$('#modal').addEventListener('close'")), context);
vm.runInContext(`
  state={screens:[{id:'custom_test',pattern:'multiyear',...Object.fromEntries(screenKeys.map(k=>[k,77]))}],jobs:[]};
  const properties=Object.fromEntries(screenKeys.map(k=>[k,{type:'number',default:25}]));
  for(const k of ['name','pattern','start','end','entry_mode','winner_exit','candidate_rank'])properties[k]={type:'string'};
  for(const k of ['capital','risk_pct','stop_pct','breakeven_r','trail_pct','max_positions','max_hold_days','slippage_bps','buy_cost_bps','sell_cost_bps'])properties[k]={type:'number',default:10};
  for(const k of ['skip_weak_markets','acknowledge_limitations'])properties[k]={type:'boolean'};
  for(const k of ['require_long_trend','require_rising_long_trend']){properties[k]={type:'boolean',default:false};state.screens[0][k]=false;}
  properties.market_breadth_pct={type:'number',default:40};properties.market_min_coverage_pct={type:'number',default:80};properties.minimum_warmup_sessions={type:'integer',default:50};
  state.backtest_schema={properties};
  properties.execution_horizon={type:'string',default:'swing',enum:['swing','intraday']};
  properties.square_off_time={type:'string',default:'15:00'};
  properties.start.format='date';properties.end.format='date';
  const form={id:'backtest-form',elements:Object.fromEntries(Object.keys(properties).concat('screen').map(k=>[k,{value:'original',type:properties[k]?.type==='boolean'?'checkbox':'text',checked:false}]))};
  modal=(_title,body)=>{globalThis.body=body;};
  api=async path=>{globalThis.windowPath=path;return {start:'2020-01-01',end:'2025-12-31',history_start:'2019-01-01',history_end:'2025-12-31',ready_symbols:50,total_symbols:50};};
  globalThis.form=form;
`, context);
const form = context.form;
function changeScreen(value) {
  listeners.change({target:{id:'screen-picker',value,closest:()=>form}});
}
(async () => {
  // Custom -> built-in must reset every filter, not just the pattern name.
  changeScreen('custom_test');
  assert.equal(form.elements.base_days.value, 77);
  for(const pattern of ['vcp','blue_sky','multiyear','ipo']) {
    changeScreen(`builtin:${pattern}`);
    assert.equal(form.elements.pattern.value, pattern);
    assert.equal(form.elements.base_days.value, 15);
    assert.equal(form.elements.max_depth_pct.value, 35);
    assert.equal(form.elements.volume_multiple.value, 1);
    assert.equal(form.elements.vcp_volume_multiple.value, .9);
    assert.equal(form.elements.multiyear_base_days.value, 260);
    assert.equal(form.elements.capital.value, 'original');
    assert.equal(form.elements.slippage_bps.value, 'original');
    changeScreen('custom_test');
  }
  // The single screen selector supplies the hidden pattern in the submitted payload.
  changeScreen('builtin:vcp');
  assert.equal(form.elements.screen.value, 'builtin:vcp');
  assert.equal(form.elements.volume_multiple.value, 1);
  const payload = vm.runInContext('readForm(form,state.backtest_schema)', context);
  assert.equal(payload.pattern, 'vcp');
  assert.equal(payload.vcp_volume_multiple, .9);
  form.elements.require_long_trend.checked=true;
  changeScreen('builtin:vcp');
  assert.equal(form.elements.require_long_trend.checked,false);

  // Bearish research has a distinct schema and preserves portfolio assumptions.
  vm.runInContext(`
    state.bearish_screens=[['new_lows','52-week low'],['vcp_breakdown','VCP breakdown']];
    state.bearish_schema={properties:{pattern:{type:'string',default:'new_lows'},require_falling_long_trend:{type:'boolean',default:true},require_weak_market:{type:'boolean',default:true},max_rs_rating:{type:'number',default:30},low_lookback_days:{type:'integer',default:252},max_market_breadth_pct:{type:'number',default:40},market_min_coverage_pct:{type:'number',default:80}}};
    state.bearish_backtest_schema={...state.backtest_schema,properties:{...state.backtest_schema.properties,...state.bearish_schema.properties,borrow_cost_bps_year:{type:'number',default:0},execution_horizon:{type:'string',default:'swing',enum:['swing','intraday']},square_off_time:{type:'string',default:'15:00'}}};
    for(const [k,v] of Object.entries(state.bearish_schema.properties))if(!form.elements[k])form.elements[k]={value:'',type:v.type==='boolean'?'checkbox':'text',checked:false};
  `,context);
  changeScreen('bearish:new_lows');
  assert.equal(form.elements.pattern.value,'new_lows');
  assert.equal(form.elements.require_falling_long_trend.checked,true);
  assert.equal(form.elements.max_rs_rating.value,30);
  assert.equal(form.elements.capital.value,'original');
  await vm.runInContext("newBacktest({pattern:'new_lows',capital:100000,risk_pct:1,stop_pct:8,winner_exit:'take_15',minimum_warmup_sessions:260})",context);
  assert.match(context.body,/value="bearish:new_lows" selected/);
  assert.match(context.body,/name="borrow_cost_bps_year"/);
  assert.match(context.body,/value="intraday" selected/);
  assert.match(context.body,/name="square_off_time"[^>]*value="15:00"/);
  assert.match(context.body,/name="require_falling_long_trend"[^>]*checked/);
  assert.doesNotMatch(context.body,/name="require_long_trend"/);
  assert.match(context.windowPath,/warmup=260$/);

  // A fresh dialog must apply VCP before rendering, without requiring a change event.
  await vm.runInContext('newBacktest()', context);
  assert.match(context.body, /name="base_days"[^>]*value="15"/);
  assert.match(context.body, /name="vcp_volume_multiple"[^>]*value="0.9"/);
  assert.match(context.body, /value="builtin:vcp" selected/);
  assert.match(context.body, /type="hidden" name="pattern" value="vcp"/);
  for(const key of ['start','end'])assert.match(context.body,new RegExp(`name="${key}"[^>]*min="2019-01-01"[^>]*max="2025-12-31"`));
  for(const dates of [{start:'2018-12-31',end:'2025-12-31'},{start:'2020-01-01',end:'2026-01-01'},{start:'2026-01-01',end:'2026-01-02'},{start:'2020-01-01',end:'2018-12-31'},{start:'2021-01-01',end:'2020-01-01'}]){
    assert.throws(()=>vm.runInContext(`validateBacktestDates(${JSON.stringify(dates)},{history_start:'2019-01-01',end:'2025-12-31'})`,context));
  }
  assert.doesNotThrow(()=>vm.runInContext("validateBacktestDates({start:'2019-01-01',end:'2025-12-31'},{history_start:'2019-01-01',end:'2025-12-31'})",context));
  assert.match(vm.runInContext("field('start',state.backtest_schema,'',backtestDateBounds({}))",context),/disabled/);
  assert.doesNotMatch(context.body, /<select name="pattern"/);
  await vm.runInContext("newBacktest({screen:'custom_test'})", context);
  assert.match(context.body, /value="custom_test" selected/);
  assert.match(context.body, /name="base_days"[^>]*value="77"/);
  assert.match(context.body, /type="hidden" name="pattern" value="multiyear"/);
  assert.match(context.windowPath, /warmup=126$/);
  // Adjust & rerun preserves explicit historical values until the user changes screen.
  await vm.runInContext("newBacktest({pattern:'vcp',base_days:25,volume_multiple:1.5,vcp_volume_multiple:.8})", context);
  assert.match(context.body, /name="base_days"[^>]*value="25"/);
  assert.match(context.body, /name="vcp_volume_multiple"[^>]*value="0.8"/);
  // The dialog appears before the slow date request resolves, and closing it cancels rendering.
  vm.runInContext(`api=()=>new Promise(resolve=>{globalThis.resolveDates=resolve;});globalThis.modalOpen=true;document.querySelector=selector=>selector==='#modal'?{open:modalOpen}:null;`,context);
  const opening=vm.runInContext('newBacktest()',context);
  assert.match(context.body,/Checking downloaded history/);
  vm.runInContext('modalOpen=false',context);
  context.resolveDates({start:'2020-01-01',end:'2025-12-31'});
  await opening;
  assert.match(context.body,/Checking downloaded history/);
  // An active job gets an explanation and polling can re-enable the existing form.
  vm.runInContext(`
    globalThis.submit={disabled:false};globalThis.availability={textContent:'',hidden:false};
    globalThis.runtimeForm={dataset:{},querySelector:()=>submit};
    document.querySelector=selector=>selector==='#backtest-form'?runtimeForm:selector==='#backtest-availability'?availability:null;
    backtestWindow={start:'2020-01-01',missing_symbols:[]};state.jobs=[{type:'Backtest',status:'running'}];
    updateBacktestAvailability();
  `,context);
  assert.equal(context.submit.disabled,true);
  assert.match(context.availability.textContent,/Backtest is running/);
  vm.runInContext('state.jobs=[];updateBacktestAvailability()',context);
  assert.equal(context.submit.disabled,false);
  vm.runInContext("backtestWindow.missing_symbols=['IDEA'];updateBacktestAvailability()",context);
  assert.equal(context.submit.disabled,true);
  assert.match(context.availability.textContent,/IDEA/);
  console.log('Screen presets, immediate dialog, cancellation, job completion and missing-data explanations passed.');
})().catch(error => {console.error(error);process.exitCode=1;});
