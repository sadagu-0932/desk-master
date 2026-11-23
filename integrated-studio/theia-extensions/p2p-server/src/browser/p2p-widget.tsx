import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { ClipboardService } from '@theia/core/lib/browser/clipboard-service';
import { HostView, JoinView, formatBytes } from '../common/index.js';
import { P2PStore } from './p2p-store.js';
import { P2PCommands } from './p2p-commands.js';

const STATE_LABEL: Record<string, string> = {
    'stopped': '꺼짐', 'needs-eula': 'EULA 동의 필요', 'preparing': '서버 준비 중(jar 받는 중)', 'starting': '서버 켜는 중',
    'waiting-lan': 'LAN 공개 기다리는 중', 'open': '열림', 'error': '오류',
    'connecting': '연결 중', 'connected': '연결됨', 'reconnecting': '다시 연결 중', 'closed': '끊김',
};

/** 서버 패널: 내가 연 서버(호스트)와 참가한 서버. */
@injectable()
export class P2PWidget extends ReactWidget {
    static readonly ID = 'studio-p2p';
    static readonly LABEL = 'P2P 서버';

    @inject(P2PStore) protected readonly store: P2PStore;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(ClipboardService) protected readonly clipboard: ClipboardService;

    protected openConsole = new Set<string>();
    protected input = new Map<string, string>();

    @postConstruct()
    protected init(): void {
        this.id = P2PWidget.ID;
        this.title.label = P2PWidget.LABEL;
        this.title.caption = 'P2P 서버 — 포트포워딩 없이 친구와 같이 하기';
        this.title.iconClass = codicon('broadcast');
        this.title.closable = true;
        this.addClass('studio-p2p');
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
        const { hosts, joins, relays } = this.store.snapshot;
        return <div className='p2p-root'>
            <div className='p2p-actions'>
                <button className='theia-button' onClick={() => this.commands.executeCommand(P2PCommands.HOST.id)}>
                    <span className={codicon('broadcast')} aria-hidden='true' /> 서버 열기</button>
                <button className='theia-button secondary' onClick={() => this.commands.executeCommand(P2PCommands.JOIN.id)}>
                    <span className={codicon('plug')} aria-hidden='true' /> 참가</button>
            </div>
            <div className='p2p-muted p2p-small'>
                {relays ? `직접 연결이 안 되면 중계 노드(${relays}개)로 바꿉니다.` : '직접 연결만 씁니다(중계 노드 설정 없음).'}
            </div>

            <h3>내가 연 서버 <span className='p2p-muted'>{hosts.length}개</span></h3>
            {hosts.length === 0 && <div className='p2p-muted'>아직 없습니다. [서버 열기]로 시작하세요.</div>}
            {hosts.map(h => this.renderHost(h))}

            <h3>참가한 서버 <span className='p2p-muted'>{joins.length}개</span></h3>
            {joins.length === 0 && <div className='p2p-muted'>친구가 보낸 코드가 있으면 [참가]를 누르세요.</div>}
            {joins.map(j => this.renderJoin(j))}
        </div>;
    }

    protected renderHost(h: HostView): React.ReactNode {
        const on = !['stopped', 'error', 'needs-eula'].includes(h.state);
        const consoleOpen = this.openConsole.has(h.id);
        return <section key={h.id} className={`p2p-card state-${h.state}`} aria-label={h.name}>
            <div className='p2p-card-head'>
                <span className={'p2p-dot' + (h.state === 'open' ? ' on' : on ? ' busy' : '')} aria-hidden='true' />
                <b className='p2p-name'>{h.name}</b>
                <span className='p2p-chip'>{h.kind === 'dedicated' ? '전용 서버' : '싱글 LAN 공개'}</span>
                <span className='p2p-chip'>{STATE_LABEL[h.state] ?? h.state}</span>
            </div>
            <div className='p2p-muted p2p-small'>{h.instanceName} · {h.version} {h.loader === 'fabric' ? 'Fabric' : '바닐라'}
                {h.kind === 'dedicated' && ` · ${h.onlineMode ? '정품 계정만' : '오프라인 허용'}${h.world ? ` · 월드 ${h.world}` : ''}`}</div>
            <div className='p2p-code-row'>
                <code className='p2p-code' title='참가 코드'>{h.code}</code>
                <button className='theia-button' onClick={() => this.copy(h.code, '참가 코드')}>복사</button>
                <button className='theia-button secondary' title='새 코드로 바꿉니다. 지금 참가한 사람은 끊기고 새 코드로 다시 들어와야 합니다.'
                    onClick={() => this.run(() => this.store.service.regenerateCode(h.id))}>코드 새로 만들기</button>
            </div>
            {h.message && <div className={'p2p-note' + (h.state === 'error' ? ' error' : '')}>{h.message}</div>}
            {h.kind === 'lan' && h.state !== 'open' && <div className='p2p-note'>호스트가 게임을 켜 둔 동안만 유지됩니다. 정품 인증은 호스트 계정 기준입니다.</div>}
            {h.state === 'open' && h.kind === 'dedicated' && h.gamePort &&
                <div className='p2p-small'>호스트 본인은 마인크래프트에서 <code>127.0.0.1:{h.gamePort}</code> 로 접속
                    <button className='theia-button secondary p2p-mini' onClick={() => this.copy(`127.0.0.1:${h.gamePort}`, '주소')}>복사</button></div>}
            {h.state === 'open' && <div className='p2p-small'>
                참가자 {h.peers.length}명 · 받음 {formatBytes(h.traffic.bytesIn)} · 보냄 {formatBytes(h.traffic.bytesOut)}
                {h.players.length > 0 && <> · 게임 접속자: {h.players.join(', ')}</>}
            </div>}
            {h.peers.length > 0 && <ul className='p2p-peers'>
                {h.peers.map(p => <li key={p.id}><code>{p.id}</code> 연결 {p.connections}개 · ↓{formatBytes(p.bytesIn)} ↑{formatBytes(p.bytesOut)}</li>)}
            </ul>}
            <div className='p2p-card-actions'>
                {h.state === 'needs-eula'
                    ? <button className='theia-button' onClick={() => this.commands.executeCommand(P2PCommands.EULA.id, h.id)}>EULA 동의</button>
                    : on
                        ? <button className='theia-button' onClick={() => this.run(() => this.store.service.stopHost(h.id))}>
                            <span className={codicon('debug-stop')} aria-hidden='true' /> 중지</button>
                        : <button className='theia-button' onClick={() => this.commands.executeCommand(P2PCommands.START.id, h.id)}>
                            <span className={codicon('play')} aria-hidden='true' /> 시작</button>}
                {h.kind === 'dedicated' && <button className='theia-button secondary'
                    onClick={() => { if (consoleOpen) { this.openConsole.delete(h.id); } else { this.openConsole.add(h.id); this.store.loadConsole(h.id); } this.update(); }}>
                    콘솔 {consoleOpen ? '닫기' : '열기'}</button>}
                <button className='theia-button secondary' title='서버 키를 파일로 저장 — 재설치·다른 PC 에서도 같은 참가 코드'
                    onClick={() => this.commands.executeCommand(P2PCommands.EXPORT_KEY.id, h.id)}>키 내보내기</button>
                <button className='theia-button secondary' title='저장해 둔 키 파일로 참가 코드를 되돌립니다'
                    onClick={() => this.commands.executeCommand(P2PCommands.IMPORT_KEY.id, h.id)}>키 가져오기</button>
                <button className='theia-button secondary' disabled={on} title={on ? '먼저 중지하세요' : '서버 설정과 코드를 지웁니다(월드는 휴지통으로)'}
                    onClick={() => this.run(() => this.store.service.deleteHost(h.id))}>삭제</button>
            </div>
            {consoleOpen && this.renderConsole(h)}
        </section>;
    }

