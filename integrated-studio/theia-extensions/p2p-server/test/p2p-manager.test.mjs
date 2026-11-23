// 백엔드 흐름(가짜 사이드카 + 로컬 테스트넷): 방식 A·B, 동시 2개, 코드 유지·새로 만들기, 참가·서버 목록 추가.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import createTestnet from 'hyperdht/testnet.js';
import { P2PManager } from '../lib/node/p2p-manager.js';

let testnet;
const cleanups = [];
before(async () => { testnet = await createTestnet(4); });
after(async () => {
    for (const c of cleanups.reverse()) {
        await c();
    }
    await testnet.destroy();
});

function echo(tag) {
    return new Promise(resolve => {
        const s = net.createServer(c => c.on('data', d => c.write(Buffer.concat([Buffer.from(tag), d]))).on('error', () => {}));
        s.listen(0, '127.0.0.1', () => {
            cleanups.push(() => new Promise(r => s.close(() => r())));
            resolve(s.address().port);
        });
    });
}

/** 사이드카 흉내: 방식 A 는 start 후 곧 ready 알림(가짜 에코 서버 포트). */
class FakeSidecar {
    constructor(dataDir, instDir) {
        this.dataDir = dataDir;
        this.instDir = instDir;
        this.ev = new EventEmitter();
        this.calls = [];
        this.servers = new Map();
        this.eula = new Set();
    }
    onNotification(cb) {
        this.ev.on('n', cb);
        return { dispose: () => this.ev.off('n', cb) };
    }
    notify(method, params) { this.ev.emit('n', { method, params }); }
    async call(method, p = {}) {
        this.calls.push([method, p]);
        if (method === 'get_instance') {
            return { id: p.id, name: '시험 인스턴스', version: '26.3', loader: 'vanilla', path: this.instDir };
        }
        if (method === 'p2p_server_create') {
            const id = 'srv_' + Math.random().toString(16).slice(2, 10);
            this.servers.set(id, { tag: `${id}:` });
            return { id };
        }
        if (method === 'p2p_server_accept_eula') {
            this.eula.add(p.sid);
            return { ok: true };
        }
        if (method === 'p2p_server_start') {
            if (!this.eula.has(p.sid)) {
                return { needsEula: true, eulaUrl: 'https://aka.ms/MinecraftEULA' };
            }
            const port = await echo(this.servers.get(p.sid).tag);
            setTimeout(() => {
                this.notify('p2p_server_state', { id: p.sid, state: 'starting', port });
                this.notify('p2p_server_log', { id: p.sid, line: '[12:00:02] [Server thread/INFO]: Done (1.0s)! For help, type "help"' });
                this.notify('p2p_server_state', { id: p.sid, state: 'ready', port });
            }, 50);
            return { port, state: 'starting' };
        }
        if (method === 'p2p_server_stop') {
            setTimeout(() => this.notify('p2p_server_state', { id: p.sid, state: 'stopped', exitCode: 0 }), 20);
            return true;
        }
        if (method === 'servers_dat_add') {
            return { name: `[P2P] ${p.name}`, ip: p.ip };
        }
        return {};
    }
}

function setup() {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'p2pm-'));
    const instDir = path.join(root, 'inst');
    fs.mkdirSync(path.join(instDir, 'logs'), { recursive: true });
    const side = new FakeSidecar(path.join(root, 'data'), instDir);
    const mk = () => {
        const m = new P2PManager(side, { bootstrap: testnet.bootstrap, lanInterval: 50,
            joinDefaults: { pingInterval: 200, connectTimeout: 2000, reconnectAttempts: 2 } });
        cleanups.push(() => m.dispose());
        return m;
    };
    return { side, instDir, mk, root };
}

const waitFor = async (fn, ms = 20000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
        if (await fn()) {
            return true;
        }
        await new Promise(r => setTimeout(r, 50));
    }
    return false;
};

function roundtrip(port, text) {
    return new Promise((resolve, reject) => {
        const c = net.connect(port, '127.0.0.1', () => c.write(text));
        let got = '';
        c.on('data', d => {
            got += d;
            if (got.length >= text.length) {
                c.destroy();
                resolve(got);
            }
        });
        c.on('error', reject);
    });
}

