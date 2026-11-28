/**
 * M10 주소 방식 "playit 중계": playit.gg 에이전트로 고정 공개 주소를 만든다.
 *
 * 공식 소스(github.com/playit-cloud/playit-agent 2.0.2, 커밋 bddcbed 2026-11-10)로 확인한 내용:
 * - 제어 채널 유지(UDP 제어 세션·주기적 ping)·터널 데이터 중계는 공식 데몬 playitd(agent_core)가 한다. 앱이 프로토콜을 직접 만들지 않는다.
 *   (사용자 질문 2026-11-28 "대시보드에 계속 Agent is offline": 원인은 ① 계정 연결 뒤 에이전트를 켜지 않음 — 서버가 playit 주소를 열 때만 켰다
 *   ② 2.0 의 playit.exe 는 CLI 라, 공식 Windows 서비스가 설치돼 있으면 그 서비스(다른 비밀키)에 붙어 우리 키를 쓰지 않음
 *   ③ 에이전트 출력(pipe)을 읽지 않아 버퍼가 차면 에이전트가 멈출 수 있었음.)
 * - 그래서 데몬을 직접 실행한다: Windows 릴리스 자산 playitd-windows-x86_64-signed.exe(없으면 서명 없는 것), Linux 는 playit-linux-amd64(=playitd).
 *   실행 인자: --secret-path <키 파일> --socket-path <앱 전용 IPC 이름>(설치된 서비스·다른 playit 창과 겹치지 않게). 로그는 표준 출력(로그 경로를 안 주면).
 *   데몬 로그 "playit connected; tunnels loaded" = 온라인(대시보드에서 Online), "configured agent secret is no longer valid" = 키 무효,
 *   "agent disabled because the account is over the agent limit" = 무료 에이전트 수 초과, "failed to start playit agent" = 연결 실패(데몬이 다시 시도).
 * - 받은 파일은 GitHub API 가 준 sha256 digest 로 검증한다. 처음 쓸 때 사용자 확인 후에만 받는다.
 * - 계정 연결(claim): 5바이트 hex 코드 → https://playit.gg/claim/<코드> 를 브라우저로 → POST /claim/setup {code, agent_type, version} 으로
 *   WaitingForUserVisit/WaitingForUser/UserAccepted/UserRejected 확인 → POST /claim/exchange {code} 로 secret_key.
 *   키 파일 형식은 데몬과 같은 TOML(secret_key = "<hex>"), 위치는 데몬 기본값 %LOCALAPPDATA%\playit_gg\playit.toml.
 * - API: https://api.playit.gg, 요청 POST JSON, 인증 헤더 "Agent-Key <비밀키>", 응답 {"status":"success|fail|error","data":…}
 *   /tunnels/list {tunnel_id, agent_id} · /tunnels/create {name, tunnel_type:"minecraft-java", port_type:"tcp", port_count:1,
 *   origin:{type:"default", data:{local_ip, local_port}}, enabled, alloc, firewall_id, proxy_protocol} ·
 *   /tunnels/update {tunnel_id, local_ip, local_port, agent_id, enabled}
 *   주소: alloc {status:"allocated", data:{assigned_domain, assigned_srv, port_start, …}}
 * - 서버마다 터널 하나(이름 "통합 작업실 · <서버 이름>")를 만들어 두고 다시 쓰므로 주소가 고정된다(포트가 바뀌면 local_port 만 갱신).
 * - 에이전트는 계정이 연결돼 있으면 앱이 켜져 있는 동안 계속 켜 둔다(대시보드 Online 유지). 예기치 않게 꺼지면 점점 길게 기다리며 다시 켠다.
 *   모든 단계(계정 연결·키 교환·에이전트 시작·연결·오류)는 'log' 이벤트와 <에이전트 폴더>/agent.log 에 남긴다.
 * 무료 요금제의 터널 수·지역 제한은 playit.gg 계정 화면 기준(바뀔 수 있음) — 넘으면 API 오류를 그대로 한국어로 안내한다.
 */
import { ChildProcess, spawn } from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { EventEmitter } from 'events';
import { PlayitStatus } from '../common/index.js';

