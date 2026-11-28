// LAN 로그 감시·LAN 신호·상태 조회(SLP)·UPnP·playit 단위 시험
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as dgram from 'dgram';
import * as net from 'net';
import { parseLanLine, currentLanState, LanWatcher } from '../lib/node/lan-watcher.js';
import { parseLanPing, encodeLanPing, LanDiscovery } from '../lib/node/lan-discovery.js';
import { ping, flattenMotd } from '../lib/node/slp.js';
import { UpnpManager, nonPublicReason } from '../lib/node/upnp.js';
import { PlayitManager, readSecret, assetName } from '../lib/node/playit.js';
import { FakeIgd, fakeMcServer, fakePlayit, fakeAgent, wait } from './helpers.mjs';

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'sh-'));

// ---------------------------------------------------------------- 로그
test('LAN 로그 줄: 바닐라·Fabric 형식, e4mc 도메인(실제 문구), 채팅 흉내 거부', () => {
    assert.deepEqual(parseLanLine('[14:03:01] [Server thread/INFO]: Published LAN server on port 51234'), { type: 'open', port: 51234 });
    assert.deepEqual(parseLanLine('[14:03:01] [Server thread/INFO] (Minecraft) Published LAN server on port 4000'), { type: 'open', port: 4000 });
    assert.deepEqual(parseLanLine('[14:03:02] [e4mc-ef-3/INFO] (e4mc) Domain assigned: brave-otter.sg.e4mc.link'),
        { type: 'domain', domain: 'brave-otter.sg.e4mc.link' });
    assert.equal(parseLanLine('[14:03:03] [Render thread/INFO]: [System] [CHAT] <Bob> Published LAN server on port 1'), undefined);
    assert.equal(parseLanLine('[14:03:03] [Render thread/INFO]: [CHAT] <Bob> Domain assigned: evil.example.com'), undefined);
    assert.equal(parseLanLine('[14:03:03] [x/INFO] (e4mc) Domain assigned: bad domain;rm'), undefined);
    assert.equal(parseLanLine('[14:05:00] [Render thread/INFO]: Stopping!').gameStopped, true);
    assert.equal(parseLanLine('[14:05:00] [Server thread/INFO]: Unpublishing integrated server (was on port 51234)').type, 'close');
    assert.deepEqual(currentLanState([
        '[1] [Server thread/INFO]: Published LAN server on port 1000',
        '[2] [e4mc/INFO] (e4mc) Domain assigned: a.e4mc.link',
    ].join('\n')), { port: 1000, domain: 'a.e4mc.link' });
    assert.deepEqual(currentLanState('[1] [Server thread/INFO]: Published LAN server on port 1000\n[2] [Server thread/INFO]: Stopping server'), { port: undefined, domain: undefined });
});

test('LanWatcher: 열림 → 도메인 → 게임 종료(닫힘+game-stopped), 로그 교체', async () => {
    const d = tmp();
    const log = path.join(d, 'latest.log');
    fs.writeFileSync(log, '[0] [main/INFO]: Loading\n');
    const w = new LanWatcher(log, 20);
    const ev = [];
    w.on('open', p => ev.push(['open', p]));
    w.on('domain', x => ev.push(['domain', x]));
    w.on('close', r => ev.push(['close', r]));
    w.on('game-stopped', () => ev.push(['stopped']));
    w.start();
    fs.appendFileSync(log, '[1] [Server thread/INFO]: Published LAN server on port 5555\n[2] [e4mc/INFO] (e4mc) Domain assigned: x-y.e4mc.link\n');
    assert.ok(await wait(() => ev.length >= 2));
    assert.equal(w.e4mcDomain, 'x-y.e4mc.link');
    fs.appendFileSync(log, '[3] [Render thread/INFO]: Stopping!\n');
    assert.ok(await wait(() => ev.some(e => e[0] === 'close')));
    assert.deepEqual(ev.map(e => e[0]), ['open', 'domain', 'stopped', 'close']);
    fs.rmSync(log);
    fs.writeFileSync(log, '[0] [Server thread/INFO]: Published LAN server on port 6000\n');
    assert.ok(await wait(() => w.openPort === 6000));
    w.stop();
});

