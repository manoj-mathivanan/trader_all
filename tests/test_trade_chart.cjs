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
