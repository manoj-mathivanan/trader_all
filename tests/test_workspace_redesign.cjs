const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const handlers = {};
const source = fs.readFileSync('dashboard/web/app.js', 'utf8');
const context = vm.createContext({
  document: {querySelector:()=>null, addEventListener:(type,handler)=>{handlers[type]=handler;}},
  location: {hash:'#backtests'},
});
vm.runInContext(source.slice(0,source.indexOf("$('#modal').addEventListener('close'")),context);
const run = code=>vm.runInContext(code,context);
run(`state={token_saved:false,paper_enabled:true,jobs:[],screens:[{id:'custom_a',name:'Saved <screen>',pattern:'vcp'}],strategies:[{id:'swing_patterns',name:'Swing patterns',status:'active'},{id:'intraday_momentum',name:'Momentum',status:'active'},{id:'scalping',name:'Scalping',status:'active'}],paper_schemas:{swing_patterns:{}},scalping_paper_schema:{}};`);
assert.deepEqual(Array.from(run('nav.map(n=>n[0])')),['overview','data','backtests','paper','live','settings','jobs','company','news']);
run('state.instruments=[];');
const dataActions=run('marketRefreshActions()');
assert.match(dataActions,/data-action="refresh-stocks" disabled/);
assert.match(dataActions,/data-action="refresh-fundamentals" disabled/);
assert.match(dataActions,/data-action="refresh-market-news"/);
run('state.instruments=[{isin:"TEST"}];state.token_saved=true;');
assert.doesNotMatch(run('marketRefreshActions()'),/disabled/);
assert.match(run('dataView()'),/Refresh stocks/);
run("state.jobs=[{status:'running'}];");
assert.match(run('marketRefreshActions()'),/data-action="refresh-market-news" disabled/);
run('state.jobs=[];');
const settings=run('settingsView()');
assert.equal((settings.match(/<input /g)||[]).length,1);
assert.match(settings,/name="access_token"/);
assert.doesNotMatch(settings,/settings-form|name="universe"|name="capital"/);
assert.match(run('strategyPicker("scalping")'),/value="scalping" selected/);
run('modal=(title,body)=>{globalThis.dialog={title,body};};chooseBacktestStrategy();');
assert.match(context.dialog.body,/id="launcher-strategy-picker"/);
assert.equal(run('researchTabs()'),'');
assert.match(run('strategyPicker()'),/Saved &lt;strategy&gt;/);
assert.match(run('strategyPicker()'),/value="custom_a"/);
run("state.reference_only=true;state.runs=[];");
assert.doesNotMatch(run('strategyPicker()'),/builtin:|Scalping|Momentum|Early breakout/);
assert.doesNotMatch(run('backtestsView()'),/data-action="new-screen"/);
run('state.reference_only=false;');
run("state.retired_strategy_choices=['builtin:ipo','bearish:new_lows'];");
assert.doesNotMatch(run('strategyPicker()'),/value="builtin:ipo"|value="bearish:new_lows"/);
// Old reports remain adjustable without restoring retired choices to new runs.
assert.match(run('strategyPicker("builtin:ipo")'),/value="builtin:ipo" selected/);
run('state.runs=[];');
assert.doesNotMatch(run('backtestsView()'),/workspace-tabs|Sector filter comparison|screen-library/);
run(`state.runs=[{id:'saved_run',config:{name:'Saved run',start:'2026-01-01',end:'2026-10-01'},metrics:{return_pct:2,max_drawdown_pct:1,trade_count:3}}];`);
assert.match(run('backtestsView()'),/<button type="button" class="panel run-card" data-action="result" data-id="saved_run"/);
assert.doesNotMatch(run('backtestsView()'),/class="run-name"/);
const settingsRows=run("settingsTable({name:'<unsafe>',investor_rules:{strict_trend:true},stop_pct:8})");
assert.match(settingsRows,/&lt;unsafe&gt;/);
assert.match(settingsRows,/investor rules \/ strict trend/);
assert.match(settingsRows,/<td>Yes<\/td>/);
run(`selectedPaperStrategy='swing_patterns';state.paper_schemas={swing_patterns:{}};`);
const recordedSettings=run("paperSettingsView({config:{risk_pct:1},cycles:[{end:'2026-10-15',config:{risk_pct:2}}]})");
assert.match(recordedSettings,/Latest execution settings/);
assert.match(recordedSettings,/2026-10-15/);
assert.match(recordedSettings,/<td>2<\/td>/);
assert.match(recordedSettings,/Current portfolio configuration/);
assert.match(run("paperSettingsView({config:{risk_pct:1},cycles:[]})"),/No executed cycle/);