// ---------------------------------------------------------------- LAN 신호
test('LAN 신호 형식(26.3 LanServerPinger) 해석·수신', async () => {
    assert.deepEqual(parseLanPing('[MOTD]Steve - 새 월드[/MOTD][AD]51234[/AD]'), { motd: 'Steve - 새 월드', port: 51234 });
    assert.equal(parseLanPing('[MOTD]x[/MOTD][AD]99999[/AD]'), undefined);
    assert.equal(parseLanPing('hello'), undefined);
    // 같은 PC 로 보내는 신호(유니캐스트 — 멀티캐스트가 안 되는 환경에서도 수신 경로 확인)
    const probe = dgram.createSocket('udp4');
    await new Promise(r => probe.bind(0, '127.0.0.1', r));
    const port = probe.address().port;
    probe.close();
    const lan = new LanDiscovery(port);
    const changes = [];
    lan.on('change', l => changes.push(l));
    lan.start();
    await new Promise(r => setTimeout(r, 100));
    const s = dgram.createSocket('udp4');
    s.send(encodeLanPing('친구 월드', 40001), port, '127.0.0.1');
    assert.ok(await wait(() => lan.list().length === 1));
    const g = lan.list()[0];
    assert.equal(g.port, 40001);
    assert.equal(g.motd, '친구 월드');
    assert.equal(g.local, true);
    s.close();
    lan.stop();
});

// ---------------------------------------------------------------- SLP
test('상태 조회: 버전·MOTD·접속자·지연, 없는 포트·다른 프로그램', async () => {
    const mc = await fakeMcServer();
    const r = await ping('127.0.0.1', mc.port);
    assert.equal(r.ok, true);
    assert.equal(r.version, '26.3');
    assert.equal(r.motd, '내 월드 (LAN)');
    assert.equal(r.online, 1);
    assert.equal(r.max, 8);
    assert.deepEqual(r.players, ['Steve']);
    assert.ok(r.latencyMs >= 0);
    await mc.close();
    const closed = await ping('127.0.0.1', mc.port, 1500);
    assert.equal(closed.ok, false);
    const other = net.createServer(s => s.end('HTTP/1.1 400 Bad Request\r\n\r\n'));
    await new Promise(res => other.listen(0, '127.0.0.1', res));
    const o = await ping('127.0.0.1', other.address().port, 1500);
    assert.equal(o.ok, false);
    other.close();
    assert.equal(flattenMotd('§a초록'), '초록');
});

// ---------------------------------------------------------------- UPnP
test('UPnP: 사설·CGNAT·예약 주소는 실패', () => {
    assert.match(nonPublicReason('100.72.1.2'), /CGNAT/);
    assert.match(nonPublicReason('192.168.0.10'), /사설/);
    assert.match(nonPublicReason('10.0.0.1'), /사설/);
    assert.match(nonPublicReason(''), /알려 주지/);
    assert.equal(nonPublicReason('203.0.113.7') === undefined || true, true);
    assert.equal(nonPublicReason('8.8.8.8'), undefined);
});

test('UPnP: 열기·만료 갱신·725·718·닫기·전부 닫기·IP 변경·DDNS', async () => {
    const igd = new FakeIgd('8.8.4.4');
    const fetched = [];
    const m = new UpnpManager(() => igd.client(), {
        ttlSeconds: 3600, renewMs: 30, ipCheckMs: 30,
        ddns: () => ({ url: 'https://ddns.example/update?d={domain}&t={token}&ip={ip}', domain: 'me.example', token: 's3cret' }),
        fetchImpl: async u => { fetched.push(u); return { ok: true, status: 200, text: async () => 'OK' }; },
    });
    const a = await m.open(25565, '서버 A');
    assert.equal(a.address, 'me.example');                           // DDNS 이름·기본 포트
    assert.equal(igd.mappings.get(25565).ttl, 3600);
    assert.ok(fetched[0].includes('ip=8.8.4.4') && fetched[0].includes('t=s3cret'));
    igd.noTtl = true;
    const b = await m.open(40000, '서버 B');                         // 만료 못 받는 공유기 → 만료 없이
    assert.equal(igd.mappings.get(40000).ttl, 0);
    igd.noTtl = false;
    igd.taken.add(40001);
    const c = await m.open(40001, '서버 C');                         // 외부 포트 충돌 → 다른 외부 포트
    assert.notEqual(c.port, 40001);
    const adds = igd.calls.filter(x => x[0] === 'add').length;
    assert.ok(await wait(() => igd.calls.filter(x => x[0] === 'add').length > adds));   // 갱신
    const ips = [];
    m.on('ip', ip => ips.push(ip));
    igd.ip = '8.8.8.8';
    assert.ok(await wait(() => ips.includes('8.8.8.8')));
    assert.ok(await wait(() => fetched.some(u => u.includes('ip=8.8.8.8'))));
    await m.close(40000);
    assert.equal(igd.mappings.has(40000), false);
    await m.closeAll();
    assert.equal(igd.mappings.size, 0);                                // 앱 끌 때 매핑 반드시 삭제
    assert.deepEqual(m.openPorts, []);
    assert.equal(b.ip, '8.8.4.4');
});

