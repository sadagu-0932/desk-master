// P2P 핵심 시험(프로토콜 v1) — hyperdht 로컬 테스트넷(인터넷 없음)에서 가짜 TCP 에코 서버로.
// 실행: npm test -w integrated-studio-p2p-server
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import crypto from 'node:crypto';
import DHT from 'hyperdht';
import createTestnet from 'hyperdht/testnet.js';
import {
    HostTunnel, JoinTunnel, P2PError, decodeCode, encodeCode, newSeed, startRelay, keyPairFromSeed, parseRelays,
} from '../lib/node/p2p-core.js';

let testnet;
const cleanups = [];

before(async () => {
    testnet = await createTestnet(4);
});

after(async () => {
    for (const c of cleanups.reverse()) {
        await c();
    }
    await testnet.destroy();
});

function node() {
    const n = testnet.createNode();
    cleanups.push(() => n.destroy({ force: true }));
    return n;
}

/** 받은 데이터 앞에 tag 를 붙여 돌려주는 에코 서버(서버 두 개가 섞이지 않는지 보려고). */
function echoServer(tag = '') {
    return new Promise(resolve => {
        const s = net.createServer(sock => sock.on('data', d => sock.write(Buffer.concat([Buffer.from(tag), d]))).on('error', () => {}));
        s.listen(0, '127.0.0.1', () => {
            cleanups.push(() => new Promise(r => s.close(() => r())));
            resolve(s.address().port);
        });
    });
}

function hostWith(seed, port, name = 'srv', mode = 'dedicated') {
    return new HostTunnel(node(), {
        seed, target: { host: '127.0.0.1', port },
        info: () => ({ name, version: '26.3', loader: 'vanilla', mode, max: 10 }),
    });
}

async function host(port, name = 'srv') {
    const h = hostWith(newSeed(), port, name);
    await h.start();
    cleanups.push(() => h.stop());
    return h;
}

async function join(code, opts = {}) {
    const j = new JoinTunnel(node(), { code, connectTimeout: 20000, reconnectAttempts: 4, pingInterval: 300, ...opts });
    await j.start();
    cleanups.push(() => j.stop());
    return j;
}

/** 로컬 포트로 접속해 payload 를 보내고 expectLen 바이트를 받는다. */
function roundtrip(port, payload, expectLen) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        let got = 0;
        const c = net.connect(port, '127.0.0.1', () => c.write(payload));
        c.on('data', d => {
            chunks.push(d);
            got += d.length;
            if (got >= expectLen) {
                c.destroy();
                resolve(Buffer.concat(chunks));
            }
        });
        c.on('error', reject);
        setTimeout(() => reject(new Error('시간 초과')), 20000);
    });
}

const waitFor = async (fn, ms = 15000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
        if (await fn()) {
            return true;
        }
        await new Promise(r => setTimeout(r, 100));
    }
    return false;
};

test('코드: "IS1-" + z-base-32, 왕복, 공백·대소문자·하이픈 무시, 다른 버전·틀린 코드는 한국어 오류', () => {
    const kp = keyPairFromSeed(newSeed());
    const code = encodeCode(kp.publicKey);
    assert.match(code, /^IS1-[ybndrfg8ejkmcpqxot1uwisza345h769]{52}$/);
    assert.deepEqual(decodeCode(code), kp.publicKey);
    const body = code.slice(4);
    const messy = ' is1-' + body.toUpperCase().replace(/(.{13})/g, '$1 ') + ' \n';
    assert.deepEqual(decodeCode(messy), kp.publicKey);
    assert.deepEqual(decodeCode(body), kp.publicKey);                 // 접두어 없이 붙여 넣어도
    assert.throws(() => decodeCode('IS2-' + body), err => err.code === 'PROTO_MISMATCH' && /다른 버전/.test(err.message));
    assert.throws(() => decodeCode('IS1-abc'), err => err instanceof P2PError && /참가 코드/.test(err.message));
    assert.deepEqual(parseRelays(`${code}, nope`), [kp.publicKey]);
});

