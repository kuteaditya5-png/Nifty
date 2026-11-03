const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('main.py','utf8');
const code=source.slice(source.indexOf('function renderBreakouts(data){'),source.indexOf('function renderTradeLevels(data){'));
let markers,status,removed=[];
const context={Set,openingRangeLines:[],candleSeries:{setMarkers:v=>markers=v,createPriceLine:v=>v,removePriceLine:v=>removed.push(v)},setText:(id,t)=>status=t};
vm.createContext(context);vm.runInContext(code,context);
const data={interval:'5m',candles:[{time:1},{time:2}],breakout:{records:[
 {time:1,orb_high:100,orb_low:90,events:[{direction:'REJECTION'}]},
 {time:2,orb_high:100,orb_low:90,events:[{direction:'UP'}]},
 {time:3,orb_high:999,orb_low:888}
]}};
context.renderBreakouts(data);
assert.equal(markers.length,0);assert.equal(context.openingRangeLines.length,2);
assert.equal(context.openingRangeLines[0].title,'OR HIGH');assert.equal(context.openingRangeLines[0].price,100);
assert.equal(context.openingRangeLines[1].title,'OR LOW');assert.equal(context.openingRangeLines[1].price,90);
assert.ok(context.openingRangeLines.every(x=>x.lineStyle===2&&x.color==='#63b4ed'));
context.renderBreakouts(data);assert.equal(removed.length,2);assert.equal(context.openingRangeLines.length,2);
context.renderBreakouts({interval:'15m',candles:[],breakout:null});assert.equal(context.openingRangeLines.length,0);assert.equal(markers.length,0);
context.renderBreakouts({interval:'5m',candles:[{time:4}],breakout:{records:[{time:4,orb_high:null,orb_low:null}]}});assert.equal(context.openingRangeLines.length,0);
console.log('Opening-range lines, labels, refresh cleanup and no candle markers: passed');
