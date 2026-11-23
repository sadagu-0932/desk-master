/**
 * M10 백엔드: 호스트(방식 A 전용 서버 / 방식 B 싱글 LAN 공개)와 참가 터널을 관리한다. 여러 개를 동시에.
 *
 * - 방식 A: 사이드카(server_runner.py)가 서버를 켜고 "Done" 을 알리면 그 포트로 P2P 를 연다.
 * - 방식 B: 인스턴스 latest.log 에서 LAN 공개 포트를 감지하면 열고, 월드에서 나가거나 게임을 끄면 닫는다.
 * - 서버마다 키(시드)를 저장해 다시 열어도 같은 코드. "코드 새로 만들기"로 바꿀 수 있다.
 * Theia 에 의존하지 않게 사이드카는 SidecarLike 로 받는다(시험에서 흉내 내기 쉽게).
 */
import { EventEmitter } from 'events';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import DHT from 'hyperdht';
import { CreateHostOptions, HostKind, HostState, HostView, JoinView, P2PSnapshot } from '../common/index.js';
import { HostTunnel, JoinOptions, JoinTunnel, createNode, explain, newSeed, parseRelays } from './p2p-core.js';
import { LanWatcher } from './lan-watcher.js';

export interface SidecarLike {
    readonly dataDir: string;
    call<T>(method: string, params?: object): Promise<T>;
    onNotification(cb: (n: { method: string; params: unknown }) => void): { dispose(): void };
}

interface InstanceMeta { id: string; name: string; version: string; loader: string; path: string }

interface StoredHost {
    id: string;
    instanceId: string;
    kind: HostKind;
    name: string;
    seed: string;
    serverId?: string;
    onlineMode?: boolean;
    world?: string | null;
    maxPlayers?: number;
}

interface HostRuntime {
    state: HostState;
    message?: string;
    eulaUrl?: string;
    gamePort?: number;
    players: string[];
    tunnel?: HostTunnel;
    watcher?: LanWatcher;
    console: string[];
    meta?: InstanceMeta;
}

const CONSOLE_MAX = 500;
const KEY_FORMAT = 'integrated-studio-p2p-key';

interface KeyFile { format: string; version: number; name?: string; kind?: string; code?: string; seed: string; exported?: string }
/** 정보 응답의 max: 전용 서버는 server.properties 기본값(server_runner 가 쓰는 값), LAN 은 게임 기본값 */
const DEDICATED_MAX_PLAYERS = 10;
const LAN_MAX_PLAYERS = 8;

export interface ManagerOptions {
    /** 테스트넷 등. 비우면 환경 변수 INTEGRATED_STUDIO_DHT_BOOTSTRAP, 그것도 없으면 hyperdht 공용 노드. */
    bootstrap?: Array<string | { host: string; port: number }>;
    relays?: Buffer[];
    /** 방식 B 로그 감시 간격(ms) */
    lanInterval?: number;
    /** 참가 터널 기본값(핑 간격·재시도 등, 시험용) */
    joinDefaults?: Partial<JoinOptions>;
}

/** 이벤트: 'snapshot'(P2PSnapshot), 'console'(hostId, line) */
export class P2PManager extends EventEmitter {
    protected node: DHT | undefined;
    protected hosts = new Map<string, StoredHost>();
    protected runtime = new Map<string, HostRuntime>();
    protected joins = new Map<string, { tunnel: JoinTunnel; view: JoinView }>();
    protected joinPorts: Record<string, number> = {};
    protected relays: Buffer[];
    protected ticker: NodeJS.Timeout | undefined;
    protected sub: { dispose(): void };
    protected dir: string;

    constructor(protected readonly sidecar: SidecarLike, protected readonly opts: ManagerOptions = {}) {
        super();
        this.dir = path.join(sidecar.dataDir, 'p2p');
        this.relays = opts.relays ?? this.loadRelays();
        this.load();
        this.sub = sidecar.onNotification(n => this.onSidecar(n.method, n.params as Record<string, unknown>));
        this.ticker = setInterval(() => this.tick(), 2000);
    }

    // ---------- 저장 ----------
    protected load(): void {
        try {
            for (const h of JSON.parse(fs.readFileSync(path.join(this.dir, 'hosts.json'), 'utf8')) as StoredHost[]) {
                this.hosts.set(h.id, h);
                this.runtime.set(h.id, { state: 'stopped', players: [], console: [] });
            }
        } catch {
            // 처음
        }
        try {
            this.joinPorts = JSON.parse(fs.readFileSync(path.join(this.dir, 'join-ports.json'), 'utf8'));
        } catch {
            this.joinPorts = {};
        }
    }

