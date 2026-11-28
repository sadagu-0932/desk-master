// HostManager 통합 시험: 방식 A·B·C, 주소 자동 선택(e4mc·Minekube → UPnP), 실패 이유, 동시 2개, 정리.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { HostManager } from '../lib/node/host-manager.js';
import { UpnpManager } from '../lib/node/upnp.js';
import { FakeIgd, FakeSidecar, fakeMcServer, wait } from './helpers.mjs';

function setup({ ip = '8.8.4.4' } = {}) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shm-'));
    const instDir = path.join(dir, 'inst');
    fs.mkdirSync(path.join(instDir, 'logs'), { recursive: true });
    fs.writeFileSync(path.join(instDir, 'logs', 'latest.log'), '[0] [main/INFO]: Loading\n');
    const sidecar = new FakeSidecar(dir, {
        inst_aaaaaaaa: { id: 'inst_aaaaaaaa', name: '내 월드', version: '26.3', loader: 'fabric', path: instDir },
        inst_bbbbbbbb: { id: 'inst_bbbbbbbb', name: '바닐라', version: '26.3', loader: 'vanilla', path: instDir },
    });
    const igd = new FakeIgd(ip);
    const upnp = new UpnpManager(() => igd.client());
    const pings = new Map();         // port → 결과(없으면 응답 없음)
    const ping = async (_h, port) => pings.get(port) ?? { ok: false, error: '응답이 없습니다' };
    const m = new HostManager(sidecar, { upnp, ping, lanInterval: 20, e4mcTimeoutMs: 400, pollMs: 60_000 });
    const log = line => fs.appendFileSync(path.join(instDir, 'logs', 'latest.log'), line + '\n');
    return { dir, sidecar, igd, upnp, m, pings, log };
}

const okPing = (extra = {}) => ({ ok: true, version: '26.3', motd: '내 월드', online: 0, max: 8, players: [], ...extra });

test('B 싱글 LAN: e4mc 도메인으로 열림 → LAN 닫으면 주소 닫힘 → 다시 공개하면 다시 열림', async () => {
    const { m, sidecar, log, pings, igd } = setup();
    sidecar.e4mc.inst_aaaaaaaa = { enabled: true };
    const s = await m.createServer({ kind: 'lan', instanceId: 'inst_aaaaaaaa' });
    await m.startServer(s.id);
    assert.equal(m.snapshot().servers[0].state, 'waiting-lan');
    pings.set(51234, okPing());
    log('[1] [Server thread/INFO]: Published LAN server on port 51234');
    log('[2] [e4mc-1/INFO] (e4mc) Domain assigned: brave-otter.sg.e4mc.link');
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'open'));
    let v = m.snapshot().servers[0];
    assert.equal(v.address.provider, 'e4mc');
    assert.equal(v.address.address, 'brave-otter.sg.e4mc.link');
    assert.equal(v.address.fixed, false);
    assert.ok(v.address.notes.some(n => n.includes('매번 바뀝니다')));
    assert.ok(v.address.notes.some(n => n.includes('정품 인증은 호스트 계정 기준')));
    assert.equal(igd.mappings.size, 0);                               // e4mc 면 공유기는 건드리지 않음
    log('[3] [Server thread/INFO]: Stopping singleplayer server as player logged out');
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'closed'));
    assert.equal(m.snapshot().servers[0].state, 'waiting-lan');
    log('[4] [Server thread/INFO]: Published LAN server on port 51300');
    pings.set(51300, okPing());
    log('[5] [e4mc-1/INFO] (e4mc) Domain assigned: calm-fox.sg.e4mc.link');
    assert.ok(await wait(() => m.snapshot().servers[0].address.address === 'calm-fox.sg.e4mc.link'));
    log('[6] [Render thread/INFO]: Stopping!');
    assert.ok(await wait(() => sidecar.calls.some(c => c[0] === 'e4mc_check_crash')));   // 게임 종료 뒤 크래시 점검
    assert.ok(sidecar.calls.some(c => c[0] === 'e4mc_restore_once'));
    await m.dispose();
});

