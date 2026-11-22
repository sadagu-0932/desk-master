const { connect, S, palette, notifications } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  console.log('창 제목:', await p.title());
  await palette(p, '사이드카 상태 보기');
  for (let i = 0; i < 60; i++) {
    await p.waitForTimeout(3000);
    const n = (await notifications(p)).filter(t => /사이드카/.test(t));
    if (n.length) { console.log('사이드카:', n.slice(-1)); break; }
  }
  console.log('홈:', await p.$eval('.studio-home h1', e => e.textContent).catch(() => '없음'));
  await p.screenshot({ path: S + '/shots/12-packaged.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