    protected save(): void {
        fs.mkdirSync(this.dir, { recursive: true });
        fs.writeFileSync(path.join(this.dir, 'hosts.json'), JSON.stringify([...this.hosts.values()], undefined, 2));
        fs.writeFileSync(path.join(this.dir, 'join-ports.json'), JSON.stringify(this.joinPorts, undefined, 2));
    }

    protected loadRelays(): Buffer[] {
        let text = process.env.INTEGRATED_STUDIO_P2P_RELAYS ?? '';
        try {
            const s = JSON.parse(fs.readFileSync(path.join(this.dir, 'settings.json'), 'utf8')) as { relays?: string[] };
            text += ',' + (s.relays ?? []).join(',');
        } catch {
            // 설정 없음
        }
        return parseRelays(text);
    }

    protected dht(): DHT {
        if (!this.node) {
            const env = process.env.INTEGRATED_STUDIO_DHT_BOOTSTRAP;
            const bootstrap = this.opts.bootstrap ?? (env ? env.split(',').map(s => s.trim()).filter(Boolean) : undefined);
            // INTEGRATED_STUDIO_DHT_HOST: UDP 를 묶을 주소(시험·문제 해결용)
            this.node = createNode({ bootstrap, host: process.env.INTEGRATED_STUDIO_DHT_HOST || undefined });
        }
        return this.node;
    }

    // ---------- 보기 ----------
    protected hostView(h: StoredHost): HostView {
        const rt = this.runtime.get(h.id)!;
        return {
            id: h.id, instanceId: h.instanceId, instanceName: rt.meta?.name ?? h.instanceId, kind: h.kind, name: h.name,
            code: HostTunnel.codeFor(Buffer.from(h.seed, 'hex')), state: rt.state,
            version: rt.meta?.version ?? '', loader: rt.meta?.loader ?? '',
            serverId: h.serverId, onlineMode: h.onlineMode, world: h.world, gamePort: rt.gamePort,
            players: rt.players, peers: rt.tunnel?.listPeers() ?? [], traffic: { ...(rt.tunnel?.traffic ?? { bytesIn: 0, bytesOut: 0 }) },
            message: rt.message, eulaUrl: rt.eulaUrl,
        };
    }

    snapshot(): P2PSnapshot {
        return {
            hosts: [...this.hosts.values()].map(h => this.hostView(h)),
            joins: [...this.joins.values()].map(j => ({ ...j.view, traffic: { ...j.view.traffic } })),
            relays: this.relays.length,
        };
    }

    protected changed(): void {
        this.emit('snapshot', this.snapshot());
    }

    protected tick(): void {
        // 핑·트래픽이 바뀌므로 무언가 열려 있으면 주기적으로 알린다
        const active = [...this.runtime.values()].some(r => r.tunnel) || [...this.joins.values()].some(j => j.view.state === 'connected');
        if (active) {
            this.changed();
        }
    }

    console(id: string): string[] {
        return [...(this.runtime.get(id)?.console ?? [])];
    }

    protected log(id: string, line: string): void {
        const rt = this.runtime.get(id);
        if (!rt) {
            return;
        }
        rt.console.push(line);
        if (rt.console.length > CONSOLE_MAX) {
            rt.console.splice(0, rt.console.length - CONSOLE_MAX);
        }
        this.emit('console', id, line);
    }

    protected get(id: string): StoredHost {
        const h = this.hosts.get(id);
        if (!h) {
            throw new Error('서버를 찾을 수 없습니다.');
        }
        return h;
    }

    protected async instance(id: string): Promise<InstanceMeta> {
        return this.sidecar.call<InstanceMeta>('get_instance', { id });
    }

    // ---------- 호스트 ----------
    async createHost(o: CreateHostOptions): Promise<HostView> {
        const meta = await this.instance(o.instanceId);
        const id = 'host_' + crypto.randomBytes(4).toString('hex');
        const name = (o.name || '').trim() || `${meta.name} 서버`;
        const h: StoredHost = { id, instanceId: o.instanceId, kind: o.kind, name: name.slice(0, 60), seed: newSeed().toString('hex') };
        if (o.kind === 'dedicated') {
            const s = await this.sidecar.call<{ id: string }>('p2p_server_create', {
                id: o.instanceId, name: h.name, online_mode: o.onlineMode ?? true, world: o.world || null,
            });
            h.serverId = s.id;
            h.onlineMode = o.onlineMode ?? true;
            h.world = o.world || null;
        }
        this.hosts.set(id, h);
        this.runtime.set(id, { state: 'stopped', players: [], console: [], meta });
        this.save();
        this.changed();
        return this.hostView(h);
    }

