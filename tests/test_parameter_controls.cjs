const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('dashboard/web/app.js','utf8');
const context=vm.createContext({document:{querySelector:()=>null,addEventListener(){}},FormData:class{
  constructor(form){this.form=form;}
  get(key){return this.form.elements[key]?.value??null;}
  has(key){return Boolean(this.form.elements[key]?.checked);}
}});
vm.runInContext(source.slice(0,source.indexOf("$('#modal').addEventListener('close'")),context);
vm.runInContext(`state={};globalThis.schema={properties:{risk_pct:{type:'number',title:'Risk per trade (%)',exclusiveMinimum:0,maximum:5,default:1.5}},required:['risk_pct']};`,context);
const html=vm.runInContext(`field('risk_pct',schema)`,context);
assert.match(html,/type="range"/);
assert.match(html,/min="0.01" max="5"/);
assert.equal((html.match(/name="risk_pct"/g)||[]).length,1,'Only the exact-value control submits a value');
assert.match(html,/Lower:.*Higher:.*Example:/s);
assert.match(html,/aria-describedby="parameter-help-/);
assert.equal(vm.runInContext(`sliderBounds({type:'number',minimum:1000,maximum:1e10},'capital')`,context),null);
assert.equal(vm.runInContext(`sliderBounds({type:'number',minimum:0},'min_turnover_rupees')`,context),null);
vm.runInContext(`
  globalThis.input={value:'1.5',disabled:false,readOnly:false,validity:{valid:true}};
  globalThis.slider={value:'2.25',min:'0.01',max:'5',disabled:false,matches:()=>true};
  globalThis.control={querySelector:()=>input,querySelectorAll:()=>[slider]};
  slider.closest=()=>control;input.closest=()=>control;input.matches=()=>false;
  updateParameterControl(slider);
`,context);
assert.equal(context.input.value,'2.25');
assert.equal(vm.runInContext(`readForm({elements:{risk_pct:input}},schema).risk_pct`,context),2.25);
context.input.value='0.125';
vm.runInContext(`updateParameterControl(input)`,context);
assert.equal(context.input.value,'0.125','Exact entry must retain precision beyond slider increments');
assert.equal(context.slider.value,'0.125');
context.input.value='';
vm.runInContext(`updateParameterControl(input)`,context);
assert.equal(context.slider.disabled,true,'Blank exact values must not silently receive a slider default');
context.input.value='2';context.input.validity.valid=false;
vm.runInContext(`syncParameterSliders(control)`,context);
assert.equal(context.slider.disabled,true);
context.input.validity.valid=true;context.input.readOnly=true;context.slider.value='4';
vm.runInContext(`updateParameterControl(slider)`,context);
assert.equal(context.input.value,'2','A slider cannot overwrite a locked value');
context.input.readOnly=false;
vm.runInContext(`state.screens=[{id:'saved',pattern:'vcp',trading_defaults:{risk_pct:3}}];applyScreenPreset({id:'backtest-form',elements:{risk_pct:input},querySelectorAll:()=>[slider]},'saved');`,context);
assert.equal(context.input.value,3);
assert.equal(context.slider.value,3,'Preset changes must synchronize the slider');
const investor=vm.runInContext(`parameterGuidance('max_extension_pct',{properties:{resistance_sessions:{},max_extension_pct:{type:'number'}}})`,context);
assert.match(investor.description,/Zero does not disable/);
assert.doesNotMatch(investor.effect[0],/0 disables/);
const swing=vm.runInContext(`parameterGuidance('max_extension_pct',{properties:{max_extension_pct:{type:'number'}}})`,context);
assert.match(swing.effect[0],/0 disables/);
const paper=vm.runInContext(`parameterGuidance('slippage_bps',{properties:{slippage_bps:{type:'number',exclusiveMinimum:0}}})`,context);
assert.match(paper.description,/zero is unavailable/);
assert.doesNotMatch(paper.effect[0],/0 removes/);
console.log('Parameter guidance, slider/exact input sync, validation, precision, locking and presets passed.');
