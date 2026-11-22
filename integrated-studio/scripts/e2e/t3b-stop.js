const { connect, S } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  await p.focus('.studio-log .studio-log-body'); await p.keyboard.press('Shift+F5');
  for (let j = 0; j < 30; j++) {
    await p.waitForTimeout(1000);
    const r = await p.$eval('.studio-run-bar .studio-dot', e => e.classList.contains('on'));
    if (!r) { console.log(`Shift+F5 로 중지됨 (${j + 1}s)`); break; }
    if (j === 29) console.log('중지 안 됨');
  }
  const lines = await p.$$eval('.studio-log .studio-log-line', e => e.map(x => x.textContent));
  console.log('마지막 로그:', lines.slice(-3));
  await p.screenshot({ path: S + '/shots/05-stopped.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