    async startHost(id: string): Promise<HostView> {
        const h = this.get(id);
        const rt = this.runtime.get(id)!;
        rt.meta = await this.instance(h.instanceId);
        rt.message = undefined;
        if (h.kind === 'dedicated') {
            rt.state = 'preparing';
            this.changed();
            try {
                const r = await this.sidecar.call<{ needsEula?: boolean; eulaUrl?: string; port?: number }>(
                    'p2p_server_start', { id: h.instanceId, sid: h.serverId });
                if (r.needsEula) {
                    rt.state = 'needs-eula';
                    rt.eulaUrl = r.eulaUrl;
                } else {
                    rt.state = 'starting';
                    rt.gamePort = r.port;
                }
            } catch (e) {
                rt.state = 'error';
                rt.message = `서버를 시작하지 못했습니다: ${(e as Error).message}`;
            }
        } else {
            rt.watcher?.stop();
            const w = new LanWatcher(path.join(rt.meta.path, 'logs', 'latest.log'), this.opts.lanInterval ?? 500);
            rt.watcher = w;
            rt.state = 'waiting-lan';
            rt.message = '게임에서 월드를 열고 [ESC] → [LAN에 공개]를 누르세요. 감지되면 자동으로 열립니다.';
            w.on('open', (port: number) => this.openTunnel(id, port).catch(e => this.fail(id, e)));
            w.on('close', (reason: string) => this.closeTunnel(id, `${reason} — P2P 를 닫았습니다. 다시 LAN에 공개하면 자동으로 열립니다.`));
            w.start();
        }
        this.changed();
        return this.hostView(h);
    }

    protected fail(id: string, e: unknown): void {
        const rt = this.runtime.get(id);
        if (rt) {
            rt.state = 'error';
            rt.message = explain(e, this.relays.length > 0).message;
            this.changed();
        }
    }

    protected async openTunnel(id: string, port: number): Promise<void> {
        const h = this.get(id);
        const rt = this.runtime.get(id)!;
        rt.gamePort = port;
        if (rt.tunnel) {
            rt.tunnel.setTarget(port);
        } else {
            const tunnel = new HostTunnel(this.dht(), {
                seed: Buffer.from(h.seed, 'hex'), target: { host: '127.0.0.1', port },
                // 접속자 수: 전용 서버는 서버 로그의 접속자, LAN 은 게임 터널이 열린 참가자 수
                info: () => ({
                    name: h.name, version: rt.meta?.version ?? '', loader: rt.meta?.loader ?? '', mode: h.kind,
                    max: h.kind === 'lan' ? LAN_MAX_PLAYERS : (h.maxPlayers ?? DEDICATED_MAX_PLAYERS),
                    players: h.kind === 'dedicated' ? rt.players.length : undefined,
                }),
            });
            tunnel.on('peers', () => this.changed());
            rt.tunnel = tunnel;
            await tunnel.start();
        }
        rt.state = 'open';
        rt.message = h.kind === 'lan'
            ? '호스트가 게임을 켜 둔 동안만 유지됩니다. 정품 인증은 호스트 계정 기준입니다.'
            : undefined;
        this.log(id, `[통합 작업실] P2P 열림 — 참가 코드: ${rt.tunnel.code}`);
        this.changed();
    }

    protected async closeTunnel(id: string, message?: string): Promise<void> {
        const rt = this.runtime.get(id);
        if (!rt) {
            return;
        }
        const t = rt.tunnel;
        rt.tunnel = undefined;
        await t?.stop();
        const h = this.hosts.get(id);
        rt.state = h?.kind === 'lan' && rt.watcher ? 'waiting-lan' : 'stopped';
        rt.message = message;
        if (h?.kind === 'lan') {
            rt.gamePort = undefined;
        }
        this.changed();
    }

    async stopHost(id: string): Promise<HostView> {
        const h = this.get(id);
        const rt = this.runtime.get(id)!;
        rt.watcher?.stop();
        rt.watcher = undefined;
        await this.closeTunnel(id);
        if (h.kind === 'dedicated' && h.serverId) {
            await this.sidecar.call('p2p_server_stop', { id: h.instanceId, sid: h.serverId }).catch(() => undefined);
        }
        rt.state = 'stopped';
        rt.players = [];
        rt.message = undefined;
        this.changed();
        return this.hostView(h);
    }

    async deleteHost(id: string): Promise<void> {
        const h = this.get(id);
        await this.stopHost(id);
        if (h.kind === 'dedicated' && h.serverId) {
            await this.sidecar.call('p2p_server_delete', { id: h.instanceId, sid: h.serverId }).catch(() => undefined);
        }
        this.hosts.delete(id);
        this.runtime.delete(id);
        this.save();
        this.changed();
    }