export const RELEASE_API = 'https://api.github.com/repos/playit-cloud/playit-agent/releases/latest';
export const TUNNEL_PREFIX = '통합 작업실 · ';

export interface PlayitOptions {
    /** 에이전트 둘 폴더(앱 데이터 폴더 안) */
    dir: string;
    apiBase?: string;
    releaseApi?: string;
    /** 단독판이 읽는 비밀키 파일 */
    secretPath?: string;
    fetchImpl?: typeof fetch;
    /** 에이전트 실행(시험에서 바꿈) */
    spawnAgent?: (exe: string, args: string[]) => ChildProcess;
    claimPollMs?: number;
    claimTimeoutMs?: number;
    openUrl?: (url: string) => void;
}

export class PlayitError extends Error {}

export function defaultSecretPath(): string {
    if (process.platform === 'win32') {
        return path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'), 'playit_gg', 'playit.toml');
    }
    return path.join(os.homedir(), '.config', 'playit_gg', 'playit.toml');
}

/** 받을 릴리스 자산(데몬 playitd). Windows 는 서명판 먼저, Linux 의 playit-linux-* 는 데몬이다(공식 build-release.yml). */
export function assetName(): string {
    if (process.platform === 'win32') {
        return process.arch === 'ia32' ? 'playitd-windows-x86-signed.exe' : 'playitd-windows-x86_64-signed.exe';
    }
    if (process.platform === 'darwin') {
        return 'playit-macos-universal.tar.gz';
    }
    return process.arch === 'arm64' ? 'playit-linux-aarch64' : 'playit-linux-amd64';
}

export function readSecret(file: string): string | undefined {
    try {
        const m = /^\s*secret_key\s*=\s*"([0-9a-fA-F]{32,128})"\s*$/m.exec(fs.readFileSync(file, 'utf8'));
        return m?.[1];
    } catch {
        return undefined;
    }
}

interface TunnelInfo { id: string; name?: string; address?: string; localPort?: number; pending: boolean; disabled?: string }

/** 이벤트: 'status'(PlayitStatus) */
export class PlayitManager extends EventEmitter {
    protected agent: ChildProcess | undefined;
    protected users = new Set<string>();
    protected claimUrl: string | undefined;
    protected message: string | undefined;
    protected online = false;
    protected recent: string[] = [];
    protected keepAlive = false;
    protected restarts = 0;
    protected restartTimer: NodeJS.Timeout | undefined;
    readonly apiBase: string;
    readonly secretPath: string;

    constructor(protected readonly opts: PlayitOptions) {
        super();
        this.apiBase = opts.apiBase ?? process.env.INTEGRATED_STUDIO_PLAYIT_API ?? 'https://api.playit.gg';
        this.secretPath = opts.secretPath ?? process.env.INTEGRATED_STUDIO_PLAYIT_SECRET ?? defaultSecretPath();
    }

    get exe(): string {
        return path.join(this.opts.dir, process.platform === 'win32' ? 'playitd.exe' : 'playitd');
    }

    /** 예전 앱이 받은 CLI(playit.exe) — 데몬으로 바꿔 받아야 한다 */
    get outdated(): boolean {
        return !fs.existsSync(this.exe) && fs.existsSync(path.join(this.opts.dir, process.platform === 'win32' ? 'playit.exe' : 'playit'));
    }

    get logPath(): string {
        return path.join(this.opts.dir, 'agent.log');
    }

    /** 앱 전용 IPC 이름(공식 서비스 \\.\pipe\playitd 나 다른 playit 창과 겹치지 않게) */
    protected socketPath(): string {
        return process.platform === 'win32' ? `\\\\.\\pipe\\integrated-studio-playitd-${process.pid}` : path.join(this.opts.dir, 'playitd.sock');
    }

    /** 단계별 기록: 'log' 이벤트(서버 콘솔·패널) + agent.log 파일(1MB 넘으면 .old 로) */
    protected log(line: string, level: 'info' | 'warn' | 'error' = 'info'): void {
        const text = `${new Date().toISOString()} [${level}] ${line}`;
        this.recent.push(text);
        if (this.recent.length > 200) {
            this.recent.splice(0, this.recent.length - 200);
        }
        try {
            fs.mkdirSync(this.opts.dir, { recursive: true });
            if (fs.existsSync(this.logPath) && fs.statSync(this.logPath).size > 1_000_000) {
                fs.renameSync(this.logPath, this.logPath + '.old');
            }
            fs.appendFileSync(this.logPath, text + '\n');
        } catch {
            // 기록 실패로 동작을 멈추지 않는다
        }
        this.emit('log', line, level);
    }

