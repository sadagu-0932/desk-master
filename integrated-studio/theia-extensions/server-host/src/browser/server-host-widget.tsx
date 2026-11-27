import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { ClipboardService } from '@theia/core/lib/browser/clipboard-service';
import { LOADER_LABELS } from 'integrated-studio-launcher-core/lib/common';
import { PROVIDER_LABEL, ProviderId, ServerError, ServerView } from '../common/index.js';
import { ServerHostStore } from './server-host-store.js';
import { ServerHostCommands } from './server-host-commands.js';

const STATE_LABEL: Record<string, string> = {
    'stopped': '꺼짐', 'needs-eula': 'EULA 동의 필요', 'preparing': '서버 준비 중(jar 받는 중)', 'starting': '서버 켜는 중',
    'waiting-lan': 'LAN 공개 기다리는 중', 'running': '켜짐', 'error': '오류',
};
const KIND_LABEL: Record<string, string> = { dedicated: '전용 서버', lan: '싱글 LAN 공개', external: '외부 서버' };
const ADDR_LABEL: Record<string, string> = { closed: '주소 닫힘', opening: '주소 여는 중', open: '주소 열림', failed: '주소 열기 실패' };

/** 서버 패널: 서버 목록(상태·접속자·주소), 이 PC 의 LAN 월드, playit·DDNS 설정. */
@injectable()
export class ServerHostWidget extends ReactWidget {
    static readonly ID = 'studio-server-host';
    static readonly LABEL = '서버';

    @inject(ServerHostStore) protected readonly store: ServerHostStore;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(ClipboardService) protected readonly clipboard: ClipboardService;

    protected openConsole = new Set<string>();
    protected input = new Map<string, string>();

    @postConstruct()
    protected init(): void {
        this.id = ServerHostWidget.ID;
        this.title.label = ServerHostWidget.LABEL;
        this.title.caption = '서버 열기 — 친구는 멀티플레이에 주소만 넣으면 됩니다';
        this.title.iconClass = codicon('broadcast');
        this.title.closable = true;
        this.addClass('studio-server-host');
        this.toDispose.push(this.store.onDidChange(() => this.update()));
        this.update();
    }

    protected copy(text: string, what: string): void {
        this.clipboard.writeText(text);
        this.messages.info(`${what}을(를) 복사했습니다.`);
    }

    protected async run(fn: () => Promise<unknown>): Promise<void> {
        try {
            await fn();
        } catch (e) {
            this.messages.error(e instanceof Error ? e.message : String(e));
        }
    }

