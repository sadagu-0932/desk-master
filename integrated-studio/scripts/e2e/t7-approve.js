const { connect, S } = require('./lib.js');
const fs = require('fs');
const path = require('path');
const DP = path.join(S, 'data/instances/inst_61bf8c37/datapacks/campsite');

function list() {
  const out = [];
  const walk = d => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) walk(full); else out.push(path.relative(DP, full));
    }
  };
  walk(DP);
  return out;
}
const stamp = () => JSON.stringify(list().map(f => f + ':' + fs.statSync(path.join(DP, f)).mtimeMs));

(async () => {
  const { b, p } = await connect();
  const before = stamp();
  let approved = 0;
  let idle = 0;
  for (let i = 0; i < 80; i++) {
    await p.waitForTimeout(6000);
    const btns = await p.$$('#chat-view-widget button');
    let clicked = false;
    for (const btn of btns) {
      const t = ((await btn.textContent()) || '').trim();
      if (/^(Allow|Approve|Accept|허용|승인)/i.test(t) && (await btn.isVisible()) && (await btn.isEnabled())) {
        await btn.click();
        approved++;
        clicked = true;
        console.log('승인 클릭:', t);
        break;
      }
    }
    const busy = await p.$('#chat-view-widget .codicon-loading, #chat-view-widget .theia-animation-spin');
    idle = (!clicked && !busy) ? idle + 1 : 0;
    if (idle >= 5 && i > 5) break;
  }
  console.log('승인 수:', approved);
  console.log('데이터팩 파일:', list().join(', '));
  console.log('변경 있음:', stamp() !== before);
  const txt = await p.$eval('#chat-view-widget', e => e.innerText);
  console.log('Claude 마지막 답:\n' + txt.slice(-1500));
  await p.screenshot({ path: path.join(S, 'shots/10-claude-done.png') });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
