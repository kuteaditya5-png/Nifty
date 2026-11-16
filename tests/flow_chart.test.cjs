const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('flow_chart.html','utf8');
const code = source.split('<script>')[1].split('</script>')[0];
const nodes = new Map();
const context = new Proxy({measureText: s => ({width: s.length*6})},{get:(o,k)=>o[k]??(()=>{})});
function get(id){
  if(!nodes.has(id))nodes.set(id,{style:{},checked:true,clientWidth:420,clientHeight:300,getContext:()=>context,setAttribute(){},replaceChildren(){}});
  return nodes.get(id);
}
const host={devicePixelRatio:1};
let response={ok:false,status:503};
class FixedDate extends Date {static now(){return Date.parse('2026-11-16T10:12:00+05:30')}}
vm.runInNewContext(code,{Date:FixedDate,fetch:async()=>response,document:{getElementById:get},window:host,Option:class {},ResizeObserver:class {observe(){}}});
assert.equal(get('flowCanvas').hidden,true);
get('flowDemo').onclick();
assert.equal(get('flowBuy').textContent,'650 · 65.0%');
assert.equal(get('flowSell').textContent,'350 · 35.0%');
get('flowCanvas').onkeydown({key:'ArrowRight',preventDefault(){}});
assert.match(get('flowTime').textContent,/10:35–10:40/);
const csv='trade_id,timestamp,price,contracts,side\na,2026-11-13T10:31:00+05:30,25000,3,BUY\nb,2026-11-13T10:32:00+05:30,25001,1,SELL';
async function load(raw){await get('flowFile').onchange({target:{files:[{name:'sample.csv',text:async()=>raw}]}})}
(async()=>{
  get('flowLive').onclick();
  await host.refreshFutures();
  assert.equal(get('flowSource').textContent,'Futures feed not connected');
  response={ok:true,text:async()=>csv};
  await host.refreshFutures();
  assert.match(get('flowSource').textContent,/Historical feed session · 2026-11-13/);
  assert.equal(get('flowCanvas').hidden,false);
  response={ok:true,text:async()=>csv.replaceAll('2026-11-13T10:3','2026-11-16T10:1').replace('10:12:00','10:12:01')};
  await host.refreshFutures();
  assert.equal(get('flowSession').value,'2026-11-16');
  assert.equal(get('flowTotal').textContent,'3 contracts');
  const twoDays=csv+'\n'+'c,2026-11-16T10:10:00+05:30,25070,2,BUY';
  response={ok:true,text:async()=>twoDays};
  await host.refreshFutures();
  assert.equal(get('flowSession').value,'2026-11-16');
  get('flowSession').value='2026-11-13';get('flowSession').onchange();
  await host.refreshFutures();
  assert.match(get('flowSource').textContent,/Historical feed session · 2026-11-13/);
  response={ok:true,text:async()=>csv.split('\n')[0]};
  await host.refreshFutures();assert.equal(get('flowCanvas').hidden,true);
  await load(csv);
  assert.equal(get('flowBuy').textContent,'3 · 75.0%');
  assert.equal(get('flowTotal').textContent,'4 contracts');
  await load(csv+'\n'+csv.split('\n')[1]);
  assert.match(get('flowError').textContent,/row 4/);
  assert.equal(get('flowTotal').textContent,'4 contracts');
  get('flowDemo').onclick();
  assert.equal(get('flowTotal').textContent,'1,000 contracts');
})().catch(e=>{console.error(e);process.exitCode=1});
