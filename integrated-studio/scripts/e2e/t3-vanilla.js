const { connect, S, notifications } = require('./lib.js');
const logText = p => p.$$eval('.studio-log .studio-log-line', e => e.map(x => x.textContent));
(async () => {
  const { b, p } = await connect();
  await p.click('.studio-instances .studio-row:has-text("바닐라 테스트")');
  await p.waitForTimeout(500);
  await p.click('.studio-home', { position: { x: 5, y: 5 } }).catch(() => {});
  const t0 = Date.now();
  await p.keyboard.press('F5');
  console.log('F5 누름');
  let shot = false;
  for (let i = 0; i < 240; i++) {        // 최대 40분
    await p.waitForTimeout(10000);
    const lines = await logText(p);
    const running = await p.$eval('.studio-run-bar .studio-dot', e => e.classList.contains('on')).catch(() => false);
    const prog = await p.$$eval('.theia-notification-list-item-content, .theia-progress-message', e => e.map(x => x.textContent.trim()).slice(-1)).catch(() => []);
    if (i % 3 === 0) console.log(`${Math.round((Date.now() - t0) / 1000)}s 실행중=${running} 로그=${lines.length} 진행=${prog}`);
    if (lines.some(l => /Render thread\/INFO|Setting user/.test(l)) && running) {
      await p.waitForTimeout(40000);
      console.log('게임 로그 일부:\n' + (await logText(p)).filter(l => /INFO|WARN|ERROR/.test(l)).slice(0, 12).join('\n'));
      await p.screenshot({ path: S + '/shots/03-vanilla-running.png' }); shot = true;
      break;
    }
    if (!running && lines.some(l => /비정상|Exception|exit/i.test(l)) && i > 3) { console.log('로그 끝:\n' + lines.slice(-25).join('\n')); break; }
  }
  if (!shot) { await p.screenshot({ path: S + '/shots/03-vanilla-fail.png' }); console.log('알림', await notifications(p)); }
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
