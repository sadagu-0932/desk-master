const { connect, notifications } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  await p.focus('.studio-log .studio-log-body');
  await p.keyboard.press('F6');
  for (let i = 0; i < 20; i++) {
    await p.waitForTimeout(1500);
    const n = (await notifications(p)).filter(t => /EULA/.test(t));
    if (n.length) { console.log('F6 결과:', n.slice(-1)); break; }
  }
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
