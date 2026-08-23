// Inspect a campaign page: title, meta, JSON-LD, embedded JSON blobs with campaign data.
// Usage: node inspect-page.mjs <url>
const url = process.argv[2];
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
  'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
};
const ctrl = new AbortController();
setTimeout(() => ctrl.abort(), 45000);
try {
  const r = await fetch(url, { headers: HEADERS, redirect: 'follow', signal: ctrl.signal });
  const b = await r.text();
  console.log(`== STATUS ${r.status} | FINAL ${r.url} | LEN ${b.length} ==`);
  const t = b.match(/<title[^>]*>([^<]*)<\/title>/i);
  console.log('TITLE:', t ? t[1].trim() : '(none)');
  const metas = [...b.matchAll(/<meta[^>]+(?:name|property)=["'](description|og:title|og:description|og:url|keywords|og:image)["'][^>]*content=["']([^"']*)["']/gi)];
  for (const m of metas) console.log(`META ${m[1]}: ${m[2].slice(0, 250)}`);
  const lds = [...b.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)];
  console.log('JSON-LD blocks:', lds.length);
  lds.slice(0, 4).forEach((m, i) => console.log(`LD${i}:`, m[1].trim().slice(0, 1200)));
  // window.IBU_HOTEL / __INITIAL_STATE__ / script JSON globals
  const g = b.match(/window\.__INITIAL_STATE__\s*=\s*([\s\S]{0,2000})/);
  if (g) console.log('INITIAL_STATE head:', g[1].slice(0, 600));
  // look for campaign-ish keys in raw html
  for (const key of ['startTime', 'endTime', 'startDate', 'endDate', 'promoCode', 'couponCode', 'campaignId', 'saleId', 'timezone', 'GMT']) {
    const idxs = [];
    let i = -1;
    while ((i = b.indexOf(key, i + 1)) !== -1 && idxs.length < 3) idxs.push(i);
    if (idxs.length) console.log(`KEY ${key} @${idxs.join(',')}:`, b.slice(idxs[0] - 40, idxs[0] + 180).replace(/\s+/g, ' '));
  }
} catch (e) { console.log('FETCH_ERROR: ' + e.message); }