test('같은 시드 = 같은 코드(다시 열어도 같은 코드)', () => {
    const seed = newSeed();
    assert.equal(HostTunnel.codeFor(seed), encodeCode(keyPairFromSeed(Buffer.from(seed)).publicKey));
});

test('호스트 1 + 참가자 3: 데이터가 정확히 오가고, 정보 요청으로 서버 정보·접속자 수·핑', async () => {
    const port = await echoServer();
    const h = await host(port, '우리 서버');
    const joins = await Promise.all([join(h.code), join(h.code), join(h.code)]);
    for (const j of joins) {
        assert.equal(j.status.state, 'connected');
        assert.equal(j.status.mode, 'direct');
        assert.deepEqual(j.status.info, { proto: 1, name: '우리 서버', version: '26.3', loader: 'vanilla', mode: 'dedicated', players: 0, max: 10 });
        assert.ok(j.status.localPort > 0);
        assert.equal(typeof j.status.rtt, 'number');
    }
    await Promise.all(joins.map(async (j, i) => {
        const payload = crypto.randomBytes(256 * 1024 + i);   // 큰 데이터(조각나도 순서·내용 그대로)
        const back = await roundtrip(j.status.localPort, payload, payload.length);
        assert.ok(back.equals(payload), `참가자 ${i} 데이터 불일치`);
    }));
    assert.ok(joins[0].status.traffic.bytesIn > 0 && h.traffic.bytesIn > 0, '트래픽 집계');
    // 게임 연결을 열어 둔 동안 접속자 수가 정보 응답에 반영된다
    const holds = await Promise.all(joins.map(j => new Promise(res => {
        const c = net.connect(j.status.localPort, '127.0.0.1', () => { c.write('x'); res(c); });
    })));
    assert.ok(await waitFor(() => h.info().players === 3), '호스트 접속자 3');
    assert.ok(await waitFor(() => joins.every(j => j.status.info.players === 3)), '참가자에게도 접속자 수 전달(정보 요청)');
    holds.forEach(c => c.destroy());
    // 한 참가자의 게임 연결 여러 개(서버 목록 핑 + 접속)도 각각 독립
    const [a, b] = await Promise.all([
        roundtrip(joins[0].status.localPort, Buffer.from('ping-1'), 6),
        roundtrip(joins[0].status.localPort, Buffer.from('ping-2'), 6),
    ]);
    assert.equal(a.toString(), 'ping-1');
    assert.equal(b.toString(), 'ping-2');
});

test('서버 2개 동시: 터널이 섞이지 않는다', async () => {
    const h1 = await host(await echoServer('A:'), '서버1');
    const h2 = await host(await echoServer('B:'), '서버2');
    assert.notEqual(h1.code, h2.code);
    const j1 = await join(h1.code);
    const j2 = await join(h2.code);
    assert.notEqual(j1.status.localPort, j2.status.localPort);
    const [r1, r2] = await Promise.all([
        roundtrip(j1.status.localPort, Buffer.from('hello'), 7),
        roundtrip(j2.status.localPort, Buffer.from('hello'), 7),
    ]);
    assert.equal(r1.toString(), 'A:hello');
    assert.equal(r2.toString(), 'B:hello');
    assert.equal(j1.status.info.name, '서버1');
    assert.equal(j2.status.info.name, '서버2');
});

test('같은 포트를 먼저 시도(다시 참가해도 같은 주소)', async () => {
    const h = await host(await echoServer());
    const j1 = await join(h.code);
    const port = j1.status.localPort;
    await j1.stop();
    const j2 = await join(h.code, { preferredPort: port });
    assert.equal(j2.status.localPort, port);
});

