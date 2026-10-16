const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const listeners={};
const nodes={};
const context=vm.createContext({
  document:{querySelector:s=>nodes[s]||null,addEventListener:(type,fn)=>{(listeners[type]??=[]).push(fn);},hidden:false},
  location:{hash:'#live'},setInterval(){},setTimeout(){},
});
const app=fs.readFileSync('dashboard/web/app.js','utf8');
vm.runInContext(app.slice(0,app.indexOf("$('#modal').addEventListener('close'")),context);
vm.runInContext(fs.readFileSync('dashboard/web/live-trading.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
run(`state={instruments:[],screens:[]};liveState={
  config:{capital:100000,max_positions:5,max_order_value:20000,filters:{pattern:'vcp'}},
  schema:{properties:{capital:{type:'number',title:'Capital',default:100000},filters:{type:'object'}}},
  filters_schema:{properties:{pattern:{type:'string',enum:['vcp','blue_sky'],default:'vcp',title:'Strategy'}}},
  connection_schema:{properties:{expected_user_id:{type:'string',title:'Expected account'},static_ip_confirmed:{type:'boolean',title:'Registered IP'}}},
  connection:{expected_user_id:'ACCOUNT1',static_ip_confirmed:true},
  running:false,paused:false,runner:{},
  ledger:{positions:{},orders:[],realized_pnl:0},
  account:{profile:{user_id:'<ACCOUNT>'},fetched_at:'2026-10-16T09:20:00+05:30',funds:{equity:{available_margin:100000}},
    holdings:[{trading_symbol:'<script>evil</script>',quantity:10,t1_quantity:0,current_price:100,average_price:90,current_unrealized_pnl:100,quote_fresh:false}],
    positions:[],orders:[],trades:[]}
};`);
const page=run('liveView()');
assert.match(page,/id="live-config-form"/);
assert.match(page,/Save strategy & risk/);
assert.match(page,/data-live="start"/);
assert.match(page,/real Upstox delivery orders/);
assert.match(page,/&lt;script&gt;evil&lt;\/script&gt;/);
assert.doesNotMatch(page,/<script>evil/);
assert.match(page,/stale \/ market closed/);
assert.match(page,/Today’s broker positions/);
assert.match(page,/Transaction history/);
assert.match(page,/require the server, a valid token and fresh market data/);
assert.match(run('liveConnectionView()'),/expected_user_id/);
assert.match(run('liveConnectionView()'),/API key and secret are not needed/);
run('liveState.running=true;liveState.paused=true;');
const running=run('liveStatusView()');
assert.match(running,/Resume new entries/);
assert.match(running,/Stop runner/);
assert.doesNotMatch(running,/data-live="start"/);
run(`liveState.ledger.orders=[{id:'1234',status:'unknown',side:'BUY',symbol:'<ALERT>',quantity:1,tag:'unique'}];`);
assert.match(run('liveStatusView()'),/Reconcile order/);
assert.match(run('liveStatusView()'),/Automatic orders are blocked/);
run(`liveHistory={page:2,start:'2026-10-01',end:'2026-10-15',has_more:true,trades:[]};`);
assert.match(run('liveHistoryView()'),/Previous page/);
assert.match(run('liveHistoryView()'),/Next page/);
// Background account refreshes update the status and holdings, preserving in-progress form edits.
nodes['#live-config']={innerHTML:'keep-config'};
nodes['#live-config-form']={dirty:true};
nodes['#live-connection-fields']={innerHTML:'keep-connection'};
nodes['#live-connection-form']={dirty:true};
nodes['#live-status']={innerHTML:''};
nodes['#live-account']={innerHTML:''};
run('updateLivePanels()');
assert.equal(nodes['#live-config'].innerHTML,'keep-config');
assert.equal(nodes['#live-connection-fields'].innerHTML,'keep-connection');
assert.match(nodes['#live-account'].innerHTML,/All Upstox holdings/);
assert.match(fs.readFileSync('dashboard/web/index.html','utf8'),/live-trading\.js/);
console.log('Live trading navigation, account rendering, controls, escaping and editable-settings refresh passed.');
