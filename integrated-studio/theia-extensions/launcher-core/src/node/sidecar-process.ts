import { ChildProcess, execFile, spawn } from 'child_process';
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

/** 설치 파일에 Python을 함께 넣은 경우: resources/python/python.exe (패키지는 미리 설치돼 있음) */
export function bundledPython(): string | undefined {
    const resourcesPath = (process as { resourcesPath?: string }).resourcesPath;
    if (!resourcesPath) {
        return undefined;
    }
    const exe = process.platform === 'win32'
        ? path.join(resourcesPath, 'python', 'python.exe')
        : path.join(resourcesPath, 'python', 'bin', 'python3');
    return fs.existsSync(exe) ? exe : undefined;
}

/** 사이드카 전용 가상환경 위치: 개발 중에는 sidecar/.venv, 패키징된 앱은 ~/.integrated-studio/venv */
export function venvDir(sidecarDir: string, dataDir: string): string {
    return isPackagedSidecar(sidecarDir) ? path.join(path.dirname(dataDir), 'venv') : path.join(sidecarDir, '.venv');
}

export function venvPython(dir: string): string {
    return process.platform === 'win32' ? path.join(dir, 'Scripts', 'python.exe') : path.join(dir, 'bin', 'python');
}

/** Python 버전 숫자(예: Python313 → 313). 폴더 이름에서 읽는다 */
function folderVersion(name: string): number {
    const m = /^Python(\d)(\d+)/i.exec(name);
    return m ? Number(m[1]) * 100 + Number(m[2]) : 0;
}

/**
 * PC 에 설치된 Python 3.11 이상(코드가 tomllib 을 쓴다)을 찾는다. 설치 프로그램이 방금 깔았으면 이 앱의 PATH 엔 아직 없어서
 * 표준 설치 위치를 먼저 본다: %LOCALAPPDATA%\Programs\Python\Python3xx (사용자 설치·winget) → Program Files → C:\Python3xx.
 * Windows 의 "앱 실행 별칭"(WindowsApps\python.exe, 누르면 Store 가 열리는 가짜)은 쓰지 않는다.
 */
export function findSystemPython(env: NodeJS.ProcessEnv = process.env): string | undefined {
    if (process.platform !== 'win32') {
        return 'python3';
    }
    const bases = [
        env.LOCALAPPDATA && path.join(env.LOCALAPPDATA, 'Programs', 'Python'),
        env.ProgramFiles, env['ProgramFiles(x86)'], 'C:\\',
    ].filter((b): b is string => !!b);
    const found: Array<{ v: number; exe: string }> = [];
    for (const base of bases) {
        let names: string[] = [];
        try { names = fs.readdirSync(base); } catch { continue; }
        for (const n of names) {
            const v = folderVersion(n);
            const exe = path.join(base, n, 'python.exe');
            if (v >= 311 && fs.existsSync(exe)) {
                found.push({ v, exe });
            }
        }
    }
    found.sort((a, b) => b.v - a.v);
    if (found.length) {
        return found[0].exe;
    }
    // PATH 의 python(가짜 별칭 제외) — 마지막 수단
    for (const dir of (env.PATH ?? env.Path ?? '').split(path.delimiter)) {
        const exe = path.join(dir, 'python.exe');
        if (dir && !/WindowsApps/i.test(dir) && fs.existsSync(exe)) {
            return exe;
        }
    }
    return undefined;
}

function run(cmd: string, args: string[], cwd: string): Promise<void> {
    return new Promise((resolve, reject) => {
        execFile(cmd, args, { cwd, windowsHide: true, maxBuffer: 16 * 1024 * 1024 }, (err, _stdout, stderr) => {
            if (err) {
                reject(new Error(`${cmd} ${args.join(' ')} 실패: ${String(stderr).split(/\r?\n/).slice(-5).join('\n') || err.message}`));
            } else {
                resolve();
            }
        });
    });
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
    python: string | undefined;

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

    /**
     * INTEGRATED_STUDIO_PYTHON → 설치 파일에 함께 넣은 Python(resources/python) →
     * 가상환경 → (없으면) PC의 Python으로 가상환경을 만들고 requirements.txt 설치
     */
    protected async ensurePython(): Promise<string> {
        if (process.env.INTEGRATED_STUDIO_PYTHON) {
            return process.env.INTEGRATED_STUDIO_PYTHON;
        }
        const bundled = bundledPython();
        if (bundled) {
            return bundled;
        }
        const dir = venvDir(this.sidecarDir!, this.dataDir);
        const py = venvPython(dir);
        // requirements.txt 가 바뀌면(새 패키지 추가 등) 다시 설치한다
        const reqFile = path.join(this.sidecarDir!, 'requirements.txt');
        const reqStamp = fs.existsSync(reqFile) ? fs.readFileSync(reqFile, 'utf8').replace(/\r\n/g, '\n').trim() : '';
        const marker = path.join(dir, '.studio-ready');
        if (fs.existsSync(py) && fs.existsSync(marker) && fs.readFileSync(marker, 'utf8') === reqStamp) {
            return py;
        }
        const notify = (text: string, done = false) =>
            this.onNotificationEmitter.fire({ method: 'progress', params: { id: '', stage: 'setup', text, done } });
        notify('처음 실행 준비: Python 가상환경 만드는 중');
        try {
            if (!fs.existsSync(py)) {
                const base = findSystemPython();
                if (!base) {
                    throw new Error('Python 3.11 이상을 찾지 못했습니다. 통합 작업실 설치 프로그램을 다시 실행해 [Python] 을 체크하거나, '
                        + 'python.org 에서 Python 3 을 설치한 뒤 앱을 다시 켜 주세요.');
                }
                await run(base, ['-m', 'venv', dir], this.sidecarDir!).catch(e => {
                    throw new Error(`Python 가상환경을 만들지 못했습니다(${base}). ${e.message}`);
                });
            }
            notify('처음 실행 준비: 런처 라이브러리 설치 중(pip)');
            await run(py, ['-m', 'pip', 'install', '--disable-pip-version-check', '-r', path.join(this.sidecarDir!, 'requirements.txt')], this.sidecarDir!);
            fs.writeFileSync(marker, reqStamp);
        } finally {
            notify('', true);
        }
        return py;
    }

    protected async start(): Promise<void> {
        if (!this.sidecarDir) {
            throw new Error('사이드카 폴더(sidecar/main.py)를 찾지 못했습니다.');
        }
        try {
            this.python = await this.ensurePython();
        } catch (e) {
            this.lastError = e instanceof Error ? e.message : String(e);
            throw e;
        }
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
