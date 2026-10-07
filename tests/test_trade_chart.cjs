const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({document:{addEventListener(){}}});
const source=fs.readFileSync('dashboard/web/app.js','utf8');
vm.runInContext(source.slice(0,source.indexOf("$('#modal').addEventListener('close'")),context);
vm.runInContext(`
  const report={id:'123456abcdef',trades:[
    {symbol:'TEST',entry_date:'2020-01-01',exit_date:'2020-01-02',quantity:1,pnl:-10,r:-1,reason:'Stop'},
    {symbol:'TEST',entry_date:'2020-02-01',exit_date:'2020-02-02',quantity:1,pnl:20,r:2,reason:'Target'}]};
  tradeSort={key:'pnl',direction:'desc'};
  globalThis.table=tradeTable(report);
  globalThis.klinecharts={registerOverlay: definition=>{globalThis.marker=definition;}};
  registerTradeMarker();
`,context);
const indices=[...context.table.matchAll(/data-trade="(\d+)"/g)].map(m=>Number(m[1]));
assert.deepEqual(indices,[1,0]);
assert.equal((context.table.match(/data-action="trade-chart"/g)||[]).length,2);
for(const side of ['buy','sell']){
  const figures=context.marker.createPointFigures({coordinates:[{x:100,y:200}],bounding:{width:500},overlay:{extendData:{side,label:side.toUpperCase()}}});
  assert.equal(figures[0].attrs.x,100);
  assert.equal(figures[0].attrs.y,200);
  assert.equal(figures[2].attrs.text,side.toUpperCase());
  assert.equal(figures[2].attrs.y,side==='buy'?224:176);
}
console.log('Sorted repeated-stock rows retain trade identity; buy/sell markers anchor to exact coordinates.');
const figures=vm.runInContext("tradeIndicatorFigures([{id:'sma_200',label:'SMA 200',color:'#5879c6'}])",context);
assert.equal(figures[0].key,'sma_200');
assert.equal(figures[0].type,'line');
assert.equal(figures[0].styles().color,'#5879c6');
const signal=context.marker.createPointFigures({coordinates:[{x:100,y:200}],bounding:{width:500},overlay:{extendData:{side:'signal',label:'SIGNAL'}}});
assert.equal(signal[2].attrs.text,'SIGNAL');
assert.equal(signal[2].attrs.y,152);

const allMarkers=vm.runInContext("stockTradeMarkers({trades:[{entry_date:'2020-01-01',exit_date:'2020-01-02',entry:100,exit:90},{direction:'short',entry_date:'2020-02-01',exit_date:'2020-02-02',entry:90,exit:80}]})",context);
assert.equal(allMarkers.length,4);
assert.deepEqual(Array.from(allMarkers,m=>m.side),['buy','sell','sell','buy']);
assert.match(allMarkers[0].label,/BUY #1/);
assert.match(allMarkers[1].label,/SELL #1/);
assert.match(allMarkers[2].label,/SHORT #2/);
assert.match(allMarkers[3].label,/COVER #2/);
const stockList=vm.runInContext("stockTradeList({symbol:'TEST',run_id:'run',trade_index:5,trades:[{trade_index:2,pnl:1},{trade_index:5,pnl:2}]})",context);
assert.match(stockList,/data-trade="2"/);
assert.match(stockList,/data-trade="5" aria-current="true"/);
console.log('All stock fills receive matching trade numbers, including short and cover fills.');
