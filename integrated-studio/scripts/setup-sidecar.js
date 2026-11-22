// 사이드카용 Python 가상환경(sidecar/.venv)을 만들고 패키지를 설치한다.
// 사용: npm run sidecar:setup
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'sidecar');
const win = process.platform === 'win32';
const venvPy = path.join(dir, '.venv', win ? 'Scripts/python.exe' : 'bin/python');
const run = (cmd, args) => execFileSync(cmd, args, { cwd: dir, stdio: 'inherit' });

if (!fs.existsSync(venvPy)) {
    console.log('가상환경 만드는 중: sidecar/.venv');
    run(win ? 'python' : 'python3', ['-m', 'venv', '.venv']);
}
run(venvPy, ['-m', 'pip', 'install', '-r', 'requirements.txt']);
console.log('사이드카 준비 완료');
