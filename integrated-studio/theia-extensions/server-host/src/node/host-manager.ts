/**
 * M10 백엔드: 서버(방식 A 전용 서버 / B 싱글 LAN 공개 / C 외부 서버)와 "주소 열기"를 관리한다. 여러 개를 동시에.
 *
 * 주소 자동 선택(실패하면 이유를 남기고 다음 방식으로). playit 은 뺐다(사용자 결정 2026-11-28 "playit 은 너무 안 됨"):
 *   B 싱글 LAN : e4mc → UPnP
 *   A 전용     : 서버에 넣은 주소 모드(e4mc — 바닐라·Fabric·NeoForge·Forge / Minekube Connect — Paper) → UPnP
 *                사이드카가 서버 로그의 주소("Domain assigned:" / "Your public address:")를 ds_address 로 알려 준다.
 *   C 외부     : UPnP
 * - A: 사이드카(server_runner.py)가 서버를 켜고 "Done" 을 알리면 그 포트로 주소를 연다.
 * - B: 인스턴스 latest.log 에서 LAN 공개 포트를 감지하면 열고, 월드에서 나가거나 게임을 끄면 닫는다.
 *      e4mc 가 들어 있으면 e4mc 가 로그에 찍은 도메인을 쓴다.
 * - C: 열기 전에 Server List Ping 으로 확인. 응답이 없으면 열지 않는다. 열린 뒤 3번 연속 응답이 없으면 닫는다.
 * Theia 에 의존하지 않게 사이드카는 SidecarLike 로 받는다(시험에서 흉내 내기 쉽게).
 */
import { EventEmitter } from 'events';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import {
    AddressView, ClientMod, CreateServerOptions, E4mcPrepare, FirewallStatus, HostSnapshot, ModCheck, ModIssue, PingResult,
    ProviderId, ServerError, ServerKind, ServerState, ServerView, UpnpSettings,
} from '../common/index.js';
import { LanWatcher } from './lan-watcher.js';
import { LanDiscovery } from './lan-discovery.js';
import { ping as slpPing } from './slp.js';
import { UpnpFailure, UpnpManager } from './upnp.js';

export interface SidecarLike {
    readonly dataDir: string;
    call<T>(method: string, params?: object): Promise<T>;
    onNotification(cb: (n: { method: string; params: unknown }) => void): { dispose(): void };
}

interface InstanceMeta { id: string; name: string; version: string; loader: string; path: string }

interface StoredServer {
    id: string;
    kind: ServerKind;
    name: string;
    instanceId?: string;
    serverId?: string;
    port?: number;
    onlineMode?: boolean;
    world?: string | null;
    preference: 'auto' | ProviderId;
    /** 전용 서버 종류(Paper 면 Minekube Connect) */
    software?: 'paper';
    /** 전용 서버 최대 메모리(MB). 없으면 사이드카 기본값(보통 2GB) */
    memoryMb?: number;
}

interface Runtime {
    state: ServerState;
    message?: string;
    eulaUrl?: string;
    gamePort?: number;
    players: string[];
    ping?: PingResult;
    pingFails: number;
    address: AddressView;
    console: string[];
    watcher?: LanWatcher;
    meta?: InstanceMeta;
    e4mcEnabled?: boolean;
    clientMods: ClientMod[];
    opening?: Promise<void>;
    errors: ServerError[];
    firewall?: FirewallStatus;
    /** 전용 서버의 주소 모드가 로그로 알려 준 주소(이번 실행) */
    modAddress?: { provider: ProviderId; address: string };
}

/** 같은 공유기 안에서 쓸 이 PC 의 사설 IPv4(와이파이·유선). 가상 어댑터(VirtualBox·WSL 등 흔한 이름)는 뒤로. */
export function lanIp(): string | undefined {
    const cands: Array<{ ip: string; virt: boolean }> = [];
    for (const [name, list] of Object.entries(os.networkInterfaces())) {
        for (const a of list ?? []) {
            if (a.family === 'IPv4' && !a.internal && /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(a.address)) {
                cands.push({ ip: a.address, virt: /virtual|vbox|vmware|wsl|hyper-v|vethernet|docker|tailscale|zerotier|hamachi/i.test(name) });
            }
        }
    }
    cands.sort((a, b) => Number(a.virt) - Number(b.virt));
    return cands[0]?.ip;
}

function errorText(e: ServerError): string {
    return `[${e.code}] ${e.title} — ${e.hint}`;
}

