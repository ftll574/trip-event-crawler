// Probe Trip.com market subdomains' deals hub. Usage: node probe-markets.mjs
const HOSTS = ['tw','jp','kr','th','sg','hk','cn','my','vn','ph','id','in','uk','fr','de','it','es','au','us','www'];
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Accept': 'text/html,*/*;q=0.8',
};
async function probe(host) {
  const url = `https://${host}.trip.com/sale/deals/`;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch(url, { headers: { ...HEADERS, 'Accept-Language': 'en-US,en;q=0.9' }, redirect: 'follow', signal: ctrl.signal });
    const b = await r.text();
    const title = (b.match(/<title[^>]*>([^<]*)<\/title>/i) || [])[1] || '';
    console.log(`${host.padEnd(4)} | ${r.status} | final=${r.url.slice(0, 70)} | ${(title.trim() || '(no title)').slice(0, 80)}`);
  } catch (e) {
    console.log(`${host.padEnd(4)} | ERR ${e.message.slice(0, 60)}`);
  } finally { clearTimeout(t); }
}
await Promise.all(HOSTS.map(probe));
