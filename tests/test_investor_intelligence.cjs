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