const CONSOLE_MAX = 500;
/** 전용 서버의 'e4mc' 자리는 "서버에 넣은 주소 모드"(Paper 면 Minekube Connect)다 */
const CHAINS: Record<ServerKind, ProviderId[]> = { lan: ['e4mc', 'upnp'], dedicated: ['e4mc', 'upnp'], external: ['upnp'] };
const NOTE = {
    relay: '중계라 핑이 조금 오를 수 있습니다.',
    carrier: '일부 통신사·학교·회사 망에서는 막힐 수 있습니다.',
    lan: '호스트가 게임을 켜 둔 동안만 유지됩니다. 정품 인증은 호스트 계정 기준입니다.',
    changing: '주소가 매번 바뀝니다 — 열 때마다 새 주소를 보내 주세요.',
    upnpNoDdns: '공인 IP 가 바뀌면 주소도 바뀝니다(DDNS 를 설정하면 고정).',
    fixed: '고정 주소입니다 — 한 번 알려 주면 계속 같은 주소로 들어옵니다.',
    modServer: '서버에 넣은 e4mc 가 연 주소입니다. 참가자는 e4mc 가 필요 없습니다(서버와 같은 콘텐츠 모드만).',
    minekube: 'Minekube Connect 주소입니다(무료). 서버를 다시 켜도 같은 주소입니다.',
};
/** 주소 모드가 주소를 알려 주기를 기다리는 시간(e4mc 는 Done 뒤 몇 초) */
const MOD_ADDRESS_TIMEOUT = 45_000;

export interface ManagerOptions {
    upnp?: UpnpManager;
    lan?: LanDiscovery;
    ping?: (host: string, port: number) => Promise<PingResult>;
    lanInterval?: number;
    /** e4mc 도메인을 기다리는 시간 */
    e4mcTimeoutMs?: number;
    pollMs?: number;
}

/** 이벤트: 'snapshot'(HostSnapshot), 'console'(serverId, line) */
export class HostManager extends EventEmitter {
    protected servers = new Map<string, StoredServer>();
    protected rt = new Map<string, Runtime>();
    protected dir: string;
    protected settings: { ddnsUrl?: string; ddnsDomain?: string; ddnsToken?: string } = {};
    protected sub: { dispose(): void };
    protected poller: NodeJS.Timeout | undefined;
    readonly upnp: UpnpManager | undefined;
    readonly lan: LanDiscovery | undefined;
    protected pinger: (host: string, port: number) => Promise<PingResult>;

    constructor(protected readonly sidecar: SidecarLike, protected readonly opts: ManagerOptions = {}) {
        super();
        this.dir = path.join(sidecar.dataDir, 'server-host');
        this.upnp = opts.upnp;
        this.lan = opts.lan;
        this.pinger = opts.ping ?? ((h, p) => slpPing(h, p));
        this.load();
        this.sub = sidecar.onNotification(n => this.onSidecar(n.method, n.params as Record<string, unknown>));
        this.upnp?.on('ip', (ip: string, prev?: string) => this.onIpChange(ip, prev));
        this.upnp?.on('ddns', (_ok: boolean, msg: string) => this.logAll('upnp', msg));
        this.upnp?.on('renew-failed', (port: number, why: string) => this.logAll('upnp', `UPnP 갱신 실패(포트 ${port}): ${why}`));
        this.lan?.on('change', () => this.changed());
        this.lan?.start();
        this.poller = setInterval(() => this.poll().catch(() => undefined), opts.pollMs ?? 10_000);
    }

    // ---------------------------------------------------------------- 저장
    protected load(): void {
        try {
            for (const s of JSON.parse(fs.readFileSync(path.join(this.dir, 'servers.json'), 'utf8')) as StoredServer[]) {
                const pref = ['auto', 'e4mc', 'upnp', 'minekube'].includes(s.preference) ? s.preference : 'auto';   // 예전 'playit' → 자동
                delete (s as { playitTunnelId?: string }).playitTunnelId;
                this.servers.set(s.id, { ...s, preference: pref });
                this.rt.set(s.id, this.freshRuntime());
            }
        } catch {
            // 처음
        }
        try {
            this.settings = JSON.parse(fs.readFileSync(path.join(this.dir, 'ddns.json'), 'utf8'));
        } catch {
            this.settings = {};
        }
    }

    protected save(): void {
        fs.mkdirSync(this.dir, { recursive: true });
        fs.writeFileSync(path.join(this.dir, 'servers.json'), JSON.stringify([...this.servers.values()], undefined, 2));
    }

    protected freshRuntime(): Runtime {
        return { state: 'stopped', players: [], pingFails: 0, console: [], clientMods: [], errors: [], address: { state: 'closed', attempts: [], notes: [] } };
    }

    ddns(): { url: string; domain?: string; token?: string } | undefined {
        return this.settings.ddnsUrl ? { url: this.settings.ddnsUrl, domain: this.settings.ddnsDomain, token: this.settings.ddnsToken } : undefined;
    }

    setUpnpSettings(s: { ddnsUrl?: string; ddnsDomain?: string; ddnsToken?: string }): UpnpSettings {
        if (s.ddnsUrl !== undefined && s.ddnsUrl && !/^https:\/\//i.test(s.ddnsUrl)) {
            throw new Error('DDNS 갱신 주소는 https:// 로 시작해야 합니다(토큰 보호).');
        }
        this.settings = {
            ddnsUrl: s.ddnsUrl ?? this.settings.ddnsUrl, ddnsDomain: s.ddnsDomain ?? this.settings.ddnsDomain,
            ddnsToken: s.ddnsToken ? s.ddnsToken : this.settings.ddnsToken,
        };
        if (!this.settings.ddnsUrl) {
            this.settings = {};
        }
        fs.mkdirSync(this.dir, { recursive: true });
        fs.writeFileSync(path.join(this.dir, 'ddns.json'), JSON.stringify(this.settings, undefined, 2), { mode: 0o600 });
        this.changed();
        return this.upnpSettings();
    }

