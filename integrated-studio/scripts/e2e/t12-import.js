// 가져오기 화면: Modrinth 검색 → 모드팩 버전 → 가져오기 / CurseForge 키 화면 / 모드 추가 창
// (가짜 Modrinth·CurseForge 서버: sidecar/tests/fake_platforms.py)
const { connect, S, notifications } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  await p.click('.studio-home button:has-text("+ 새 인스턴스")');
  await p.waitForSelector('.studio-newinst .ni-row.selected', { timeout: 60000 });

  // Modrinth
  await p.click('.ni-source:has-text("Modrinth")');
  await p.waitForSelector('.pb-item', { timeout: 30000 });
  console.log('Modrinth 결과:', await p.$$eval('.pb-item .pb-title', e => e.map(x => x.textContent)));
  await p.click('.pb-item');
  await p.waitForSelector('.ni-platform-versions .ni-row.selected', { timeout: 30000 });
  console.log('버전:', await p.$$eval('.ni-platform-versions .ni-row:not(.ni-head)', e => e.map(x => x.innerText.replace(/\s+/g, ' '))));
  console.log('이름 자동:', await p.inputValue('.ni-field input >> nth=0'), '| 버튼:', await p.textContent('.dialogControl .theia-button.main'));
  await p.screenshot({ path: S + '/shots/16-modrinth.png' });

  // CurseForge (키 없음 → 키 화면)
  await p.click('.ni-source:has-text("CurseForge")');
  await p.waitForSelector('.pb-keyform', { timeout: 15000 });
  console.log('CurseForge:', (await p.textContent('.pb-keyform h3')), '| 오류 줄:', await p.textContent('.dialogControl .error'));
  await p.screenshot({ path: S + '/shots/17-curseforge-key.png' });

  // 파일 가져오기 화면
  await p.click('.ni-source:has-text("파일 가져오기")');
  await p.waitForSelector('.ni-file-pick');
  await p.screenshot({ path: S + '/shots/18-file.png' });

  // Modrinth 로 돌아가 가져오기
  await p.click('.ni-source:has-text("Modrinth")');
  await p.waitForSelector('.pb-item');
  await p.click('.pb-item');
  await p.waitForSelector('.ni-platform-versions .ni-row.selected', { timeout: 30000 });
  await p.click('.dialogControl .theia-button.main');
  for (let i = 0; i < 30; i++) {
    await p.waitForTimeout(1000);
    const n = (await notifications(p)).filter(t => /가져오기 (완료|실패)/.test(t));
    if (n.length) { console.log('결과 알림:', n.slice(-1)); break; }
  }
  const cards = await p.$$eval('.studio-inst-card', e => e.map(x => x.innerText.replace(/\s+/g, ' ')).filter(t => t.includes('Test Pack')));
  console.log('홈 카드:', cards);

  // 모드 추가 창 (방금 만든 Fabric 인스턴스가 실행 대상)
  await p.keyboard.press('Escape');
  await p.keyboard.press('Control+Shift+P'); await p.waitForTimeout(600);
  await p.keyboard.type('모드 추가'); await p.waitForTimeout(600); await p.keyboard.press('Enter');
  await p.waitForSelector('.studio-addmods-dialog .pb-item', { timeout: 30000 });
  console.log('모드 추가 창 제목:', await p.textContent('.studio-addmods-dialog .dialogTitle'));
  await p.screenshot({ path: S + '/shots/19-addmods.png' });
  await p.click('.studio-addmods-dialog .dialogControl .theia-button');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
