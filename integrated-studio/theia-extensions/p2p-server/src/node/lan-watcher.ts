/**
 * M10 방식 B: 싱글플레이 "LAN 에 공개" 감지.
 *
 * 인스턴스의 logs/latest.log 를 따라 읽는다. 문구는 26.3 jar 의 실제 로그 문자열에서 가져왔다(게임 언어와 무관한 로그):
 *   IntegratedServer: "Published LAN server on port {}"            → 공개됨(포트)
 *   IntegratedServer: "Unpublishing integrated server (was on port {})" → 공개 끝
 *   ServerCommonPacketListenerImpl: "Stopping singleplayer server as player logged out" → 월드에서 나감
 *   MinecraftServer: "Stopping server"                               → 내장 서버 멈춤
 *   Minecraft: "Stopping!"                                           → 게임 종료
 * 파일이 교체되면(게임을 새로 켬) 처음부터 다시 읽는다. 파일을 열어 두지 않는다(게임의 로그 교체를 막지 않게).
 */
import { EventEmitter } from 'events';
import * as fs from 'fs';

/** 줄 머리: "[시간] [스레드/레벨]: " (Fabric 은 "[시간] [스레드/레벨] (로거) "). 채팅으로 문구를 흉내 내도 맞지 않게 줄 처음에 고정. */
const HEAD = String.raw`^\[[^\]]*\] \[[^\]]+\](?: \([^)]*\))?:? `;
export const PUBLISH_RE = new RegExp(HEAD + String.raw`Published LAN server on port (\d{1,5})\s*$`);
export const UNPUBLISH_RE = new RegExp(HEAD + String.raw`Unpublishing integrated server \(was on port (\d{1,5})\)\s*$`);
export const CLOSE_RES: Array<[RegExp, string]> = [
    [new RegExp(HEAD + String.raw`Stopping singleplayer server as player logged out\s*$`), '월드에서 나갔습니다'],
    [new RegExp(HEAD + String.raw`Stopping server\s*$`), '월드를 닫았습니다'],
    [new RegExp(HEAD + String.raw`Stopping!\s*$`), '게임을 껐습니다'],
    [/Game crashed!|#@!@# Game crashed/, '게임이 멈췄습니다(크래시)'],
];

export type LanEvent = { type: 'open'; port: number } | { type: 'close'; reason: string };

/** 한 줄을 해석한다(시험·재사용용). */
export function parseLanLine(line: string): LanEvent | undefined {
    let m = PUBLISH_RE.exec(line);
    if (m) {
        return { type: 'open', port: Number(m[1]) };
    }
    m = UNPUBLISH_RE.exec(line);
    if (m) {
        return { type: 'close', reason: 'LAN 공개를 끝냈습니다' };
    }
    for (const [re, reason] of CLOSE_RES) {
        if (re.test(line)) {
            return { type: 'close', reason };
        }
    }
    return undefined;
}

/** 로그 전체에서 지금 상태(마지막으로 열린 포트, 그 뒤 닫혔는지). */
export function currentLanState(text: string): number | undefined {
    let port: number | undefined;
    for (const line of text.split(/\r?\n/)) {
        const ev = parseLanLine(line);
        if (ev?.type === 'open') {
            port = ev.port;
        } else if (ev?.type === 'close') {
            port = undefined;
        }
    }
    return port;
}

/**
 * 이벤트: 'open'(port) — LAN 에 공개됨, 'close'(reason) — 공개가 끝남
 */
export class LanWatcher extends EventEmitter {
    protected timer: NodeJS.Timeout | undefined;
    protected pos = 0;
    protected ident: string | undefined;
    protected buf = '';
    protected port: number | undefined;

    constructor(readonly logFile: string, protected readonly interval = 500) {
        super();
    }

    get openPort(): number | undefined {
        return this.port;
    }

    start(): void {
        // 이미 공개된 상태에서 시작했으면 바로 알린다
        try {
            const text = fs.readFileSync(this.logFile, 'utf8');
            const st = fs.statSync(this.logFile);
            this.pos = st.size;
            this.ident = `${st.dev}:${st.ino}:${st.birthtimeMs}`;
            const port = currentLanState(text);
            if (port) {
                this.set({ type: 'open', port });
            }
        } catch {
            this.pos = 0;
        }
        this.timer = setInterval(() => this.poll(), this.interval);
    }

    stop(): void {
        if (this.timer) {
            clearInterval(this.timer);
        }
        this.timer = undefined;
    }

    protected set(ev: LanEvent): void {
        if (ev.type === 'open') {
            if (this.port === ev.port) {
                return;
            }
            this.port = ev.port;
            this.emit('open', ev.port);
        } else if (this.port !== undefined) {
            this.port = undefined;
            this.emit('close', ev.reason);
        }
    }

    poll(): void {
        let st: fs.Stats;
        try {
            st = fs.statSync(this.logFile);
        } catch {
            return;
        }
        const ident = `${st.dev}:${st.ino}:${st.birthtimeMs}`;
        if (this.ident !== undefined && (ident !== this.ident || st.size < this.pos)) {
            // 게임을 새로 켜서 로그가 새로 생김 → 이전 공개는 끝난 것
            this.pos = 0;
            this.buf = '';
            this.set({ type: 'close', reason: '게임을 다시 켰습니다' });
        }
        this.ident = ident;
        if (st.size <= this.pos) {
            return;
        }
        let chunk: Buffer;
        try {
            const fd = fs.openSync(this.logFile, 'r');
            try {
                chunk = Buffer.alloc(st.size - this.pos);
                fs.readSync(fd, chunk, 0, chunk.length, this.pos);
            } finally {
                fs.closeSync(fd);
            }
        } catch {
            return;
        }
        this.pos = st.size;
        this.buf += chunk.toString('utf8');
        const lines = this.buf.split(/\r?\n/);
        this.buf = lines.pop() ?? '';
        for (const line of lines) {
            const ev = parseLanLine(line);
            if (ev) {
                this.set(ev);
            }
        }
    }
}