    protected upnpSettings(): UpnpSettings {
        return { ddnsUrl: this.settings.ddnsUrl, ddnsDomain: this.settings.ddnsDomain, hasToken: !!this.settings.ddnsToken };
    }

    // ---------------------------------------------------------------- 보기
    protected view(s: StoredServer): ServerView {
        const r = this.rt.get(s.id)!;
        return {
            id: s.id, kind: s.kind, name: s.name, instanceId: s.instanceId, instanceName: r.meta?.name,
            version: r.meta?.version ?? r.ping?.version, loader: r.meta?.loader, serverId: s.serverId, onlineMode: s.onlineMode,
            world: s.world, gamePort: r.gamePort ?? s.port, state: r.state, message: r.message, eulaUrl: r.eulaUrl,
            players: r.players.length ? r.players : (r.ping?.players ?? []), playersOnline: r.ping?.online ?? (r.players.length || undefined),
            maxPlayers: r.ping?.max, motd: r.ping?.motd, serverVersion: r.ping?.version,
            address: { ...r.address, attempts: [...r.address.attempts], notes: [...r.address.notes] },
            clientMods: r.clientMods, preference: s.preference, memoryMb: s.memoryMb,
            errors: [...r.errors], firewall: r.firewall,
            lanAddress: (() => {
                const port = r.gamePort ?? s.port;
                const ip = port ? lanIp() : undefined;
                return ip && port ? (port === 25565 ? ip : `${ip}:${port}`) : undefined;
            })(),
        };
    }

    snapshot(): HostSnapshot {
        return {
            servers: [...this.servers.values()].map(s => this.view(s)),
            lanGames: this.lan?.list() ?? [],
            upnp: { ...this.upnpSettings(), publicIp: this.upnp?.publicIp },
        };
    }

    protected changed(): void {
        this.emit('snapshot', this.snapshot());
    }

    console(id: string): string[] {
        return [...(this.rt.get(id)?.console ?? [])];
    }

    protected log(id: string, line: string): void {
        const r = this.rt.get(id);
        if (!r) {
            return;
        }
        r.console.push(line);
        if (r.console.length > CONSOLE_MAX) {
            r.console.splice(0, r.console.length - CONSOLE_MAX);
        }
        this.emit('console', id, line);
    }

    protected logAll(provider: ProviderId, line: string): void {
        for (const [id, r] of this.rt) {
            if (r.address.provider === provider && r.address.state === 'open') {
                this.log(id, `[통합 작업실] ${line}`);
            }
        }
    }

    protected get(id: string): StoredServer {
        const s = this.servers.get(id);
        if (!s) {
            throw new Error('서버를 찾을 수 없습니다.');
        }
        return s;
    }

    protected async instance(id: string): Promise<InstanceMeta> {
        return this.sidecar.call<InstanceMeta>('get_instance', { id });
    }

    // ---------------------------------------------------------------- 만들기·지우기
    async createServer(o: CreateServerOptions): Promise<ServerView> {
        const id = 'srv-' + crypto.randomBytes(4).toString('hex');
        const s: StoredServer = { id, kind: o.kind, name: '', preference: o.preference ?? 'auto' };
        const r = this.freshRuntime();
        if (o.kind === 'external') {
            const port = Number(o.port ?? 25565);
            if (!(port > 0 && port < 65536)) {
                throw new Error('포트 번호가 올바르지 않습니다(1~65535).');
            }
            s.port = port;
            s.name = (o.name || '').trim() || `이 PC 의 서버 (포트 ${port})`;
        } else {
            if (!o.instanceId) {
                throw new Error('인스턴스를 고르세요.');
            }
            const meta = await this.instance(o.instanceId);
            r.meta = meta;
            s.instanceId = o.instanceId;
            s.name = ((o.name || '').trim() || `${meta.name} 서버`).slice(0, 60);
            if (o.kind === 'dedicated') {
                const d = await this.sidecar.call<{ id: string }>('ds_create', {
                    id: o.instanceId, name: s.name, online_mode: o.onlineMode ?? true, world: o.world || null,
                    software: o.software ?? null,
                });
                s.serverId = d.id;
                if (o.software === 'paper') {
                    s.software = 'paper';
                }
                s.onlineMode = o.onlineMode ?? true;
                s.world = o.world || null;
            }
        }
        s.name = s.name.slice(0, 60);
        this.servers.set(id, s);
        this.rt.set(id, r);
        this.save();
        this.changed();
        return this.view(s);
    }

