// M10 서버 열기 + 인스턴스 불러오기 e2e
// 준비: 가짜 런처 폴더(APPDATA·USERPROFILE 을 바꿔서 띄움 — Prism Fabric 인스턴스·CurseForge NeoForge 인스턴스)와
//       127.0.0.1:25599 에 가짜 마인크래프트 서버(상태 조회 응답). 이 PC 에는 공유기가 없어 UPnP 는 실패, playit 은 준비 전.
// 흐름: 서버 패널 → 불러오기(감지 목록 → 복사 미리보기 → 불러오기 → 완료) → [서버로 열기] 대화 상자
//       → 외부 서버(포트 25599) 상태 확인 → 열기 → 주소 실패 이유(UPnP·playit) 표시
const { connect, S, palette, notifications } = require('./lib.js');
const fs = require('fs');

(async () => {
  const { b, p } = await connect();
  fs.mkdirSync(S + '/shots', { recursive: true });
  await palette(p, '서버 패널 열기');
  await p.waitForSelector('.sh-root', { timeout: 20000 });
  console.log('패널:', (await p.textContent('.sh-root')).replace(/\s+/g, ' ').slice(0, 120));

  // ---------- 불러오기 ----------
  await p.click('.sh-actions button:has-text("인스턴스 불러오기")');
  await p.waitForSelector('.imp-table tbody tr', { timeout: 30000 });
  const rows = await p.$$eval('.imp-table tbody tr', r => r.map(x => x.innerText.replace(/\s+/g, ' ').trim()));
  console.log('감지:', rows);
  await p.screenshot({ path: S + '/shots/40-import-list.png' });
  await p.click('.imp-table tbody tr:has-text("Fabric 생존")');
  await p.click('.imp-root button:has-text("다음")');
  await p.waitForSelector('.imp-root .sh-kinds');
  console.log('미리보기:', (await p.textContent('.imp-root')).replace(/\s+/g, ' ').slice(0, 260));
  await p.screenshot({ path: S + '/shots/41-import-preview.png' });
  await p.click('.imp-root button:has-text("불러오기")');
  await p.waitForSelector('.imp-root button:has-text("서버로 열기")', { timeout: 240000 });
  console.log('완료:', (await p.textContent('.imp-root')).replace(/\s+/g, ' ').slice(0, 200));
  await p.screenshot({ path: S + '/shots/42-import-done.png' });

  // ---------- 서버로 열기 → 대화 상자(외부 서버로 바꿔 상태 확인) ----------
  await p.click('.imp-root button:has-text("서버로 열기")');
  await p.waitForSelector('.sh-dialog .sh-kinds');
  console.log('대화 상자 인스턴스:', await p.$eval('.sh-dialog select', s => s.options[s.selectedIndex].textContent));
  await p.screenshot({ path: S + '/shots/43-open-dialog.png' });
  await p.click('.sh-kind:has-text("외부 서버 연결")');
  await p.fill('.sh-dialog .sh-row input', '25599');
  await p.click('.sh-dialog button:has-text("상태 확인")');
  await p.waitForSelector('.sh-dialog .sh-note', { timeout: 10000 });
  console.log('상태 확인:', (await p.textContent('.sh-dialog .sh-note')).trim());
  await p.fill('.sh-dialog .sh-field input:not(.sh-mono)', 'e2e 외부 서버');
  await p.click('.dialogControl .theia-button.main');
  const card = p.locator('.sh-card', { hasText: 'e2e 외부 서버' });
  await card.waitFor({ timeout: 20000 });
  for (let i = 0; i < 60; i++) {
    const st = await card.getAttribute('class');
    if (/addr-(open|failed)/.test(st)) { break; }
    await p.waitForTimeout(500);
  }
  console.log('외부 서버 카드:', (await card.innerText()).replace(/\s+/g, ' ').slice(0, 400));
  await p.screenshot({ path: S + '/shots/44-external-card.png' });
  console.log('알림:', (await notifications(p)).slice(-3));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
