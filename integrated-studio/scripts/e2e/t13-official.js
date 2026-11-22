// 공식 런처로 플레이: 카드 버튼 → 확인 창(아니오/예) → 등록 → 로그 따라 읽기 → 런처 열기 → 등록 해제
// Linux에서는 sidecar 를 가짜 공식 런처로 띄운다(INTEGRATED_STUDIO_PYTHON=<scratchpad>/fakeol/py.sh, sitecustomize 로 흉내).
// 인자: 설치된 인스턴스 이름, 그 인스턴스 폴더, 가짜 .minecraft 폴더
const fs = require('fs');
const path = require('path');
const { connect, S, notifications, palette } = require('./lib.js');
const [name, instDir, mcDir] = process.argv.slice(2);
const profiles = () => JSON.parse(fs.readFileSync(path.join(mcDir, 'launcher_profiles.json'), 'utf8')).profiles;

(async () => {
  const { b, p } = await connect();
  fs.mkdirSync(S + '/shots', { recursive: true });
  const card = p.locator('.studio-inst-card', { hasText: name });
  await card.locator('button[aria-label$="공식 런처로 플레이"]').click();

  // 1) 아니오
  await p.waitForSelector('.dialogOverlay .dialogTitle:has-text("공식 런처")', { timeout: 30000 });
  console.log('확인 창:', (await p.textContent('.dialogOverlay .dialogTitle')).trim(), '|', (await p.textContent('.dialogOverlay .dialogContent')).trim());
  await p.screenshot({ path: S + '/shots/20-official-confirm.png' });
  await p.click('.dialogOverlay .theia-button.secondary');
  await p.waitForTimeout(1500);
  console.log('아니오 뒤 항목 수:', Object.keys(profiles()).length, '| 알림:', (await notifications(p)).slice(-1));

  // 2) 예
  await card.locator('button[aria-label$="공식 런처로 플레이"]').click();
  await p.waitForSelector('.dialogOverlay .dialogTitle:has-text("공식 런처")', { timeout: 30000 });
  await p.click('.dialogOverlay .theia-button.main');
  for (let i = 0; i < 20 && !fs.existsSync(path.join(mcDir, 'opened.txt')); i++) await p.waitForTimeout(500);
  const ours = Object.entries(profiles()).filter(([k]) => k.startsWith('integrated-studio-'));
  console.log('등록:', JSON.stringify(ours.map(([k, v]) => [k, v.name, v.lastVersionId, v.gameDir])), '| 내 프로필 유지:', 'user-own' in profiles());
  console.log('런처 열림:', fs.existsSync(path.join(mcDir, 'opened.txt')));
  await p.waitForTimeout(1000);
  console.log('알림:', (await notifications(p)).slice(-2));

  // 3) 로그 따라 읽기 → 게임 로그 탭
  fs.mkdirSync(path.join(instDir, 'logs'), { recursive: true });
  fs.appendFileSync(path.join(instDir, 'logs', 'latest.log'), '[12:00:00] [Render thread/WARN]: 공식 런처 게임에서 온 줄\n');
  let seen = false;
  for (let i = 0; i < 20 && !seen; i++) {
    await p.waitForTimeout(500);
    seen = await p.$$eval('.studio-log-line.source-official', e => e.some(x => x.textContent.includes('공식 런처 게임에서 온 줄'))).catch(() => false);
  }
  console.log('게임 로그 탭에 표시:', seen, '| 등록 결과 줄:', await p.$$eval('.studio-log-line.source-official', e => e.map(x => x.textContent).slice(0, 2)));
  await p.screenshot({ path: S + '/shots/21-official-log.png' });

  // 4) 사이드바 아이콘 존재 + 등록 해제(명령 팔레트)
  console.log('사이드바 아이콘:', await p.$$eval('.codicon-globe[aria-label$="공식 런처로 플레이"]', e => e.length));
  await palette(p, '공식 런처에서 등록 해제');
  const picked = await p.$('.quick-input-widget .monaco-list-row');
  if (picked && await p.isVisible('.quick-input-widget')) { await p.keyboard.type(name); await p.waitForTimeout(500); await p.keyboard.press('Enter'); }
  await p.waitForSelector('.dialogOverlay .dialogTitle:has-text("공식 런처")', { timeout: 30000 });
  await p.click('.dialogOverlay .theia-button.main');
  await p.waitForTimeout(1500);
  console.log('해제 뒤 우리 항목:', Object.keys(profiles()).filter(k => k.startsWith('integrated-studio-')).length, '| 내 프로필 유지:', 'user-own' in profiles(),
    '| 토큰 파일 그대로:', fs.readFileSync(path.join(mcDir, 'launcher_accounts.json'), 'utf8').trim());
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
