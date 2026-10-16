const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const app=fs.readFileSync('dashboard/web/app.js','utf8');
const ui=fs.readFileSync('dashboard/web/investor-intelligence.js','utf8');
const context=vm.createContext({document:{addEventListener(){}},setInterval(){}});
vm.runInContext(app.slice(0,app.indexOf("$('#modal').addEventListener('close'")),context);
vm.runInContext(ui,context);
vm.runInContext(`
state={settings:{universe:'niftytotalmarket'},jobs:[]};investorUniverse='niftytotalmarket';
investorState={companies:[{isin:'INE000A01001',symbol:'<TEST>',name:'Example'}],coverage:[],llm:{enabled:false,reason:'Not connected'}};
investorEvidence={articles:[],groups:[],review:null};
globalThis.page=investorView();
`,context);
assert.match(context.page,/&lt;TEST&gt;/);
assert.doesNotMatch(context.page,/<TEST>/);
assert.match(context.page,/not connected yet/);
assert.match(context.page,/No interpretation saved/);
assert.match(context.page,/does not imply a positive or negative outlook/);
assert.match(context.page,/data-investor="interpret" disabled/);
assert.match(context.page,/Candidates/);
assert.match(context.page,/Portfolio holdings/);
assert.match(context.page,/New catalysts/);
assert.match(context.page,/Dated review history/);
assert.match(context.page,/Automatic profit exits are disabled/);
assert.match(context.page,/Backtest technical rules/);
vm.runInContext(`investorState.queues={candidates:[],holdings:[],catalysts:[],alerts:[{id:'a',review_id:'r',kind:'material_news_review',status:'open',company:{symbol:'<ALERT>'},reason:'<script>bad</script>'}]};globalThis.alertPage=investorView();`,context);
assert.match(context.alertPage,/&lt;ALERT&gt;/);
assert.doesNotMatch(context.alertPage,/<script>bad/);
vm.runInContext(`
investorState.execution_environment='local';
globalThis.localResearch=investorView();
globalThis.detailsPage=investorDetails({as_of:'2026-10-12T00:00:00Z',fundamentals:{business:'<script>unsafe</script>',ratios:{'P/E':{company:12,sector:20}}},technical:{trend:'bullish',rsi14:60},quote:{last_trade_time:'invalid'},sections:{profile:{status:'available',data:{text:'<script>unsafe</script>'}}}});
`,context);
assert.match(context.localResearch,/Update all queues/);
assert.match(context.detailsPage,/Technical assessment/);
assert.match(context.detailsPage,/&lt;script&gt;unsafe/);
assert.doesNotMatch(context.detailsPage,/<script>unsafe/);
assert.match(context.detailsPage,/Quote trade time Unknown/);
console.log('Investor UI checks passed.');

(async()=>{
  context.structuredClone=structuredClone;
  vm.runInContext(`
    state.backtest_schema={properties:{
      candidate_rank:{type:'string',title:'Priority',enum:['alphabetical','rs_126','fundamental_score'],default:'alphabetical'},
      buy_cost_bps:{type:'number',title:'Buy costs',default:10},sell_cost_bps:{type:'number',title:'Sell costs',default:10},
      slippage_bps:{type:'number',title:'Slippage',default:10},
      name:{type:'string',title:'Name'},start:{type:'string',format:'date',title:'Start'},end:{type:'string',format:'date',title:'End'}
    },$defs:{Rules:{properties:{
      resistance_sessions:{type:'integer',title:'Resistance sessions',default:40},
      max_extension_pct:{type:'number',title:'Maximum extension above pivot (%)',default:5},
      strict_trend:{type:'boolean',title:'Strict trend',default:false}
    }}}};
    modal=(title,html)=>{globalThis.dialogTitle=title;globalThis.dialogHtml=html;};
    document.querySelector=selector=>selector==='#modal'?{open:true}:null;
    updateBacktestAvailability=()=>{};
    api=async path=>{globalThis.requestPath=path;return {start:'2025-10-01',end:'2026-10-09',history_start:'2018-01-01',history_end:'2026-10-09',ready_symbols:600,total_symbols:750};};
  `,context);
  await vm.runInContext(`newBacktest({pattern:'investor_early_breakout',investor_rules:{resistance_sessions:60,max_extension_pct:3,strict_trend:true}})`,context);
  assert.match(context.requestPath,/warmup=100/);
  assert.match(context.dialogHtml,/name="investor_resistance_sessions"[^>]*value="60"/);
  assert.match(context.dialogHtml,/name="investor_max_extension_pct"[^>]*value="3"/);
  assert.match(context.dialogHtml,/name="investor_strict_trend"[^>]*checked/);
  assert.match(context.dialogHtml,/name="buy_cost_bps"[^>]*value="10"/);
  assert.doesNotMatch(context.dialogHtml,/value="fundamental_score"/);
  assert.doesNotMatch(context.dialogHtml,/name="entry_mode"/);
  assert.match(context.dialogHtml,/value="investor_early_breakout" selected/);
  assert.match(context.dialogHtml,/Financial and news assessments are excluded/);
  assert.equal(vm.runInContext(`state.backtest_schema.properties.candidate_rank.enum.includes('fundamental_score')`,context),true);
  console.log('Investor backtest dialog preserves saved rules, warmup, cost defaults and the general schema.');
})().catch(error=>{console.error(error);process.exitCode=1;});

vm.runInContext(`investorEvidence.news_coverage={status:'full_article_unavailable',reason:'<unsafe>'};globalThis.coveragePage=investorView();`,context);
assert.match(context.coveragePage,/full_article_unavailable/);
assert.match(context.coveragePage,/&lt;unsafe&gt;/);
assert.match(context.coveragePage,/Google News and Bing/);

// Score ranges retain missing evidence; source text is escaped.
vm.runInContext(`globalThis.scoreHtml=investorScore({score:null,range:[42,70],confidence:72,decision:'insufficient_evidence',version:'pilot',components:{news:{score:null,range:[0,100],confidence:0,factors:[{name:'<source>',value:null,score:null,weight:100}]}},blockers:['<missing>'],reasons:[],entry_plan:{},notice:'Observation only'});globalThis.historyHtml=investorScoreHistory([{as_of:'2026-10-13T00:00:00Z',score:80,confidence:90,decision:'buy_candidate',outcome:{returns:{5:{net_return_pct:1.5}}}}]);`,context);
assert.match(context.scoreHtml,/42.*70.*incomplete/);
assert.match(context.scoreHtml,/News 20%/);
assert.match(context.scoreHtml,/&lt;source&gt;/);
assert.match(context.scoreHtml,/&lt;missing&gt;/);
assert.doesNotMatch(context.scoreHtml,/<missing>|<source>/);
assert.match(context.historyHtml,/5 sessions: 1\.5%/);
console.log('Investor score ranges, forward outcomes and source escaping passed.');
