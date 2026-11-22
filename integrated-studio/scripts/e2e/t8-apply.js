const { connect, S, palette, notifications } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  const no = p.locator('.dialogOverlay button:has-text("No")');
  if (await no.count()) { await no.first().click(); await p.waitForTimeout(800); console.log('대화상자: No'); }
  await palette(p, 'Revert File'); await p.waitForTimeout(1000);
  console.log('저장 안 됨 탭:', await p.$$eval('.lm-TabBar-tab.theia-mod-dirty', e => e.length));
  await palette(p, 'Claude 변경 적용 후 /reload');
  await p.waitForTimeout(2500);
  console.log('알림:', (await notifications(p)).slice(-2));
  await palette(p, '게임 로그 보기'); await p.waitForTimeout(1000);
  const log = await p.$$eval('.studio-log .studio-log-line', e => e.map(x => x.textContent).slice(-4));
  console.log('게임 로그 탭:', log);
  await p.screenshot({ path: S + '/shots/11-apply-reload.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
