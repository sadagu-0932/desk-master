/**
 * P2P 터널 핵심 — 프로토콜 v1 (참가 전용 앱 feat/join-app 과 호환). Theia 에 의존하지 않는다.
 *
 * hyperdht: 공용 DHT 노드로 상대를 찾고 UDP 홀펀칭으로 PC 끼리 직접 연결한다(암호화된 Noise 스트림).
 * 직접 연결이 안 되면 설정된 중계 노드(blind-relay)를 거친다(hyperdht 의 relayThrough 옵션).
 *
 * 프로토콜 v1
 *   참가 코드 = "IS1-" + 호스트 공개키(32바이트)의 z-base-32
 *   참가자가 연 스트림의 첫 바이트:
 *     0x01 게임 터널 — 나머지 바이트를 호스트의 127.0.0.1:<마인크래프트 포트> 와 그대로 주고받는다
 *     0x02 정보 요청 — 호스트가 JSON 한 줄을 보내고 스트림을 닫는다:
 *          {"proto":1,"name","version","loader","mode":"dedicated|lan|external","players","max"}
 *   proto 가 1 이 아니면 참가자는 연결하지 않고 안내한다.
 * 호스트(스타형 중심): 키쌍으로 DHT 에 서버 등록 → 게임 터널마다 로컬 서버로 TCP 파이프.
 * 참가자: 정보 요청으로 확인 → 127.0.0.1:<빈 포트> 리스너 → 마인크래프트 연결마다 새 게임 터널.
 *        핑·호스트 생존 확인은 주기적인 정보 요청으로 한다(요청 보낸 뒤 응답까지 시간).
 */
import { EventEmitter } from 'events';
import * as crypto from 'crypto';
import * as net from 'net';
import DHT, { HyperServer, HyperSocket, KeyPair } from 'hyperdht';
import * as idEncoding from 'hypercore-id-encoding';
import { Server as RelayServer } from 'blind-relay';

export const PROTOCOL_VERSION = 1;
export const CODE_PREFIX = 'IS1-';
export const KIND_GAME = 0x01;
export const KIND_INFO = 0x02;

export type ServerMode = 'dedicated' | 'lan' | 'external';
export type LinkMode = 'direct' | 'relay';

/** 정보 응답(프로토콜 v1 그대로). */
export interface ServerInfo {
    proto: number;
    name: string;
    version: string;
    loader: string;
    mode: ServerMode;
    players: number;
    max: number;
}

export interface TrafficStats {
    bytesIn: number;
    bytesOut: number;
}

// ================================================================ 코드
/** 참가 코드 = "IS1-" + z-base-32(52자). */
export function encodeCode(publicKey: Buffer): string {
    return CODE_PREFIX + idEncoding.encode(publicKey);
}

/** 붙여넣은 코드 → 공개키. 앞뒤 공백·줄바꿈, 대소문자, 중간의 공백·- 는 무시한다. */
export function decodeCode(code: string): Buffer {
    let clean = (code || '').trim().replace(/\s+/g, '');
    const m = /^IS(\d+)-/i.exec(clean);
    if (m) {
        if (m[1] !== String(PROTOCOL_VERSION)) {
            throw new P2PError('PROTO_MISMATCH', `다른 버전(IS${m[1]})의 참가 코드입니다. 이 앱은 IS${PROTOCOL_VERSION} 코드만 씁니다. 호스트와 같은 버전으로 업데이트하세요.`);
        }
        clean = clean.slice(m[0].length);
    }
    clean = clean.toLowerCase().replace(/-/g, '');
    try {
        const key = idEncoding.decode(clean);
        if (key.length === 32) {
            return key;
        }
    } catch {
        // 아래에서 안내
    }
    throw new P2PError('BAD_CODE', '참가 코드가 올바르지 않습니다. 호스트가 보낸 코드(IS1-로 시작)를 빠짐없이 붙여 넣었는지 확인하세요.');
}

export function isCode(text: string): boolean {
    try {
        decodeCode(text);
        return true;
    } catch {
        return false;
    }
}