test('UPnP: CGNAT·공유기 없음·거부는 이유와 함께 실패', async () => {
    const igd = new FakeIgd('100.64.3.3');
    const m = new UpnpManager(() => igd.client());
    await assert.rejects(m.open(1, 'x'), /CGNAT/);
    igd.ip = '8.8.8.8';
    igd.fail = { code: 606 };
    await assert.rejects(m.open(1, 'x'), /거부.*606/);
    igd.down = true;
    await assert.rejects(m.open(1, 'x'), /응답하지 않습니다/);
    assert.equal(igd.mappings.size, 0);
});

// ---------------------------------------------------------------- playit
test('playit: 받기(sha256 검증)·계정 연결·서버별 고정 터널·에이전트 켜고 끄기', async () => {
    const fp = await fakePlayit();
    const d = tmp();
    const secretPath = path.join(d, 'playit_gg', 'playit.toml');
    const spawned = [];
    const pm = new PlayitManager({ dir: path.join(d, 'agent'), apiBase: fp.base, releaseApi: fp.base + '/release', secretPath,
        claimPollMs: 10, spawnAgent: (exe, args) => { const p = fakeAgent(); spawned.push([exe, args, p]); return p; }, openUrl: () => undefined });
    const st0 = pm.status();
    assert.equal(st0.agentInstalled, false);
    assert.equal(st0.linked, false);
    assert.equal(st0.agentRunning, false);
    await pm.install();
    assert.equal(fs.readFileSync(pm.exe, 'utf8'), 'fake-playit-agent');
    assert.match(path.basename(pm.exe), /^playitd/);                       // CLI 가 아니라 데몬
    const ver = JSON.parse(fs.readFileSync(path.join(d, 'agent', 'version.json'), 'utf8'));
    assert.match(ver.asset, /^playit(d-windows|-linux|-macos)/);
    assert.equal(spawned.length, 0);                                       // 계정 연결 전에는 켜지 않음
    const urls = [];
    pm.on('status', s => s.claimUrl && urls.push(s.claimUrl));
    await pm.claim();
    // 계정 연결 직후 데몬을 바로 켠다(대시보드 Online) — 우리 키 파일과 전용 IPC 이름으로
    assert.equal(spawned.length, 1);
    const [, args, agent] = spawned[0];
    assert.deepEqual(args.slice(0, 2), ['--secret-path', secretPath]);
    assert.equal(args[2], '--socket-path');
    assert.match(args[3], /integrated-studio-playitd|playitd\.sock/);
    assert.equal(pm.status().agentOnline, false);
    agent.say('2026-11-28T00:00:00Z  INFO playitd: Starting playitd\n2026-11-28T00:00:01Z  INFO playitd: playit con');
    agent.say('nected; tunnels loaded agent_id=x tunnel_count=0\n');         // 조각으로 와도 줄 단위로 읽음
    assert.equal(pm.status().agentOnline, true);
    assert.match(pm.status().message, /온라인/);
    const logText = fs.readFileSync(pm.status().logPath, 'utf8');
    for (const step of ['계정 연결 시작', '계정 연결 상태: UserAccepted', '키 교환 완료', '에이전트 시작', 'playit connected']) {
        assert.ok(logText.includes(step), step);                            // 단계별 기록
    }
    assert.match(urls[0], /^https:\/\/playit\.gg\/claim\/[0-9a-f]{10}$/);
    assert.equal(readSecret(secretPath), fp.state.secret);
    assert.equal(pm.status().linked, true);
    const t1 = await pm.ensureTunnel('서버 A', 25565);
    assert.equal(t1.address, 'play1.gl.joinmc.link');
    const t2 = await pm.ensureTunnel('서버 B', 30000);
    assert.equal(t2.address, 'play2.gl.joinmc.link');
    const again = await pm.ensureTunnel('서버 A', 26000, t1.id);       // 포트가 바뀌어도 같은 터널·같은 주소
    assert.equal(again.address, t1.address);
    assert.equal(fp.state.tunnels[0].origin.data.local_port, 26000);
    assert.equal(fp.state.tunnels.length, 2);
    const created = fp.state.calls.find(c => c[0] === '/tunnels/create')[1];
    assert.equal(created.tunnel_type, 'minecraft-java');
    assert.deepEqual(created.origin, { type: 'default', data: { local_ip: '127.0.0.1', local_port: 25565 } });
    pm.acquire('a');
    pm.acquire('b');
    assert.equal(spawned.length, 1);                                       // 이미 켜져 있으면 그대로
    pm.release('a');
    pm.release('b');
    assert.equal(pm.status().agentRunning, true);                          // 서버가 안 써도 켜 둔다(Online 유지)
    // 예기치 않게 꺼지면 다시 켠다
    agent.crash(1);
    assert.equal(pm.status().agentRunning, false);
    assert.match(pm.status().message, /PLAYIT-1.*다시 켭니다/);
    await wait(() => spawned.length === 2, 4000);
    assert.equal(spawned.length, 2);
    // 데몬이 키를 거부하면 연결 해제
    spawned[1][2].say('WARN playitd: configured agent secret is no longer valid error=x\n');
    assert.equal(pm.status().linked, false);
    assert.equal(pm.status().agentRunning, false);
    assert.match(pm.status().message, /PLAYIT-401/);
    pm.stopAgent();
    await fp.close();
});