    async deleteServer(id: string): Promise<void> {
        const s = this.get(id);
        await this.stopServer(id);
        if (s.kind === 'dedicated' && s.serverId && s.instanceId) {
            await this.sidecar.call('ds_delete', { id: s.instanceId, sid: s.serverId }).catch(() => undefined);
        }
        this.servers.delete(id);
        this.rt.delete(id);
        this.save();
        this.changed();
    }

    async setPreference(id: string, pref: 'auto' | ProviderId): Promise<ServerView> {
        const s = this.get(id);
        if ((pref === 'e4mc' || pref === 'minekube') && s.kind === 'external') {
            throw new Error('외부 서버는 UPnP 로만 엽니다(이 앱이 켠 서버가 아니라 모드를 넣을 수 없음).');
        }
        s.preference = pref;
        this.save();
        this.changed();
        return this.view(s);
    }

    /** 전용 서버 최대 메모리(다음 시작부터). null = 기본값 */
    async setServerMemory(id: string, memoryMb: number | null): Promise<ServerView> {
        const s = this.get(id);
        if (s.kind !== 'dedicated' || !s.serverId) {
            throw new Error('메모리는 전용 서버에서만 정합니다.');
        }
        await this.sidecar.call('ds_update', { id: s.instanceId, sid: s.serverId, memory_mb: memoryMb ?? 0 });
        s.memoryMb = memoryMb ?? undefined;
        this.save();
        this.changed();
        return this.view(s);
    }

    // ---------------------------------------------------------------- 시작·중지
    async startServer(id: string): Promise<ServerView> {
        const s = this.get(id);
        const r = this.rt.get(id)!;
        r.message = undefined;
        if (s.instanceId) {
            r.meta = await this.instance(s.instanceId);
        }
        if (s.kind === 'external') {
            await this.openAddress(id);
            return this.view(s);
        }
        if (s.kind === 'dedicated') {
            r.state = 'preparing';
            r.errors = [];
            r.modAddress = undefined;
            this.changed();
            try {
                const res = await this.sidecar.call<{ needsEula?: boolean; eulaUrl?: string; port?: number }>(
                    'ds_start', { id: s.instanceId, sid: s.serverId });
                if (res.needsEula) {
                    r.state = 'needs-eula';
                    r.eulaUrl = res.eulaUrl;
                } else {
                    r.state = 'starting';
                    r.gamePort = res.port;
                }
            } catch (e) {
                r.state = 'error';
                const msg = (e as Error).message;
                const code = /^\[([A-Z]+-[\w]+)\]\s*/.exec(msg);
                r.message = `서버를 시작하지 못했습니다: ${msg}`;
                if (code) {
                    r.errors = [{ code: code[1], title: '서버를 시작하지 못했습니다', hint: msg.slice(code[0].length) }];
                }
            }
            this.refreshMods(id).catch(() => undefined);
        } else {
            r.watcher?.stop();
            const st = await this.sidecar.call<{ enabled: boolean }>('e4mc_status', { id: s.instanceId }).catch(() => ({ enabled: false }));
            r.e4mcEnabled = st.enabled;
            const w = new LanWatcher(path.join(r.meta!.path, 'logs', 'latest.log'), this.opts.lanInterval ?? 500);
            r.watcher = w;
            r.state = 'waiting-lan';
            r.message = '게임에서 월드를 열고 [ESC] → [LAN에 공개]를 누르세요. 감지되면 자동으로 주소를 엽니다.';
            w.on('open', (port: number) => {
                r.state = 'running';
                r.gamePort = port;
                r.message = undefined;
                this.log(id, `[통합 작업실] LAN 공개 감지: 포트 ${port}`);
                this.refreshMods(id).catch(() => undefined);
                this.openAddress(id).catch(e => this.fail(id, e));
            });
            w.on('domain', (domain: string) => this.log(id, `[통합 작업실] e4mc 도메인: ${domain}`));
            w.on('close', (reason: string) => {
                this.closeAddress(id, `${reason} — 주소를 닫았습니다. 다시 LAN에 공개하면 자동으로 엽니다.`).catch(() => undefined);
                const rr = this.rt.get(id);
                if (rr && rr.watcher) {
                    rr.state = 'waiting-lan';
                    rr.gamePort = undefined;
                }
                this.changed();
            });
            w.on('game-stopped', () => this.afterGameStopped(id).catch(() => undefined));
            w.start();
        }
        this.changed();
        return this.view(s);
    }

    /** 게임이 꺼진 뒤: e4mc 크래시 점검(문제면 다음 실행부터 e4mc 끄고 다음 방식) + '이번만 끈' 모드 되살리기. */
    protected async afterGameStopped(id: string): Promise<void> {
        const s = this.servers.get(id);
        if (!s?.instanceId) {
            return;
        }
        const r = this.rt.get(id)!;
        if (r.e4mcEnabled) {
            const c = await this.sidecar.call<{ e4mcProblem: boolean; reason?: string }>('e4mc_check_crash', { id: s.instanceId });
            if (c.e4mcProblem) {
                r.e4mcEnabled = false;
                r.message = c.reason;
                this.log(id, `[통합 작업실] ${c.reason}`);
            }
        }
        const back = await this.sidecar.call<string[]>('e4mc_restore_once', { id: s.instanceId }).catch(() => []);
        if (back.length) {
            this.log(id, `[통합 작업실] 이번만 꺼 둔 모드를 되살렸습니다: ${back.join(', ')}`);
        }
        this.changed();
    }