export function newSeed(): Buffer {
    return crypto.randomBytes(32);
}

export function keyPairFromSeed(seed: Buffer): KeyPair {
    return DHT.keyPair(seed);
}

// ================================================================ 오류(한국어)
export class P2PError extends Error {
    constructor(readonly code: string, message: string, readonly detail?: string) {
        super(message);
    }
}

const HOLEPUNCH_CODES = new Set([
    'HOLEPUNCH_ABORTED', 'HOLEPUNCH_INVALID', 'HOLEPUNCH_PROBE_TIMEOUT', 'HOLEPUNCH_DOUBLE_RANDOMIZED_NATS',
    'CANNOT_HOLEPUNCH', 'REMOTE_NOT_HOLEPUNCHING', 'REMOTE_NOT_HOLEPUNCHABLE', 'PEER_CONNECTION_FAILED', 'REMOTE_ABORTED',
    'HANDSHAKE_UNFINISHED', 'CONNECT_TIMEOUT',
]);

export function isHolepunchFailure(err: unknown): boolean {
    const code = (err as { code?: string })?.code;
    return !!code && HOLEPUNCH_CODES.has(code);
}

/** hyperdht 오류를 사용자용 한국어로. */
export function explain(err: unknown, relaysConfigured: boolean): P2PError {
    if (err instanceof P2PError) {
        return err;
    }
    const code = (err as { code?: string })?.code ?? 'UNKNOWN';
    const detail = (err as Error)?.message ?? String(err);
    if (code === 'PEER_NOT_FOUND') {
        return new P2PError(code, '호스트를 찾지 못했습니다. 코드가 맞는지, 호스트가 지금 서버를 열어 두었는지 확인하세요.', detail);
    }
    if (code === 'HOLEPUNCH_DOUBLE_RANDOMIZED_NATS') {
        return new P2PError(code, '두 PC 모두 통신사·공유기 NAT 가 연결마다 포트를 바꿔서 직접 연결할 수 없습니다.'
            + (relaysConfigured ? ' 중계 연결도 실패했습니다.' : ' 중계 노드가 설정돼 있지 않아 중계로 바꿀 수 없습니다.')
            + ' 한쪽이 다른 네트워크(예: 휴대폰 핫스팟 ↔ 집 와이파이 바꾸기)로 시도해 보세요.', detail);
    }
    if (HOLEPUNCH_CODES.has(code)) {
        return new P2PError(code, '네트워크(공유기·통신사 NAT 나 방화벽)가 두 PC 의 직접 연결을 막았습니다.'
            + (relaysConfigured ? ' 중계 연결도 실패했습니다.' : ' 중계 노드가 설정돼 있지 않아 중계로 바꿀 수 없습니다.'), detail);
    }
    if (code === 'RELAY_ABORTED') {
        return new P2PError(code, '중계 노드를 통한 연결이 끊어졌습니다. 중계 노드가 켜져 있는지 확인하세요.', detail);
    }
    if (code === 'NODE_DESTROYED' || code === 'SUSPENDED') {
        return new P2PError(code, 'P2P 연결이 종료되었습니다.', detail);
    }
    return new P2PError(code, `P2P 연결에 실패했습니다(${code}).`, detail);
}

// ================================================================ 노드
export interface NodeOptions {
    /** 테스트넷 등 다른 부트스트랩. 비우면 hyperdht 기본 공용 노드. */
    bootstrap?: Array<string | { host: string; port: number }>;
    /** UDP 를 묶을 주소(시험·문제 해결용). 비우면 모든 인터페이스. */
    host?: string;
}

export function createNode(opts: NodeOptions = {}): DHT {
    const o: Record<string, unknown> = {};
    if (opts.bootstrap) {
        o.bootstrap = opts.bootstrap;
    }
    if (opts.host) {
        o.host = opts.host;
    }
    return new DHT(o);
}