    protected render(): React.ReactNode {
        const { servers, lanGames, playit, upnp } = this.store.snapshot;
        const localLan = lanGames.filter(g => g.local);
        const hosted = new Set(servers.filter(s => s.kind === 'external').map(s => s.gamePort));
        return <div className='sh-root'>
            <div className='sh-actions'>
                <button className='theia-button' onClick={() => this.commands.executeCommand(ServerHostCommands.OPEN_SERVER.id)}>
                    <span className={codicon('broadcast')} aria-hidden='true' /> 서버 열기</button>
                <button className='theia-button secondary' onClick={() => this.commands.executeCommand(ServerHostCommands.IMPORT.id)}>
                    <span className={codicon('cloud-download')} aria-hidden='true' /> 인스턴스 불러오기</button>
            </div>

            <h3>서버 <span className='sh-muted'>{servers.length}개</span></h3>
            {servers.length === 0 && <div className='sh-muted'>아직 없습니다. [서버 열기]로 시작하세요. 친구 쪽에는 프로그램이 필요 없습니다.</div>}
            {servers.map(s => this.renderServer(s))}

            <h3>이 PC 에서 LAN 에 공개된 월드 <span className='sh-muted'>{localLan.length}개</span></h3>
            {localLan.length === 0 && <div className='sh-muted sh-small'>어떤 런처로 열었든 [LAN에 공개]를 누르면 여기에 뜹니다.</div>}
            {localLan.map(g => <div key={g.port} className='sh-lan-row'>
                <span className={codicon('globe')} aria-hidden='true' />
                <span className='sh-name'>{g.motd}</span><span className='sh-muted'>포트 {g.port}</span>
                {hosted.has(g.port)
                    ? <span className='sh-chip'>열림</span>
                    : <button className='theia-button sh-mini' onClick={() => this.commands.executeCommand(ServerHostCommands.OPEN_LAN.id, g.port, g.motd)}>주소 열기</button>}
            </div>)}

            <h3>주소 방식 설정</h3>
            <div className='sh-small sh-setting'>
                <b>playit 중계</b> — {playit.linked ? '계정 연결됨' : '계정 연결 안 됨'} · {playit.agentInstalled ? (playit.agentRunning ? '에이전트 켜짐' : '에이전트 꺼짐') : '에이전트 없음'}
                {!playit.agentInstalled &&
                    <button className='theia-button secondary sh-mini' onClick={() => this.commands.executeCommand(ServerHostCommands.PLAYIT_SETUP.id)}>playit 준비</button>}
                {playit.agentInstalled && !playit.claimUrl &&
                    <button className={'theia-button sh-mini' + (playit.linked ? ' secondary' : '')} title='연결이 풀렸거나 다른 계정으로 바꿀 때'
                        onClick={() => this.commands.executeCommand(ServerHostCommands.PLAYIT_RELINK.id)}>{playit.linked ? '다시 연결' : 'playit 다시 연결'}</button>}
                {playit.linked && <button className='theia-button secondary sh-mini' onClick={() => this.commands.executeCommand(ServerHostCommands.PLAYIT_VERIFY.id)}>연결 확인</button>}
                {playit.claimUrl && <div className='sh-note'>브라우저에서 승인을 기다리는 중: <a href={playit.claimUrl} target='_blank' rel='noreferrer'>{playit.claimUrl}</a></div>}
                {playit.message && <div className='sh-muted'>{playit.message}</div>}
            </div>
            <div className='sh-small sh-setting'>
                <b>UPnP</b> — {upnp.publicIp ? `공인 IP ${upnp.publicIp}` : '아직 열지 않음'} · {upnp.ddnsUrl ? `DDNS ${upnp.ddnsDomain ?? ''} (고정 주소)` : 'DDNS 없음(IP 가 바뀌면 주소도 바뀜)'}
                <button className='theia-button secondary sh-mini' onClick={() => this.commands.executeCommand(ServerHostCommands.DDNS.id)}>DDNS 설정</button>
            </div>
        </div>;
    }