    async stopServer(id: string): Promise<ServerView> {
        const s = this.get(id);
        const r = this.rt.get(id)!;
        r.watcher?.stop();
        r.watcher = undefined;
        await this.closeAddress(id);
        if (s.kind === 'dedicated' && s.serverId) {
            await this.sidecar.call('ds_stop', { id: s.instanceId, sid: s.serverId }).catch(() => undefined);
        }
        r.state = 'stopped';
        r.players = [];
        r.ping = undefined;
        r.message = undefined;
        if (s.kind !== 'external') {
            r.gamePort = undefined;
        }
        this.changed();
        return this.view(s);
    }

    async acceptEula(id: string): Promise<ServerView> {
        const s = this.get(id);
        await this.sidecar.call('ds_accept_eula', { id: s.instanceId, sid: s.serverId });
        return this.startServer(id);
    }

    async command(id: string, command: string): Promise<void> {
        const s = this.get(id);
        if (s.kind !== 'dedicated') {
            throw new Error('콘솔은 전용 서버에서만 씁니다.');
        }
        await this.sidecar.call('ds_command', { id: s.instanceId, sid: s.serverId, command });
    }

    protected async refreshMods(id: string): Promise<void> {
        const s = this.get(id);
        if (!s.instanceId) {
            return;
        }
        const r = await this.sidecar.call<{ clientRequired: ClientMod[] }>('host_mods', { id: s.instanceId, sid: s.serverId ?? null });
        this.rt.get(id)!.clientMods = r.clientRequired ?? [];
        this.changed();
    }

    protected fail(id: string, e: unknown): void {
        const r = this.rt.get(id);
        if (r) {
            r.message = (e as Error).message;
            this.changed();
        }
    }

    // ---------------------------------------------------------------- e4mc 준비
    async prepareE4mc(id: string, choice: string): Promise<E4mcPrepare> {
        const s = this.get(id);
        if (s.kind !== 'lan' || !s.instanceId) {
            throw new Error('e4mc 는 싱글 LAN 공개에서만 씁니다.');
        }
        if (choice === 'skip') {
            await this.setPreference(id, 'upnp');
            return { ok: false, fallback: true, reason: '사용자가 e4mc 대신 UPnP 를 골랐습니다.' };
        }
        const res = await this.sidecar.call<E4mcPrepare>('e4mc_install', { id: s.instanceId, conflict_choice: choice });
        const r = this.rt.get(id)!;
        if (res.ok) {
            r.e4mcEnabled = true;
            this.log(id, `[통합 작업실] e4mc 준비 완료${res.installed?.length ? `: ${res.installed.join(', ')}` : '(이미 있음)'}`);
        } else if (res.fallback) {
            r.address.attempts = [{ provider: 'e4mc', ok: false, reason: res.reason }];
            this.log(id, `[통합 작업실] ${res.reason}`);
        }
        this.changed();
        return res;
    }

    // ---------------------------------------------------------------- 주소 열기
    async openAddress(id: string, skip: ProviderId[] = []): Promise<ServerView> {
        const r = this.rt.get(id)!;
        if (r.opening) {
            await r.opening;
            return this.view(this.get(id));
        }
        r.opening = this.doOpen(id, skip).finally(() => { r.opening = undefined; });
        await r.opening;
        return this.view(this.get(id));
    }