// ================================================================ 파이프
function pipeBoth(a: HyperSocket | net.Socket, b: HyperSocket | net.Socket, stats: { in: (n: number) => void; out: (n: number) => void }): void {
    let closed = false;
    const close = (): void => {
        if (closed) {
            return;
        }
        closed = true;
        a.destroy();
        b.destroy();
    };
    // a = P2P 쪽(들어오는 데이터 = in), b = 로컬 TCP 쪽
    a.on('data', (d: Buffer) => {
        stats.in(d.length);
        if (!b.write(d)) {
            a.pause();
        }
    });
    b.on('data', (d: Buffer) => {
        stats.out(d.length);
        if (!a.write(d)) {
            b.pause();
        }
    });
    b.on('drain', () => a.resume());
    a.on('drain', () => b.resume());
    for (const s of [a, b]) {
        s.on('end', close);
        s.on('close', close);
        s.on('error', close);
    }
}

// ================================================================ 호스트
export interface HostPeer {
    id: string;              // 참가자 공개키(16진) 앞부분
    since: number;
    connections: number;
    bytesIn: number;
    bytesOut: number;
}

export interface HostOptions {
    seed: Buffer;
    /** 마인크래프트 서버(또는 LAN 공개 포트) */
    target: { host: string; port: number };
    /** 정보 응답에 넣을 값. players 를 주지 않으면 게임 터널이 열린 참가자 수. */
    info: () => { name: string; version: string; loader: string; mode: ServerMode; max: number; players?: number };
}

/** 호스트 터널. 이벤트: 'peers'(목록 바뀜), 'target-error' */
export class HostTunnel extends EventEmitter {
    readonly keyPair: KeyPair;
    readonly code: string;
    protected server: HyperServer | undefined;
    protected peers = new Map<string, HostPeer>();
    protected sockets = new Set<HyperSocket | net.Socket>();
    readonly traffic: TrafficStats = { bytesIn: 0, bytesOut: 0 };

    /** 시드로 참가 코드를 계산한다(터널을 열지 않고). */
    static codeFor(seed: Buffer): string {
        return encodeCode(keyPairFromSeed(seed).publicKey);
    }

    constructor(protected readonly node: DHT, protected readonly opts: HostOptions) {
        super();
        this.keyPair = keyPairFromSeed(opts.seed);
        this.code = encodeCode(this.keyPair.publicKey);
    }

    get target(): { host: string; port: number } {
        return this.opts.target;
    }

    /** 대상 포트를 바꾼다(LAN 공개 포트가 바뀐 경우). */
    setTarget(port: number): void {
        this.opts.target = { ...this.opts.target, port };
    }

    async start(): Promise<string> {
        const server = this.node.createServer({}, socket => this.onConnection(socket));
        this.server = server;
        await server.listen(this.keyPair);
        return this.code;
    }

    listPeers(): HostPeer[] {
        return [...this.peers.values()];
    }

    info(): ServerInfo {
        const i = this.opts.info();
        return {
            proto: PROTOCOL_VERSION, name: i.name, version: i.version, loader: i.loader, mode: i.mode,
            players: i.players ?? this.peers.size, max: i.max,
        };
    }

    protected onConnection(socket: HyperSocket): void {
        this.sockets.add(socket);
        socket.on('error', () => undefined);
        socket.once('close', () => this.sockets.delete(socket));
        socket.once('data', (first: Buffer) => {
            const kind = first[0];
            if (kind === KIND_GAME) {
                this.onGame(socket, first.subarray(1));
            } else if (kind === KIND_INFO) {
                socket.end(JSON.stringify(this.info()) + '\n');
            } else {
                socket.destroy();   // v1 에 없는 종류
            }
        });
    }

