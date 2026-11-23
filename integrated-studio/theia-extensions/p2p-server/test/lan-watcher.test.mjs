// 방식 B: LAN 공개 감지 — 26.3 실제 로그 문구로 만든 샘플 로그.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { LanWatcher, currentLanState, parseLanLine } from '../lib/node/lan-watcher.js';

const SAMPLE = [
    '[14:02:11] [Render thread/INFO]: Setting user: Player',
    '[14:02:30] [Server thread/INFO]: Starting integrated minecraft server version 26.3',
    '[14:02:33] [Server thread/INFO]: Player joined the game',
    '[14:03:01] [Server thread/INFO]: Published LAN server on port 53419',
    // 채팅 로그(게임 언어에 따라 바뀜)는 쓰지 않는다
    '[14:03:01] [Render thread/INFO]: [System] [CHAT] 로컬 게임이 53419 포트에서 열렸습니다',
].join('\n') + '\n';

test('한 줄 해석: 공개·공개 끝·월드 나감·게임 종료·크래시', () => {
    assert.deepEqual(parseLanLine('[14:03:01] [Server thread/INFO]: Published LAN server on port 53419'), { type: 'open', port: 53419 });
    assert.equal(parseLanLine('[14:05:00] [Server thread/INFO]: Unpublishing integrated server (was on port 53419)').type, 'close');
    assert.match(parseLanLine('[14:06:00] [Server thread/INFO]: Stopping singleplayer server as player logged out').reason, /나갔습니다/);
    assert.equal(parseLanLine('[14:06:01] [Server thread/INFO]: Stopping server').type, 'close');
    assert.match(parseLanLine('[14:07:00] [Render thread/INFO]: Stopping!').reason, /껐습니다/);
    // 채팅으로 문구를 흉내 내도 맞지 않는다(줄 머리 고정)
    assert.equal(parseLanLine('[14:07:00] [Render thread/INFO]: [System] [CHAT] <Steve> [x/INFO]: Published LAN server on port 1'), undefined);
    assert.equal(parseLanLine('[14:07:00] [Render thread/INFO]: [CHAT] <Steve> Stopping server'), undefined);
    // Fabric 로그 형식
    assert.deepEqual(parseLanLine('[14:03:01] [Server thread/INFO] (Minecraft) Published LAN server on port 4242'), { type: 'open', port: 4242 });
    assert.equal(parseLanLine('[14:02:30] [Server thread/INFO]: Starting integrated minecraft server version 26.3'), undefined);
    assert.equal(parseLanLine('<Steve> Stopping server'), undefined);   // 채팅으로 흉내 낸 문구는 무시
});

test('로그 전체로 지금 상태', () => {
    assert.equal(currentLanState(SAMPLE), 53419);
    assert.equal(currentLanState(SAMPLE + '[14:06:00] [Server thread/INFO]: Stopping singleplayer server as player logged out\n'), undefined);
    assert.equal(currentLanState(''), undefined);
});

async function waitFor(fn, ms = 5000) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
        if (fn()) {
            return true;
        }
        await new Promise(r => setTimeout(r, 30));
    }
    return false;
}

test('따라 읽기: 공개 → 월드 나감 → 다시 공개 → 게임 새로 켬', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lan-'));
    const log = path.join(dir, 'latest.log');
    fs.writeFileSync(log, '[14:02:11] [Render thread/INFO]: Setting user: Player\n');
    const w = new LanWatcher(log, 30);
    const events = [];
    w.on('open', p => events.push(['open', p]));
    w.on('close', r => events.push(['close', r]));
    w.start();
    fs.appendFileSync(log, '[14:03:01] [Server thread/INFO]: Published LAN server on port 50001\n');
    assert.ok(await waitFor(() => events.length === 1));
    assert.deepEqual(events[0], ['open', 50001]);
    assert.equal(w.openPort, 50001);
    fs.appendFileSync(log, '[14:06:00] [Server thread/INFO]: Stopping singleplayer server as player logged out\n[14:06:00] [Server thread/INFO]: Stopping server\n');
    assert.ok(await waitFor(() => events.length === 2));
    assert.equal(events[1][0], 'close');                    // 닫힘은 한 번만
    fs.appendFileSync(log, '[14:08:00] [Server thread/INFO]: Published LAN server on port 50002\n');
    assert.ok(await waitFor(() => events.length === 3));
    assert.deepEqual(events[2], ['open', 50002]);
    // 게임을 새로 켜서 latest.log 가 교체됨
    fs.rmSync(log);
    fs.writeFileSync(log, '[15:00:00] [Render thread/INFO]: Setting user: Player\n');
    assert.ok(await waitFor(() => events.length === 4));
    assert.equal(events[3][0], 'close');
    w.stop();
});

test('이미 공개된 상태에서 감시를 시작해도 바로 연다', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lan-'));
    const log = path.join(dir, 'latest.log');
    fs.writeFileSync(log, SAMPLE);
    const w = new LanWatcher(log, 30);
    let opened;
    w.on('open', p => { opened = p; });
    w.start();
    assert.equal(opened, 53419);
    fs.appendFileSync(log, '[14:07:00] [Render thread/INFO]: Stopping!\n');
    let closed;
    w.on('close', r => { closed = r; });
    assert.ok(await waitFor(() => closed !== undefined));
    assert.match(closed, /껐습니다/);
    w.stop();
});
