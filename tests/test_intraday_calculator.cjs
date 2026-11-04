const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({document:{addEventListener(){}}});
vm.runInContext(fs.readFileSync('dashboard/web/intraday-calculator.js','utf8'),context);
const calculate=input=>{context.input=input;return vm.runInContext('intradayCalculate(input)',context);};
const base={price:1000,movement:1,capital:10000,success:true};
const win=calculate(base);
assert.equal(win.quantity,50);assert.equal(win.gross,500);assert.equal(win.exit,1010);
// Independent per-order tariff calculation at a notional below the brokerage cap.
const expected=30.15+12.625+100500*.0000307+.1005+1.5+.18*(30.15+100500*.0000307+.1005);
assert.ok(Math.abs(win.charges-expected)<1e-8);
assert.ok(Math.abs(win.net-(500-expected))<1e-8);
assert.equal(calculate({...base,success:false}).gross,-500);
assert.equal(calculate({...base,direction:'short'}).gross,500);
assert.equal(calculate({...base,direction:'short',success:false}).gross,-500);
assert.equal(calculate({...base,capital:100}).charges,0);
assert.equal(calculate({...base,price:3000}).quantity,16);
assert.equal(calculate({...base,movement:0}).gross,0);
assert.equal(calculate({...base,capital:0}).balance,0);
assert.ok(calculate({...base,movement:.001}).net<0);
assert.equal(calculate({...base,capital:100000}).fees.brokerage,40);
for(const input of [{...base,price:0},{...base,price:NaN},{...base,movement:100},{...base,capital:-1}])assert.equal(calculate(input),null);
console.log('Intraday whole-share leverage, long/short outcomes, fees, caps and invalid inputs passed.');

// Exercise the summary and complete ledger using the generated report.
context.report=JSON.parse(fs.readFileSync('dashboard/reports/hdfcbank-target.json','utf8'));
vm.runInContext(`
  intradayBacktest=report;
  function esc(v){return String(v).replaceAll('<','&lt;');}
  function money(v){return Number(v).toFixed(2);}
  function number(v){return String(v);}
  function pct(v){return String(v)+'%';}
  function equitySvg(curve){return '<svg data-points="'+curve.length+'"></svg>';}
  function modal(title,body){globalThis.detail={title,body};}
  globalThis.summary=intradayBacktestView();
  intradayBacktestDetails();
`,context);
assert.ok(context.summary.includes('259 / 235'));
assert.ok(context.summary.includes('169516.03'));
assert.ok(context.detail.body.includes('<svg data-points="495">'));
assert.ok(context.detail.body.includes('2024-11-04'));
assert.ok(context.detail.body.includes('2026-11-03'));
assert.equal((context.detail.body.match(/>Failure<\/td>/g)||[]).length,235);
assert.equal((context.detail.body.match(/>Success<\/td>/g)||[]).length,259);
context.shortReport=JSON.parse(fs.readFileSync('dashboard/reports/hdfcbank-short-target.json','utf8'));
vm.runInContext('intradayShortBacktest=shortReport; globalThis.summary=intradayBacktestView(); intradayBacktestDetails(shortReport.id);',context);
assert.ok(context.summary.includes('249 / 245'));
assert.ok(context.summary.includes('259 / 235'));
assert.ok(context.detail.title.includes('Short'));
assert.ok(context.detail.body.includes('Sell · 09:30'));
assert.ok(context.detail.body.includes('Buy back / minute'));
assert.ok(context.detail.body.includes('155993.97'));
console.log('Backtest summary, capital graph input and all 494 daily ledger rows passed.');