    protected onGame(socket: HyperSocket, rest: Buffer): void {
        const key = socket.remotePublicKey.toString('hex');
        let peer = this.peers.get(key);
        if (!peer) {
            peer = { id: key.slice(0, 12), since: Date.now(), connections: 0, bytesIn: 0, bytesOut: 0 };
            this.peers.set(key, peer);
        }
        const p = peer;
        p.connections++;
        this.emit('peers', this.listPeers());
        const tcp = net.connect(this.opts.target.port, this.opts.target.host);
        this.sockets.add(tcp);
        tcp.once('close', () => this.sockets.delete(tcp));
        tcp.once('error', err => this.emit('target-error', err));
        if (rest.length) {
            tcp.write(rest);
            p.bytesIn += rest.length;
            this.traffic.bytesIn += rest.length;
        }
        pipeBoth(socket, tcp, {
            in: n => { p.bytesIn += n; this.traffic.bytesIn += n; },
            out: n => { p.bytesOut += n; this.traffic.bytesOut += n; },
        });
        socket.once('close', () => {
            p.connections = Math.max(0, p.connections - 1);
            if (p.connections === 0) {
                this.peers.delete(key);
            }
            this.emit('peers', this.listPeers());
        });
    }

    async stop(): Promise<void> {
        for (const s of this.sockets) {
            s.destroy();
        }
        this.sockets.clear();
        this.peers.clear();
        await this.server?.close().catch(() => undefined);
        this.server = undefined;
    }
}

// ================================================================ 참가자
export interface JoinOptions {
    code: string;
    /** 이 포트를 먼저 시도(같은 서버는 같은 주소가 되도록). 0 이면 아무 빈 포트. */
    preferredPort?: number;
    /** 중계 노드 공개키 목록. 직접 연결이 실패하면 이리로. */
    relays?: Buffer[];
    /** 처음부터 중계로(시험용) */
    forceRelay?: boolean;
    connectTimeout?: number;
    /** 정보 요청(핑·생존 확인) 간격 */
    pingInterval?: number;
    /** 연속으로 이만큼 정보 요청이 실패하면 호스트가 닫은 것으로 보고 정리 */
    reconnectAttempts?: number;
}

export interface JoinStatus {
    state: 'connecting' | 'connected' | 'reconnecting' | 'closed';
    mode?: LinkMode;
    rtt?: number;
    localPort?: number;
    info?: ServerInfo;
    traffic: TrafficStats;
    error?: string;
}

/** 정보 요청 한 번(참가 전용 앱과 같은 방식). 응답 시간 = 요청을 쓴 뒤 JSON 줄을 받을 때까지. */
export function readInfo(socket: HyperSocket, timeoutMs = 15000): Promise<{ info: ServerInfo; rtt: number }> {
    return new Promise((resolve, reject) => {
        const t0 = Date.now();
        let buf = '';
        const done = (err?: Error, info?: ServerInfo): void => {
            clearTimeout(timer);
            socket.removeAllListeners('data');
            socket.destroy();
            if (err) {
                reject(err);
            } else {
                resolve({ info: info!, rtt: Date.now() - t0 });
            }
        };
        const timer = setTimeout(() => done(new P2PError('NO_INFO', '호스트가 서버 정보를 보내지 않았습니다.')), timeoutMs);
        socket.on('data', (d: Buffer) => {
            buf += d.toString('utf8');
            const i = buf.indexOf('\n');
            if (i < 0) {
                if (buf.length > 16 * 1024) {
                    done(new P2PError('BAD_INFO', '호스트가 보낸 서버 정보가 올바르지 않습니다.'));
                }
                return;
            }
            let info: ServerInfo;
            try {
                info = JSON.parse(buf.slice(0, i));
            } catch {
                done(new P2PError('BAD_INFO', '호스트가 보낸 서버 정보가 올바르지 않습니다.'));
                return;
            }
            if (info.proto !== PROTOCOL_VERSION) {
                done(new P2PError('PROTO_MISMATCH',
                    `호스트의 P2P 프로토콜 버전(${info.proto ?? '알 수 없음'})이 이 앱(${PROTOCOL_VERSION})과 달라 연결하지 않습니다. 호스트와 참가자 모두 최신 버전으로 업데이트하세요.`));
                return;
            }
            done(undefined, info);
        });
        socket.once('close', () => done(new P2PError('NO_INFO', '호스트가 서버 정보를 보내기 전에 연결을 닫았습니다.')));
        socket.once('error', err => done(err));
    });
}

