const { chromium } = require('playwright');
exports.S = process.env.E2E_DIR || require('path').join(__dirname, 'out');
exports.connect = async () => {
  for (let i = 0; i < 90; i++) {
    try {
      const b = await chromium.connectOverCDP('http://127.0.0.1:9333');
      const p = b.contexts().flatMap(c => c.pages()).find(p => !p.url().startsWith('devtools'));
      if (p && await p.$('#theia-app-shell').catch(() => null)) { await p.waitForTimeout(1500); return { b, p }; }
      await b.close().catch(() => {});
    } catch {}
    await new Promise(r => setTimeout(r, 1000));
  }
  throw new Error('앱에 연결 못 함');
};
exports.palette = async (p, text) => {
  await p.keyboard.press('Escape');
  await p.keyboard.press('Control+Shift+P'); await p.waitForTimeout(800);
  await p.keyboard.type(text); await p.waitForTimeout(800);
  await p.keyboard.press('Enter'); await p.waitForTimeout(1000);
};
exports.notifications = p => p.$$eval('.theia-notification-message, .theia-notification-list-item-content', e => e.map(x => x.textContent.trim()));