test('호스트가 잠깐 끊겼다 같은 코드로 다시 열리면 참가자가 다시 붙는다', async () => {
    const port = await echoServer();
    const seed = newSeed();
    const h1 = hostWith(seed, port, 's', 'lan');
    await h1.start();
    const j = await join(h1.code, { pingInterval: 200, connectTimeout: 2000, reconnectAttempts: 50 });
    const states = [];
    j.on('status', s => states.push(s.state));
    await h1.stop();
    assert.ok(await waitFor(() => states.includes('reconnecting'), 30000), '끊김 감지');
    const h2 = hostWith(seed, port, 's', 'lan');
    await h2.start();
    cleanups.push(() => h2.stop());
    assert.ok(await waitFor(() => j.status.state === 'connected' && states.at(-1) === 'connected', 30000), '재연결');
    const back = await roundtrip(j.status.localPort, Buffer.from('again'), 5);
    assert.equal(back.toString(), 'again');
});

test('호스트가 서버를 닫으면 참가자 정리(로컬 포트 닫힘, 이유 안내)', async () => {
    const h = await host(await echoServer());
    const j = await join(h.code, { pingInterval: 200, connectTimeout: 2000, reconnectAttempts: 2 });
    const port = j.status.localPort;
    const closed = new Promise(r => j.once('closed', r));
    await h.stop();
    const reason = await closed;
    assert.match(reason, /연결할 수 없습니다/);
    assert.equal(j.status.state, 'closed');
    await assert.rejects(() => new Promise((res, rej) => {
        const c = net.connect(port, '127.0.0.1', () => { c.destroy(); res(); });
        c.on('error', rej);
    }));
});

test('중계 노드로 연결(직접 연결 대신)', async () => {
    const relayNode = node();
    const relay = await startRelay(relayNode);
    cleanups.push(() => relay.close());
    const h = await host(await echoServer('R:'));
    const j = await join(h.code, { relays: [relay.publicKey], forceRelay: true });
    assert.equal(j.status.mode, 'relay');
    const back = await roundtrip(j.status.localPort, Buffer.from('via-relay'), 11);
    assert.equal(back.toString(), 'R:via-relay');
});

test('직접 연결 실패 → 자동으로 중계로 전환', async () => {
    const relayNode = node();
    const relay = await startRelay(relayNode);
    cleanups.push(() => relay.close());
    const h = await host(await echoServer());
    const n = node();
    const realConnect = n.connect.bind(n);
    // 중계 없이 여는 연결은 홀펀칭 실패로 만든다
    n.connect = (key, opts) => {
        if (!opts?.relayThrough) {
            const s = realConnect(key, opts);
            setImmediate(() => s.destroy(Object.assign(new Error('Cannot holepunch to remote'), { code: 'CANNOT_HOLEPUNCH' })));
            return s;
        }
        return realConnect(key, opts);
    };
    const logs = [];
    const j = new JoinTunnel(n, { code: h.code, relays: [relay.publicKey], connectTimeout: 20000 });
    j.on('log', l => logs.push(l));
    cleanups.push(() => j.stop());
    await j.start();
    assert.equal(j.status.mode, 'relay');
    assert.ok(logs.some(l => l.includes('중계로 다시 시도')));
    const back = await roundtrip(j.status.localPort, Buffer.from('fallback'), 8);
    assert.equal(back.toString(), 'fallback');
});

test('직접 연결 실패 + 중계 없음 → 한국어로 이유 안내', async () => {
    const h = await host(await echoServer());
    const n = node();
    const realConnect = n.connect.bind(n);
    n.connect = (key, opts) => {
        const s = realConnect(key, opts);
        setImmediate(() => s.destroy(Object.assign(new Error('x'), { code: 'HOLEPUNCH_DOUBLE_RANDOMIZED_NATS' })));
        return s;
    };
    const j = new JoinTunnel(n, { code: h.code, connectTimeout: 5000 });
    await assert.rejects(() => j.start(), err => {
        assert.ok(err instanceof P2PError);
        assert.match(err.message, /NAT/);
        assert.match(err.message, /중계 노드가 설정돼 있지 않아/);
        return true;
    });
    await j.stop();
});

test('없는 호스트 코드 → "호스트를 찾지 못했습니다"', async () => {
    const code = encodeCode(keyPairFromSeed(newSeed()).publicKey);
    const j = new JoinTunnel(node(), { code, connectTimeout: 20000 });
    await assert.rejects(() => j.start(), err => err instanceof P2PError && /찾지 못했습니다|실패/.test(err.message));
    await j.stop();
});

