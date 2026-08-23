// Extract links matching keywords from a page. Usage: node grep-links.mjs <url> [keywords-csv]
import { setTimeout as sleep } from 'node:timers/promises';
const url = process.argv[2];
const kws = (process.argv[3] || 'promo,campaign,sale,coupon,deal,event,activity,1111,1010,1212,black-friday,blackfriday,cyber,discount,offer,優惠,促銷,活動,折扣,折價').toLowerCase().split(',');
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
  'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
};
const ctrl = new AbortController();
const t = setTimeout(() => ctrl.abort(), 45000);
try {
  const r = await fetch(url, { headers: HEADERS, redirect: 'follow', signal: ctrl.signal });
  const body = await r.text();
  console.log(`== STATUS ${r.status} | FINAL ${r.url} | ${Math.round(body.length/1024)}KB ==`);
  const seen = new Set();
  for (const m of body.matchAll(/<a[^>]+href=["']([^"'#]+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    let href = m[1], text = m[2].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    if (href.startsWith('//')) href = 'https:' + href;
    const hay = (href + ' ' + text).toLowerCase();
    if (!kws.some(k => hay.includes(k))) continue;
    const key = href.split('?')[0];
    if (seen.has(key)) { continue; }
    seen.add(key);
    console.log(`- ${href} | ${text.slice(0, 90)}`);
  }
} catch (e) {
  console.log('FETCH_ERROR: ' + e.message);
} finally { clearTimeout(t); }
