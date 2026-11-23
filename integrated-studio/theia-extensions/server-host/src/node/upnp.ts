/**
 * M10 주소 방식 "직접 UPnP": 공유기(IGD)에 포트 매핑을 요청한다(중계 없이 직접 접속).
 *
 * - 라이브러리: @runonflux/nat-upnp 2.2.0 (2026-11 확인. 3.x 는 나온 지 며칠이라 고정)
 * - 공유기가 알려 준 외부 IP 가 사설·CGNAT(100.64.0.0/10)·예약 대역이면 실패로 본다(통신사 공유기 뒤 → 밖에서 못 들어옴).
 * - 매핑에는 만료 시간(1시간)을 두고 20분마다 갱신. 만료를 못 받는 공유기(오류 725)는 만료 없이 걸고 반드시 지운다.
 * - 서버를 닫거나 앱을 끌 때 매핑을 지운다. 5분마다 공인 IP 를 확인해 바뀌면 알리고(DDNS 가 있으면 갱신).
 * Theia 에 의존하지 않는다(시험에서 가짜 공유기 클라이언트를 넣는다).
 */
import { EventEmitter } from 'events';

export interface UpnpClientLike {
    createMapping(o: { public: number; private: { port: number; host?: string } | number; protocol?: string; ttl?: number; description?: string }): Promise<unknown>;
    removeMapping(o: { public: number; protocol?: string }): Promise<unknown>;
    getPublicIp(): Promise<string>;
    close(): void;
}

export class UpnpFailure extends Error {
    constructor(message: string, readonly code?: string) {
        super(message);
    }
}

function ipv4(ip: string): number[] | undefined {
    const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(ip.trim());
    if (!m) {
        return undefined;
    }
    const parts = m.slice(1).map(Number);
    return parts.every(n => n <= 255) ? parts : undefined;
}

/** 밖에서 들어올 수 없는 주소인지(사설·CGNAT·루프백·링크 로컬·예약). 이유를 돌려준다. */
export function nonPublicReason(ip: string): string | undefined {
    const p = ipv4(ip);
    if (!p) {
        return ip ? `공유기가 알려 준 외부 주소(${ip})가 IPv4 가 아닙니다` : '공유기가 외부 주소를 알려 주지 않았습니다';
    }
    const [a, b] = p;
    if (a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)) {
        return `공유기의 외부 주소(${ip})가 사설 주소입니다 — 공유기가 두 겹이거나 통신사 장비 뒤에 있어 밖에서 들어올 수 없습니다`;
    }
    if (a === 100 && b >= 64 && b <= 127) {
        return `공유기의 외부 주소(${ip})가 통신사 공유 주소(CGNAT, 100.64.0.0/10)입니다 — 밖에서 들어올 수 없습니다`;
    }
    if (a === 0 || a === 127 || (a === 169 && b === 254) || a >= 224 || (a === 192 && b === 0 && p[2] === 0) ||
        (a === 198 && (b === 18 || b === 19))) {
        return `공유기의 외부 주소(${ip})가 인터넷에서 쓸 수 없는 주소입니다`;
    }
    return undefined;
}

interface Mapping {
    port: number;
    publicPort: number;
    ttl: number;
    description: string;
}

export interface UpnpOptions {
    ttlSeconds?: number;
    renewMs?: number;
    ipCheckMs?: number;
    /** DDNS 갱신(공인 IP 가 바뀌었을 때·처음 열 때). 실패해도 주소는 연다. */
    ddns?: () => { url: string; domain?: string; token?: string } | undefined;
    fetchImpl?: typeof fetch;
}

/** 이벤트: 'ip'(새 공인 IP, 이전 IP) · 'renew-failed'(포트, 이유) · 'ddns'(ok, 메시지) */
export class UpnpManager extends EventEmitter {
    protected mappings = new Map<number, Mapping>();
    protected renewTimer: NodeJS.Timeout | undefined;
    protected ipTimer: NodeJS.Timeout | undefined;
    publicIp: string | undefined;

    constructor(protected readonly makeClient: () => UpnpClientLike, protected readonly opts: UpnpOptions = {}) {
        super();
    }

    protected client: UpnpClientLike | undefined;
    protected get c(): UpnpClientLike {
        if (!this.client) {
            this.client = this.makeClient();
        }
        return this.client;
    }

