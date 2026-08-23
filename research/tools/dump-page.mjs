// Dump all visible text and JSON-ish blobs from a page. Usage: node dump-page.mjs <url> [maxText]
const url = process.argv[2];
const maxText = Number(process.argv[3] || 20000);
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Accept': 'text/html,*/*;q=0.8',
};
const ctrl = new AbortController();
setTimeout(() => ctrl.abort(), 45000);
try {
  const r = await fetch(url, { headers: HEADERS, redirect: 'follow', signal: ctrl.signal });
  const b = await r.text();
  console.log(`== STATUS ${r.status} | FINAL ${r.url} ==`);
  // visible text
  const text = b.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, '\n').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"')
    .split('\n').map(s => s.trim()).filter(Boolean).join('\n');
  console.log('--- TEXT ---');
  console.log(text.slice(0, maxText));
  console.log('--- SCRIPT SRCs ---');
  for (const m of b.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)) console.log(m[1]);
} catch (e) { console.log('FETCH_ERROR: ' + e.message); }
