// 새 인스턴스 창: 열기 → 기본 선택 확인 → 스냅샷 필터·검색 → 바닐라/Fabric 전환 → 만들기
const { connect, S, palette, notifications } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  await p.setViewportSize({ width: 1400, height: 860 }).catch(() => {});
  await p.click('.studio-home button:has-text("+ 새 인스턴스")');
  await p.waitForSelector('.studio-newinst .ni-row.selected', { timeout: 60000 });
  await p.waitForSelector('.ni-loader-versions .ni-row.selected', { timeout: 60000 });
  const state = () => p.evaluate(() => ({
    name: document.querySelector('.ni-field input').value,
    version: document.querySelector('.ni-versions .ni-row.selected span')?.textContent,
    count: document.querySelector('.ni-count')?.textContent,
    loaderVer: document.querySelector('.ni-loader-versions .ni-row.selected span')?.textContent,
    error: document.querySelector('.dialogControl .error')?.textContent || '',
  }));
  console.log('처음:', await state());
  await p.screenshot({ path: S + '/shots/13-newinst.png' });
  // 스냅샷 보이기 + 검색
  await p.click('.ni-filters label:has-text("스냅샷") input');
  await p.fill('.ni-table-tools input', '26.4');
  await p.waitForTimeout(300);
  console.log('스냅샷+검색:', await state(), await p.$$eval('.ni-versions .ni-row:not(.ni-head) span:first-child', e => e.slice(0, 3).map(x => x.textContent)));
  // 아주 옛 버전 → Fabric 미지원 안내
  await p.click('.ni-filters label:has-text("알파") input');
  await p.fill('.ni-table-tools input', 'a1.2.6');
  await p.waitForTimeout(300);
  await p.click('.ni-versions .ni-row:not(.ni-head)');
  await p.waitForSelector('.ni-loader-versions .ni-warn, .ni-loader-versions .ni-error', { timeout: 30000 });
  console.log('알파 + Fabric:', (await p.textContent('.ni-loader-versions')).trim(), '| 오류 문구:', await p.textContent('.dialogControl .error'));
  // 다시 26.3 + Fabric, 이름·그룹·아이콘
  await p.fill('.ni-table-tools input', '26.3');
  await p.click('.ni-filters label:has-text("스냅샷") input');
  await p.click('.ni-filters label:has-text("알파") input');
  await p.waitForTimeout(300);
  await p.click('.ni-versions .ni-row:not(.ni-head) >> text="26.3"');
  await p.waitForSelector('.ni-loader-versions .ni-row.selected', { timeout: 30000 });
  await p.fill('.ni-field input >> nth=0', '창 테스트 맵');
  await p.fill('.ni-field input >> nth=1', '맵 제작');
  await p.click('.ni-swatch >> nth=2');
  await p.click('.studio-newinst-installnow input'); // 바로 설치 끄기
  console.log('만들기 전:', await state());
  await p.screenshot({ path: S + '/shots/14-newinst-filled.png' });
  await p.click('.dialogControl .theia-button.main');
  await p.waitForTimeout(2500);
  console.log('알림:', (await notifications(p)).slice(-1));
  const card = await p.$$eval('.studio-inst-card', e => e.map(x => x.innerText.replace(/\s+/g, ' ')).filter(t => t.includes('창 테스트 맵')));
  console.log('홈 카드:', card);
  await p.screenshot({ path: S + '/shots/15-after-create.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
