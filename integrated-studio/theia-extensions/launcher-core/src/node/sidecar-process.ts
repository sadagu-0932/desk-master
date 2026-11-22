import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as readline from 'readline';
import { fileURLToPath } from 'url';
import { injectable } from '@theia/core/shared/inversify';
import { Emitter } from '@theia/core/lib/common/event';
import { SidecarStatus } from '../common/index.js';

interface Pending {
    resolve(value: unknown): void;
    reject(err: Error): void;
}

/** sidecar/main.py 를 찾는다: 환경 변수 → 패키징된 앱의 resources → 개발 중 저장소 위쪽 폴더 */
export function findSidecarDir(): string | undefined {
    const candidates: string[] = [];
    if (process.env.INTEGRATED_STUDIO_SIDECAR) {
        candidates.push(process.env.INTEGRATED_STUDIO_SIDECAR);
    }
    const resourcesPath = (process as { resourcesPath?: string }).resourcesPath;
    if (resourcesPath) {
        candidates.push(path.join(resourcesPath, 'sidecar'));
    }
    let dir = path.dirname(fileURLToPath(import.meta.url));
    for (let i = 0; i < 8; i++) {
        candidates.push(path.join(dir, 'sidecar'));
        dir = path.dirname(dir);
    }
    return candidates.find(c => fs.existsSync(path.join(c, 'main.py')));
}

export function isPackagedSidecar(sidecarDir: string): boolean {
    const resourcesPath = (process as { resourcesPath?: string }).resourcesPath;
    return !!resourcesPath && path.resolve(sidecarDir).startsWith(path.resolve(resourcesPath));
}

export function resolveDataDir(sidecarDir: string | undefined): string {
    if (process.env.INTEGRATED_STUDIO_DATA) {
        return path.resolve(process.env.INTEGRATED_STUDIO_DATA);
    }
    if (sidecarDir && !isPackagedSidecar(sidecarDir)) {
        // 개발 중: 저장소 루트의 data/ (git 제외)
        return path.join(path.dirname(sidecarDir), 'data');
    }
    return path.join(os.homedir(), '.integrated-studio', 'data');
}

export function findPython(sidecarDir: string): string {
    if (process.env.INTEGRATED_STUDIO_PYTHON) {
        return process.env.INTEGRATED_STUDIO_PYTHON;
    }
    const venv = process.platform === 'win32'
        ? path.join(sidecarDir, '.venv', 'Scripts', 'python.exe')
        : path.join(sidecarDir, '.venv', 'bin', 'python');
    if (fs.existsSync(venv)) {
        return venv;
    }
    return process.platform === 'win32' ? 'python' : 'python3';
}

/** Python 사이드카 자식 프로세스와 줄 단위 JSON-RPC 통신 */
@injectable()
export class SidecarProcess {
    protected proc: ChildProcess | undefined;
    protected nextId = 1;
    protected pending = new Map<number, Pending>();
    protected starting: Promise<void> | undefined;
    protected lastError = '';
    protected stderrTail: string[] = [];

    readonly sidecarDir = findSidecarDir();
    readonly dataDir = resolveDataDir(this.sidecarDir);
    readonly python = this.sidecarDir ? findPython(this.sidecarDir) : undefined;

    protected readonly onNotificationEmitter = new Emitter<{ method: string; params: unknown }>();
    readonly onNotification = this.onNotificationEmitter.event;

    status(): SidecarStatus {
        if (!this.sidecarDir) {
            return { ok: false, message: '사이드카 폴더(sidecar/main.py)를 찾지 못했습니다.', dataDir: this.dataDir };
        }
        return {
            ok: !!this.proc && !this.lastError,
            message: this.lastError || (this.proc ? '사이드카 실행 중' : '사이드카 대기 중'),
            dataDir: this.dataDir,
            python: this.python,
        };
    }

    protected ensureStarted(): Promise<void> {
        if (this.proc) {
            return Promise.resolve();
        }
        if (!this.starting) {
            this.starting = this.start().finally(() => { this.starting = undefined; });
        }
        return this.starting;
    }

    protected start(): Promise<void> {
        return new Promise<void>((resolve, reject) => {
            if (!this.sidecarDir || !this.python) {
                reject(new Error('사이드카 폴더(sidecar/main.py)를 찾지 못했습니다.'));
                return;
            }
            fs.mkdirSync(this.dataDir, { recursive: true });
            const proc = spawn(this.python, ['-u', path.join(this.sidecarDir, 'main.py'), '--data', this.dataDir], {
                cwd: this.sidecarDir,
                env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
                stdio: ['pipe', 'pipe', 'pipe'],
                windowsHide: true,
            });
            this.proc = proc;
            this.lastError = '';
            let ready = false;
            const rl = readline.createInterface({ input: proc.stdout! });
            rl.on('line', line => {
                let msg: { id?: number; method?: string; params?: unknown; result?: unknown; error?: { message: string } };
                try {
                    msg = JSON.parse(line);
                } catch {
                    return;
                }
                if (msg.id !== undefined && msg.id !== null) {
                    const p = this.pending.get(msg.id);
                    if (p) {
                        this.pending.delete(msg.id);
                        if (msg.error) {
                            p.reject(new Error(msg.error.message));
                        } else {
                            p.resolve(msg.result);
                        }
                    }
                } else if (msg.method) {
                    if (msg.method === 'ready' && !ready) {
                        ready = true;
                        resolve();
                    }
                    this.onNotificationEmitter.fire({ method: msg.method, params: msg.params });
                }
            });
            proc.stderr!.on('data', (chunk: Buffer) => {
                const text = chunk.toString('utf8');
                process.stderr.write(`[sidecar] ${text}`);
                this.stderrTail.push(...text.split(/\r?\n/).filter(Boolean));
                this.stderrTail = this.stderrTail.slice(-20);
            });
            proc.on('error', err => {
                this.lastError = `Python을 실행하지 못했습니다(${this.python}): ${err.message}`;
                this.proc = undefined;
                reject(new Error(this.lastError));
            });
            proc.on('exit', code => {
                this.proc = undefined;
                const tail = this.stderrTail.slice(-5).join('\n');
                const message = code === 0 ? '사이드카 종료' : `사이드카가 종료되었습니다(코드 ${code}).\n${tail}`;
                if (code !== 0) {
                    this.lastError = message;
                }
                for (const p of this.pending.values()) {
                    p.reject(new Error(message));
                }
                this.pending.clear();
                if (!ready) {
                    reject(new Error(tail.includes('ModuleNotFoundError')
                        ? `Python 패키지가 없습니다. sidecar 폴더에서 설치하세요: ${this.python} -m pip install -r requirements.txt\n${tail}`
                        : message));
                }
                this.onNotificationEmitter.fire({ method: 'sidecar_exit', params: { code } });
            });
        });
    }

    async call<T>(method: string, params: object = {}): Promise<T> {
        await this.ensureStarted();
        const id = this.nextId++;
        return new Promise<T>((resolve, reject) => {
            this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
            this.proc!.stdin!.write(JSON.stringify({ id, method, params }) + '\n');
        });
    }

    dispose(): void {
        if (this.proc) {
            this.proc.stdin?.end();
            const p = this.proc;
            setTimeout(() => p.kill(), 3000);
        }
    }
}