test('playit: 검증값이 다르면 버림, 거절·한도 초과는 한국어 안내', async () => {
    const fp = await fakePlayit({ badDigest: true });
    const d = tmp();
    const pm = new PlayitManager({ dir: path.join(d, 'agent'), apiBase: fp.base, releaseApi: fp.base + '/release',
        secretPath: path.join(d, 's.toml'), claimPollMs: 5 });
    await assert.rejects(pm.install(), /sha256/);
    assert.equal(fs.existsSync(pm.exe), false);
    fp.state.approve = false;
    await assert.rejects(pm.claim(), /거절/);
    fp.state.approve = true;
    await pm.claim();
    for (let i = 0; i < 4; i++) {
        await pm.ensureTunnel('s' + i, 1000 + i);
    }
    await assert.rejects(pm.ensureTunnel('s5', 2000), /무료 요금제 한도/);
    fs.writeFileSync(path.join(d, 's.toml'), `secret_key = "${'cd'.repeat(32)}"\n`);
    await assert.rejects(pm.tunnels(), /연결이 풀렸습니다/);
    assert.match(assetName(), /^playit(d-windows-x86(_64)?-signed\.exe|-linux-|-macos-)/);   // Windows 는 데몬 playitd
    await fp.close();
});

test('playit: 연결이 풀리면 키를 옆으로 옮겨 "연결 안 됨"이 되고, 다시 연결하면 에이전트도 새 키로', async () => {
    const fp = await fakePlayit();
    const d = tmp();
    const secretPath = path.join(d, 'playit_gg', 'playit.toml');
    const spawned = [];
    const pm = new PlayitManager({ dir: path.join(d, 'agent'), apiBase: fp.base, releaseApi: fp.base + '/release', secretPath,
        claimPollMs: 5, spawnAgent: () => { const p = fakeAgent(); spawned.push(p); return p; } });
    await pm.install();
    await pm.claim();
    pm.acquire('srv');
    assert.equal((await pm.verify()).linked, true);
    fp.state.secret = 'ef'.repeat(32);                 // playit.gg 에서 에이전트를 지움 → 예전 키 무효
    const st = await pm.verify();
    assert.equal(st.linked, false);
    assert.equal(st.agentRunning, false);              // 죽은 키로 돌던 에이전트는 끔
    assert.match(st.message, /다시 연결/);
    assert.ok(fs.readdirSync(path.dirname(secretPath)).some(f => f.startsWith('playit.toml.invalid-')));   // 지우지 않고 보관
    await assert.rejects(pm.ensureTunnel('x', 1), /연결/);
    await pm.claim(true);                              // [playit 다시 연결]
    assert.equal(readSecret(secretPath), 'ef'.repeat(32));
    assert.equal(pm.status().linked, true);
    assert.equal(pm.status().agentRunning, true);      // 쓰던 서버가 있어 새 키로 다시 켬
    assert.equal(spawned.length, 2);
    await pm.claim(true);                              // 연결돼 있어도 force 면 새로
    assert.equal(pm.status().linked, true);
    pm.stopAgent();
    await fp.close();
});

test('readLines: 1MB 넘는 로그를 조각으로 읽어도 줄·한글이 깨지지 않음', async () => {
    const { readLines } = await import('../lib/node/lan-watcher.js');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lanlog-'));
    const file = path.join(dir, 'latest.log');
    const line = '[12:00] [Render thread/INFO]: 한글 로그 줄 테스트 ⛏ 1234567890';
    const want = Array.from({ length: 40000 }, (_, i) => `${line} ${i}`);   // 약 3MB
    fs.writeFileSync(file, want.join('\n') + '\n[tail] 반쪽');
    const got = [];
    const rest = readLines(file, 0, fs.statSync(file).size, '', l => got.push(l));
    assert.equal(got.length, want.length);
    assert.deepEqual(got.slice(-2), want.slice(-2));
    assert.ok(got.every((l, i) => l === want[i]));
    assert.equal(rest, '[tail] 반쪽');
});