    protected renderServer(s: ServerView): React.ReactNode {
        const on = !['stopped', 'error', 'needs-eula'].includes(s.state);
        const a = s.address;
        const consoleOpen = this.openConsole.has(s.id);
        const players = s.players.length ? s.players.join(', ') : '';
        return <section key={s.id} className={`sh-card state-${s.state} addr-${a.state}`} aria-label={s.name}>
            <div className='sh-card-head'>
                <span className={'sh-dot' + (a.state === 'open' ? ' on' : on ? ' busy' : '')} aria-hidden='true' />
                <b className='sh-name'>{s.name}</b>
                <span className='sh-chip'>{KIND_LABEL[s.kind]}</span>
                <span className='sh-chip'>{STATE_LABEL[s.state] ?? s.state}</span>
            </div>
            <div className='sh-muted sh-small'>
                {s.instanceName ? `${s.instanceName} · ${s.version ?? ''} ${s.loader ? LOADER_LABELS[s.loader] ?? s.loader : ''}` : `이 PC 포트 ${s.gamePort ?? '?'}`}
                {s.kind === 'dedicated' && ` · ${s.onlineMode ? '정품 계정만' : '오프라인 허용'}${s.world ? ` · 월드 ${s.world}` : ''}`}
                {s.gamePort && s.kind !== 'external' ? ` · 포트 ${s.gamePort}` : ''}
            </div>
            {(s.state === 'running' || a.state === 'open') && <div className='sh-small'>
                접속 {s.playersOnline ?? s.players.length}/{s.maxPlayers ?? '?'}명{players && ` — ${players}`}
                {s.motd && <span className='sh-muted'> · {s.motd}</span>}
            </div>}

            <div className={'sh-address ' + a.state}>
                <span className='sh-chip'>{ADDR_LABEL[a.state]}</span>
                {a.state === 'opening' && a.trying && <span className='sh-muted sh-small'>
                    <span className={codicon('loading') + ' codicon-modifier-spin'} aria-hidden='true' /> {PROVIDER_LABEL[a.trying]} 시도 중…</span>}
                {a.state === 'open' && a.address && <>
                    <code className='sh-code' title='친구가 멀티플레이 → 서버 추가에 넣을 주소'>{a.address}</code>
                    <button className='theia-button' onClick={() => this.copy(a.address!, '주소')}>복사</button>
                    {a.provider && <span className='sh-chip via'>{PROVIDER_LABEL[a.provider]}</span>}
                    <span className={'sh-chip ' + (a.fixed ? 'fixed' : 'changing')}>{a.fixed ? '고정 주소' : '매번 바뀜'}</span>
                    <button className='theia-button secondary sh-mini' title='지금 방식을 닫고 다음 방식(UPnP → playit 등)으로 다시 엽니다'
                        onClick={() => this.run(() => this.store.service.nextProvider(s.id))}>친구가 못 들어와요</button>
                </>}
            </div>
            {s.lanAddress && (a.state === 'open' || s.state === 'running') && <div className='sh-small sh-muted'>
                같은 와이파이·공유기에 있는 사람은 <code className='sh-code'>{s.lanAddress}</code>
                <button className='theia-button secondary sh-mini' onClick={() => this.copy(s.lanAddress!, '같은 공유기용 주소')}>복사</button>
                — 집 안에서는 공인 주소로 안 들어가지는 공유기가 많습니다.
            </div>}
            {s.firewall && !s.firewall.ok && !s.firewall.unknown && <div className='sh-note error'>
                {s.firewall.message}
                <button className='theia-button sh-mini' onClick={() => this.commands.executeCommand(ServerHostCommands.FIREWALL.id, s.id)}>방화벽 허용</button>
            </div>}
            {a.attempts.filter(t => !t.ok).length > 0 && <ul className='sh-attempts'>
                {a.attempts.filter(t => !t.ok).map((t, i) => <li key={i}>
                    <span className={codicon('arrow-small-right')} aria-hidden='true' /> {PROVIDER_LABEL[t.provider]} 건너뜀: {t.reason}</li>)}
            </ul>}
            {a.notes.length > 0 && <ul className='sh-notes'>{a.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
            {s.message && <div className={'sh-note' + (s.state === 'error' || a.state === 'failed' ? ' error' : '')}>{s.message}</div>}
            {s.errors.length > 0 && this.renderErrors(s)}
            {s.clientMods.length > 0 && <details className='sh-mods'>
                <summary>참가자도 같은 모드가 필요합니다({s.clientMods.length}개)</summary>
                <ul>{s.clientMods.map(m => <li key={m.file}>{m.name ?? m.id} <span className='sh-muted'>{m.version ?? ''}{m.library ? ' · 라이브러리' : ''}</span></li>)}</ul>
            </details>}

            <div className='sh-card-actions'>
                {s.state === 'needs-eula'
                    ? <button className='theia-button' onClick={() => this.commands.executeCommand(ServerHostCommands.EULA.id, s.id)}>EULA 동의</button>
                    : s.kind === 'external'
                        ? (a.state === 'open' || a.state === 'opening'
                            ? <button className='theia-button' onClick={() => this.run(() => this.store.service.closeAddress(s.id))}>주소 닫기</button>
                            : <button className='theia-button' onClick={() => this.run(() => this.store.service.openAddress(s.id))}>주소 열기</button>)
                        : on
                            ? <button className='theia-button' onClick={() => this.run(() => this.store.service.stopServer(s.id))}>
                                <span className={codicon('debug-stop')} aria-hidden='true' /> 중지</button>
                            : <button className='theia-button' onClick={() => this.commands.executeCommand(ServerHostCommands.START.id, s.id)}>
                                <span className={codicon('play')} aria-hidden='true' /> 시작</button>}
                {s.kind !== 'external' && on && a.state !== 'open' && s.gamePort &&
                    <button className='theia-button secondary' onClick={() => this.run(() => this.store.service.openAddress(s.id))}>주소 다시 열기</button>}
                {s.kind !== 'external' && a.state === 'open' &&
                    <button className='theia-button secondary' onClick={() => this.run(() => this.store.service.closeAddress(s.id))}>주소 닫기</button>}
                <select className='theia-select sh-pref' value={s.preference} title='주소 여는 방식'
                    onChange={e => this.run(() => this.store.service.setPreference(s.id, e.target.value as 'auto' | ProviderId))}>
                    <option value='auto'>자동</option>
                    {s.kind === 'lan' && <option value='e4mc'>e4mc 먼저</option>}
                    <option value='upnp'>UPnP 먼저</option>
                    <option value='playit'>playit 먼저</option>
                </select>
                {s.kind === 'dedicated' && <button className='theia-button secondary' title='서버 최대 메모리(다음 시작부터)'
                    onClick={() => this.commands.executeCommand(ServerHostCommands.MEMORY.id, s.id)}>
                    메모리 {s.memoryMb ? `${Math.round(s.memoryMb / 102.4) / 10}GB` : '기본'}</button>}
                {s.kind === 'dedicated' && <button className='theia-button secondary' title='서버 폴더(월드·mods·config·logs)를 파일 탐색기로'
                    onClick={() => this.run(() => this.store.service.openFolder(s.id))}>
                    <span className={codicon('folder-opened')} aria-hidden='true' /> 폴더</button>}
                {s.kind === 'dedicated' && s.loader && !['vanilla', 'paper'].includes(s.loader) &&
                    <button className='theia-button secondary' title='서버와 인스턴스(참가자 쪽) 모드가 같은지 확인하고 맞춥니다'
                        onClick={() => this.commands.executeCommand(ServerHostCommands.MOD_CHECK.id, s.id)}>모드 확인</button>}
                {s.kind === 'dedicated' && <button className='theia-button secondary'
                    onClick={() => { if (consoleOpen) { this.openConsole.delete(s.id); } else { this.openConsole.add(s.id); this.store.loadConsole(s.id); } this.update(); }}>
                    콘솔 {consoleOpen ? '닫기' : '열기'}</button>}
                <button className='theia-button secondary' disabled={on} title={on ? '먼저 중지하세요' : '서버 설정을 지웁니다(전용 서버 폴더는 휴지통으로)'}
                    onClick={() => this.run(() => this.store.service.deleteServer(s.id))}>삭제</button>
            </div>
            {consoleOpen && this.renderConsole(s)}
        </section>;
    }

    protected renderErrors(s: ServerView): React.ReactNode {
        const modErr = s.errors.some(e => e.code.startsWith('MOD-'));
        const javaErr = s.errors.some(e => e.code.startsWith('JAVA-'));
        return <div className='sh-errors' role='alert'>
            {s.errors.map((e: ServerError) => <details key={e.code} className='sh-error'>
                <summary><span className='sh-code-chip'>{e.code}</span> {e.title}</summary>
                <div className='sh-small'>{e.hint}</div>
                {e.line && <pre className='sh-mono sh-small'>{[e.line, ...(e.details ?? [])].join('\n')}</pre>}
                {e.crashFile && <div className='sh-muted sh-small'>크래시 리포트: {e.crashFile}</div>}
            </details>)}
            <div className='sh-card-actions'>
                {modErr && s.kind === 'dedicated' && <button className='theia-button sh-mini'
                    onClick={() => this.commands.executeCommand(ServerHostCommands.MOD_CHECK.id, s.id)}>모드 확인</button>}
                {javaErr && <button className='theia-button sh-mini'
                    onClick={() => this.commands.executeCommand(ServerHostCommands.JAVA_INSTALL.id)}>Java 25 JDK 설치</button>}
                <button className='theia-button secondary sh-mini' onClick={() => this.copy(
                    s.errors.map(e => `[${e.code}] ${e.title}\n${e.line ?? ''}\n${(e.details ?? []).join('\n')}`).join('\n\n'), '오류 내용')}>오류 복사</button>
            </div>
        </div>;
    }

    protected renderConsole(s: ServerView): React.ReactNode {
        const lines = this.store.consoles.get(s.id) ?? [];
        const value = this.input.get(s.id) ?? '';
        const live = s.state === 'running' || s.state === 'starting';
        const send = (): void => {
            if (value.trim()) {
                this.run(() => this.store.service.command(s.id, value.trim()));
                this.input.set(s.id, '');
                this.update();
            }
        };
        return <div className='sh-console'>
            <pre ref={el => { if (el) { el.scrollTop = el.scrollHeight; } }}>{lines.slice(-200).join('\n')}</pre>
            <div className='sh-console-input'>
                <input className='theia-input sh-mono' value={value} placeholder={live ? '명령어(예: say 안녕, op 이름)' : '서버가 꺼져 있습니다'}
                    disabled={!live} aria-label='서버 콘솔 명령'
                    onChange={e => { this.input.set(s.id, e.target.value); this.update(); }}
                    onKeyDown={e => { if (e.key === 'Enter') { send(); } }} />
                <button className='theia-button' onClick={send} disabled={!value.trim()}>보내기</button>
            </div>
        </div>;
    }
}
