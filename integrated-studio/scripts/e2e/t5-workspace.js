const { connect, S, palette, notifications } = require('./lib.js');
(async () => {
  let { b, p } = await connect();
  await p.click('.studio-instances .studio-row:has-text("캠핑장 맵") .codicon-folder-opened');
  await b.close().catch(() => {});
  await new Promise(r => setTimeout(r, 8000));
  ({ b, p } = await connect());
  await p.waitForTimeout(5000);
  console.log('창 제목:', await p.title());
  const tree = await p.$$eval('#files .theia-TreeNodeSegmentGrow', e => e.map(x => x.textContent.trim()));
  console.log('파일 트리:', tree.join(', '));
  console.log('상태 표시줄:', (await p.$$eval('#theia-statusBar .element', e => e.map(x => x.textContent.trim()).filter(Boolean))).join(' | '));
  // 새 데이터팩
  await palette(p, '새 데이터팩 만들기');
  await p.keyboard.type('campsite'); await p.keyboard.press('Enter'); await p.waitForTimeout(800);
  await p.keyboard.press('Enter'); await p.waitForTimeout(3000);
  console.log('열린 탭:', await p.$$eval('#theia-main-content-panel .lm-TabBar-tabLabel', e => e.map(x => x.textContent)));
  console.log('알림:', (await notifications(p)).slice(-1));
  // 예비 자동완성 준비(데이터 생성기)
  await palette(p, '게임 없이 쓸 자동완성 준비');
  for (let i = 0; i < 60; i++) {
    await p.waitForTimeout(5000);
    const n = (await notifications(p)).join(' ');
    if (/명령어 목록을 준비했습니다|데이터 생성기 실패|오류/.test(n)) { console.log('자동완성 준비:', n.match(/[^']*(명령어 목록을 준비했습니다|데이터 생성기 실패)[^.]*/)?.[0]); break; }
  }
  // load.mcfunction 에서 자동완성
  await p.click('.monaco-editor .view-lines'); await p.keyboard.press('Control+End');
  await p.keyboard.press('Enter'); await p.keyboard.type('execute as @a at @s if '); await p.waitForTimeout(400);
  await p.keyboard.press('Control+Space'); await p.waitForTimeout(1500);
  console.log('자동완성(execute … if):', await p.$$eval('.suggest-widget .monaco-list-row', e => e.slice(0, 8).map(x => x.getAttribute('aria-label') || x.textContent)));
  await p.screenshot({ path: S + '/shots/06-datapack-completion.png' });
  await p.keyboard.press('Escape');
  await p.keyboard.press('Control+S'); await p.waitForTimeout(800);
  // /reload 버튼 (게임 꺼짐)
  await p.click('.studio-run-bar .studio-bar-btn'); await p.waitForTimeout(2000);
  console.log('/reload 결과:', (await notifications(p)).slice(-1));
  // Claude 패널과 작업 종류
  await palette(p, 'Claude 패널 열기'); await p.waitForTimeout(3000);
  console.log('Claude 툴바:', await p.$$eval('.lm-TabBar-toolbar .item', e => e.map(x => x.textContent.trim()).filter(Boolean)));
  await p.screenshot({ path: S + '/shots/07-claude-panel.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