    recentLog(): string[] {
        return [...this.recent];
    }

    protected get fetch(): typeof fetch {
        return this.opts.fetchImpl ?? fetch;
    }

    status(): PlayitStatus {
        const running = !!this.agent && this.agent.exitCode === null;
        return {
            agentInstalled: fs.existsSync(this.exe),
            agentRunning: running,
            agentOnline: running && this.online,
            outdated: this.outdated || undefined,
            linked: !!readSecret(this.secretPath),
            claimUrl: this.claimUrl,
            message: this.message,
            logPath: this.logPath,
        };
    }

    protected changed(message?: string): void {
        if (message !== undefined) {
            this.message = message;
        }
        this.emit('status', this.status());
    }

    // ---------------------------------------------------------------- 에이전트 받기
    async install(): Promise<PlayitStatus> {
        const name = assetName();
        let rel: { tag_name?: string; assets?: Array<{ name: string; browser_download_url: string; digest?: string | null; size?: number }> };
        try {
            const res = await this.fetch(this.opts.releaseApi ?? RELEASE_API, { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'integrated-studio' } });
            if (!res.ok) {
                throw new PlayitError(`GitHub 응답 ${res.status}`);
            }
            rel = await res.json() as typeof rel;
        } catch (e) {
            throw new PlayitError(`playit 배포 정보를 받지 못했습니다: ${(e as Error).message}`);
        }
        const asset = (rel.assets ?? []).find(a => a.name === name)
            ?? (rel.assets ?? []).find(a => a.name === name.replace('-signed', ''));
        this.log(`에이전트 받기: 릴리스 ${rel.tag_name ?? '?'}, 자산 ${asset?.name ?? '(없음)'}`);
        if (!asset) {
            throw new PlayitError(`playit ${rel.tag_name ?? ''} 에 이 PC 용 파일(${name})이 없습니다.`);
        }
        const digest = /^sha256:([0-9a-f]{64})$/i.exec(asset.digest ?? '')?.[1]?.toLowerCase();
        if (!digest) {
            throw new PlayitError('GitHub 이 파일 검증값(sha256)을 주지 않아 설치하지 않았습니다. playit.gg/download 에서 직접 받아 주세요.');
        }
        const host = new URL(asset.browser_download_url).hostname;
        if (!['github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com', '127.0.0.1', 'localhost'].includes(host)) {
            throw new PlayitError(`공식 배포처가 아닌 주소라 받지 않았습니다: ${host}`);
        }
        const res = await this.fetch(asset.browser_download_url, { headers: { 'User-Agent': 'integrated-studio' } });
        if (!res.ok) {
            throw new PlayitError(`playit 을 받지 못했습니다(응답 ${res.status}).`);
        }
        const data = Buffer.from(await res.arrayBuffer());
        const got = crypto.createHash('sha256').update(data).digest('hex');
        if (got !== digest) {
            throw new PlayitError('받은 playit 파일의 sha256 이 GitHub 값과 달라 버렸습니다.');
        }
        fs.mkdirSync(this.opts.dir, { recursive: true });
        const tmp = this.exe + '.part';
        fs.writeFileSync(tmp, data, { mode: 0o755 });
        fs.renameSync(tmp, this.exe);
        fs.writeFileSync(path.join(this.opts.dir, 'version.json'), JSON.stringify({ tag: rel.tag_name, asset: asset.name, sha256: digest }, undefined, 2));
        this.log(`에이전트를 받았습니다(sha256 확인): ${this.exe}`);
        this.changed(`playit ${rel.tag_name ?? ''} 을(를) 받았습니다.`);
        if (readSecret(this.secretPath)) {
            this.ensureRunning();
        }
        return this.status();
    }

    // ---------------------------------------------------------------- API
    protected async api<T>(route: string, body: unknown, auth = true): Promise<T> {
        const headers: Record<string, string> = { 'Content-Type': 'application/json', 'User-Agent': 'integrated-studio' };
        if (auth) {
            const secret = readSecret(this.secretPath);
            if (!secret) {
                throw new PlayitError('playit 계정이 아직 연결되지 않았습니다.');
            }
            headers.Authorization = `Agent-Key ${secret}`;
        }
        let res: Response;
        try {
            res = await this.fetch(this.apiBase + route, { method: 'POST', headers, body: JSON.stringify(body) });
        } catch (e) {
            this.log(`API ${route} 요청 실패(네트워크): ${(e as Error).message}`, 'error');
            throw new PlayitError(`playit 서버에 연결하지 못했습니다(일부 통신사·회사망에서 막힐 수 있음): ${(e as Error).message}`);
        }
        if (auth && (res.status === 401 || res.status === 403)) {
            this.log(`API ${route} 인증 거부(${res.status})`, 'error');
            this.unlink('playit 계정 연결이 풀렸습니다(playit.gg 에서 에이전트를 지웠거나 키가 바뀜). [playit 다시 연결]을 눌러 주세요.');
            throw new PlayitError('[PLAYIT-401] playit 계정 연결이 풀렸습니다. 서버 패널의 [playit 다시 연결]을 눌러 주세요.');
        }
        if (res.status === 429) {
            throw new PlayitError('playit 요청이 너무 많습니다. 잠시 뒤 다시 해 주세요.');
        }
        let json: { status?: string; data?: unknown };
        try {
            json = await res.json() as typeof json;
        } catch {
            throw new PlayitError(`playit 응답을 읽지 못했습니다(${res.status}).`);
        }
        if (json.status === 'success') {
            return json.data as T;
        }
        const detail = typeof json.data === 'string' ? json.data : JSON.stringify(json.data);
        this.log(`API ${route} 응답 ${res.status} ${json.status}: ${detail}`, 'warn');
        if (auth && /Auth|Unauthorized|InvalidAgentKey|InvalidSignature|AgentNotFound/i.test(detail)) {
            this.unlink('playit 계정 연결이 풀렸습니다(playit.gg 에서 에이전트를 지웠거나 키가 바뀜). [playit 다시 연결]을 눌러 주세요.');
            throw new PlayitError('[PLAYIT-401] playit 계정 연결이 풀렸습니다. 서버 패널의 [playit 다시 연결]을 눌러 주세요.');
        }
        if (/Limit|Quota|Premium|Tunnel.*Exceed|RequiresPlayitPremium/i.test(detail)) {
            throw new PlayitError(`playit 무료 요금제 한도에 걸렸습니다(${detail}). playit.gg 계정에서 쓰지 않는 터널을 지워 주세요.`);
        }
        throw new PlayitError(`playit 이 요청을 거부했습니다: ${detail}`);
    }

    // ---------------------------------------------------------------- 계정 연결
    /**
     * 연결이 풀렸을 때(사용자 요청 2026-11-27): 쓸모없어진 비밀키 파일을 옆에 .invalid 로 옮기고(지우지 않음) 에이전트를 끈다.
     * 그러면 상태가 '연결 안 됨'이 되어 패널에 [playit 다시 연결]이 뜨고, claim() 이 새로 연결한다.
     */
    unlink(message: string): void {
        try {
            if (fs.existsSync(this.secretPath)) {
                fs.renameSync(this.secretPath, `${this.secretPath}.invalid-${Date.now()}`);
            }
        } catch {
            // 옮기지 못해도 상태 메시지는 남긴다
        }
        const hadUsers = this.users.size > 0;
        this.log(`계정 연결 해제: ${message}`, 'warn');
        this.stopAgent();
        this.changed(message + (hadUsers ? ' 다시 연결하면 열려 있던 서버 주소를 다시 여세요.' : ''));
    }

    /** 지금 키가 아직 유효한지 playit 에 물어본다(풀렸으면 unlink 까지). */
    async verify(): Promise<PlayitStatus> {
        if (!readSecret(this.secretPath)) {
            return this.status();
        }
        try {
            await this.tunnels();
            this.changed('playit 계정 연결이 정상입니다.');
        } catch (e) {
            if (!(e instanceof PlayitError) || !/PLAYIT-401/.test(e.message)) {
                this.changed(`playit 연결을 확인하지 못했습니다: ${(e as Error).message}`);
            }
        }
        return this.status();
    }

    /** 브라우저로 연결 링크를 열고, 사용자가 승인할 때까지 기다린다. 비밀키는 단독판이 읽는 위치에만 쓴다.
     *  force = 지금 키가 있어도 새로 연결(다른 계정으로 바꾸거나 풀린 연결 고치기). */
    async claim(force = false): Promise<PlayitStatus> {
        if (readSecret(this.secretPath)) {
            if (!force) {
                return this.status();
            }
            this.unlink('playit 계정을 새로 연결합니다.');
        }
        const code = crypto.randomBytes(5).toString('hex');
        const url = `https://playit.gg/claim/${code}`;
        this.claimUrl = url;
        this.log(`계정 연결 시작: ${url}`);
        this.changed('브라우저에서 playit.gg 에 로그인하고 "통합 작업실" 연결을 승인해 주세요.');
        this.opts.openUrl?.(url);
        const deadline = Date.now() + (this.opts.claimTimeoutMs ?? 10 * 60_000);
        let lastState = '';
        try {
            for (;;) {
                const st = await this.api<string>('/claim/setup', { code, agent_type: 'self-managed', version: `integrated-studio playitd` }, false);
                if (st !== lastState) {
                    this.log(`계정 연결 상태: ${st}`);
                    lastState = st;
                }
                if (st === 'UserAccepted') {
                    break;
                }
                if (st === 'UserRejected') {
                    throw new PlayitError('playit 연결을 거절했습니다.');
                }
                if (Date.now() > deadline) {
                    throw new PlayitError('10분 안에 승인하지 않아 playit 연결을 멈췄습니다. 다시 눌러 주세요.');
                }
                await new Promise(r => setTimeout(r, this.opts.claimPollMs ?? 2000));
            }
            const { secret_key } = await this.api<{ secret_key: string }>('/claim/exchange', { code }, false);
            if (!/^[0-9a-fA-F]{32,128}$/.test(secret_key ?? '')) {
                throw new PlayitError('playit 이 준 비밀키 형식이 이상합니다.');
            }
            fs.mkdirSync(path.dirname(this.secretPath), { recursive: true });
            fs.writeFileSync(this.secretPath, `secret_key = "${secret_key}"\n`, { mode: 0o600 });
            this.claimUrl = undefined;
            this.log(`키 교환 완료, 저장: ${this.secretPath}`);
            this.changed('playit 계정을 연결했습니다. 에이전트를 켜는 중…');
            this.ensureRunning();          // 연결 직후 바로 켜야 대시보드에서 Online 이 된다
        } catch (e) {
            this.claimUrl = undefined;
            this.log(`계정 연결 실패: ${(e as Error).message}`, 'error');
            this.changed((e as Error).message);
            throw e;
        }
        return this.status();
    }


    // ---------------------------------------------------------------- 터널
    protected toInfo(t: Record<string, unknown>): TunnelInfo {
        const alloc = t.alloc as { status?: string; data?: Record<string, unknown> } | undefined;
        const origin = t.origin as { data?: { local_port?: number } } | undefined;
        let address: string | undefined;
        if (alloc?.status === 'allocated' && alloc.data) {
            const d = alloc.data;
            address = (d.assigned_srv as string) || (d.port_start === 25565 ? d.assigned_domain as string : `${d.assigned_domain}:${d.port_start}`);
        }
        return { id: String(t.id), name: t.name as string | undefined, address, localPort: origin?.data?.local_port,
            pending: alloc?.status === 'pending', disabled: alloc?.status === 'disabled' ? JSON.stringify(alloc.data ?? {}) : undefined };
    }

    async tunnels(): Promise<TunnelInfo[]> {
        const r = await this.api<{ tunnels: Array<Record<string, unknown>> }>('/tunnels/list', { tunnel_id: null, agent_id: null });
        return (r.tunnels ?? []).map(t => this.toInfo(t));
    }

    /** 서버 이름의 터널을 찾아(없으면 만들어) 로컬 포트를 맞추고 공개 주소를 돌려준다. */
    async ensureTunnel(name: string, localPort: number, knownId?: string): Promise<{ id: string; address: string }> {
        const label = (TUNNEL_PREFIX + name).slice(0, 60);
        let list = await this.tunnels();
        let t = list.find(x => x.id === knownId) ?? list.find(x => x.name === label);
        if (!t) {
            const id = await this.api<string>('/tunnels/create', {
                name: label, tunnel_type: 'minecraft-java', port_type: 'tcp', port_count: 1,
                origin: { type: 'default', data: { local_ip: '127.0.0.1', local_port: localPort } },
                enabled: true, alloc: null, firewall_id: null, proxy_protocol: null,
            });
            list = await this.tunnels();
            t = list.find(x => x.id === String(id)) ?? { id: String(id), pending: true };
        } else if (t.localPort !== localPort) {
            await this.api('/tunnels/update', { tunnel_id: t.id, local_ip: '127.0.0.1', local_port: localPort, agent_id: null, enabled: true });
        }
        for (let i = 0; i < 15 && !t.address; i++) {       // 주소 배정은 몇 초 걸릴 수 있다
            await new Promise(r => setTimeout(r, i === 0 ? 0 : 1000));
            t = (await this.tunnels()).find(x => x.id === t!.id) ?? t;
            if (t.disabled) {
                throw new PlayitError(`playit 이 이 터널을 꺼 두었습니다: ${t.disabled}`);
            }
        }
        if (!t.address) {
            throw new PlayitError('playit 이 주소를 아직 배정하지 않았습니다. 잠시 뒤 다시 열어 주세요.');
        }
        return { id: t.id, address: t.address };
    }

    // ---------------------------------------------------------------- 에이전트 실행
    /** 데몬 출력 한 줄 해석: 온라인·키 무효·한도 초과·연결 실패 */
    protected onAgentLine(raw: string): void {
        // eslint-disable-next-line no-control-regex
        const line = raw.replace(/\x1b\[[0-9;]*m/g, '').trim();
        if (!line) {
            return;
        }
        const level = /\bERROR\b/.test(line) ? 'error' : /\bWARN\b/.test(line) ? 'warn' : 'info';
        this.log(`에이전트: ${line}`, level);
        if (/playit connected; tunnels loaded|playit tunnel state updated/.test(line)) {
            if (!this.online) {
                this.online = true;
                this.restarts = 0;
                this.changed('playit 에이전트가 온라인입니다(playit.gg 대시보드에서 Online).');
            }
        } else if (/configured agent secret is no longer valid|InvalidSecret/.test(line)) {
            this.online = false;
            this.unlink('[PLAYIT-401] playit 이 이 에이전트 키를 거부했습니다(대시보드에서 지웠거나 키가 바뀜). [playit 다시 연결]을 눌러 주세요.');
        } else if (/over the agent limit/.test(line)) {
            this.online = false;
            this.changed('[PLAYIT-LIMIT] playit 계정의 에이전트 수가 무료 한도를 넘어 이 에이전트가 꺼져 있습니다. playit.gg 에서 안 쓰는 에이전트를 지워 주세요.');
        } else if (/failed to start playit agent|playit agent stopped unexpectedly/.test(line)) {
            this.online = false;
            const why = /message=([^,]+)/.exec(line)?.[1] ?? '';
            this.changed(`[PLAYIT-CONNECT] playit 제어 서버에 연결하지 못했습니다${why ? `(${why})` : ''}. 에이전트가 스스로 다시 시도합니다 — 방화벽·회사망·통신사 차단을 확인하세요.`);
        } else if (/Waiting for frontend secret provisioning/.test(line)) {
            this.online = false;
            this.changed('playit 에이전트가 키를 찾지 못했습니다. [playit 다시 연결]을 눌러 주세요.');
        }
    }

    /** 계정이 연결돼 있으면 에이전트를 켜 두고(앱이 켜진 동안), 꺼지면 다시 켠다. */
    ensureRunning(): void {
        this.keepAlive = true;
        if (this.agent && this.agent.exitCode === null) {
            return;
        }
        if (!readSecret(this.secretPath)) {
            this.log('에이전트를 켜지 않음: 계정이 연결되지 않았습니다.', 'warn');
            return;
        }
        if (!fs.existsSync(this.exe)) {
            this.log(this.outdated ? '에이전트를 켜지 않음: 예전 playit.exe 만 있어 새 데몬(playitd)을 받아야 합니다.' : '에이전트를 켜지 않음: 아직 받지 않았습니다.', 'warn');
            this.changed(this.outdated ? 'playit 에이전트를 새 방식(playitd)으로 바꿔야 합니다. [playit 준비]를 눌러 주세요.' : undefined);
            return;
        }
        this.start();
    }

    protected start(): void {
        const args = ['--secret-path', this.secretPath, '--socket-path', this.socketPath()];
        this.log(`에이전트 시작: ${this.exe} ${args.join(' ')}`);
        this.online = false;
        let p: ChildProcess;
        try {
            p = (this.opts.spawnAgent ?? ((exe: string, a: string[]) => spawn(exe, a, {
                windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
                env: { ...process.env, PLAYIT_LOG: process.env.PLAYIT_LOG ?? 'info' },
            })))(this.exe, args);
        } catch (e) {
            this.log(`에이전트를 실행하지 못했습니다: ${(e as Error).message}`, 'error');
            this.changed(`playit 에이전트를 켜지 못했습니다: ${(e as Error).message}`);
            return;
        }
        this.agent = p;
        // 출력은 반드시 읽는다 — 안 읽으면 파이프가 차서 에이전트가 멈춘다
        for (const stream of [p.stdout, p.stderr]) {
            let buf = '';
            stream?.setEncoding?.('utf8');
            stream?.on('data', (chunk: string) => {
                buf += chunk;
                const lines = buf.split(/\r?\n/);
                buf = lines.pop() ?? '';
                lines.forEach(l => this.onAgentLine(l));
            });
        }
        p.on('exit', code => {
            if (this.agent !== p) {
                return;
            }
            this.agent = undefined;
            this.online = false;
            this.log(`에이전트 종료(코드 ${code})`, code ? 'error' : 'info');
            if (this.keepAlive && readSecret(this.secretPath)) {
                const delay = Math.min(60_000, 2000 * 2 ** this.restarts++);
                this.changed(`[PLAYIT-${code ?? 'X'}] playit 에이전트가 꺼졌습니다(코드 ${code}). ${Math.round(delay / 1000)}초 뒤 다시 켭니다. `
                    + `자세한 내용: ${this.logPath}`);
                this.restartTimer = setTimeout(() => {
                    this.restartTimer = undefined;
                    if (this.keepAlive && !this.agent) {
                        this.ensureRunning();
                    }
                }, delay);
            } else {
                this.changed();
            }
        });
        p.on('error', e => {
            this.log(`에이전트 실행 오류: ${e.message}`, 'error');
            this.changed(`playit 에이전트를 켜지 못했습니다: ${e.message}`);
        });
        this.changed('playit 에이전트를 켰습니다. playit.gg 에 연결하는 중…');
    }

    /** 서버 하나가 playit 을 쓰기 시작(에이전트가 꺼져 있으면 켠다). */
    acquire(serverId: string): void {
        this.users.add(serverId);
        if (!fs.existsSync(this.exe)) {
            throw new PlayitError(this.outdated
                ? 'playit 에이전트를 새 방식(playitd)으로 바꿔야 합니다. 패널의 [playit 준비]를 눌러 주세요.'
                : 'playit 에이전트가 없습니다. 먼저 받아 주세요.');
        }
        this.ensureRunning();
    }

    /** 서버가 playit 을 그만 씀. 에이전트는 계속 켜 둔다(대시보드 Online 유지, 다음에 바로 열림) — 끄는 건 앱 종료·연결 해제 때. */
    release(serverId: string): void {
        this.users.delete(serverId);
    }

    stopAgent(): void {
        this.keepAlive = false;
        if (this.restartTimer) {
            clearTimeout(this.restartTimer);
            this.restartTimer = undefined;
        }
        const p = this.agent;
        this.agent = undefined;
        this.online = false;
        if (p && p.exitCode === null) {
            this.log('에이전트 끄기');
            p.kill();
        }
        this.changed();
    }
}
