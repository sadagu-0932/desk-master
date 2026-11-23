/**
 * M10 방식 C: 마인크래프트 LAN 공개 신호 수신.
 *
 * 26.3 client.jar net/minecraft/client/server/LanServerPinger 를 확인했다:
 *   UTF-8 문자열 "[MOTD]" + motd + "[/MOTD][AD]" + 포트 + "[/AD]" 를 UDP 224.0.2.60:4445 로 1.5초마다 보낸다.
 * 어떤 런처로 연 LAN 월드든 이 신호를 보내므로 목록에 띄울 수 있다. 신호가 5초 동안 없으면 목록에서 뺀다.
 * 같은 포트(4445)를 게임도 듣기 때문에 reuseAddr 로 연다.
 */
import * as dgram from 'dgram';
import * as os from 'os';
import { EventEmitter } from 'events';
import { LanGame } from '../common/index.js';

export const LAN_GROUP = '224.0.2.60';
export const LAN_PORT = 4445;
const EXPIRE_MS = 5000;

export function parseLanPing(text: string): { motd: string; port: number } | undefined {
    const m = /^\[MOTD\]([\s\S]*?)\[\/MOTD\]\[AD\](?:[^\]:]*:)?(\d{1,5})\[\/AD\]$/.exec(text.trim());
    if (!m) {
        return undefined;
    }
    const port = Number(m[2]);
    if (!(port > 0 && port < 65536)) {
        return undefined;
    }
    return { motd: m[1].slice(0, 200), port };
}

export function encodeLanPing(motd: string, port: number): Buffer {
    return Buffer.from(`[MOTD]${motd}[/MOTD][AD]${port}[/AD]`, 'utf8');
}

export function localAddresses(): Set<string> {
    const out = new Set<string>(['127.0.0.1', '::1']);
    for (const list of Object.values(os.networkInterfaces())) {
        for (const a of list ?? []) {
            out.add(a.address.replace(/^::ffff:/, ''));
        }
    }
    return out;
}

/** 이벤트: 'change'(LanGame[]) */
export class LanDiscovery extends EventEmitter {
    protected socket: dgram.Socket | undefined;
    protected games = new Map<string, LanGame>();
    protected timer: NodeJS.Timeout | undefined;
    protected locals = localAddresses();
    error: string | undefined;

    constructor(protected readonly port = LAN_PORT, protected readonly group = LAN_GROUP) {
        super();
    }

    start(): void {
        if (this.socket) {
            return;
        }
        const s = dgram.createSocket({ type: 'udp4', reuseAddr: true });
        this.socket = s;
        s.on('error', e => {
            this.error = `LAN 신호를 받을 수 없습니다: ${e.message}`;
            this.stop();
        });
        s.on('message', (msg, rinfo) => this.onMessage(msg, rinfo.address));
        s.bind(this.port, () => {
            try {
                s.addMembership(this.group);
            } catch {
                // 일부 환경(가상 어댑터만 있음 등)에서는 실패 — 같은 PC 의 루프백 신호는 그래도 받는다
                for (const addr of this.locals) {
                    if (/^\d+\.\d+\.\d+\.\d+$/.test(addr)) {
                        try {
                            s.addMembership(this.group, addr);
                        } catch {
                            // 무시
                        }
                    }
                }
            }
            try {
                s.setMulticastLoopback(true);
            } catch {
                // 무시
            }
        });
        this.timer = setInterval(() => this.expire(), 1000);
    }

    stop(): void {
        if (this.timer) {
            clearInterval(this.timer);
        }
        this.timer = undefined;
        try {
            this.socket?.close();
        } catch {
            // 이미 닫힘
        }
        this.socket = undefined;
    }

    list(): LanGame[] {
        return [...this.games.values()].sort((a, b) => Number(b.local) - Number(a.local) || a.port - b.port);
    }

    onMessage(msg: Buffer, from: string): void {
        const p = parseLanPing(msg.toString('utf8'));
        if (!p) {
            return;
        }
        const host = from.replace(/^::ffff:/, '');
        const key = `${host}:${p.port}`;
        const fresh = !this.games.has(key) || this.games.get(key)!.motd !== p.motd;
        this.games.set(key, { host, port: p.port, motd: p.motd, local: this.locals.has(host), lastSeen: Date.now() });
        if (fresh) {
            this.emit('change', this.list());
        }
    }

    protected expire(): void {
        const now = Date.now();
        let changed = false;
        for (const [k, g] of this.games) {
            if (now - g.lastSeen > EXPIRE_MS) {
                this.games.delete(k);
                changed = true;
            }
        }
        if (changed) {
            this.emit('change', this.list());
        }
    }
}