test('B: e4mc 없음 → UPnP, CGNAT 면 실패 이유가 남음', async () => {
    const { m, log, pings, igd } = setup({ ip: '100.80.1.1' });
    const s = await m.createServer({ kind: 'lan', instanceId: 'inst_aaaaaaaa', name: '친구들' });
    await m.startServer(s.id);
    pings.set(40000, okPing());
    log('[1] [Server thread/INFO]: Published LAN server on port 40000');
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'failed', 8000));
    const v = m.snapshot().servers[0];
    assert.deepEqual(v.address.attempts.map(a => [a.provider, a.ok]), [['e4mc', false], ['upnp', false]]);
    assert.match(v.address.attempts[0].reason, /e4mc 가 들어 있지 않습니다/);
    assert.match(v.address.attempts[1].reason, /CGNAT/);
    assert.equal(igd.mappings.size, 0);
    await m.stopServer(s.id);
    await m.dispose();
});

test('A 전용 서버: Done 뒤 UPnP 로 열림, 접속자 표시, 중지하면 매핑 삭제', async () => {
    const { m, sidecar, pings, igd } = setup();
    const s = await m.createServer({ kind: 'dedicated', instanceId: 'inst_aaaaaaaa', name: '전용', onlineMode: false });
    sidecar.nextPort = 25565;
    await m.startServer(s.id);
    const sid = m.snapshot().servers[0].serverId;
    assert.equal(m.snapshot().servers[0].state, 'starting');
    pings.set(25565, okPing({ online: 1, players: ['Alex'] }));
    sidecar.notify('ds_state', { id: sid, state: 'ready', port: 25565 });
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'open'));
    let v = m.snapshot().servers[0];
    assert.equal(v.address.provider, 'upnp');
    assert.equal(v.address.address, '8.8.4.4');                       // 기본 포트는 포트를 붙이지 않음
    assert.equal(v.address.relay, false);
    assert.ok(v.address.notes.some(n => n.includes('DDNS')));
    assert.ok(igd.mappings.has(25565));
    sidecar.notify('ds_players', { id: sid, players: ['Alex'] });
    sidecar.notify('ds_log', { id: sid, line: '[12:00] [Server thread/INFO]: Alex joined the game' });
    assert.ok(await wait(() => m.snapshot().servers[0].players.includes('Alex')));
    assert.ok(m.console(s.id).some(l => l.includes('Alex joined')));
    await m.stopServer(s.id);
    assert.equal(igd.mappings.size, 0);
    assert.ok(sidecar.calls.some(c => c[0] === 'ds_stop'));
    v = m.snapshot().servers[0];
    assert.equal(v.state, 'stopped');
    await m.dispose();
});

test('C 외부 서버: 상태 조회 실패면 열지 않음 → 켜면 열림 → 3번 무응답이면 닫힘', async () => {
    const { m, pings, igd } = setup();
    const s = await m.createServer({ kind: 'external', port: 25570 });
    await m.startServer(s.id);
    let v = m.snapshot().servers[0];
    assert.equal(v.address.state, 'failed');
    assert.equal(v.state, 'error');
    assert.match(v.message, /응답하지 않아 주소를 열지 않았습니다/);
    assert.equal(igd.mappings.size, 0);
    pings.set(25570, okPing({ version: '1.21.4', motd: '다른 런처 월드' }));
    await m.openAddress(s.id);
    v = m.snapshot().servers[0];
    assert.equal(v.address.state, 'open');
    assert.equal(v.address.address, '8.8.4.4:25570');
    assert.equal(v.serverVersion, '1.21.4');
    pings.delete(25570);
    for (let i = 0; i < 3; i++) {
        await m.poll();
    }
    v = m.snapshot().servers[0];
    assert.equal(v.address.state, 'closed');
    assert.match(v.message, /응답하지 않아 주소를 닫았습니다/);
    assert.equal(igd.mappings.size, 0);
    await m.dispose();
});

