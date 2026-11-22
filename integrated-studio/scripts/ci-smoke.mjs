// 빌드한 앱이 실제로 켜지는지 확인한다(CI용).
// 사용: node scripts/ci-smoke.mjs <앱 실행 파일>
// 앱을 디버그 포트와 함께 띄우고, 창 제목에 "통합 작업실"이 나오면 통과.
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const exe = process.argv[2];
if (!exe || !fs.existsSync(exe)) {
    console.error(`실행 파일이 없습니다: ${exe}`);
    process.exit(1);
}
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-smoke-'));
const ws = path.join(tmp, 'ws');
fs.mkdirSync(ws);
const port = 9333;
const proc = spawn(exe, [ws, `--remote-debugging-port=${port}`], {
    env: { ...process.env, INTEGRATED_STUDIO_DATA: path.join(tmp, 'data') },
    stdio: 'inherit',
});

function stop() {
    try {
        if (process.platform === 'win32') {
            execFileSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
        } else {
            proc.kill();
        }
    } catch { /* 이미 종료 */ }
}

let ok = false;
let lastTitles = [];
for (let i = 0; i < 90 && !ok; i++) {
    await new Promise(r => setTimeout(r, 2000));
    try {
        const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        lastTitles = pages.map(p => p.title);
        ok = lastTitles.some(t => t.includes('통합 작업실'));
    } catch { /* 아직 안 뜸 */ }
}
stop();
if (ok) {
    console.log(`앱 실행 확인: ${lastTitles.join(' | ')}`);
} else {
    console.error(`앱 창을 확인하지 못했습니다. 마지막 제목: ${JSON.stringify(lastTitles)}`);
    process.exit(1);
}
