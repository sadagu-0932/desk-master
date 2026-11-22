const { connect, S } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  console.log('툴바 항목:', await p.evaluate(() => [...document.querySelectorAll('[id*="studio.claude"], .lm-TabBar-toolbar [title]')].map(e => e.id + ' ' + (e.getAttribute('title') || '') + ' ' + e.textContent.trim()).filter(t => /studio|작업|reload/.test(t))));
  await p.evaluate(() => document.querySelectorAll('.theia-notification-close, .theia-notification-list-item .codicon-close').forEach(e => e.click()));
  await p.click('#chat-input-widget .theia-ChatInput-Editor', { force: true }); await p.waitForTimeout(500);
  await p.keyboard.insertText('모닥불 5칸 안에 5초 있으면 보상 주는 기능 만들어줘. datapacks/campsite 데이터팩에 넣어줘.');
  await p.waitForTimeout(500);
  console.log('입력됨:', await p.evaluate(() => document.activeElement?.closest('[id]')?.id + ' / ' + (document.querySelector('#chat-input-widget .view-lines')?.innerText || '').slice(0, 80)));
  await p.keyboard.press('Enter');
  const t0 = Date.now();
  let last = '';
  for (let i = 0; i < 40; i++) {
    await p.waitForTimeout(10000);
    const txt = await p.$eval('#chat-view-widget, .chat-view-widget, [id="chat-view-widget"]', e => e.innerText).catch(() => '');
    if (txt !== last) { last = txt; }
    if (/error|오류|not found|Unauthorized|로그인|login/i.test(txt) && i > 1) break;
    if (/변경|Changes|reward/i.test(txt) && i > 3) break;
  }
  console.log(`${Math.round((Date.now() - t0) / 1000)}s Claude 패널 내용(끝):\n` + last.slice(-1500));
  await p.screenshot({ path: S + '/shots/08-claude-request.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