/** 참가 터널. 이벤트: 'status'(JoinStatus), 'closed'(reason), 'log'(line) */
export class JoinTunnel extends EventEmitter {
    readonly hostKey: Buffer;
    readonly keyPair: KeyPair = DHT.keyPair();
    protected listener: net.Server | undefined;
    protected sockets = new Set<HyperSocket | net.Socket>();
    protected pollTimer: NodeJS.Timeout | undefined;
    protected failures = 0;
    protected polling = false;
    protected stopped = false;
    readonly status: JoinStatus = { state: 'connecting', traffic: { bytesIn: 0, bytesOut: 0 } };

    constructor(protected readonly node: DHT, protected readonly opts: JoinOptions) {
        super();
        this.hostKey = decodeCode(opts.code);
    }

    get relaysConfigured(): boolean {
        return (this.opts.relays?.length ?? 0) > 0;
    }

    protected update(patch: Partial<JoinStatus>): void {
        Object.assign(this.status, patch);
        this.emit('status', { ...this.status, traffic: { ...this.status.traffic } });
    }

    /** 한 번 연결(직접 → 실패하면 중계)하고 첫 바이트(kind)를 쓴다. */
    protected async open(kind: number, preferMode?: LinkMode): Promise<{ socket: HyperSocket; mode: LinkMode }> {
        const tryOnce = (relay: boolean): Promise<HyperSocket> => new Promise((resolve, reject) => {
            const sock = this.node.connect(this.hostKey, {
                keyPair: this.keyPair,
                relayThrough: relay ? this.opts.relays : null,
            });
            const timer = setTimeout(() => {
                sock.destroy();
                reject(Object.assign(new Error('연결 시간 초과'), { code: 'CONNECT_TIMEOUT' }));
            }, this.opts.connectTimeout ?? 30000);
            sock.once('open', () => {
                clearTimeout(timer);
                sock.write(Buffer.from([kind]));
                resolve(sock);
            });
            sock.once('error', err => {
                clearTimeout(timer);
                reject(err);
            });
        });
        const wantRelay = this.opts.forceRelay || preferMode === 'relay';
        if (!wantRelay) {
            try {
                return { socket: await tryOnce(false), mode: 'direct' };
            } catch (err) {
                if (!(isHolepunchFailure(err) && this.relaysConfigured)) {
                    throw explain(err, this.relaysConfigured);
                }
                this.emit('log', `직접 연결 실패(${(err as { code?: string }).code}) — 중계로 다시 시도합니다.`);
            }
        }
        if (!this.relaysConfigured) {
            throw new P2PError('NO_RELAY', '중계 노드가 설정돼 있지 않아 중계로 연결할 수 없습니다.');
        }
        try {
            return { socket: await tryOnce(true), mode: 'relay' };
        } catch (err) {
            throw explain(err, true);
        }
    }

    /** 정보 요청: 서버 정보·핑. 처음 연결 방식(직접/중계)도 여기서 정해진다. */
    async requestInfo(): Promise<ServerInfo> {
        const { socket, mode } = await this.open(KIND_INFO, this.status.mode);
        this.sockets.add(socket);
        socket.once('close', () => this.sockets.delete(socket));
        const { info, rtt } = await readInfo(socket);
        this.update({ info, rtt, mode });
        return info;
    }

    async start(): Promise<JoinStatus> {
        await this.requestInfo();     // 프로토콜이 다르면 여기서 거부
        await this.listen();
        this.update({ state: 'connected', error: undefined });
        this.pollTimer = setInterval(() => this.poll(), this.opts.pingInterval ?? 5000);
        return this.status;
    }

