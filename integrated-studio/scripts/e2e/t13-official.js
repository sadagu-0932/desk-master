// 실행 = 항상 공식 런처: 카드 '실행' → 확인 창(아니오/예) → 등록 → 로그 따라 읽기 → 런처 열기
// → 다시 '실행'은 묻지 않음 → 로그로 실행 중 표시 → 게임 종료 → 등록 해제
// Linux에서는 sidecar 를 가짜 공식 런처로 띄운다(INTEGRATED_STUDIO_PYTHON=<scratchpad>/fakeol/py.sh, sitecustomize 로 흉내).
// 인자: 설치된 인스턴스 이름, 그 인스턴스 폴더, 가짜 .minecraft 폴더
const fs = require('fs');
const path = require('path');
const { connect, S, palette } = require('./lib.js');
const [name, instDir, mcDir] = process.argv.slice(2);
const profiles = () => JSON.parse(fs.readFileSync(path.join(mcDir, 'launcher_profiles.json'), 'utf8')).profiles;
const opened = path.join(mcDir, 'opened.txt');
const logFile = path.join(instDir, 'logs', 'latest.log');
const waitFor = async (p, fn, n = 30) => { for (let i = 0; i < n; i++) { if (await fn()) return true; await p.waitForTimeout(500); } return false; };

(async () => {
  const { b, p } = await connect();
  fs.mkdirSync(S + '/shots', { recursive: true });
  fs.rmSync(opened, { force: true });
  const runBtn = () => p.locator('.studio-inst-card', { hasText: name }).locator('button[aria-label$="실행 (공식 런처)"]');
  console.log('상단 막대:', (await p.textContent('.studio-account')).trim(), '| 오프라인 문구 남음:', (await p.content()).includes('오프라인 · Dev'));

  // 1) 아니오
  await runBtn().click();
  await p.waitForSelector('.dialogOverlay .dialogTitle:has-text("공식 런처")', { timeout: 30000 });
  await p.screenshot({ path: S + '/shots/20-official-confirm.png' });
  await p.click('.dialogOverlay .theia-button.secondary');
  await p.waitForTimeout(1500);
  console.log('아니오 → 우리 항목:', Object.keys(profiles()).filter(k => k.startsWith('integrated-studio-')).length, '| 런처 열림:', fs.existsSync(opened));

  // 2) 예
  await runBtn().click();
  await p.waitForSelector('.dialogOverlay .dialogTitle:has-text("공식 런처")', { timeout: 30000 });
  await p.click('.dialogOverlay .theia-button.main');
  console.log('예 → 런처 열림:', await waitFor(p, () => fs.existsSync(opened)), '| 등록:', Object.keys(profiles()).filter(k => k.startsWith('integrated-studio-')));

  // 3) 다시 실행 → 묻지 않고 바로 런처
  fs.rmSync(opened, { force: true });
  await runBtn().click();
  const reopened = await waitFor(p, () => fs.existsSync(opened));
  console.log('두 번째 실행: 확인 창 없음:', !(await p.$('.dialogOverlay .dialogTitle:has-text("공식 런처")')), '| 런처 열림:', reopened);

  // 4) 로그로 실행 중 표시
  fs.mkdirSync(path.dirname(logFile), { recursive: true });
  fs.appendFileSync(logFile, '[12:00:00] [main/INFO]: Setting user: Player\n');
  const busy = await waitFor(p, async () => (await runBtn().textContent()).includes('실행 중'));
  console.log('실행 중 표시:', busy, '| 버튼 비활성:', await runBtn().isDisabled(), '| 로그 탭:', await p.$$eval('.studio-log-line.source-official', e => e.some(x => x.textContent.includes('Setting user'))));
  await p.screenshot({ path: S + '/shots/21-official-running.png' });
  fs.appendFileSync(logFile, '[12:30:00] [Render thread/INFO]: Stopping!\n');
  console.log('게임 종료 → 다시 실행 가능:', await waitFor(p, async () => !(await runBtn().isDisabled())));

  // 5) 등록 해제
  await palette(p, '공식 런처에서 등록 해제');
  if (await p.isVisible('.quick-input-widget')) { await p.keyboard.type(name); await p.waitForTimeout(500); await p.keyboard.press('Enter'); }
  await p.waitForSelector('.dialogOverlay .dialogTitle:has-text("공식 런처")', { timeout: 30000 });
  await p.click('.dialogOverlay .theia-button.main');
  await p.waitForTimeout(1500);
  console.log('해제 → 우리 항목:', Object.keys(profiles()).filter(k => k.startsWith('integrated-studio-')).length, '| 내 프로필 유지:', 'user-own' in profiles(),
    '| 토큰 파일 그대로:', fs.readFileSync(path.join(mcDir, 'launcher_accounts.json'), 'utf8').trim());
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