test('방식 A: EULA 동의 → 시작 → Done 뒤 P2P 열림 → 참가 → 서버 목록 추가 → 중지', async () => {
    const { side, mk } = setup();
    const host = mk();
    const joiner = mk();
    const h = await host.createHost({ instanceId: 'inst_00000001', kind: 'dedicated', name: '친구 서버', onlineMode: true });
    assert.match(h.code, /^IS1-.{52}$/);
    let v = await host.startHost(h.id);
    assert.equal(v.state, 'needs-eula');                       // 자동 동의 없음
    assert.ok(!side.eula.has(h.serverId));
    v = await host.acceptEula(h.id);
    assert.ok(await waitFor(() => host.snapshot().hosts[0].state === 'open'), '열림');
    assert.ok(host.console(h.id).some(l => l.includes('Done')));
    const j = await joiner.join(h.code);
    assert.equal(j.state, 'connected');
    assert.equal(j.info.name, '친구 서버');
    assert.equal(j.info.mode, 'dedicated');
    assert.equal(j.info.proto, 1);
    assert.equal(j.info.max, 10);
    assert.equal(await roundtrip(j.localPort, 'hi'), `${h.serverId}:hi`);
    const added = await joiner.addToServerList(j.id, 'inst_00000002');
    assert.equal(added.ip, `127.0.0.1:${j.localPort}`);
    assert.ok(await waitFor(() => host.snapshot().hosts[0].peers.length === 1), '접속자 표시');
    await host.stopHost(h.id);
    assert.equal(host.snapshot().hosts[0].state, 'stopped');
    assert.ok(await waitFor(() => joiner.snapshot().joins[0].state === 'closed'), '참가자 정리');
});

test('방식 B: LAN 공개 감지 → 열림 → 월드 나감 → 닫힘 → 다시 공개하면 같은 코드로 열림', async () => {
    const { instDir, mk } = setup();
    const log = path.join(instDir, 'logs', 'latest.log');
    fs.writeFileSync(log, '[14:00:00] [Render thread/INFO]: Setting user: Player\n');
    const host = mk();
    const h = await host.createHost({ instanceId: 'inst_00000001', kind: 'lan' });
    let v = await host.startHost(h.id);
    assert.equal(v.state, 'waiting-lan');
    const port = await echo('LAN:');
    fs.appendFileSync(log, `[14:03:01] [Server thread/INFO]: Published LAN server on port ${port}\n`);
    assert.ok(await waitFor(() => host.snapshot().hosts[0].state === 'open'), 'LAN 감지 → 열림');
    v = host.snapshot().hosts[0];
    assert.equal(v.gamePort, port);
    assert.match(v.message, /게임을 켜 둔 동안만/);
    assert.match(v.message, /정품 인증은 호스트 계정/);
    const j = await mk().join(h.code);
    assert.equal(await roundtrip(j.localPort, 'yo'), 'LAN:yo');
    fs.appendFileSync(log, '[14:06:00] [Server thread/INFO]: Stopping singleplayer server as player logged out\n');
    assert.ok(await waitFor(() => host.snapshot().hosts[0].state === 'waiting-lan'), '월드 나감 → 닫힘');
    const port2 = await echo('LAN2:');
    fs.appendFileSync(log, `[14:08:00] [Server thread/INFO]: Published LAN server on port ${port2}\n`);
    assert.ok(await waitFor(() => host.snapshot().hosts[0].state === 'open'));
    assert.equal(host.snapshot().hosts[0].code, h.code, '같은 코드');
});

