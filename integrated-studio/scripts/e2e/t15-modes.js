// 런처 모드 ↔ 작업실 모드(2026-11-27): 켤 때 런처(확장 실행기 없음) → [작업실 열기] → 편집기·확장 실행기 → [런처로] → 다시 켜도 런처
// 사용: 앱을 인자 없이 켜 둔 상태(start-app.sh 를 인자 없이)에서 node t15-modes.js
const { execSync } = require('child_process');
const { connect, S } = require('./lib.js');

function procs() {
    const out = execSync('ps -eo pid,rss,args --no-headers', { encoding: 'utf8' });
    const rows = out.split('\n').filter(l => /electron|python.*main\.py/.test(l) && !/xvfb|ps -eo/.test(l));
    const rss = rows.reduce((a, l) => a + Number(l.trim().split(/\s+/)[1] || 0), 0);
    return { pluginHost: rows.filter(l => /plugin-host/.test(l)).length, mb: Math.round(rss / 1024), n: rows.length };
}

async function state(p) {
    return {
        hash: await p.evaluate(() => decodeURIComponent(location.hash)),
        bar: await p.$$eval('.studio-run-bar .studio-bar-btn', e => e.map(x => x.textContent.trim())),
        home: !!(await p.$('.lm-TabBar-tab[id*="studio-home"], #studio-home')),
        explorer: await p.$eval('#explorer-view-container', e => e.offsetParent !== null).catch(() => false),
        editorTabs: await p.$$eval('#theia-main-content-panel .lm-TabBar-tabLabel', e => e.map(x => x.textContent)),
    };
}

(async () => {
    let { b, p } = await connect();
    await p.waitForTimeout(8000);
    const a = await state(p);
    console.log('1) 켤 때:', JSON.stringify(a), '프로세스:', JSON.stringify(procs()));
    if (a.hash.length > 1 && !a.hash.includes('defaultWindow')) throw new Error('켤 때 작업실이 열렸습니다(런처여야 함)');
    console.log('   확장 활성화 파일:', require('fs').existsSync(require('os').tmpdir() + '/zz-probe-activated'));
    if (!a.bar.some(t => t.includes('작업실 열기'))) throw new Error('작업실 열기 버튼이 없습니다');
    await p.screenshot({ path: S + '/shots/15-launcher.png' });

    await p.click('.studio-run-bar .studio-bar-btn:has-text("작업실 열기")');
    await b.close().catch(() => {});
    await new Promise(r => setTimeout(r, 8000));
    ({ b, p } = await connect());
    await p.waitForTimeout(12000);
    const w = await state(p);
    console.log('2) 작업실:', JSON.stringify(w), '프로세스:', JSON.stringify(procs()));
    if (w.hash.length <= 1) throw new Error('작업실이 열리지 않았습니다');
    console.log('   확장 활성화 파일:', require('fs').existsSync(require('os').tmpdir() + '/zz-probe-activated'));
    if (!w.bar.some(t => t.includes('런처로'))) throw new Error('런처로 버튼이 없습니다');
    await p.screenshot({ path: S + '/shots/15-workspace.png' });

    await p.click('.studio-run-bar .studio-bar-btn:has-text("런처로")');
    await b.close().catch(() => {});
    await new Promise(r => setTimeout(r, 8000));
    ({ b, p } = await connect());
    await p.waitForTimeout(10000);
    const l = await state(p);
    console.log('3) 런처로 돌아옴:', JSON.stringify(l), '프로세스:', JSON.stringify(procs()));
    if (l.hash.length > 1 && !l.hash.includes('defaultWindow')) throw new Error('런처로 돌아오지 않았습니다');
    await b.close();
})().catch(e => { console.error(e); process.exit(1); });
