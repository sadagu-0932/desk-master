/**
 * Server List Ping(멀티플레이 목록의 상태 조회) — 주소를 열기 전에 그 포트에 정말 마인크래프트 서버가 있는지,
 * 버전·MOTD·접속자를 확인한다. 1.7 이후 형식(핸드셰이크 → 상태 요청 → JSON → 핑) 그대로.
 */
import * as net from 'net';
import { PingResult } from '../common/index.js';

function varint(n: number): Buffer {
    const out: number[] = [];
    let v = n >>> 0;
    do {
        let b = v & 0x7f;
        v >>>= 7;
        if (v !== 0) {
            b |= 0x80;
        }
        out.push(b);
    } while (v !== 0);
    return Buffer.from(out);
}

function readVarint(buf: Buffer, off: number): [number, number] | undefined {
    let n = 0;
    let shift = 0;
    for (let i = 0; i < 5; i++) {
        if (off + i >= buf.length) {
            return undefined;
        }
        const b = buf[off + i];
        n |= (b & 0x7f) << shift;
        if (!(b & 0x80)) {
            return [n, i + 1];
        }
        shift += 7;
    }
    throw new Error('잘못된 VarInt');
}

function packet(id: number, ...parts: Buffer[]): Buffer {
    const body = Buffer.concat([varint(id), ...parts]);
    return Buffer.concat([varint(body.length), body]);
}

function str(s: string): Buffer {
    const b = Buffer.from(s, 'utf8');
    return Buffer.concat([varint(b.length), b]);
}

/** MOTD(description)는 문자열이거나 텍스트 컴포넌트(JSON) */
export function flattenMotd(d: unknown): string {
    if (typeof d === 'string') {
        return d.replace(/§./g, '');
    }
    if (d && typeof d === 'object') {
        const o = d as { text?: string; extra?: unknown[]; translate?: string };
        return ((o.text ?? o.translate ?? '') + (o.extra ?? []).map(flattenMotd).join('')).replace(/§./g, '');
    }
    return '';
}

export function ping(host: string, port: number, timeoutMs = 3000): Promise<PingResult> {
    return new Promise(resolve => {
        const sock = net.createConnection({ host, port });
        let buf = Buffer.alloc(0);
        let status: PingResult | undefined;
        let sentAt = 0;
        const done = (r: PingResult): void => {
            clearTimeout(timer);
            sock.destroy();
            resolve(r);
        };
        const timer = setTimeout(() => done(status ?? { ok: false, error: '응답이 없습니다(시간 초과)' }), timeoutMs);
        sock.on('error', e => done(status ?? { ok: false, error: (e as NodeJS.ErrnoException).code === 'ECONNREFUSED' ? '이 포트에 열린 서버가 없습니다' : e.message }));
        sock.on('connect', () => {
            const portBuf = Buffer.alloc(2);
            portBuf.writeUInt16BE(port);
            sock.write(packet(0x00, varint(-1), str(host), portBuf, varint(1)));
            sock.write(packet(0x00));
        });
        sock.on('data', (chunk: Buffer) => {
            buf = Buffer.concat([buf, chunk]);
            for (;;) {
                const len = readVarint(buf, 0);
                if (!len || buf.length < len[1] + len[0]) {
                    return;
                }
                const body = buf.subarray(len[1], len[1] + len[0]);
                buf = buf.subarray(len[1] + len[0]);
                const id = readVarint(body, 0);
                if (!id) {
                    return;
                }
                if (id[0] === 0x00 && !status) {
                    const sl = readVarint(body, id[1]);
                    if (!sl) {
                        return done({ ok: false, error: '응답을 읽지 못했습니다' });
                    }
                    try {
                        const json = JSON.parse(body.subarray(id[1] + sl[1], id[1] + sl[1] + sl[0]).toString('utf8'));
                        status = {
                            ok: true, version: json.version?.name, protocol: json.version?.protocol,
                            motd: flattenMotd(json.description), online: json.players?.online, max: json.players?.max,
                            players: (json.players?.sample ?? []).map((p: { name?: string }) => p.name).filter(Boolean),
                        };
                    } catch {
                        return done({ ok: false, error: '마인크래프트 서버 응답이 아닙니다' });
                    }
                    const t = Buffer.alloc(8);
                    t.writeBigInt64BE(BigInt(Date.now()));
                    sentAt = Date.now();
                    sock.write(packet(0x01, t));
                } else if (id[0] === 0x01 && status) {
                    return done({ ...status, latencyMs: Date.now() - sentAt });
                }
            }
        });
        sock.on('end', () => done(status ?? { ok: false, error: '연결이 끊겼습니다' }));
    });
}
