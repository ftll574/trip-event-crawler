// Minimal HTTP fetch helper for research (OpenSSL via Node, bypasses schannel sandbox limits).
// Usage: node fetch.mjs <url> [mode]
//   mode: text (default) | html | head | links
import { setTimeout as sleep } from 'node:timers/promises';

const url = process.argv[2];
const mode = process.argv[3] || 'text';

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
  'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
};

async function fetchOnce(u) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 45000);
  try {
    const r = await fetch(u, { headers: HEADERS, redirect: 'follow', signal: ctrl.signal });
    const body = await r.text();
    return { status: r.status, finalUrl: r.url, body };
  } finally { clearTimeout(t); }
}

function decodeEntities(s) {
  return s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ').replace(/&#x?\w+;/g, ' ');
}

function toText(html) {
  return decodeEntities(
    html.replace(/<script[\s\S]*?<\/script>/gi, ' ')
        .replace(/<style[\s\S]*?<\/style>/gi, ' ')
        .replace(/<[^>]+>/g, ' ')
  ).replace(/\s+/g, ' ').trim();
}

try {
  const { status, finalUrl, body } = await fetchOnce(url);
  console.log(`== STATUS ${status} | FINAL ${finalUrl} | ${Math.round(body.length / 1024)}KB ==`);
  if (mode === 'head') {
    const title = body.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    const desc = body.match(/<meta[^>]+name=["']description["'][^>]*content=["']([^"']*)["']/i);
    console.log('TITLE:', title ? decodeEntities(title[1]).trim() : '(none)');
    console.log('DESC:', desc ? decodeEntities(desc[1]).trim() : '(none)');
  } else if (mode === 'links') {
    const out = new Set();
    for (const m of body.matchAll(/<a[^>]+href=["']([^"'#]+)["']/gi)) {
      let h = m[1]; if (h.startsWith('//')) h = 'https:' + h;
      if (/^https?:\/\//.test(h)) out.add(h);
    }
    for (const h of [...out].slice(0, 200)) console.log(h);
  } else if (mode === 'html') {
    console.log(body.slice(0, 60000));
  } else {
    const t = toText(body);
    console.log(t.slice(0, 12000));
  }
} catch (e) {
  console.log('FETCH_ERROR: ' + e.message);
  process.exit(2);
}