test('동시 2개: 서로 다른 포트·주소, 앱 끌 때 매핑 모두 삭제, IP 변경 반영', async () => {
    const { m, pings, igd } = setup();
    const a = await m.createServer({ kind: 'external', port: 30001, name: 'A' });
    const b = await m.createServer({ kind: 'external', port: 30002, name: 'B' });
    pings.set(30001, okPing());
    pings.set(30002, okPing());
    await m.openAddress(a.id);
    await m.openAddress(b.id);
    const addrs = m.snapshot().servers.map(s => s.address.address);
    assert.deepEqual(addrs, ['8.8.4.4:30001', '8.8.4.4:30002']);
    assert.equal(igd.mappings.size, 2);
    igd.ip = '8.8.8.8';
    await m.upnp.checkIp();
    assert.deepEqual(m.snapshot().servers.map(s => s.address.address), ['8.8.8.8:30001', '8.8.8.8:30002']);
    await m.dispose();
    assert.equal(igd.mappings.size, 0);
});

test('선호 방식·저장: UPnP 먼저 고르면 저장되고, 예전 playit 설정은 자동으로', async () => {
    const { m, dir, sidecar } = setup({ ip: '8.8.4.4' });
    const s = await m.createServer({ kind: 'external', port: 30010 });
    await m.setPreference(s.id, 'upnp');
    await assert.rejects(m.setPreference(s.id, 'e4mc'), /외부 서버/);
    await m.dispose();
    const file = path.join(dir, 'server-host', 'servers.json');
    const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.equal(saved[0].preference, 'upnp');
    saved.push({ ...saved[0], id: 'srv-old', preference: 'playit', playitTunnelId: 'x' });   // 예전 앱이 저장한 것
    fs.writeFileSync(file, JSON.stringify(saved));
    const m2 = new HostManager(sidecar, { ping: async () => ({ ok: false }) });
    assert.deepEqual(m2.snapshot().servers.map(x => x.preference), ['upnp', 'auto']);
    await m2.dispose();
});

test('실제 상태 조회와 함께(가짜 마인크래프트 서버)', async () => {
    const mc = await fakeMcServer();
    const { m, igd } = setup();
    const mgr = new HostManager(m.sidecar, { upnp: m.upnp });
    await m.dispose();
    const s = await mgr.createServer({ kind: 'external', port: mc.port });
    await mgr.openAddress(s.id);
    const v = mgr.snapshot().servers.find(x => x.id === s.id);
    assert.equal(v.address.state, 'open');
    assert.equal(v.motd, '내 월드 (LAN)');
    assert.deepEqual(v.players, ['Steve']);
    await mgr.dispose();
    assert.equal(igd.mappings.size, 0);
    await mc.close();
});

test('전용 서버 오류 코드: 로그 오류(ds_error)·종료 코드가 카드에 남고, 다시 시작하면 지워짐', async () => {
    const { m, sidecar } = setup();
    const s = await m.createServer({ kind: 'dedicated', instanceId: 'inst_aaaaaaaa', name: '모드 서버' });
    sidecar.nextPort = 25570;
    await m.startServer(s.id);
    const sid = m.snapshot().servers[0].serverId;
    sidecar.notify('ds_error', { id: sid, error: { code: 'MOD-201', title: '필요한 모드가 없거나', hint: '모드 확인', details: ['requires fabric-api'] } });
    sidecar.notify('ds_state', { id: sid, state: 'stopped', exitCode: 1, errors: [{ code: 'MOD-201', title: 'x', hint: 'y' }, { code: 'CRASH-101', title: '튕김', hint: 'z' }] });
    assert.ok(await wait(() => m.snapshot().servers[0].state === 'error'));
    let v = m.snapshot().servers[0];
    assert.deepEqual(v.errors.map(e => e.code), ['MOD-201', 'CRASH-101']);
    assert.match(v.message, /종료 코드 1.*MOD-201/);
    assert.ok(m.console(s.id).some(l => l.includes('[MOD-201]')));
    await m.startServer(s.id);
    v = m.snapshot().servers[0];
    assert.equal(v.errors.length, 0);
    // 시작 자체가 실패(사이드카 오류에 코드)
    sidecar.call = async (method) => { if (method === 'ds_start') { throw new Error('[JAVA-001] Java 25 을(를) 찾지 못했습니다.'); } return {}; };
    await m.startServer(s.id);
    v = m.snapshot().servers[0];
    assert.equal(v.state, 'error');
    assert.equal(v.errors[0].code, 'JAVA-001');
    await m.dispose();
});

