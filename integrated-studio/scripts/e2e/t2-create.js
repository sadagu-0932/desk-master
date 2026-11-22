const { connect, S, palette, notifications } = require('./lib.js');
async function create(p, name, loaderLabel) {
  await palette(p, '새 인스턴스 만들기');
  await p.keyboard.type(name); await p.keyboard.press('Enter');
  // 버전 목록(사이드카가 Mojang 목록을 받아옴)
  await p.waitForSelector('.quick-input-list .monaco-list-row', { timeout: 60000 });
  await p.keyboard.type('26.3'); await p.waitForTimeout(800);
  const rows = await p.$$eval('.quick-input-list .monaco-list-row', e => e.slice(0, 4).map(x => x.textContent.trim()));
  console.log('버전 후보:', rows);
  await p.keyboard.press('Enter'); await p.waitForTimeout(800);
  await p.keyboard.type(loaderLabel); await p.waitForTimeout(500); await p.keyboard.press('Enter');
  await p.waitForTimeout(2500);
  console.log('알림:', await notifications(p));
}
(async () => {
  const { b, p } = await connect();
  await create(p, '바닐라 테스트', '바닐라');
  await create(p, '캠핑장 맵 / Fabric?', 'Fabric');
  const rows = await p.$$eval('.studio-instances .studio-row', e => e.map(x => x.textContent.trim()));
  console.log('인스턴스 뷰:', rows);
  console.log('상단:', await p.$eval('.studio-run-bar-inner', e => e.textContent.trim()));
  await p.screenshot({ path: S + '/shots/02-created.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