// ================================================================ 프로토콜 v1 호환(참가 전용 앱과 같은 바이트)
function rawConnect(n, publicKey, firstByte) {
    return new Promise((resolve, reject) => {
        const s = n.connect(publicKey);
        s.once('open', () => { s.write(Buffer.from([firstByte])); resolve(s); });
        s.once('error', reject);
    });
}

test('v1 호환: 우리 호스트 ← 원시 v1 클라이언트(0x02 정보 한 줄 후 종료, 0x01 게임 터널, 그 밖은 끊음)', async () => {
    const h = await host(await echoServer('G:'), '호환 서버');
    const n = node();
    const pk = decodeCode(h.code);
    const s = await rawConnect(n, pk, 0x02);
    const text = await new Promise((res, rej) => {
        let buf = '';
        s.on('data', d => { buf += d; });
        s.on('end', () => res(buf));
        s.on('error', rej);
    });
    s.destroy();
    assert.ok(text.endsWith('\n') && text.indexOf('\n') === text.length - 1, 'JSON 한 줄');
    const info = JSON.parse(text);
    assert.deepEqual(Object.keys(info).sort(), ['loader', 'max', 'mode', 'name', 'players', 'proto', 'version']);
    assert.equal(info.proto, 1);
    assert.equal(info.name, '호환 서버');
    assert.ok(['dedicated', 'lan', 'external'].includes(info.mode));
    const g = await rawConnect(n, pk, 0x01);
    const echoed = await new Promise(res => {
        g.once('data', d => res(d.toString()));
        g.write('hello');
    });
    g.destroy();
    assert.equal(echoed, 'G:hello');
    const x = await rawConnect(n, pk, 0x07);
    await new Promise(res => x.once('close', res));
});

/** 프로토콜 문서대로만 만든 원시 v1 호스트(참가 전용 앱의 test-host 자리). */
async function rawHost(info, target) {
    const n = node();
    const kp = DHT.keyPair();
    const server = n.createServer({}, sock => {
        sock.on('error', () => {});
        sock.once('data', d => {
            if (d[0] === 0x02) {
                sock.end(JSON.stringify(info) + '\n');
            } else if (d[0] === 0x01) {
                const t = net.connect(target, '127.0.0.1');
                t.on('error', () => sock.destroy());
                if (d.length > 1) {
                    t.write(d.subarray(1));
                }
                sock.pipe(t).pipe(sock);
            } else {
                sock.destroy();
            }
        });
    });
    await server.listen(kp);
    cleanups.push(() => server.close());
    return encodeCode(kp.publicKey);
}

test('v1 호환: 원시 v1 호스트 → 우리 참가자(정보·게임 터널, mode "external")', async () => {
    const code = await rawHost({ proto: 1, name: '외부 호스트', version: '26.3', loader: 'vanilla', mode: 'external', players: 2, max: 20 },
        await echoServer('X:'));
    const j = await join(code);
    assert.equal(j.status.info.mode, 'external');
    assert.equal(j.status.info.max, 20);
    const back = await roundtrip(j.status.localPort, Buffer.from('hi'), 4);
    assert.equal(back.toString(), 'X:hi');
});

test('v1 호환: proto 가 다른 호스트는 거부하고 안내', async () => {
    const code = await rawHost({ proto: 2, name: '미래 호스트', version: '26.3', loader: 'vanilla', mode: 'dedicated', players: 0, max: 10 },
        await echoServer());
    const j = new JoinTunnel(node(), { code, connectTimeout: 20000 });
    await assert.rejects(() => j.start(), err => {
        assert.equal(err.code, 'PROTO_MISMATCH');
        assert.match(err.message, /프로토콜 버전\(2\)/);
        assert.match(err.message, /업데이트/);
        return true;
    });
    await j.stop();
    assert.equal(j.status.localPort, undefined, '로컬 포트를 열지 않는다');
});
