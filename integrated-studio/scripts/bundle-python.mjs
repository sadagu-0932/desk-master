// Windows용 임베디드 Python을 build-python/ 에 준비하고 사이드카 패키지를 미리 설치한다.
// 설치 파일 "Python 포함판"이 PC에 Python 없이도 동작하게 하는 용도. (GitHub Actions의 Windows에서 실행)
// 사용: node scripts/bundle-python.mjs   — 지금 PATH의 python 과 같은 버전의 임베디드판을 받는다
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yauzl = require('yauzl');

if (process.platform !== 'win32') {
    console.error('임베디드 Python 묶기는 Windows에서만 합니다.');
    process.exit(1);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, 'build-python');
const version = execFileSync('python', ['-c', 'import platform; print(platform.python_version())'], { encoding: 'utf8' }).trim();
const [major, minor] = version.split('.');
const url = `https://www.python.org/ftp/python/${version}/python-${version}-embed-amd64.zip`;

function unzip(buffer, dest) {
    return new Promise((resolve, reject) => {
        yauzl.fromBuffer(buffer, { lazyEntries: true }, (err, zip) => {
            if (err) return reject(err);
            zip.readEntry();
            zip.on('entry', entry => {
                const target = path.resolve(dest, entry.fileName);
                if (!target.startsWith(path.resolve(dest) + path.sep)) return reject(new Error(`잘못된 경로: ${entry.fileName}`));
                if (/\/$/.test(entry.fileName)) { fs.mkdirSync(target, { recursive: true }); zip.readEntry(); return; }
                fs.mkdirSync(path.dirname(target), { recursive: true });
                zip.openReadStream(entry, (e, stream) => {
                    if (e) return reject(e);
                    stream.pipe(fs.createWriteStream(target)).on('finish', () => zip.readEntry());
                });
            });
            zip.on('end', resolve);
        });
    });
}

console.log(`임베디드 Python ${version} 받는 중: ${url}`);
const r = await fetch(url);
if (!r.ok) throw new Error(`HTTP ${r.status} — ${url}`);
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
await unzip(Buffer.from(await r.arrayBuffer()), out);

// ._pth: site-packages 를 경로에 넣고 site 를 켠다
const pth = path.join(out, `python${major}${minor}._pth`);
const lines = fs.readFileSync(pth, 'utf8').split(/\r?\n/).filter(l => l.trim() && !/^#?\s*import site/.test(l));
lines.push('Lib\\site-packages', 'import site');
fs.writeFileSync(pth, lines.join('\r\n') + '\r\n');

const site = path.join(out, 'Lib', 'site-packages');
fs.mkdirSync(site, { recursive: true });
console.log('사이드카 패키지 설치 중');
execFileSync('python', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
    '--target', site, '-r', path.join(root, 'sidecar', 'requirements.txt')], { stdio: 'inherit' });

// 확인: 임베디드 Python 으로 사이드카가 쓰는 모듈을 불러온다
execFileSync(path.join(out, 'python.exe'), ['-c',
    'import minecraft_launcher_lib, send2trash, json, zipfile, urllib.request; print("embedded python OK")'],
    { stdio: 'inherit', env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } });
console.log('임베디드 Python 확인 완료');
