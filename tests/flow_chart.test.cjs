const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('flow_chart.html','utf8');
const code = source.split('<script>')[1].split('</script>')[0];
const nodes = new Map();
const context = new Proxy({measureText: s => ({width: s.length*6})},{get:(o,k)=>o[k]??(()=>{})});
function get(id){
  if(!nodes.has(id))nodes.set(id,{style:{},checked:true,clientWidth:420,clientHeight:300,getContext:()=>context,replaceChildren(){}});
  return nodes.get(id);
}
vm.runInNewContext(code,{document:{getElementById:get},window:{devicePixelRatio:1},Option:class {},ResizeObserver:class {observe(){}}});
assert.equal(get('flowBuy').textContent,'650 · 65.0%');
assert.equal(get('flowSell').textContent,'350 · 35.0%');
get('flowCanvas').onkeydown({key:'ArrowRight',preventDefault(){}});
assert.match(get('flowTime').textContent,/10:35–10:40/);
const csv='trade_id,timestamp,price,contracts,side\na,2026-11-13T10:31:00+05:30,25000,3,BUY\nb,2026-11-13T10:32:00+05:30,25001,1,SELL';
async function load(raw){await get('flowFile').onchange({target:{files:[{name:'sample.csv',text:async()=>raw}]}})}
(async()=>{
  await load(csv);
  assert.equal(get('flowBuy').textContent,'3 · 75.0%');
  assert.equal(get('flowTotal').textContent,'4 contracts');
  await load(csv+'\n'+csv.split('\n')[1]);
  assert.match(get('flowError').textContent,/row 4/);
  assert.equal(get('flowTotal').textContent,'4 contracts');
  get('flowDemo').onclick();
  assert.equal(get('flowTotal').textContent,'1,000 contracts');
})().catch(e=>{console.error(e);process.exitCode=1});
