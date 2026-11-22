// M0 완료 조건 자동 확인: node scripts/smoke-m0.js <작업 폴더> <스크린샷 폴더>
// Linux 컨테이너에서는 xvfb-run으로 감싸서 실행한다. playwright가 필요하다.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const APP = '/home/user/desk-master/integrated-studio/applications/electron';
const WS = process.argv[2], OUT = process.argv[3];
(async () => {
  const proc = spawn(path.join(APP, '../../node_modules/electron/dist/electron'), [APP, WS, '--remote-debugging-port=9333', '--no-sandbox'], { cwd: APP });
  proc.stderr.on('data', d => { const t = d.toString(); if (/error/i.test(t) && !/socket_posix|dbus/.test(t)) process.stderr.write('[app] ' + t); });
  let browser; for (let i = 0; i < 60; i++) { try { browser = await chromium.connectOverCDP('http://127.0.0.1:9333'); break; } catch { await new Promise(r => setTimeout(r, 1000)); } }
  console.log('CDP 연결:', !!browser);
  let win; for (let i = 0; i < 90; i++) { const pages = browser.contexts().flatMap(c => c.pages()); win = pages.find(p => !p.url().startsWith('devtools')); if (win && await win.$('#theia-app-shell').catch(()=>null)) break; await new Promise(r => setTimeout(r, 1000)); }
  await win.waitForTimeout(4000);
  const app = { close: async () => { await browser.close().catch(()=>{}); proc.kill(); } };
  console.log('창 제목:', await win.title());
  // 파일 트리
  await win.waitForSelector('.theia-FileTree, #files', { timeout: 60000 }).catch(()=>{});
  await win.keyboard.press('Control+Shift+E'); await win.waitForTimeout(1500);
  const nodes = await win.$$eval('.theia-TreeNodeSegment.theia-TreeNodeSegmentGrow', e => e.map(x => x.textContent.trim()));
  console.log('파일 트리:', nodes.join(', '));
  // 파일 열기 → 에디터
  await win.getByText('pack.mcmeta', { exact: true }).first().dblclick(); await win.waitForTimeout(2500);
  const editorText = await win.$eval('.monaco-editor .view-lines', e => e.textContent).catch(() => '');
  console.log('에디터 내용:', editorText);
  await win.click('.monaco-editor .view-lines'); await win.keyboard.press('Control+End'); await win.keyboard.type(' ');
  const dirty = await win.$$eval('.p-TabBar-tab.theia-mod-dirty, .lm-TabBar-tab.theia-mod-dirty', e => e.length);
  console.log('편집 후 저장 안 됨 표시 탭 수:', dirty);
  await win.screenshot({ path: OUT + '/m0-editor.png' });
  // 명령 팔레트
  await win.keyboard.press('Control+Shift+P'); await win.waitForTimeout(1500);
  await win.keyboard.type('Toggle Bottom Panel'); await win.waitForTimeout(1000);
  const items = await win.$$eval('.quick-input-list .monaco-list-row', e => e.slice(0,5).map(x => x.textContent.trim()));
  console.log('명령 팔레트 결과:', items);
  await win.screenshot({ path: OUT + '/m0-palette.png' });
  await win.keyboard.press('Enter'); await win.waitForTimeout(1500);
  console.log('하단 패널 보임:', await win.$eval('#theia-bottom-content-panel', e => !e.classList.contains('lm-mod-hidden') && !e.classList.contains('p-mod-hidden') && e.offsetHeight > 0).catch(()=>false));
  await app.close();
})().catch(e => { console.error('실패:', e); process.exit(1); });
