// 앱에 함께 넣을 VS Code 확장을 Open VSX에서 받는다(설치 시점의 최신 안정판).
// 결과: applications/electron/plugins/<게시자>.<이름>/  (Theia download:plugins 와 같은 구조)
// 사용: npm run download:plugins   (이미 받은 확장은 건너뜀, --force 로 다시 받기)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yauzl = require('yauzl');

const PLUGINS = [
    // 데이터팩 자동완성·디버거·게임 콘솔 (게임 쪽 Fabric 모드와 짝)
    'Papierkorb2292.commandcrafter',
    // 한국어 화면
    'MS-CEINTL.vscode-language-pack-ko',
];

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pluginsDir = path.join(root, 'applications', 'electron', 'plugins');
const force = process.argv.includes('--force');

async function json(url) {
    const r = await fetch(url, { headers: { 'User-Agent': 'integrated-studio/0.1' } });
    if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
    return r.json();
}

function unzip(buffer, dest) {
    return new Promise((resolve, reject) => {
        yauzl.fromBuffer(buffer, { lazyEntries: true }, (err, zip) => {
            if (err) return reject(err);
            zip.readEntry();
            zip.on('entry', entry => {
                const target = path.resolve(dest, entry.fileName);
                if (!target.startsWith(path.resolve(dest) + path.sep)) {
                    return reject(new Error(`잘못된 경로: ${entry.fileName}`));
                }
                if (/\/$/.test(entry.fileName)) {
                    fs.mkdirSync(target, { recursive: true });
                    zip.readEntry();
                    return;
                }
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

let failed = 0;
fs.mkdirSync(pluginsDir, { recursive: true });
for (const id of PLUGINS) {
    const [ns, name] = id.split('.');
    const dest = path.join(pluginsDir, id);
    try {
        const meta = await json(`https://open-vsx.org/api/${ns}/${name}`);
        const version = meta.version;
        const stamp = path.join(dest, '.studio-version');
        if (!force && fs.existsSync(stamp) && fs.readFileSync(stamp, 'utf8') === version) {
            console.log(`= ${id}@${version} 이미 있음`);
            continue;
        }
        const url = meta.files?.download;
        if (!url) throw new Error('다운로드 주소 없음');
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        fs.rmSync(dest, { recursive: true, force: true });
        fs.mkdirSync(dest, { recursive: true });
        await unzip(Buffer.from(await r.arrayBuffer()), dest);
        fs.writeFileSync(stamp, version);
        console.log(`+ ${id}@${version}`);
    } catch (e) {
        failed++;
        console.error(`! ${id}: 받지 못했습니다 — ${e.message}`);
    }
}
if (failed) {
    console.error(`확장 ${failed}개를 받지 못했습니다. 네트워크(open-vsx.org)를 확인하고 다시 실행하세요. 앱은 확장 없이도 실행됩니다.`);
}