    protected async doOpen(id: string, skip: ProviderId[] = []): Promise<void> {
        const s = this.get(id);
        const r = this.rt.get(id)!;
        const port = s.kind === 'external' ? s.port! : r.gamePort;
        if (!port) {
            throw new Error(s.kind === 'lan' ? '아직 LAN 에 공개되지 않았습니다.' : '서버가 아직 켜지지 않았습니다.');
        }
        if (r.address.state === 'open') {
            return;
        }
        const keepE4mc = r.address.attempts.filter(a => a.provider === 'e4mc' && !a.ok);
        r.address = { state: 'opening', attempts: keepE4mc, notes: [] };
        this.changed();
        // 상태 조회: 정말 마인크래프트 서버가 듣고 있는지
        const p = await this.pinger('127.0.0.1', port);
        r.ping = p.ok ? p : undefined;
        if (!p.ok) {
            if (s.kind === 'external') {
                r.address = { state: 'failed', attempts: [], notes: [] };
                r.state = 'error';
                r.message = `포트 ${port} 에서 마인크래프트 서버가 응답하지 않아 주소를 열지 않았습니다(${p.error}). 서버를 켠 뒤 다시 여세요.`;
                this.changed();
                return;
            }
            this.log(id, `[통합 작업실] 상태 조회 응답 없음(${p.error}) — 그래도 주소를 엽니다.`);
        } else if (s.kind === 'external') {
            r.state = 'running';
            r.message = undefined;
        }
        const base = CHAINS[s.kind];
        const pref = s.preference === 'minekube' ? 'e4mc' : s.preference;      // 전용 서버의 'e4mc' 자리 = 주소 모드
        const chain = pref === 'auto' || !base.includes(pref) ? base : [pref, ...base.filter(x => x !== pref)];
        for (const provider of chain) {
            if (provider === 'e4mc' && keepE4mc.length) {
                continue;   // 준비 단계에서 이미 실패(이유는 남겨 둠)
            }
            if (skip.includes(provider)) {
                r.address.attempts.push({ provider, ok: false, reason: '친구가 이 방식으로 들어오지 못해 건너뜀' });
                continue;
            }
            r.address.trying = provider;
            this.changed();
            try {
                const res = await this.tryProvider(s, r, provider, port);
                const used = res.provider ?? provider;
                r.address = { state: 'open', provider: used, address: res.address, fixed: res.fixed, relay: used !== 'upnp',
                    attempts: [...r.address.attempts, { provider: used, ok: true }], notes: res.notes };
                this.log(id, `[통합 작업실] 주소 열림(${used}): ${res.address}`);
                this.changed();
                if (used === 'upnp') {
                    this.checkFirewall(id).catch(() => undefined);   // 직접 들어오는 방식은 방화벽이 막으면 소용없다
                }
                return;
            } catch (e) {
                const reason = (e as Error).message;
                r.address.attempts.push({ provider, ok: false, reason });
                this.log(id, `[통합 작업실] ${provider} 실패 → 다음 방식: ${reason}`);
                this.changed();
            }
        }
        r.address.state = 'failed';
        r.address.trying = undefined;
        r.message = '모든 방식이 실패해 주소를 열지 못했습니다. 아래 이유를 확인해 주세요.';
        this.changed();
    }

    protected async tryProvider(s: StoredServer, r: Runtime, provider: ProviderId, port: number):
        Promise<{ address: string; fixed: boolean; notes: string[]; provider?: ProviderId }> {
        const lanNote = s.kind === 'lan' ? [NOTE.lan] : [];
        if (provider !== 'upnp' && s.kind === 'dedicated') {
            // 전용 서버: 사이드카가 서버에 넣은 e4mc(Paper 면 Minekube Connect)가 로그로 알려 준 주소
            const got = await this.waitModAddress(r, this.opts.e4mcTimeoutMs ?? MOD_ADDRESS_TIMEOUT);
            if (!got) {
                const what = s.software === 'paper' ? 'Minekube Connect' : 'e4mc';
                throw new Error(`${what} 가 주소를 알려 주지 않았습니다(${Math.round((this.opts.e4mcTimeoutMs ?? MOD_ADDRESS_TIMEOUT) / 1000)}초). `
                    + '서버 콘솔에서 오류를 확인하세요 — 인터넷이 막혔거나 그 게임 버전용 파일이 없을 수 있습니다.');
            }
            return got.provider === 'minekube'
                ? { address: got.address, fixed: true, notes: [NOTE.minekube, NOTE.relay], provider: 'minekube' }
                : { address: got.address, fixed: false, notes: [NOTE.modServer, NOTE.relay, NOTE.changing], provider: 'e4mc' };
        }
        if (provider === 'e4mc' || provider === 'minekube') {
            if (!r.e4mcEnabled) {
                throw new Error('이 실행에는 e4mc 가 들어 있지 않습니다(설치한 뒤 게임을 다시 켜야 적용).');
            }
            const domain = await this.waitDomain(r, this.opts.e4mcTimeoutMs ?? 20_000);
            if (!domain) {
                throw new Error('e4mc 가 공개 도메인을 알려 주지 않았습니다(20초). 네트워크가 막혔거나 e4mc 가 동작하지 않습니다.');
            }
            return { address: domain, fixed: false, notes: [NOTE.relay, NOTE.changing, ...lanNote] };
        }
        if (provider === 'upnp') {
            if (!this.upnp) {
                throw new Error('UPnP 를 쓸 수 없습니다.');
            }
            try {
                const m = await this.upnp.open(port, s.name);
                const fixed = !!m.ddns;
                return { address: m.address, fixed, notes: [fixed ? NOTE.fixed : NOTE.upnpNoDdns, ...lanNote] };
            } catch (e) {
                throw new Error(e instanceof UpnpFailure ? e.message : `UPnP 실패: ${(e as Error).message}`);
            }
        }
        throw new Error(`알 수 없는 방식: ${provider}`);
    }

    /** 전용 서버의 주소 모드가 주소를 알려 줄 때까지 기다린다(이미 알면 바로). 서버가 꺼지면 그만. */
    protected async waitModAddress(r: Runtime, timeout: number): Promise<{ provider: ProviderId; address: string } | undefined> {
        const end = Date.now() + timeout;
        while (!r.modAddress && Date.now() < end && !['stopped', 'error'].includes(r.state)) {
            await new Promise(res => setTimeout(res, 200));
        }
        return r.modAddress;
    }

