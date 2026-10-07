const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = {'#modal': {open: true}, '#bearish-results': {innerHTML: ''}};
const context = vm.createContext({
  document: {querySelector: s => nodes[s], addEventListener: () => {}},
  FormData: class {constructor(form){this.form=form;}get(k){return this.form.elements[k]?.value;}has(k){return Boolean(this.form.elements[k]?.checked);}},
});
const source = fs.readFileSync('dashboard/web/app.js', 'utf8');
vm.runInContext(source.slice(0,source.indexOf("$('#modal').addEventListener('close'")),context);
vm.runInContext(`
  state={bearish_schema:{properties:{pattern:{type:'string',default:'vcp_breakdown',enum:['vcp_breakdown','new_lows','multiyear_breakdown','ipo_breakdown']},max_rs_rating:{type:'number',default:30},require_weak_market:{type:'boolean',default:true}}}};
  modal=(_title,body)=>{globalThis.body=body;};
  globalThis.form={elements:{pattern:{value:'new_lows'},max_rs_rating:{value:30},require_weak_market:{checked:true}},querySelector:s=>s==='[type="submit"]'?submit:errorBox};
  globalThis.submit={disabled:false};globalThis.errorBox={textContent:''};
  api=async(path,method,payload)=>{globalThis.sent={path,method,payload};return {as_of:'2024-10-07',scanned_symbols:50,total_symbols:50,market_breadth_pct:20,market_coverage_pct:100,market_gate_passed:true,matches:[],excluded:[]};};
`,context);
nodes['#bearish-form']=context.form;
(async()=>{
  vm.runInContext("newBearishScreen('new_lows')",context);
  assert.match(context.body,/value="new_lows" selected/);
  assert.match(context.body,/52-week low/);
  assert.match(context.body,/name="require_weak_market"[^>]*checked/);
  assert.match(context.body,/long positions only/);
  await vm.runInContext('submitBearishScreen(form)',context);
  assert.equal(context.sent.path,'bearish/scan');
  assert.equal(context.sent.payload.pattern,'new_lows');
  assert.equal(context.sent.payload.require_weak_market,true);
  assert.match(nodes['#bearish-results'].innerHTML,/No bearish setups qualify/);
  assert.equal(context.submit.disabled,false);
  const html=vm.runInContext(`bearishResults({as_of:'2024-10-07',scanned_symbols:1,total_symbols:2,market_breadth_pct:80,market_coverage_pct:50,market_gate_passed:false,matches:[],excluded:[{symbol:'<img>',reason:'stale'}]})`,context);
  assert.match(html,/weak-market gate did not pass/);
  assert.match(html,/&lt;img&gt;/);
  // A result arriving after the dialog closes cannot replace its content.
  vm.runInContext('api=()=>new Promise(resolve=>{globalThis.resolveScan=resolve;})',context);
  const pending=vm.runInContext('submitBearishScreen(form)',context);
  nodes['#modal'].open=false;
  context.resolveScan({});
  await pending;
  assert.match(nodes['#bearish-results'].innerHTML,/Scanning completed/);
  console.log('Bearish form, scan payload, results, escaping and dialog cancellation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