    protected renderConsole(h: HostView): React.ReactNode {
        const lines = this.store.consoles.get(h.id) ?? [];
        const value = this.input.get(h.id) ?? '';
        const send = (): void => {
            if (value.trim()) {
                this.run(() => this.store.service.command(h.id, value.trim()));
                this.input.set(h.id, '');
                this.update();
            }
        };
        return <div className='p2p-console'>
            <pre ref={el => { if (el) { el.scrollTop = el.scrollHeight; } }}>{lines.slice(-200).join('\n')}</pre>
            <div className='p2p-console-input'>
                <input className='theia-input p2p-mono' value={value} placeholder={h.state === 'open' || h.state === 'starting' ? '명령어(예: say 안녕, op 이름)' : '서버가 꺼져 있습니다'}
                    disabled={!(h.state === 'open' || h.state === 'starting')} aria-label='서버 콘솔 명령'
                    onChange={e => { this.input.set(h.id, e.target.value); this.update(); }}
                    onKeyDown={e => { if (e.key === 'Enter') { send(); } }} />
                <button className='theia-button' onClick={send} disabled={!value.trim()}>보내기</button>
            </div>
        </div>;
    }

    protected renderJoin(j: JoinView): React.ReactNode {
        const addr = j.localPort ? `127.0.0.1:${j.localPort}` : undefined;
        return <section key={j.id} className={`p2p-card state-${j.state}`} aria-label={j.info?.name ?? '참가'}>
            <div className='p2p-card-head'>
                <span className={'p2p-dot' + (j.state === 'connected' ? ' on' : j.state === 'connecting' || j.state === 'reconnecting' ? ' busy' : '')} aria-hidden='true' />
                <b className='p2p-name'>{j.info?.name ?? '참가'}</b>
                <span className='p2p-chip'>{STATE_LABEL[j.state] ?? j.state}</span>
                {j.mode && <span className='p2p-chip'>{j.mode === 'direct' ? '직접 연결' : '중계 연결'}</span>}
            </div>
            {j.info && <div className='p2p-muted p2p-small'>{j.info.version} {j.info.loader === 'fabric' ? 'Fabric' : '바닐라'} ·
                {j.info.mode === 'dedicated' ? ' 전용 서버' : j.info.mode === 'lan' ? ' 싱글 LAN 공개' : ' 외부 호스트'} · 접속 {j.info.players}/{j.info.max}명</div>}
            {j.state === 'connected' && <div className='p2p-small'>핑 {j.rtt ?? '—'}ms · 받음 {formatBytes(j.traffic.bytesIn)} · 보냄 {formatBytes(j.traffic.bytesOut)}</div>}
            {addr && j.state !== 'closed' && j.state !== 'error' && <div className='p2p-code-row'>
                <span>마인크래프트에서 접속할 주소</span><code className='p2p-code'>{addr}</code>
                <button className='theia-button' onClick={() => this.copy(addr, '주소')}>복사</button>
            </div>}
            {j.message && <div className={'p2p-note' + (j.state === 'error' ? ' error' : '')}>{j.message}</div>}
            <div className='p2p-card-actions'>
                {j.state === 'connected' && <button className='theia-button' onClick={() => this.commands.executeCommand(P2PCommands.PLAY.id, j.id)}>
                    <span className={codicon('play')} aria-hidden='true' /> 게임에서 접속</button>}
                <button className='theia-button secondary' onClick={() => this.run(() => this.store.service.leave(j.id))}>
                    {j.state === 'closed' || j.state === 'error' ? '목록에서 지우기' : '나가기'}</button>
            </div>
        </section>;
    }
}