    protected waitDomain(r: Runtime, timeout: number): Promise<string | undefined> {
        const w = r.watcher;
        if (!w) {
            return Promise.resolve(undefined);
        }
        if (w.e4mcDomain) {
            return Promise.resolve(w.e4mcDomain);
        }
        return new Promise(resolve => {
            const onDomain = (d: string): void => { cleanup(); resolve(d); };
            const onClose = (): void => { cleanup(); resolve(undefined); };
            const timer = setTimeout(() => { cleanup(); resolve(undefined); }, timeout);
            const cleanup = (): void => {
                clearTimeout(timer);
                w.off('domain', onDomain);
                w.off('close', onClose);
            };
            w.on('domain', onDomain);
            w.on('close', onClose);
        });
    }

    async closeAddress(id: string, message?: string): Promise<ServerView> {
        const s = this.get(id);
        const r = this.rt.get(id)!;
        const a = r.address;
        const port = s.kind === 'external' ? s.port : r.gamePort;
        if (a.state === 'open') {
            if (a.provider === 'upnp' && port) {
                await this.upnp?.close(port);
            } else if (a.provider === 'e4mc' || a.provider === 'minekube') {
                this.log(id, s.kind === 'dedicated'
                    ? '[통합 작업실] 서버에 넣은 주소 모드의 주소는 서버를 끄면 닫힙니다.'
                    : '[통합 작업실] e4mc 주소는 LAN 공개를 끝내거나 게임을 끄면 닫힙니다.');
            }
            this.log(id, `[통합 작업실] 주소를 닫았습니다${message ? `: ${message}` : ''}`);
        }
        r.address = { state: 'closed', attempts: [], notes: [] };
        if (message) {
            r.message = message;
        }
        if (s.kind === 'external') {
            r.state = 'stopped';
            r.ping = undefined;
        }
        this.changed();
        return this.view(s);
    }

    /** 친구가 못 들어올 때: 지금 방식(과 이미 건너뛴 방식)을 빼고 다음 방식으로 다시 연다. */
    async nextProvider(id: string): Promise<ServerView> {
        const r = this.rt.get(id)!;
        const skip = [...new Set([...r.address.attempts.filter(a => !a.ok).map(a => a.provider),
            ...(r.address.provider ? [r.address.provider] : [])])];
        const s = this.get(id);
        const chain = CHAINS[s.kind];
        if (chain.every(p => skip.includes(p))) {
            skip.length = 0;           // 다 해 봤으면 처음부터
        }
        await this.closeAddress(id);
        this.log(id, `[통합 작업실] 다른 방식으로 다시 엽니다(건너뜀: ${skip.join(', ') || '없음'})`);
        return this.openAddress(id, skip);
    }

    protected port(id: string): number | undefined {
        const s = this.get(id);
        return s.kind === 'external' ? s.port : this.rt.get(id)!.gamePort;
    }

    async checkFirewall(id: string): Promise<FirewallStatus> {
        const port = this.port(id);
        if (!port) {
            throw new Error('서버가 켜져 있을 때 확인할 수 있습니다.');
        }
        const st = await this.sidecar.call<FirewallStatus>('firewall_check', { port });
        const r = this.rt.get(id)!;
        r.firewall = st;
        if (!st.ok && !st.unknown) {
            this.log(id, `[통합 작업실] ${st.message}`);
        }
        this.changed();
        return st;
    }

    async allowFirewall(id: string): Promise<FirewallStatus> {
        const port = this.port(id);
        if (!port) {
            throw new Error('서버를 켠 뒤 눌러 주세요(어느 프로그램인지 알아야 합니다).');
        }
        const st = await this.sidecar.call<FirewallStatus>('firewall_allow', { port });
        this.rt.get(id)!.firewall = st;
        this.changed();
        return st;
    }

    protected dedicated(id: string): StoredServer {
        const s = this.get(id);
        if (s.kind !== 'dedicated' || !s.serverId || !s.instanceId) {
            throw new Error('전용 서버에서만 됩니다.');
        }
        return s;
    }

    async modCheck(id: string): Promise<ModCheck> {
        const s = this.dedicated(id);
        return this.sidecar.call<ModCheck>('ds_mod_check', { id: s.instanceId, sid: s.serverId });
    }

    async modFix(id: string, items: ModIssue[]): Promise<{ done: number; failed: Array<ModIssue & { error: string }>; check: ModCheck }> {
        const s = this.dedicated(id);
        const res = await this.sidecar.call<{ done: number; failed: Array<ModIssue & { error: string }>; check: ModCheck }>(
            'ds_mod_fix', { id: s.instanceId, sid: s.serverId, items });
        this.log(id, `[통합 작업실] 모드 맞추기: ${res.done}개 처리${res.failed.length ? `, ${res.failed.length}개 실패` : ''}`);
        this.refreshMods(id).catch(() => undefined);
        return res;
    }

    async openFolder(id: string): Promise<string> {
        const s = this.dedicated(id);
        const r = await this.sidecar.call<{ path: string }>('ds_open_folder', { id: s.instanceId, sid: s.serverId });
        return r.path;
    }

