// Extract and analyze the __foxpage_data__ JSON from a Trip.com campaign page.
// Usage: node foxpage.mjs <url>
const url = process.argv[2];
const HEADERS = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36' };
const r = await fetch(url, { headers: HEADERS });
const b = await r.text();
console.log(`== ${r.status} | LEN ${b.length} ==`);
const m = b.match(/<script id="__foxpage_data__" type="application\/json">([\s\S]*?)<\/script>/);
if (!m) { console.log('NO __foxpage_data__ FOUND'); process.exit(1); }
const data = JSON.parse(m[1]);
console.log('TOP KEYS:', Object.keys(data));
console.log('PAGE:', JSON.stringify(data.page));
console.log('MODULES COUNT:', (data.modules || []).length);
for (const mod of (data.modules || []).slice(0, 30)) {
  console.log(`- module: ${mod.name} v${mod.version}`);
}
// components tree: find coupon/timer/campaign components
function walk(nodes, depth) {
  if (!nodes || depth > 4) return;
  for (const n of nodes) {
    const label = n.structure?.label || n.name || '';
    if (/coupon|timer|countdown|campaign|promo|seckill/i.test(label + ' ' + (n.name || ''))) {
      console.log(`\n### COMPONENT ${label} (${n.name}) id=${n.id}`);
      console.log(JSON.stringify(n.props || {}, null, 1).slice(0, 1500));
    }
    if (n.childrenIds && n.componentsMap) {
      // children referenced by id in componentsMap
    }
  }
}
// The data structure may include a components map
const compMap = data.components || data.componentsMap;
if (compMap) {
  const arr = Array.isArray(compMap) ? compMap : Object.values(compMap);
  let shown = 0;
  for (const n of arr) {
    const label = n.structure?.label || '';
    if (/coupon|timer|countdown|seckill/i.test((n.name || '') + label) && shown < 8) {
      shown++;
      console.log(`\n### ${label || n.name} [${n.id}]`);
      const p = JSON.stringify(n.props ?? n, null, 1);
      console.log(p.slice(0, 2000));
    }
  }
  if (!shown) console.log('(no coupon/timer components in map; keys: ', Object.keys(arr[0] || {}).join(','), ')');
} else {
  console.log('NO component map key. Available keys:', Object.keys(data).join(','));
}