// Switching tabs changes only the selected panel, preserving the saved content.
run(`
  const panels=[{id:'main',hidden:false},{id:'settings',hidden:true}];
  const tabs=['main','settings'].map(id=>({attrs:{'aria-controls':id},getAttribute(key){return this.attrs[key];},setAttribute(key,value){this.attrs[key]=value;},closest(){return root;}}));
  const root={querySelectorAll:selector=>selector==='[role="tab"]'?tabs:panels};
  activateDetailTab(tabs[1]);
`);
assert.equal(run('panels[0].hidden'),true);
assert.equal(run('panels[1].hidden'),false);
assert.equal(run("tabs[1].attrs['aria-selected']"),'true');

// Changing the strategy inside a dialog routes to the matching engine form.
run('newBacktest=seed=>{globalThis.selectedSeed=seed;};');
handlers.change({target:{id:'backtest-strategy-picker',value:'intraday_momentum',closest:()=>({})}});
assert.equal(context.selectedSeed.strategy_id,'intraday_momentum');
// Switching to Swing while creating paper execution must create an independent ID.
run('paperForm=()=>{};selectedPaperScenario="existing";');
handlers.change({target:{id:'paper-form-strategy-picker',value:'swing_patterns'}});
assert.match(run('selectedPaperScenario'),/^scenario_/);
assert.notEqual(run('selectedPaperScenario'),'existing');

run(`state.paper_scenarios=[{id:'first',strategy_name:'swing_patterns',status:'active',config:{name:'First',pattern:'vcp',capital:10000}},{id:'second',strategy_name:'swing_patterns',status:'paused',config:{name:'Second',pattern:'blue_sky',capital:20000}}];selectedPaperScenario='second';`);
assert.equal(run('paperPortfolio().config.capital'),20000);
assert.match(run("paperPath('portfolio')"),/portfolio_id=second$/);
assert.equal((run('paperPortfolioCards()').match(/class="paper-tile"/g)||[]).length,2);
assert.match(run('paperPortfolioCards()'),/data-id="second"/);
assert.doesNotMatch(run('paperPortfolioCards()'),/disabled|portfolio-card|panel/);
assert.match(run('paperPortfolioCards()'),/Net P&amp;L|Net P&L/);
run("selectedPaperScenario='first';");
assert.equal(run('paperPortfolio().config.capital'),10000);
assert.match(run('paperStrategyPicker()'),/value="intraday_momentum"[^>]*disabled/);
run('state.paper_enabled=false;');
assert.match(run('paperStrategyPicker()'),/Swing patterns · production only/);
run("selectedPaperStrategy='scalping';state.paper_portfolios={};state.scalping_paper={config:{name:'Local scalping',risk_pct:1},stream_session:{day:'2026-10-16',config:{risk_pct:0.5}}};");
assert.equal(run('paperPortfolio().config.name'),'Local scalping');
assert.match(run('paperSettingsView(paperPortfolio())'),/2026-10-16/);
assert.match(run('paperSettingsView(paperPortfolio())'),/<td>0.5<\/td>/);
assert.doesNotMatch(fs.readFileSync('dashboard/web/index.html','utf8'),/<aside/);
console.log('Workspace navigation, token-only settings, saved-screen access, strategy routing and independent portfolio selection passed.');
(async()=>{
  run(`api=async()=>({id:'preview',config:{name:'Preview',pattern:'vcp',entry_mode:'next_open'},metrics:{},curve:[],trades:[],warnings:[],excluded:[]});`);
  await run("showResult('preview')");
  const toolbar=context.dialog.body.split('<div class="stats">')[0];
  assert.deepEqual([...toolbar.matchAll(/data-action="([^"]+)"/g)].map(match=>match[1]).filter(action=>action!=='detail-tab'),['clone']);
  assert.match(context.dialog.body,/role="tab"[^>]*id="backtest-settings-tab"/);
  assert.match(context.dialog.body,/configuration recorded with this backtest/);
  assert.match(toolbar,/Adjust & rerun/);
  console.log('Backtest report exposes only Adjust & rerun in its action toolbar.');
})().catch(error=>{console.error(error);process.exitCode=1;});
