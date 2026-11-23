// M10 P2P: 패널 → 서버 열기(방식 B 싱글 LAN 공개) → 로그로 LAN 공개 감지 → 코드 → 외부 참가자 왕복
//          → 참가(외부 호스트 코드) → 연결 정보 → 서버 목록 추가(servers.dat)
// 준비: <scratchpad>/p2p/helper.mjs 가 로컬 DHT 테스트넷·에코 서버·외부 호스트를 띄우고 env.json 을 씀.
// 앱은 INTEGRATED_STUDIO_DHT_BOOTSTRAP=<env.bootstrap> 로 띄운다.
// 인자: helper 출력 폴더, LAN 으로 열 인스턴스 이름, 그 인스턴스 폴더
const fs = require('fs');
const path = require('path');
const { connect, S, palette } = require('./lib.js');
const [OUT, instName, instDir] = process.argv.slice(2);
const env = JSON.parse(fs.readFileSync(path.join(OUT, 'env.json'), 'utf8'));
const waitFor = async (p, fn, n = 60) => { for (let i = 0; i < n; i++) { if (await fn()) return true; await p.waitForTimeout(500); } return false; };

(async () => {
  const { b, p } = await connect();
  fs.mkdirSync(S + '/shots', { recursive: true });
  await palette(p, 'P2P 서버 패널 열기');
  await p.waitForSelector('.p2p-root', { timeout: 20000 });

  // ---------- 호스트: 방식 B ----------
  await p.click('.p2p-actions button:has-text("서버 열기")');
  await p.waitForSelector('.p2p-dialog select');
  const optVal = await p.$eval('.p2p-dialog select', (s, name) => [...s.options].find(o => o.textContent.startsWith(name))?.value, instName);
  await p.selectOption('.p2p-dialog select', optVal);
  await p.click('.p2p-kind:has-text("싱글 LAN 공개")');
  await p.fill('.p2p-field input', 'e2e LAN 서버');
  await p.screenshot({ path: S + '/shots/30-p2p-host-dialog.png' });
  await p.click('.dialogControl .theia-button.main');
  const card = p.locator('.p2p-card', { hasText: 'e2e LAN 서버' });
  await card.waitFor({ timeout: 20000 });
  console.log('호스트 상태:', (await card.locator('.p2p-chip').allTextContents()).join(' / '));
  // 게임에서 LAN 공개를 누른 것처럼 로그에 쓴다(26.3 실제 문구)
  fs.mkdirSync(path.join(instDir, 'logs'), { recursive: true });
  fs.appendFileSync(path.join(instDir, 'logs', 'latest.log'), `[14:03:01] [Server thread/INFO]: Published LAN server on port ${env.echo}\n`);
  console.log('LAN 감지 → 열림:', await waitFor(p, async () => (await card.locator('.p2p-chip').allTextContents()).includes('열림')));
  const code = (await card.locator('.p2p-code').first().textContent()).trim();
  console.log('코드:', code.slice(0, 12) + '…', '| 안내:', (await card.locator('.p2p-note').allTextContents()).join(' / ').slice(0, 80));
  fs.writeFileSync(path.join(OUT, 'join-code.txt'), code);
  const res = path.join(OUT, 'join-result.json');
  await waitFor(p, () => fs.existsSync(res));
  console.log('외부 참가자 결과:', fs.readFileSync(res, 'utf8'));
  fs.unlinkSync(res);
  await p.screenshot({ path: S + '/shots/31-p2p-host-open.png' });

  // ---------- 참가: 외부 호스트 코드 ----------
  await p.click('.p2p-actions button:has-text("참가")');
  await p.waitForSelector('.p2p-dialog input');
  await p.fill('.p2p-dialog input', 'IS2-' + env.extCode.slice(4));
  await p.waitForTimeout(300);
  console.log('다른 버전 코드 안내:', (await p.textContent('.dialogControl .error').catch(() => '')).trim());
  await p.fill('.p2p-dialog input', ' ' + env.extCode.toLowerCase() + '\n');
  await p.click('.dialogControl .theia-button.main');
  await p.waitForSelector('.quick-input-widget .monaco-list-row', { timeout: 40000 });
  console.log('인스턴스 선택지:', await p.$$eval('.quick-input-widget .monaco-list-row', e => e.map(x => x.textContent.trim().slice(0, 40))));
  await p.screenshot({ path: S + '/shots/32-p2p-join-pick.png' });
  await p.keyboard.type(instName);
  await p.waitForTimeout(400);
  await p.keyboard.press('Enter');
  const jcard = p.locator('.p2p-card', { hasText: '외부 친구 서버' });
  await jcard.waitFor({ timeout: 20000 });
  await p.waitForTimeout(2500);
  console.log('참가 카드:', (await jcard.innerText()).replace(/\s+/g, ' ').slice(0, 220));
  const dat = path.join(instDir, 'servers.dat');
  console.log('servers.dat 에 추가:', fs.existsSync(dat) && fs.readFileSync(dat).includes(Buffer.from('[P2P] 외부 친구 서버')));
  await p.screenshot({ path: S + '/shots/33-p2p-panel.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
