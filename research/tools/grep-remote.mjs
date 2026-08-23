// Search a fetched JS/HTML for keyword contexts. Usage: node grep-remote.mjs <url> <keyword> [contextLen]
const url = process.argv[2];
const kw = process.argv[3];
const ctx = Number(process.argv[4] || 300);
const HEADERS = { 'User-Agent': 'Mozilla/5.0 Chrome/126.0' };
try {
  const r = await fetch(url, { headers: HEADERS });
  const b = await r.text();
  console.log(`== ${r.status} | LEN ${b.length} ==`);
  let count = 0;
  let i = -1;
  while ((i = b.toLowerCase().indexOf(kw.toLowerCase(), i + 1)) !== -1 && count < 40) {
    console.log(`--- @${i} ---`);
    console.log(b.slice(Math.max(0, i - ctx / 2), i + ctx).replace(/\s+/g, ' '));
    count++;
  }
  if (!count) console.log('(no match)');
} catch (e) { console.log('FETCH_ERROR: ' + e.message); }