    async regenerateCode(id: string): Promise<HostView> {
        const h = this.get(id);
        const rt = this.runtime.get(id)!;
        const wasOpen = rt.tunnel ? rt.gamePort : undefined;
        if (rt.tunnel) {
            const t = rt.tunnel;
            rt.tunnel = undefined;
            await t.stop();   // 옛 코드로 참가한 사람은 정보 요청이 실패해 정리된다
        }
        h.seed = newSeed().toString('hex');
        this.save();
        if (wasOpen) {
            await this.openTunnel(id, wasOpen);
        }
        this.changed();
        return this.hostView(h);
    }

    // ---------- 키 백업 ----------
    /** 서버 키(시드)를 파일로 내보낸다. 인스턴스 폴더(각각 git 저장소) 안에는 저장하지 않는다. */
    async exportKey(id: string, filePath: string): Promise<{ path: string; code: string }> {
        const h = this.get(id);
        const target = path.resolve(filePath);
        const instancesDir = path.resolve(this.sidecar.dataDir, 'instances');
        if (target === instancesDir || target.startsWith(instancesDir + path.sep)) {
            throw new Error('키 파일은 인스턴스 폴더(git 저장소) 안에 저장할 수 없습니다. 문서 폴더나 USB 처럼 따로 보관할 곳을 고르세요.');
        }
        const code = HostTunnel.codeFor(Buffer.from(h.seed, 'hex'));
        const body: KeyFile = { format: KEY_FORMAT, version: 1, name: h.name, kind: h.kind, code, seed: h.seed, exported: new Date().toISOString() };
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, JSON.stringify(body, undefined, 2) + '\n', { encoding: 'utf8', mode: 0o600 });
        return { path: target, code };
    }

    /** 키 파일을 이 서버에 넣는다(같은 참가 코드가 된다). 열려 있으면 새 키로 다시 연다. */
    async importKey(id: string, filePath: string): Promise<HostView> {
        const h = this.get(id);
        let data: KeyFile;
        try {
            data = JSON.parse(fs.readFileSync(path.resolve(filePath), 'utf8'));
        } catch {
            throw new Error('키 파일을 읽지 못했습니다(통합 작업실에서 내보낸 .iskey 파일인지 확인하세요).');
        }
        if (data?.format !== KEY_FORMAT || typeof data.seed !== 'string' || !/^[0-9a-f]{64}$/.test(data.seed)) {
            throw new Error('통합 작업실 서버 키 파일이 아닙니다.');
        }
        if (data.version !== 1) {
            throw new Error(`이 앱이 모르는 키 파일 버전(${data.version})입니다. 앱을 업데이트하세요.`);
        }
        const code = HostTunnel.codeFor(Buffer.from(data.seed, 'hex'));
        if (data.code && data.code !== code) {
            throw new Error('키 파일이 손상되었습니다(코드가 키와 맞지 않음).');
        }
        if ([...this.hosts.values()].some(o => o.id !== id && o.seed === data.seed)) {
            throw new Error('이 키는 이미 다른 서버가 쓰고 있습니다. 같은 키로 두 서버를 동시에 열 수 없습니다.');
        }
        const rt = this.runtime.get(id)!;
        const port = rt.tunnel ? rt.gamePort : undefined;
        if (rt.tunnel) {
            const t = rt.tunnel;
            rt.tunnel = undefined;
            await t.stop();
        }
        h.seed = data.seed;
        this.save();
        if (port) {
            await this.openTunnel(id, port);
        }
        this.changed();
        return this.hostView(h);
    }

    async acceptEula(id: string): Promise<HostView> {
        const h = this.get(id);
        if (h.kind !== 'dedicated' || !h.serverId) {
            throw new Error('전용 서버에만 EULA 가 있습니다.');
        }
        await this.sidecar.call('p2p_server_accept_eula', { id: h.instanceId, sid: h.serverId });
        this.runtime.get(id)!.eulaUrl = undefined;
        return this.startHost(id);
    }

    async command(id: string, command: string): Promise<void> {
        const h = this.get(id);
        if (h.kind !== 'dedicated') {
            throw new Error('콘솔은 전용 서버에서만 쓸 수 있습니다.');
        }
        this.log(id, `> ${command}`);
        await this.sidecar.call('p2p_server_command', { id: h.instanceId, sid: h.serverId, command });
    }

    async setWorld(id: string, world: string): Promise<HostView> {
        const h = this.get(id);
        await this.sidecar.call('p2p_server_set_world', { id: h.instanceId, sid: h.serverId, world });
        h.world = world;
        this.save();
        this.changed();
        return this.hostView(h);
    }

    protected hostByServer(sid: unknown): StoredHost | undefined {
        return [...this.hosts.values()].find(h => h.serverId === sid);
    }

    protected onSidecar(method: string, p: Record<string, unknown>): void {
        if (method === 'p2p_server_log') {
            const h = this.hostByServer(p.id);
            if (h) {
                this.log(h.id, String(p.line ?? ''));
            }
        } else if (method === 'p2p_server_players') {
            const h = this.hostByServer(p.id);
            if (h) {
                this.runtime.get(h.id)!.players = (p.players as string[]) ?? [];
                this.changed();
            }
        } else if (method === 'p2p_server_state') {
            const h = this.hostByServer(p.id);
            if (!h) {
                return;
            }
            const rt = this.runtime.get(h.id)!;
            if (p.state === 'starting') {
                rt.state = 'starting';
                rt.gamePort = Number(p.port) || rt.gamePort;
                this.changed();
            } else if (p.state === 'ready') {
                this.openTunnel(h.id, Number(p.port)).catch(e => this.fail(h.id, e));
            } else if (p.state === 'stopped') {
                const code = Number(p.exitCode ?? 0);
                this.closeTunnel(h.id, code !== 0 ? `서버가 멈췄습니다(코드 ${code}). 콘솔을 확인하세요.` : undefined).then(() => {
                    rt.state = code !== 0 ? 'error' : 'stopped';
                    rt.players = [];
                    this.changed();
                });
            }
        } else if (method === 'sidecar_exit') {
            for (const h of this.hosts.values()) {
                if (h.kind === 'dedicated') {
                    this.closeTunnel(h.id, '사이드카가 멈춰 서버가 꺼졌습니다.');
                }
            }
        }
    }

    // ---------- 참가 ----------
    async join(code: string): Promise<JoinView> {
        const id = 'join_' + crypto.randomBytes(4).toString('hex');
        const key = code.trim().toLowerCase().replace(/[\s-]/g, '');
        const view: JoinView = { id, code: key, state: 'connecting', traffic: { bytesIn: 0, bytesOut: 0 } };
        let tunnel: JoinTunnel;
        try {
            tunnel = new JoinTunnel(this.dht(), { ...this.opts.joinDefaults, code, preferredPort: this.joinPorts[key], relays: this.relays });
        } catch (e) {
            // 잘못된 코드 등: 목록에 오류로 보여 준다
            view.state = 'error';
            view.message = explain(e, this.relays.length > 0).message;
            return { ...view };
        }
        this.joins.set(id, { tunnel, view });
        tunnel.on('status', s => {
            Object.assign(view, { state: s.state, mode: s.mode, rtt: s.rtt, localPort: s.localPort, info: s.info, traffic: s.traffic });
            if (s.error) {
                view.message = s.error;
            }
            this.changed();
        });
        tunnel.on('closed', (reason: string) => {
            view.state = 'closed';
            view.message = reason;
            this.changed();
        });
        tunnel.on('log', (line: string) => {
            view.message = line;
            this.changed();
        });
        this.changed();
        try {
            await tunnel.start();
            if (view.localPort) {
                this.joinPorts[key] = view.localPort;
                this.save();
            }
        } catch (e) {
            view.state = 'error';
            view.message = explain(e, this.relays.length > 0).message;
            await tunnel.stop(view.message).catch(() => undefined);
            view.state = 'error';
        }
        this.changed();
        return { ...view };
    }

    async leave(id: string): Promise<void> {
        const j = this.joins.get(id);
        if (j) {
            await j.tunnel.stop();
            this.joins.delete(id);
            this.changed();
        }
    }

    async addToServerList(joinId: string, instanceId: string): Promise<{ name: string; ip: string }> {
        const j = this.joins.get(joinId);
        if (!j?.view.localPort) {
            throw new Error('먼저 참가 연결이 되어야 합니다.');
        }
        const name = j.view.info?.name ?? 'P2P 서버';
        const ip = `127.0.0.1:${j.view.localPort}`;
        return this.sidecar.call('servers_dat_add', { id: instanceId, name, ip });
    }

    async dispose(): Promise<void> {
        if (this.ticker) {
            clearInterval(this.ticker);
        }
        this.sub.dispose();
        for (const id of this.hosts.keys()) {
            await this.stopHost(id).catch(() => undefined);
        }
        for (const id of [...this.joins.keys()]) {
            await this.leave(id).catch(() => undefined);
        }
        await this.node?.destroy().catch(() => undefined);
        this.node = undefined;
    }
}
