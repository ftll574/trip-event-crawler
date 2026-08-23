// Try unauthenticated affiliate API endpoint to confirm auth requirement.
// Endpoint pattern: POST https://www.trip.com/restapi/soa2/18073/json/<operation>
const ops = ['queryCommissionPlan', 'queryPromotionList', 'getCouponList', 'queryCampaignList'];
for (const op of ops) {
  try {
    const r = await fetch(`https://www.trip.com/restapi/soa2/18073/json/${op}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0 Chrome/126.0', 'Origin': 'https://www.trip.com', 'Referer': 'https://www.trip.com/partners/' },
      body: JSON.stringify({}),
    });
    const t = await r.text();
    console.log(`${op}: HTTP ${r.status} => ${t.slice(0, 300).replace(/\s+/g, ' ')}`);
  } catch (e) { console.log(`${op}: ERR ${e.message}`); }
}
