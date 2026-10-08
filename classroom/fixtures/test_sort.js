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
console.log('test_sort: OK (',s.length,'accounts)');