    async ping(port: number): Promise<PingResult> {
        return this.pinger('127.0.0.1', port);
    }

    // ---------------------------------------------------------------- 주기 점검
    async poll(): Promise<void> {
        let changed = false;
        for (const [id, s] of this.servers) {
            const r = this.rt.get(id)!;
            const port = s.kind === 'external' ? s.port : r.gamePort;
            if (!port || !(r.state === 'running' || r.address.state === 'open')) {
                continue;
            }
            const p = await this.pinger('127.0.0.1', port);
            if (p.ok) {
                r.ping = p;
                r.pingFails = 0;
                changed = true;
            } else if (s.kind === 'external' && ++r.pingFails >= 3) {
                r.pingFails = 0;
                await this.closeAddress(id, `포트 ${port} 의 서버가 응답하지 않아 주소를 닫았습니다(서버가 꺼졌을 수 있음).`);
                r.state = 'stopped';
                changed = true;
            }
        }
        if (changed) {
            this.changed();
        }
    }

    protected onIpChange(ip: string, prev?: string): void {
        for (const [id, r] of this.rt) {
            if (r.address.state === 'open' && r.address.provider === 'upnp' && !this.settings.ddnsUrl && r.address.address) {
                const port = r.address.address.includes(':') ? r.address.address.split(':')[1] : undefined;
                r.address.address = port ? `${ip}:${port}` : ip;
                this.log(id, `[통합 작업실] 공인 IP 가 바뀌었습니다(${prev ?? '?'} → ${ip}). 새 주소: ${r.address.address}`);
            }
        }
        this.changed();
    }

    // ---------------------------------------------------------------- 사이드카 알림(전용 서버)
    protected byServerId(sid: unknown): [string, StoredServer] | undefined {
        return [...this.servers.entries()].find(([, s]) => s.serverId === sid);
    }

    protected onSidecar(method: string, p: Record<string, unknown>): void {
        if (method === 'ds_log') {
            const hit = this.byServerId(p.id);
            if (hit) {
                this.log(hit[0], String(p.line ?? ''));
            }
        } else if (method === 'ds_state') {
            const hit = this.byServerId(p.id);
            if (!hit) {
                return;
            }
            const [id] = hit;
            const r = this.rt.get(id)!;
            if (p.state === 'ready') {
                r.state = 'running';
                r.gamePort = Number(p.port);
                this.changed();
                this.openAddress(id).catch(e => this.fail(id, e));
            } else if (p.state === 'stopped') {
                this.closeAddress(id).catch(() => undefined);
                r.state = 'stopped';
                r.players = [];
                r.ping = undefined;
                r.modAddress = undefined;
                const errs = (p.errors as ServerError[] | undefined) ?? [];
                for (const e of errs) {
                    if (!r.errors.some(x => x.code === e.code)) {
                        r.errors.push(e);
                    }
                }
                if (p.exitCode && p.exitCode !== 0) {
                    r.state = 'error';
                    r.message = r.errors.length
                        ? `서버가 멈췄습니다(종료 코드 ${p.exitCode}): ${errorText(r.errors[0])}`
                        : `서버가 멈췄습니다(종료 코드 ${p.exitCode}). 콘솔을 확인하세요.`;
                }
                this.changed();
            }
        } else if (method === 'ds_address') {
            // 서버에 넣은 e4mc·Minekube Connect 가 로그로 알려 준 주소
            const hit = this.byServerId(p.id);
            if (hit) {
                const [id] = hit;
                const r = this.rt.get(id)!;
                r.modAddress = { provider: p.provider as ProviderId, address: String(p.address) };
                this.log(id, `[통합 작업실] ${p.provider === 'minekube' ? 'Minekube Connect' : 'e4mc'} 주소: ${p.address}`);
                if (r.address.state === 'open' && r.address.provider === 'upnp') {
                    // 늦게 왔으면 UPnP 대신 이 주소로(포트 열기 필요 없음)
                    this.closeAddress(id).then(() => this.openAddress(id)).catch(e => this.fail(id, e));
                }
                this.changed();
            }
        } else if (method === 'ds_error') {
            const hit = this.byServerId(p.id);
            if (hit) {
                const r = this.rt.get(hit[0])!;
                const err = p.error as ServerError;
                if (!r.errors.some(e => e.code === err.code)) {
                    r.errors.push(err);
                }
                this.log(hit[0], `[통합 작업실] 오류 ${errorText(err)}`);
                this.changed();
            }
        } else if (method === 'ds_players') {
            const hit = this.byServerId(p.id);
            if (hit) {
                this.rt.get(hit[0])!.players = (p.players as string[]) ?? [];
                this.changed();
            }
        }
    }

    async dispose(): Promise<void> {
        if (this.poller) {
            clearInterval(this.poller);
        }
        this.sub.dispose();
        this.lan?.stop();
        for (const r of this.rt.values()) {
            r.watcher?.stop();
        }
        await this.upnp?.closeAll();   // 앱을 끌 때 공유기 매핑을 반드시 지운다
    }
}
