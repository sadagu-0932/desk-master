// 시험용 가짜들: 마인크래프트 상태 응답 서버, 공유기(UPnP) 클라이언트, playit API·GitHub 릴리스, 사이드카.
import * as net from 'net';
import * as http from 'http';
import * as crypto from 'crypto';
import { EventEmitter } from 'events';

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

/** 가짜 playit API + GitHub 릴리스 + 다운로드. */
export async function fakePlayit({ agentBytes = Buffer.from('fake-playit-agent'), badDigest = false } = {}) {
    // 실제 API 흉내(공식 api_client 2.0.2): 자기 관리 에이전트는 자기 에이전트 터널만(origin.type=agent, 자기 agent_id) 만들 수 있다.
    // freePlan 이면 앱의 터널 만들기를 RequiresPlayitPremium 으로 거부(웹사이트에서 만든 터널은 state.tunnels 에 직접 넣는다).
    const state = { claims: new Map(), tunnels: [], secret: 'ab'.repeat(32), calls: [], approve: true,
        agentId: '11111111-2222-3333-4444-555555555555', freePlan: false, updateBlocked: false };
    const digest = crypto.createHash('sha256').update(badDigest ? Buffer.from('other') : agentBytes).digest('hex');
    let base = '';
    const srv = http.createServer((req, res) => {
        let body = '';
        req.on('data', c => { body += c; });
        req.on('end', () => {
            const send = (code, obj, raw) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(raw ?? JSON.stringify(obj)); };
            const ok = data => send(200, { status: 'success', data });
            const json = body ? JSON.parse(body) : {};
            state.calls.push([req.url, json, req.headers.authorization]);
            if (req.url === '/release') {
                return send(200, { tag_name: 'v2.0.2', assets: [
                    { name: 'playit-windows-x86_64-signed.exe', browser_download_url: `${base}/dl`, digest: `sha256:${digest}` },
                    { name: 'playitd-windows-x86_64-signed.exe', browser_download_url: `${base}/dl`, digest: `sha256:${digest}` },
                    { name: 'playit-linux-amd64', browser_download_url: `${base}/dl`, digest: `sha256:${digest}` },
                    { name: 'playit-linux-aarch64', browser_download_url: `${base}/dl`, digest: `sha256:${digest}` },
                    { name: 'playit-macos-universal.tar.gz', browser_download_url: `${base}/dl`, digest: `sha256:${digest}` },
                ] });
            }
            if (req.url === '/dl') { res.writeHead(200); return res.end(agentBytes); }
            if (req.url === '/claim/setup') {
                const n = (state.claims.get(json.code) ?? 0) + 1;
                state.claims.set(json.code, n);
                return ok(n < 2 ? 'WaitingForUserVisit' : n < 3 ? 'WaitingForUser' : state.approve ? 'UserAccepted' : 'UserRejected');
            }
            if (req.url === '/claim/exchange') { return ok({ secret_key: state.secret }); }
            if (req.headers.authorization !== `Agent-Key ${state.secret}`) {
                return send(200, { status: 'error', data: { type: 'auth', message: 'InvalidAgentKey' } });
            }
            if (req.url === '/agents/rundata') { return ok({ agent_id: state.agentId, agent_type: 'self-managed', tunnels: [], pending: [] }); }
            if (req.url === '/tunnels/list') { return ok({ tunnels: state.tunnels, tcp_alloc: {}, udp_alloc: {} }); }
            if (req.url === '/tunnels/create' && /[^\x00-\x7F]/.test(json.name ?? '')) {
                // 실제 응답(사용자 로그 2026-11-28): HTTP 400 error/validation "Tunnel name can only contain ASCII characters"
                return send(400, { status: 'error', data: { type: 'validation', message: 'Tunnel name can only contain ASCII characters' } });
            }
            if (req.url === '/tunnels/create') {
                if (json.origin?.type !== 'agent' || json.origin.data.agent_id !== state.agentId) {
                    return send(200, { status: 'error', data: { type: 'auth', message: 'SelfManagedAgentCanOnlyAffectSelf' } });
                }
                if (state.freePlan) { return send(200, { status: 'fail', data: 'RequiresPlayitPremium' }); }
                if (state.tunnels.length >= 4) { return send(200, { status: 'fail', data: 'TunnelLimitReached' }); }
                return ok(state.addTunnel(json.name, json.origin.data.local_port));
            }
            if (req.url === '/tunnels/update') {
                if (state.updateBlocked) { return send(200, { status: 'fail', data: 'CannotUpdateLocalAddressForUnassignedTunnel' }); }
                const t = state.tunnels.find(x => x.id === json.tunnel_id);
                t.origin.data.local_port = json.local_port;
                return ok(null);
            }
            send(404, { status: 'error', data: 'path-not-found' });
        });
    });
    /** 터널 추가(앱이 만들거나, 사용자가 웹사이트에서 만든 것 흉내) */
    state.addTunnel = (name, localPort, type = 'minecraft-java', agentId = state.agentId) => {
        const id = crypto.randomUUID();
        const n = state.tunnels.length + 1;
        state.tunnels.push({ id, name, tunnel_type: type,
            origin: { type: 'agent', data: { agent_id: agentId, agent_name: 'agent', local_ip: '127.0.0.1', local_port: localPort } },
            alloc: { status: 'allocated', data: { assigned_domain: `play${n}.gl.joinmc.link`, assigned_srv: `play${n}.gl.joinmc.link`, port_start: 40000 + n, ip_hostname: 'x' } } });
        return id;
    };
    /** 터널 추가(앱이 만들거나, 사용자가 웹사이트에서 만든 것 흉내) */
    state.addTunnel = (name, localPort, type = 'minecraft-java', agentId = state.agentId) => {
        const id = crypto.randomUUID();
        const n = state.tunnels.length + 1;
        state.tunnels.push({ id, name, tunnel_type: type,
            origin: { type: 'agent', data: { agent_id: agentId, agent_name: 'agent', local_ip: '127.0.0.1', local_port: localPort } },
            alloc: { status: 'allocated', data: { assigned_domain: `play${n}.gl.joinmc.link`, assigned_srv: `play${n}.gl.joinmc.link`, port_start: 40000 + n, ip_hostname: 'x' } } });
        return id;
    };
    await new Promise(r => srv.listen(0, '127.0.0.1', r));
    base = `http://127.0.0.1:${srv.address().port}`;
    return { base, state, close: () => new Promise(r => srv.close(r)) };
}

/** 가짜 에이전트 프로세스 */
export function fakeAgent() {
    const p = new EventEmitter();
    p.exitCode = null;
    p.stdout = new EventEmitter();
    p.stderr = new EventEmitter();
    p.stdout.setEncoding = () => p.stdout;
    p.stderr.setEncoding = () => p.stderr;
    /** 데몬 표준 출력 흉내(조각으로 나눠 보내도 줄 단위로 읽는지) */
    p.say = text => { p.stdout.emit('data', text); };
    p.kill = () => { p.exitCode = 0; p.emit('exit', 0); };
    p.crash = code => { p.exitCode = code; p.emit('exit', code); };
    return p;
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
