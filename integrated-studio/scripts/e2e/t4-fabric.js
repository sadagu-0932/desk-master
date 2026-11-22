const { connect, S, notifications } = require('./lib.js');
const logText = p => p.$$eval('.studio-log .studio-log-line', e => e.map(x => x.textContent));
(async () => {
  const { b, p } = await connect();
  const row = '.studio-instances .studio-row:has-text("캠핑장 맵")';
  await p.click(row); await p.waitForTimeout(500);
  await p.click(row + ' .codicon-play');
  console.log('▶ 클릭(Fabric)');
  const t0 = Date.now(); let ok = false;
  for (let i = 0; i < 240; i++) {
    await p.waitForTimeout(10000);
    const lines = await logText(p);
    const running = await p.$eval('.studio-run-bar .studio-dot', e => e.classList.contains('on')).catch(() => false);
    if (i % 3 === 0) console.log(`${Math.round((Date.now() - t0) / 1000)}s 실행중=${running} 로그=${lines.length}`);
    if (running && lines.some(l => /Loading Minecraft .* with Fabric Loader/.test(l)) && lines.some(l => /Render thread\/INFO|Setting user/.test(l))) {
      await p.waitForTimeout(30000);
      const all = await logText(p);
      console.log('Fabric 로그:\n' + all.filter(l => /Fabric Loader|CommandCrafter|Loading \d+ mods|Setting user|services|52854/i.test(l)).slice(0, 12).join('\n'));
      await p.screenshot({ path: S + '/shots/04-fabric-running.png' });
      // 상단 막대의 중지 버튼
      await p.click('.studio-run-bar .codicon-debug-stop');
      for (let j = 0; j < 30; j++) {
        await p.waitForTimeout(1000);
        const r = await p.$eval('.studio-run-bar .studio-dot', e => e.classList.contains('on'));
        if (!r) { console.log(`상단 ■ 로 중지됨 (${j + 1}s)`); ok = true; break; }
      }
      break;
    }
    if (!running && i > 3 && lines.some(l => /비정상|exit code|Exception/i.test(l))) { console.log('로그 끝:\n' + lines.slice(-25).join('\n')); break; }
  }
  if (!ok) { await p.screenshot({ path: S + '/shots/04-fabric-fail.png' }); console.log('알림', await notifications(p)); }
  console.log(ok ? 'FABRIC_OK' : 'FABRIC_FAIL');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