    /** 포트를 연다. 성공하면 { ip, port } — 실패하면 UpnpFailure(한국어 이유). */
    async open(port: number, label: string): Promise<{ ip: string; port: number; address: string; ddns?: string }> {
        let ip: string;
        try {
            ip = await this.c.getPublicIp();
        } catch (e) {
            throw new UpnpFailure(`공유기가 UPnP 에 응답하지 않습니다(꺼져 있거나 지원하지 않음): ${(e as Error).message}`, 'no-igd');
        }
        const bad = nonPublicReason(ip);
        if (bad) {
            throw new UpnpFailure(bad, 'not-public');
        }
        const description = `통합 작업실 ${label}`.slice(0, 60);
        let ttl = this.opts.ttlSeconds ?? 3600;
        let publicPort = port;
        for (let attempt = 0; attempt < 4; attempt++) {
            try {
                await this.c.createMapping({ public: publicPort, private: port, protocol: 'TCP', ttl, description });
                break;
            } catch (e) {
                const code = (e as { code?: number }).code;
                if (code === 725 && ttl !== 0) {           // OnlyPermanentLeasesSupported
                    ttl = 0;
                    attempt--;
                    continue;
                }
                if (code === 718 && attempt < 3) {          // ConflictInMappingEntry: 다른 기기가 그 외부 포트를 씀
                    publicPort = 20000 + Math.floor(Math.random() * 40000);
                    continue;
                }
                throw new UpnpFailure(`공유기가 포트 열기를 거부했습니다${code ? `(오류 ${code})` : ''}: ${(e as Error).message}`, 'refused');
            }
        }
        this.mappings.set(port, { port, publicPort, ttl, description });
        this.publicIp = ip;
        this.startTimers();
        let ddnsName: string | undefined;
        const d = this.opts.ddns?.();
        if (d?.url) {
            ddnsName = d.domain ? `${d.domain}` : undefined;
            await this.updateDdns(ip).catch(() => undefined);
        }
        const host = ddnsName ?? ip;
        return { ip, port: publicPort, address: publicPort === 25565 ? host : `${host}:${publicPort}`, ddns: ddnsName };
    }

    async close(port: number): Promise<void> {
        const m = this.mappings.get(port);
        if (!m) {
            return;
        }
        this.mappings.delete(port);
        try {
            await this.c.removeMapping({ public: m.publicPort, protocol: 'TCP' });
        } catch {
            // 공유기가 이미 지웠거나 꺼짐 — 만료 시간이 있으면 저절로 사라진다
        }
        if (!this.mappings.size) {
            this.stopTimers();
        }
    }

    async closeAll(): Promise<void> {
        await Promise.all([...this.mappings.keys()].map(p => this.close(p)));
        this.stopTimers();
        try {
            this.client?.close();
        } catch {
            // 무시
        }
        this.client = undefined;
    }

    get openPorts(): number[] {
        return [...this.mappings.keys()];
    }

    protected startTimers(): void {
        if (!this.renewTimer) {
            this.renewTimer = setInterval(() => this.renew(), this.opts.renewMs ?? 20 * 60_000);
        }
        if (!this.ipTimer) {
            this.ipTimer = setInterval(() => this.checkIp(), this.opts.ipCheckMs ?? 5 * 60_000);
        }
    }

    protected stopTimers(): void {
        if (this.renewTimer) {
            clearInterval(this.renewTimer);
        }
        if (this.ipTimer) {
            clearInterval(this.ipTimer);
        }
        this.renewTimer = undefined;
        this.ipTimer = undefined;
    }

    async renew(): Promise<void> {
        for (const m of this.mappings.values()) {
            if (m.ttl === 0) {
                continue;
            }
            try {
                await this.c.createMapping({ public: m.publicPort, private: m.port, protocol: 'TCP', ttl: m.ttl, description: m.description });
            } catch (e) {
                this.emit('renew-failed', m.port, (e as Error).message);
            }
        }
    }

    async checkIp(): Promise<void> {
        let ip: string;
        try {
            ip = await this.c.getPublicIp();
        } catch {
            return;
        }
        if (ip && ip !== this.publicIp) {
            const prev = this.publicIp;
            this.publicIp = ip;
            if (this.opts.ddns?.()?.url) {
                await this.updateDdns(ip).catch(() => undefined);
            }
            this.emit('ip', ip, prev);
        }
    }

    async updateDdns(ip: string): Promise<void> {
        const d = this.opts.ddns?.();
        if (!d?.url) {
            return;
        }
        const url = d.url.replace(/\{ip\}/g, encodeURIComponent(ip)).replace(/\{token\}/g, encodeURIComponent(d.token ?? ''))
            .replace(/\{domain\}/g, encodeURIComponent(d.domain ?? ''));
        if (!/^https:\/\//i.test(url)) {
            this.emit('ddns', false, 'DDNS 주소는 https:// 로 시작해야 합니다(토큰 보호).');
            return;
        }
        try {
            const res = await (this.opts.fetchImpl ?? fetch)(url, { method: 'GET' });
            const body = (await res.text()).trim().slice(0, 80);
            const ok = res.ok && !/^(ko|bad|error|fail)/i.test(body);
            this.emit('ddns', ok, ok ? `DDNS 갱신: ${d.domain ?? ''} → ${ip}` : `DDNS 갱신 실패(${res.status}): ${body}`);
        } catch (e) {
            this.emit('ddns', false, `DDNS 서버에 연결하지 못했습니다: ${(e as Error).message}`);
        }
    }
}

/** 실제 공유기 클라이언트(@runonflux/nat-upnp). 라이브러리는 처음 쓸 때 불러온다. */
export function natUpnpClient(): () => UpnpClientLike {
    return () => {
        let real: Promise<UpnpClientLike> | undefined;
        const get = (): Promise<UpnpClientLike> => real ??= import('@runonflux/nat-upnp').then(mod => {
            const Client = (mod as unknown as { Client: new (o?: object) => UpnpClientLike }).Client;
            return new Client({ timeout: 4000, url: process.env.INTEGRATED_STUDIO_UPNP_URL || undefined });
        });
        return {
            createMapping: async o => (await get()).createMapping(o),
            removeMapping: async o => (await get()).removeMapping(o),
            getPublicIp: async () => (await get()).getPublicIp(),
            close: () => { real?.then(c => c.close()).catch(() => undefined); },
        };
    };
}
