const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({document:{querySelector:()=>null,addEventListener(){}},location:{hash:'#intraday'}});
const app=fs.readFileSync('dashboard/web/app.js','utf8');
vm.runInContext(app.slice(0,app.indexOf("$('#modal').addEventListener('close'")),context);
vm.runInContext(fs.readFileSync('dashboard/web/research-archive.js','utf8'),context);
const data=JSON.parse(fs.readFileSync('dashboard/web/research-archive-data.json','utf8'));
context.archive=data;
vm.runInContext('state={user:{is_admin:false}};researchArchiveData=archive;',context);
for(const category of ['intraday','futures']){
  const page=vm.runInContext(`researchArchiveView('${category}')`,context);
  assert.match(page,/No positive automation found/);
  assert.match(page,/Download all analysis/);
  const expected=data.records.filter(r=>r.category===category);
  assert.ok(expected.length>30);
  assert.equal((page.match(/class="research-record"/g)||[]).length,expected.length);
  assert.match(vm.runInContext(`workspaceNavigation('${category}')`,context),new RegExp(`<s>${category==='intraday'?'Intraday':'Futures'}</s>`));
}
assert.match(vm.runInContext("researchArchiveView('futures')",context),/investigations tested options/);
vm.runInContext(`researchArchiveData={as_of:'today',records:[{category:'intraday',title:'<img src=x>',source:'<script>',content:'<script>alert(1)</script>'}]};`,context);
const unsafe=vm.runInContext("researchArchiveView('intraday')",context);
assert.doesNotMatch(unsafe,/<script>|<img/);
assert.match(unsafe,/&lt;script&gt;/);
vm.runInContext('researchArchiveData=null;researchArchiveError=true;',context);
assert.match(vm.runInContext("researchArchiveView('intraday')",context),/Reload this page to retry/);
console.log('Research archive routes, source coverage, strikethrough, HTML escaping and load failure passed.');
