// 통합 작업실 Electron 진입점: 함께 넣은 VS Code 확장 폴더(plugins/)를 Theia에 알려 준 뒤 Theia를 시작한다.
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (!process.env.THEIA_DEFAULT_PLUGINS) {
    process.env.THEIA_DEFAULT_PLUGINS = `local-dir:${path.join(appDir, 'plugins')}`;
}
await import('../lib/backend/electron-main.js');
