// 시험용 가짜들: 마인크래프트 상태 응답 서버, 공유기(UPnP) 클라이언트, 사이드카.
import * as net from 'net';
import * as crypto from 'crypto';

function varint(n) {
    const out = [];
    let v = n >>> 0;
    do {
        let b = v & 0x7f;
        v >>>= 7;
        if (v) { b |= 0x80; }
        out.push(b);
    } while (v);
    return Buffer.from(out);
}
function readVarint(buf, off) {
    let n = 0, shift = 0;
    for (let i = 0; i < 5; i++) {
        if (off + i >= buf.length) { return undefined; }
        const b = buf[off + i];
        n |= (b & 0x7f) << shift;
        if (!(b & 0x80)) { return [n, i + 1]; }
        shift += 7;
    }
}
const packet = (id, ...parts) => { const body = Buffer.concat([varint(id), ...parts]); return Buffer.concat([varint(body.length), body]); };

/** 가짜 마인크래프트 서버(상태 조회만). status 를 바꾸면 응답도 바뀐다. */
export async function fakeMcServer(status = {}) {
    const st = { version: { name: '26.3', protocol: 775 }, players: { online: 1, max: 8, sample: [{ name: 'Steve', id: '0' }] },
        description: { text: '내 월드', extra: [{ text: ' §a(LAN)' }] }, ...status };
    const srv = net.createServer(sock => {
        let buf = Buffer.alloc(0);
        sock.on('data', chunk => {
            buf = Buffer.concat([buf, chunk]);
            for (;;) {
                const len = readVarint(buf, 0);
                if (!len || buf.length < len[1] + len[0]) { return; }
                const body = buf.subarray(len[1], len[1] + len[0]);
                buf = buf.subarray(len[1] + len[0]);
                const id = readVarint(body, 0);
                if (id[0] === 0x00 && body.length === id[1]) {          // 상태 요청(빈 본문)
                    const json = Buffer.from(JSON.stringify(st), 'utf8');
                    sock.write(packet(0x00, varint(json.length), json));
                } else if (id[0] === 0x01) {                            // 핑 → 같은 값
                    sock.write(packet(0x01, body.subarray(id[1])));
                }
            }
        });
        sock.on('error', () => undefined);
    });
    await new Promise(r => srv.listen(0, '127.0.0.1', r));
    return { port: srv.address().port, status: st, close: () => new Promise(r => srv.close(r)) };
}

/** 가짜 공유기 클라이언트. ip 를 바꾸면 공인 IP 가 바뀐다. */
export class FakeIgd {
    constructor(ip = '203.0.113.7') {
        this.ip = ip;
        this.mappings = new Map();
        this.calls = [];
        this.fail = undefined;      // { code } 를 넣으면 createMapping 이 그 오류로 실패
        this.noTtl = false;         // true 면 만료 있는 매핑은 725
        this.taken = new Set();     // 다른 기기가 쓰는 외부 포트(718)
        this.down = false;
    }
    client() {
        const igd = this;
        return {
            async createMapping(o) {
                igd.calls.push(['add', o]);
                if (igd.down) { throw new Error('timeout'); }
                if (igd.fail) { const e = new Error('refused'); e.code = igd.fail.code; throw e; }
                if (igd.noTtl && o.ttl) { const e = new Error('OnlyPermanentLeasesSupported'); e.code = 725; throw e; }
                if (igd.taken.has(o.public)) { const e = new Error('ConflictInMappingEntry'); e.code = 718; throw e; }
                igd.mappings.set(o.public, { ...o });
            },
            async removeMapping(o) { igd.calls.push(['remove', o]); igd.mappings.delete(o.public); },
            async getPublicIp() { if (igd.down) { throw new Error('no gateway'); } return igd.ip; },
            close() { igd.calls.push(['close']); },
        };
    }
}

/** 가짜 사이드카(사이드카 RPC 흉내) */
export class FakeSidecar {
    constructor(dataDir, instances) {
        this.dataDir = dataDir;
        this.instances = instances;   // { id: {id, name, version, loader, path} }
        this.calls = [];
        this.e4mc = {};               // id → { enabled }
        this.listeners = new Set();
        this.crash = {};              // id → { e4mcProblem, reason }
    }
    onNotification(cb) { this.listeners.add(cb); return { dispose: () => this.listeners.delete(cb) }; }
    notify(method, params) { for (const l of this.listeners) { l({ method, params }); } }
    async call(method, params = {}) {
        this.calls.push([method, params]);
        switch (method) {
            case 'get_instance': return this.instances[params.id];
            case 'e4mc_status': return { enabled: !!this.e4mc[params.id]?.enabled };
            case 'e4mc_install': this.e4mc[params.id] = { enabled: true }; return { ok: true, installed: ['e4mc-fabric-6.2.3-modern.jar'] };
            case 'e4mc_check_crash': return this.crash[params.id] ?? { e4mcProblem: false };
            case 'e4mc_restore_once': return [];
            case 'host_mods': return { clientRequired: [] };
            case 'ds_create': return { id: 'srv_' + crypto.randomBytes(4).toString('hex') };
            case 'ds_start': return { port: params.port ?? this.nextPort, state: 'starting' };
            case 'ds_stop': case 'ds_delete': case 'ds_accept_eula': case 'ds_command': return true;
            default: throw new Error('모르는 메서드 ' + method);
        }
    }
}

export const wait = async (pred, ms = 5000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
        if (await pred()) { return true; }
        await new Promise(r => setTimeout(r, 25));
    }
    return false;
};