test('전용 서버: 서버에 넣은 e4mc 주소로 열림, 친구가 못 들어오면 UPnP(방화벽 확인) ↔ e4mc', async () => {
    const { m, sidecar, pings, igd } = setup();
    const fw = { ok: false, block: 1, message: '[NET-201] 막고 있습니다', path: 'C:/java.exe' };
    const orig = sidecar.call.bind(sidecar);
    sidecar.call = async (method, params) => method === 'firewall_check' ? fw : orig(method, params);
    const s = await m.createServer({ kind: 'dedicated', instanceId: 'inst_aaaaaaaa', name: '모드 서버' });
    sidecar.nextPort = 25580;
    await m.startServer(s.id);
    const sid = m.snapshot().servers[0].serverId;
    pings.set(25580, okPing());
    sidecar.notify('ds_state', { id: sid, state: 'ready', port: 25580 });
    sidecar.notify('ds_address', { id: sid, provider: 'e4mc', address: 'brave-cat.sg.e4mc.link' });   // Done 뒤 몇 초
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'open'));
    let v = m.snapshot().servers[0];
    assert.equal(v.address.provider, 'e4mc');
    assert.equal(v.address.address, 'brave-cat.sg.e4mc.link');
    assert.equal(v.address.fixed, false);
    assert.equal(igd.mappings.size, 0);                                             // 공유기는 건드리지 않음
    await m.nextProvider(s.id);                                                     // 친구가 못 들어와요 → UPnP
    v = m.snapshot().servers[0];
    assert.equal(v.address.provider, 'upnp');
    assert.ok(igd.mappings.has(25580));
    assert.ok(await wait(() => m.snapshot().servers[0].firewall?.block === 1));       // UPnP 면 방화벽도 확인
    await m.nextProvider(s.id);                                                     // 다시 누르면 e4mc 로
    assert.equal(m.snapshot().servers[0].address.provider, 'e4mc');
    assert.equal(igd.mappings.size, 0);
    await m.stopServer(s.id);
    await m.dispose();
});

test('Paper 전용 서버: Minekube Connect 고정 주소, 늦게 오면 UPnP 에서 바꿈', async () => {
    const { m, sidecar, pings, igd } = setup();
    const s = await m.createServer({ kind: 'dedicated', instanceId: 'inst_aaaaaaaa', name: '플러그인', software: 'paper' });
    sidecar.nextPort = 25590;
    await m.startServer(s.id);
    const sid = m.snapshot().servers[0].serverId;
    pings.set(25590, okPing());
    // 주소가 안 오면(시험은 0.4초) UPnP 로
    sidecar.notify('ds_state', { id: sid, state: 'ready', port: 25590 });
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'open'));
    let v = m.snapshot().servers[0];
    assert.equal(v.address.provider, 'upnp');
    assert.match(v.address.attempts[0].reason, /Minekube Connect 가 주소를 알려 주지 않았습니다/);
    // Connect 가 늦게 주소를 알리면 그 주소로 바꾸고 UPnP 매핑은 닫음
    sidecar.notify('ds_address', { id: sid, provider: 'minekube', address: 'quick-fox.play.minekube.net' });
    assert.ok(await wait(() => m.snapshot().servers[0].address.provider === 'minekube' && m.snapshot().servers[0].address.state === 'open'));
    v = m.snapshot().servers[0];
    assert.equal(v.address.address, 'quick-fox.play.minekube.net');
    assert.equal(v.address.fixed, true);
    assert.equal(igd.mappings.size, 0);
    // 다시 켤 때 이번엔 Done 전에 주소가 오면 바로 그 주소
    await m.stopServer(s.id);
    await m.startServer(s.id);
    sidecar.notify('ds_address', { id: sid, provider: 'minekube', address: 'quick-fox.play.minekube.net' });
    sidecar.notify('ds_state', { id: sid, state: 'ready', port: 25590 });
    assert.ok(await wait(() => m.snapshot().servers[0].address.state === 'open'));
    assert.equal(m.snapshot().servers[0].address.provider, 'minekube');
    assert.deepEqual(m.snapshot().servers[0].address.attempts.map(a => [a.provider, a.ok]), [['minekube', true]]);
    await m.stopServer(s.id);
    await m.dispose();
});
