// node fixtures/test_sort.js — sorting + masking + grid-size, stdlib only
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
const js=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const sandbox={module:{exports:{}},window:undefined};vm.runInNewContext(js,sandbox);
const C=sandbox.module.exports;
const d=JSON.parse(fs.readFileSync(path.join(__dirname,'status.sample.json'),'utf8'));
const s=C.sortAccounts(d.accounts);
assert.strictEqual(C.worstWindow(s[0]).severity,'exhausted','first tile is the exhausted one');
assert.ok(C.worstWindow(s[1]).projected_exhaust_epoch,'second tile has a projected exhaust');
assert.ok(C.worstWindow(s[1]).projected_exhaust_epoch<=C.worstWindow(s[2]).projected_exhaust_epoch||!C.worstWindow(s[2]).projected_exhaust_epoch,'soonest projection first');
for(let i=3;i<s.length-1;i++){const a=C.used(C.worstWindow(s[i])),b=C.used(C.worstWindow(s[i+1]));assert.ok(a>=b,`used_pct descending at ${i}: ${a} ${b}`);}
assert.strictEqual(C.mask('trainee01@example.co.kr'),'tr***@example.co.kr');
assert.strictEqual(C.mask(''),'');
assert.strictEqual(C.gridSize(30),'l');assert.strictEqual(C.gridSize(16),'m');assert.strictEqual(C.gridSize(8),'s');assert.strictEqual(C.gridSize(31),'xl');
assert.strictEqual(C.used({used_pct:50,used_pct_effective:0}),0,'effective wins');
assert.strictEqual(C.used({used_pct:50}),50);
assert.strictEqual(C.fmtDelta(3725),'1h 02m');assert.strictEqual(C.fmtDelta(125),'2:05');
// producer-compatible case (Codex finding 2026-10-09): rate_limited severity at 97% must beat a low-usage projected tile
const synth=[
 {id:'low_projected',provider:'codex',email:'a@x',label:'a',plan:'Pro',state:{auth:'ok',subscription:'paid',quota:'ok',usable:true},
  windows:[{kind:'session',label:'5h',used_pct:20,used_pct_effective:20,reset_at_epoch:9e9,severity:'normal',phase:'live',stale:false,projected_exhaust_epoch:1e9}]},
 {id:'exhausted_real',provider:'claude',email:'b@x',label:'b',plan:'Max',state:{auth:'ok',subscription:'paid',quota:'exhausted',usable:false},
  windows:[{kind:'session',label:'5h',used_pct:97,used_pct_effective:97,reset_at_epoch:9e9,severity:'rate_limited',phase:'live',stale:false}]},
 {id:'over100',provider:'xai',email:'c@x',label:'c',plan:'S',state:{auth:'ok',subscription:'paid',quota:'ok',usable:true},
  windows:[{kind:'daily',label:'Daily',used_pct:100,used_pct_effective:100,reset_at_epoch:9e9,severity:'normal',phase:'live',stale:false}]},
 {id:'status_only',provider:'devin',email:'d@x',label:'d',plan:'Core',state:{auth:'ok',subscription:'paid',quota:'exhausted',usable:false},
  windows:[{kind:'weekly',label:'ACUs',used_pct:40,used_pct_effective:40,reset_at_epoch:9e9,severity:'normal',phase:'live',stale:false}]}
];
const o=C.sortAccounts(synth).map(a=>a.id);
assert.ok(o.indexOf('low_projected')>o.indexOf('exhausted_real'),'rate_limited beats projected: '+o);
assert.ok(o.indexOf('low_projected')>o.indexOf('over100'),'used>=100 beats projected: '+o);
assert.ok(o.indexOf('low_projected')>o.indexOf('status_only'),'state.quota exhausted beats projected: '+o);
assert.strictEqual(C.isExhausted({severity:'exceeded',used_pct:5}),true);
assert.strictEqual(C.isExhausted({severity:'normal',used_pct:99.9}),false);
console.log('test_sort: OK (',s.length,'accounts + 4 synthetic)');
