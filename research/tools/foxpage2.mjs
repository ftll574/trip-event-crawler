// Extract coupon/timer component props from __foxpage_data__ structures.
// Usage: node foxpage2.mjs <url>
const url = process.argv[2];
const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 Chrome/126.0' } });
const b = await r.text();
const m = b.match(/<script id="__foxpage_data__" type="application\/json">([\s\S]*?)<\/script>/);
if (!m) { console.log('NO DATA'); process.exit(1); }
const data = JSON.parse(m[1]);
console.log('structures type:', typeof data.structures, Array.isArray(data.structures) ? 'array len ' + data.structures.length : Object.keys(data.structures || {}).length);
const structs = Array.isArray(data.structures) ? data.structures : Object.values(data.structures || {});
let shown = 0;
for (const n of structs) {
  const label = n.structure?.label || n.label || '';
  if (/coupon|timer|countdown|seckill/i.test((n.name || '') + ' ' + label) && shown < 6) {
    shown++;
    console.log(`\n### ${label} [${n.id}] name=${n.name}`);
    console.log(JSON.stringify(n.props, null, 1).slice(0, 2500));
  }
}
if (!shown) {
  // show one sample structure node to learn schema
  console.log('SAMPLE NODE:', JSON.stringify(structs[10] || structs[0], null, 1).slice(0, 3000));
}