    protected async poll(): Promise<void> {
        if (this.polling || this.stopped) {
            return;
        }
        this.polling = true;
        try {
            await this.requestInfo();
            this.failures = 0;
            if (this.status.state !== 'connected') {
                this.update({ state: 'connected', error: undefined });
            }
        } catch (err) {
            if (this.stopped) {
                return;
            }
            const e = explain(err, this.relaysConfigured);
            if (e.code === 'PROTO_MISMATCH') {
                await this.stop(e.message);
                return;
            }
            this.failures++;
            if (this.failures >= (this.opts.reconnectAttempts ?? 3)) {
                await this.stop('호스트에 연결할 수 없습니다 — 호스트가 서버를 닫았거나 네트워크가 끊겼습니다.');
            } else {
                this.update({ state: 'reconnecting', error: e.message });
            }
        } finally {
            this.polling = false;
        }
    }

    protected listen(): Promise<void> {
        return new Promise((resolve, reject) => {
            const server = net.createServer(tcp => this.onLocal(tcp));
            this.listener = server;
            const tryPort = (port: number): void => {
                server.once('error', err => {
                    if ((err as NodeJS.ErrnoException).code === 'EADDRINUSE' && port !== 0) {
                        tryPort(0);
                    } else {
                        reject(err);
                    }
                });
                server.listen(port, '127.0.0.1', () => {
                    this.update({ localPort: (server.address() as net.AddressInfo).port });
                    resolve();
                });
            };
            tryPort(this.opts.preferredPort ?? 0);
        });
    }

    protected async onLocal(tcp: net.Socket): Promise<void> {
        this.sockets.add(tcp);
        tcp.pause();
        tcp.on('error', () => undefined);
        tcp.once('close', () => this.sockets.delete(tcp));
        try {
            const { socket } = await this.open(KIND_GAME, this.status.mode);
            this.sockets.add(socket);
            socket.once('close', () => this.sockets.delete(socket));
            pipeBoth(socket, tcp, {
                in: n => { this.status.traffic.bytesIn += n; },
                out: n => { this.status.traffic.bytesOut += n; },
            });
            tcp.resume();
        } catch (err) {
            this.emit('log', `게임 연결을 열지 못했습니다: ${explain(err, this.relaysConfigured).message}`);
            tcp.destroy();
        }
    }

    async stop(reason = '참가를 끝냈습니다.'): Promise<void> {
        if (this.stopped) {
            return;
        }
        this.stopped = true;
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
        }
        for (const s of this.sockets) {
            s.destroy();
        }
        this.sockets.clear();
        await new Promise<void>(r => this.listener ? this.listener.close(() => r()) : r());
        this.update({ state: 'closed', error: reason });
        this.emit('closed', reason);
    }
}

// ================================================================ 중계 노드(직접 연결이 안 될 때 쓸 수 있게 — 공인 IP 가 있는 PC 에서)
export async function startRelay(node: DHT, seed?: Buffer): Promise<{ publicKey: Buffer; close: () => Promise<void> }> {
    const relay = new RelayServer({ createStream: (o: unknown) => node.createRawStream({ ...(o as object), framed: true }) });
    const keyPair = keyPairFromSeed(seed ?? newSeed());
    const server = node.createServer({}, socket => {
        const session = relay.accept(socket, { id: socket.remotePublicKey });
        session.on('error', () => undefined);
    });
    await server.listen(keyPair);
    return {
        publicKey: keyPair.publicKey,
        close: async () => {
            await relay.close().catch(() => undefined);
            await server.close().catch(() => undefined);
        },
    };
}

/** 쉼표로 구분된 중계 노드 코드(공개키) 목록 → 버퍼 목록. 잘못된 것은 건너뛴다. */
export function parseRelays(text: string | undefined): Buffer[] {
    return (text || '').split(/[,\s]+/).filter(Boolean).flatMap(c => {
        try {
            return [decodeCode(c)];
        } catch {
            return [];
        }
    });
}

/** 127.0.0.1 의 빈 TCP 포트. */
export function freePort(): Promise<number> {
    return new Promise((resolve, reject) => {
        const s = net.createServer();
        s.once('error', reject);
        s.listen(0, '127.0.0.1', () => {
            const port = (s.address() as net.AddressInfo).port;
            s.close(() => resolve(port));
        });
    });
}