test('동시 2개 + 코드 유지(다시 만든 매니저도 같은 코드) + 코드 새로 만들기', async () => {
    const { mk, side } = setup();
    const host = mk();
    const a = await host.createHost({ instanceId: 'inst_00000001', kind: 'dedicated', name: 'A' });
    const b = await host.createHost({ instanceId: 'inst_00000001', kind: 'dedicated', name: 'B' });
    for (const h of [a, b]) {
        await host.acceptEula(h.id);
    }
    assert.ok(await waitFor(() => host.snapshot().hosts.every(h => h.state === 'open')));
    const joiner = mk();
    const ja = await joiner.join(a.code);
    const jb = await joiner.join(b.code);
    assert.equal(await roundtrip(ja.localPort, 'x'), `${a.serverId}:x`);
    assert.equal(await roundtrip(jb.localPort, 'x'), `${b.serverId}:x`);
    // 저장된 키 → 앱을 다시 켜도 같은 코드
    const again = new P2PManager(side, { bootstrap: testnet.bootstrap });
    cleanups.push(() => again.dispose());
    assert.deepEqual(again.snapshot().hosts.map(h => h.code).sort(), [a.code, b.code].sort());
    // 코드 새로 만들기: 열린 채로 바꾸면 새 코드로 다시 열리고, 옛 코드 참가자는 안내와 함께 정리
    const nv = await host.regenerateCode(a.id);
    assert.notEqual(nv.code, a.code);
    assert.equal(nv.state, 'open');
    assert.ok(await waitFor(() => joiner.snapshot().joins.find(j => j.id === ja.id).state === 'closed'));
    assert.match(joiner.snapshot().joins.find(j => j.id === ja.id).message, /연결할 수 없습니다/);
    const ja2 = await joiner.join(nv.code);
    assert.equal(await roundtrip(ja2.localPort, 'y'), `${a.serverId}:y`);
});

test('잘못된 코드로 참가하면 오류 상태와 한국어 안내', async () => {
    const { mk } = setup();
    const j = await mk().join('this-is-not-a-code');
    assert.equal(j.state, 'error');
    assert.match(j.message, /참가 코드가 올바르지 않습니다/);
});

test('서버 키 내보내기·가져오기: 다른 PC(새 데이터 폴더)에서도 같은 참가 코드', async () => {
    const a = setup();
    const m1 = a.mk();
    const h = await m1.createHost({ instanceId: 'inst_00000001', kind: 'lan', name: '키 서버' });
    const keyFile = path.join(a.root, 'backup', '키 서버.iskey');
    const r = await m1.exportKey(h.id, keyFile);
    assert.equal(r.code, h.code);
    const body = JSON.parse(fs.readFileSync(keyFile, 'utf8'));
    assert.equal(body.format, 'integrated-studio-p2p-key');
    assert.equal(body.code, h.code);
    if (process.platform !== 'win32') {
        assert.equal(fs.statSync(keyFile).mode & 0o777, 0o600, '본인만 읽기');
    }
    // 키는 앱 데이터 폴더에 있다(git 밖)
    assert.ok(fs.readFileSync(path.join(a.side.dataDir, 'p2p', 'hosts.json'), 'utf8').includes(body.seed));
    // 인스턴스 폴더(git 저장소) 안에는 저장 거부
    await assert.rejects(() => m1.exportKey(h.id, path.join(a.side.dataDir, 'instances', 'inst_00000001', 'k.iskey')), /인스턴스 폴더/);
    // 다른 PC: 새 데이터 폴더에서 서버를 만들면 코드가 다르고, 키를 가져오면 같아진다
    const b = setup();
    const m2 = b.mk();
    const h2 = await m2.createHost({ instanceId: 'inst_00000001', kind: 'lan' });
    assert.notEqual(h2.code, h.code);
    const v = await m2.importKey(h2.id, keyFile);
    assert.equal(v.code, h.code);
    // 열린 서버에 가져오면 새 키로 다시 연다
    fs.appendFileSync(path.join(b.instDir, 'logs', 'latest.log'), `[14:03:01] [Server thread/INFO]: Published LAN server on port ${await echo('K:')}\n`);
    await m2.startHost(h2.id);
    assert.ok(await waitFor(() => m2.snapshot().hosts[0].state === 'open'));
    const j = await b.mk().join(h.code);
    assert.equal(await roundtrip(j.localPort, 'k'), 'K:k');
    // 잘못된 파일·손상된 파일·같은 키 중복
    const bad = path.join(a.root, 'bad.iskey');
    fs.writeFileSync(bad, '{"format":"nope"}');
    await assert.rejects(() => m2.importKey(h2.id, bad), /키 파일이 아닙니다/);
    fs.writeFileSync(bad, JSON.stringify({ ...body, code: 'IS1-' + 'y'.repeat(52) }));
    await assert.rejects(() => m2.importKey(h2.id, bad), /손상/);
    const h3 = await m2.createHost({ instanceId: 'inst_00000001', kind: 'lan' });
    await assert.rejects(() => m2.importKey(h3.id, keyFile), /이미 다른 서버/);
});
