import * as React from '@theia/core/shared/react';
import { ReactDialog } from '@theia/core/lib/browser/dialogs/react-dialog';
import { Message } from '@theia/core/shared/@lumino/messaging';
import { Instance } from 'integrated-studio-launcher-core/lib/common';
import { CreateHostOptions, HostKind } from '../common/index.js';

// ================================================================ 서버 열기
export interface HostDialogDeps {
    instances: readonly Instance[];
    currentId?: string;
    listWorlds: (instanceId: string) => Promise<string[]>;
}

export class HostDialog extends ReactDialog<CreateHostOptions> {
    protected instanceId: string;
    protected kind: HostKind = 'dedicated';
    protected name = '';
    protected onlineMode = true;
    protected world = '';
    protected worlds: string[] = [];

    constructor(protected readonly deps: HostDialogDeps) {
        super({ title: '서버 열기' });
        this.instanceId = deps.currentId ?? deps.instances[0]?.id ?? '';
        this.appendAcceptButton('서버 열기');
        this.appendCloseButton('취소');
        this.loadWorlds();
    }

    protected async loadWorlds(): Promise<void> {
        this.worlds = this.instanceId ? await this.deps.listWorlds(this.instanceId).catch(() => []) : [];
        this.update();
    }

    get value(): CreateHostOptions {
        return { instanceId: this.instanceId, kind: this.kind, name: this.name.trim() || undefined,
            onlineMode: this.onlineMode, world: this.world || undefined };
    }

    protected override isValid(): string {
        return this.instanceId ? '' : '인스턴스를 먼저 만드세요.';
    }

    protected override onAfterAttach(msg: Message): void {
        super.onAfterAttach(msg);
        this.update();
    }

    protected render(): React.ReactNode {
        const inst = this.deps.instances.find(i => i.id === this.instanceId);
        const kinds: Array<[HostKind, string, string]> = [
            ['dedicated', '전용 서버', '이 PC 에서 마인크래프트 서버를 따로 켭니다. 호스트가 게임을 꺼도 서버는 계속 돌아갑니다. 콘솔로 명령을 넣을 수 있습니다.'],
            ['lan', '싱글 LAN 공개', '지금 하는 싱글 월드를 그대로 엽니다. 게임에서 [LAN에 공개]를 누르면 자동으로 열립니다. 호스트가 게임을 켜 둔 동안만 유지되고, 정품 인증은 호스트 계정 기준입니다.'],
        ];
        return <div className='p2p-dialog'>
            <label className='p2p-field'>인스턴스
                <select className='theia-select' value={this.instanceId}
                    onChange={e => { this.instanceId = e.target.value; this.world = ''; this.loadWorlds(); this.update(); }}>
                    {this.deps.instances.map(i => <option key={i.id} value={i.id}>{i.name} — {i.version} · {i.loader === 'fabric' ? 'Fabric' : '바닐라'}</option>)}
                </select>
            </label>
            <div className='p2p-kinds' role='radiogroup' aria-label='서버 여는 방식'>
                {kinds.map(([k, title, desc]) =>
                    <label key={k} className={'p2p-kind' + (this.kind === k ? ' selected' : '')}>
                        <input type='radio' name='p2p-kind' checked={this.kind === k} onChange={() => { this.kind = k; this.update(); }} />
                        <span><b>{title}</b><span className='p2p-muted'>{desc}</span></span>
                    </label>)}
            </div>
            <label className='p2p-field'>서버 이름
                <input className='theia-input' value={this.name} placeholder={inst ? `${inst.name} 서버` : ''}
                    onChange={e => { this.name = e.target.value; this.update(); }} maxLength={60} />
            </label>
            {this.kind === 'dedicated' && <>
                <label className='p2p-field'>월드
                    <select className='theia-select' value={this.world} onChange={e => { this.world = e.target.value; this.update(); }}>
                        <option value=''>새 월드(서버가 만듦)</option>
                        {this.worlds.map(w => <option key={w} value={w}>{w} (복사해서 씀 — 원본은 그대로)</option>)}
                    </select>
                </label>
                <label className='p2p-check'>
                    <input type='checkbox' checked={this.onlineMode} onChange={e => { this.onlineMode = e.target.checked; this.update(); }} />
                    정품 계정만 접속(online-mode) — 공식 런처 계정이면 켜 두세요
                </label>
                {inst?.loader === 'fabric' && <div className='p2p-muted'>Fabric 인스턴스라서 Fabric 서버 런처로 엽니다(서버에 모드는 넣지 않습니다).</div>}
            </>}
            <div className='p2p-muted'>비밀번호·화이트리스트는 없습니다. 코드를 아는 사람은 누구나 참가할 수 있으니 믿을 수 있는 사람에게만 보내세요.</div>
        </div>;
    }
}

// ================================================================ EULA
export class EulaDialog extends ReactDialog<boolean> {
    constructor(protected readonly url: string, protected readonly openUrl: (u: string) => void) {
        super({ title: '마인크래프트 EULA 동의' });
        this.appendAcceptButton('읽었고 동의합니다');
        this.appendCloseButton('취소');
    }

    get value(): boolean {
        return true;
    }

    protected override onAfterAttach(msg: Message): void {
        super.onAfterAttach(msg);
        this.update();
    }

    protected render(): React.ReactNode {
        return <div className='p2p-dialog'>
            <p>전용 서버를 처음 켜려면 마인크래프트 최종 사용자 사용권 계약(EULA)에 동의해야 합니다.</p>
            <p><a href='#' onClick={e => { e.preventDefault(); this.openUrl(this.url); }}>{this.url}</a> 를 열어 직접 읽어 주세요.</p>
            <p className='p2p-muted'>"동의"를 누르면 이 서버 폴더의 eula.txt 에 동의가 기록됩니다. 통합 작업실이 대신 동의하지 않습니다.</p>
        </div>;
    }
}

// ================================================================ 참가
export class JoinDialog extends ReactDialog<string> {
    protected code = '';

    constructor() {
        super({ title: '서버 참가' });
        this.appendAcceptButton('참가');
        this.appendCloseButton('취소');
    }

    get value(): string {
        return this.code.trim();
    }

    protected override isValid(value: string): string {
        const clean = value.replace(/\s+/g, '');
        if (!clean) {
            return '';
        }
        const m = /^IS(\d+)-/i.exec(clean);
        if (m && m[1] !== '1') {
            return `다른 버전(IS${m[1]})의 코드입니다. 호스트와 같은 버전으로 업데이트하세요.`;
        }
        const body = (m ? clean.slice(m[0].length) : clean).toLowerCase().replace(/-/g, '');
        return /^[ybndrfg8ejkmcpqxot1uwisza345h769]{52}$/.test(body) ? '' : '참가 코드는 IS1- 로 시작하는 코드입니다.';
    }

    protected override onAfterAttach(msg: Message): void {
        super.onAfterAttach(msg);
        this.update();
        setTimeout(() => this.node.querySelector('input')?.focus(), 50);
    }

    protected render(): React.ReactNode {
        return <div className='p2p-dialog'>
            <label className='p2p-field'>호스트가 보낸 참가 코드
                <input className='theia-input p2p-mono' value={this.code} autoFocus spellCheck={false}
                    placeholder='IS1-… 코드를 붙여 넣으세요' onChange={e => { this.code = e.target.value; this.update(); this.validate(); }} />
            </label>
            <div className='p2p-muted'>연결은 두 PC 가 직접(안 되면 중계로) 주고받습니다. 포트포워딩·방화벽 설정은 필요 없습니다.</div>
        </div>;
    }
}
