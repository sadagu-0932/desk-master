import * as React from '@theia/core/shared/react';
import { ReactDialog } from '@theia/core/lib/browser/dialogs/react-dialog';
import { Message } from '@theia/core/shared/@lumino/messaging';
import { Instance, LOADER_LABELS } from 'integrated-studio-launcher-core/lib/common';
import { CreateServerOptions, LanGame, ModCheck, ModIssue, PingResult, ServerKind } from '../common/index.js';

// ================================================================ 서버 열기
export interface OpenDialogDeps {
    instances: readonly Instance[];
    currentId?: string;
    kind?: ServerKind;
    listWorlds: (instanceId: string) => Promise<string[]>;
    lanGames: () => LanGame[];
    ping: (port: number) => Promise<PingResult>;
}

export class OpenServerDialog extends ReactDialog<CreateServerOptions> {
    protected instanceId: string;
    protected kind: ServerKind;
    protected name = '';
    protected onlineMode = true;
    /** 전용 서버 종류: 인스턴스 로더 그대로 / Paper(플러그인 서버) */
    protected paper = false;
    protected world = '';
    protected worlds: string[] = [];
    protected port = '25565';
    protected check: PingResult | undefined;
    protected checking = false;
    protected timer: number | undefined;

    constructor(protected readonly deps: OpenDialogDeps) {
        super({ title: '서버 열기' });
        this.instanceId = deps.currentId ?? deps.instances[0]?.id ?? '';
        this.kind = deps.kind ?? (deps.instances.length ? 'lan' : 'external');
        this.appendAcceptButton('서버 열기');
        this.appendCloseButton('취소');
        this.loadWorlds();
    }

    protected async loadWorlds(): Promise<void> {
        this.worlds = this.instanceId ? await this.deps.listWorlds(this.instanceId).catch(() => []) : [];
        this.update();
    }

    get value(): CreateServerOptions {
        return {
            kind: this.kind, instanceId: this.kind === 'external' ? undefined : this.instanceId, name: this.name.trim() || undefined,
            onlineMode: this.onlineMode, world: this.world || undefined, port: this.kind === 'external' ? Number(this.port) : undefined,
            software: this.kind === 'dedicated' && this.paper ? 'paper' : undefined,
        };
    }

    protected override isValid(): string {
        if (this.kind === 'external') {
            const p = Number(this.port);
            return p > 0 && p < 65536 && /^\d+$/.test(this.port) ? '' : '포트 번호(1~65535)를 넣으세요.';
        }
        const inst = this.deps.instances.find(i => i.id === this.instanceId);
        if (!inst) {
            return '인스턴스를 먼저 만드세요.';
        }
        if (this.kind === 'dedicated' && !this.paper && !['vanilla', 'fabric', 'neoforge', 'forge'].includes(inst.loader)) {
            return `전용 서버는 바닐라·Fabric·NeoForge·Forge 인스턴스만 됩니다(${LOADER_LABELS[inst.loader] ?? inst.loader}). 싱글 LAN 공개를 쓰세요.`;
        }
        return '';
    }

    protected override onAfterAttach(msg: Message): void {
        super.onAfterAttach(msg);
        this.update();
        this.timer = window.setInterval(() => this.kind === 'external' && this.update(), 1500);  // LAN 목록 새로 고침
    }

    protected override onBeforeDetach(msg: Message): void {
        window.clearInterval(this.timer);
        super.onBeforeDetach(msg);
    }

    protected async runCheck(): Promise<void> {
        this.checking = true;
        this.update();
        this.check = await this.deps.ping(Number(this.port)).catch(e => ({ ok: false, error: String(e) }));
        this.checking = false;
        this.update();
    }

    protected render(): React.ReactNode {
        const inst = this.deps.instances.find(i => i.id === this.instanceId);
        const kinds: Array<[ServerKind, string, string]> = [
            ['lan', '싱글 LAN 공개', '지금 하는 싱글 월드를 그대로 엽니다. 게임에서 [LAN에 공개]를 누르면 자동으로 주소가 열립니다(e4mc → UPnP).'],
            ['dedicated', '전용 서버', '이 PC 에서 마인크래프트 서버를 따로 켭니다. 호스트가 게임을 꺼도 계속 돌아가고 콘솔이 있습니다(서버에 e4mc · Paper 는 Minekube Connect → UPnP).'],
            ['external', '외부 서버 연결', '다른 런처로 연 LAN 월드나 이 PC 에서 켠 서버에 주소만 열어 줍니다(UPnP).'],
        ];
        const lan = this.deps.lanGames().filter(g => g.local);
        return <div className='sh-dialog'>
            <div className='sh-kinds' role='radiogroup' aria-label='서버 여는 방식'>
                {kinds.map(([k, title, desc]) =>
                    <label key={k} className={'sh-kind' + (this.kind === k ? ' selected' : '')}>
                        <input type='radio' name='sh-kind' checked={this.kind === k} onChange={() => { this.kind = k; this.update(); this.validate(); }} />
                        <span><b>{title}</b><span className='sh-muted'>{desc}</span></span>
                    </label>)}
            </div>
            {this.kind !== 'external' && <label className='sh-field'>인스턴스
                <select className='theia-select' value={this.instanceId}
                    onChange={e => { this.instanceId = e.target.value; this.world = ''; this.loadWorlds(); this.update(); this.validate(); }}>
                    {this.deps.instances.map(i => <option key={i.id} value={i.id}>{i.name} — {i.version} · {LOADER_LABELS[i.loader] ?? i.loader}</option>)}
                </select>
            </label>}
            {this.kind === 'external' && <>
                <div className='sh-field'>이 PC 에서 LAN 에 공개된 월드
                    {lan.length === 0
                        ? <div className='sh-muted'>아직 없습니다. 다른 런처에서 월드를 열고 [LAN에 공개]를 누르면 여기에 뜹니다.</div>
                        : <div className='sh-lan-list'>{lan.map(g =>
                            <button key={g.port} className={'theia-button secondary sh-lan' + (this.port === String(g.port) ? ' selected' : '')}
                                onClick={() => { this.port = String(g.port); this.name = this.name || g.motd; this.check = undefined; this.update(); this.validate(); }}>
                                {g.motd} <span className='sh-muted'>포트 {g.port}</span></button>)}</div>}
                </div>
                <label className='sh-field'>포트(직접 입력, 기본 25565)
                    <span className='sh-row'>
                        <input className='theia-input sh-mono' value={this.port} inputMode='numeric'
                            onChange={e => { this.port = e.target.value.trim(); this.check = undefined; this.update(); this.validate(); }} />
                        <button className='theia-button secondary' disabled={this.checking} onClick={() => this.runCheck()}>
                            {this.checking ? '확인 중…' : '상태 확인'}</button>
                    </span>
                </label>
                {this.check && <div className={'sh-note' + (this.check.ok ? '' : ' error')}>
                    {this.check.ok
                        ? `응답함: ${this.check.version ?? ''} · ${this.check.motd ?? ''} · 접속 ${this.check.online ?? 0}/${this.check.max ?? '?'}명 · ${this.check.latencyMs ?? '?'}ms`
                        : `응답 없음: ${this.check.error}`}</div>}
            </>}
            <label className='sh-field'>서버 이름
                <input className='theia-input' value={this.name} placeholder={inst && this.kind !== 'external' ? `${inst.name} 서버` : ''}
                    onChange={e => { this.name = e.target.value; this.update(); }} maxLength={60} />
            </label>
            {this.kind === 'dedicated' && <>
                <label className='sh-field'>월드
                    <select className='theia-select' value={this.world} onChange={e => { this.world = e.target.value; this.update(); }}>
                        <option value=''>새 월드(서버가 만듦)</option>
                        {this.worlds.map(w => <option key={w} value={w}>{w} (복사해서 씀 — 원본은 그대로)</option>)}
                    </select>
                </label>
                <label className='sh-check'>
                    <input type='checkbox' checked={this.paper} onChange={e => { this.paper = e.target.checked; this.update(); }} />
                    Paper 서버(플러그인) — 같은 게임 버전의 Paper 로 엽니다. F9 로 빌드한 플러그인이 이 서버의 plugins/ 에 들어갑니다(모드는 넣지 않음).
                </label>
                {inst && inst.loader !== 'vanilla' && !this.paper && <div className='sh-muted'>
                    {LOADER_LABELS[inst.loader]} 서버로 엽니다{inst.loader === 'fabric' ? '(Fabric 서버 런처)' : '(공식 메이븐 설치기, 처음 한 번 몇 분)'}. 인스턴스 mods 중 서버에서도 도는 모드를 서버에 넣습니다.</div>}
                <label className='sh-check'>
                    <input type='checkbox' checked={this.onlineMode} onChange={e => { this.onlineMode = e.target.checked; this.update(); }} />
                    정품 계정만 접속(online-mode) — Microsoft 계정으로 플레이하면 켜 두세요. 끄면 오프라인 시험용.
                </label>
            </>}
            <div className='sh-muted'>비밀번호·화이트리스트는 없습니다. 주소를 아는 사람은 누구나 들어올 수 있으니 믿을 수 있는 사람에게만 보내세요.</div>
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
        return <div className='sh-dialog'>
            <p>전용 서버를 처음 켜려면 마인크래프트 최종 사용자 사용권 계약(EULA)에 동의해야 합니다.</p>
            <p><a href='#' onClick={e => { e.preventDefault(); this.openUrl(this.url); }}>{this.url}</a> 를 열어 직접 읽어 주세요.</p>
            <p className='sh-muted'>"동의"를 누르면 이 서버 폴더의 eula.txt 에 동의가 기록됩니다. 통합 작업실이 대신 동의하지 않습니다.</p>
        </div>;
    }
}

// ================================================================ 고르기(여러 선택지)
export interface Choice { id: string; label: string; description?: string; primary?: boolean }

export class ChoiceDialog extends ReactDialog<string | undefined> {
    protected chosen: string | undefined;

    constructor(title: string, protected readonly body: React.ReactNode, protected readonly choices: Choice[]) {
        super({ title });
        this.appendCloseButton('취소');
    }

    get value(): string | undefined {
        return this.chosen;
    }

    protected override onAfterAttach(msg: Message): void {
        super.onAfterAttach(msg);
        this.update();
    }

    protected render(): React.ReactNode {
        return <div className='sh-dialog'>
            <div>{this.body}</div>
            <div className='sh-choices'>
                {this.choices.map(c => <button key={c.id} className={'theia-button sh-choice' + (c.primary ? '' : ' secondary')}
                    onClick={() => { this.chosen = c.id; this.accept(); }}>
                    <b>{c.label}</b>{c.description && <span className='sh-muted'>{c.description}</span>}
                </button>)}
            </div>
        </div>;
    }
}

// ================================================================ DDNS
export interface DdnsValue { ddnsUrl: string; ddnsDomain: string; ddnsToken: string }

export class DdnsDialog extends ReactDialog<DdnsValue> {
    protected v: DdnsValue;

    constructor(init: { ddnsUrl?: string; ddnsDomain?: string; hasToken?: boolean }) {
        super({ title: 'UPnP 고정 주소(무료 DDNS)' });
        this.v = { ddnsUrl: init.ddnsUrl ?? '', ddnsDomain: init.ddnsDomain ?? '', ddnsToken: '' };
        this.hasToken = !!init.hasToken;
        this.appendAcceptButton('저장');
        this.appendCloseButton('취소');
    }

    protected hasToken: boolean;

    get value(): DdnsValue {
        return this.v;
    }

    protected override isValid(): string {
        return !this.v.ddnsUrl || /^https:\/\//i.test(this.v.ddnsUrl) ? '' : '갱신 주소는 https:// 로 시작해야 합니다.';
    }

    protected override onAfterAttach(msg: Message): void {
        super.onAfterAttach(msg);
        this.update();
    }

    protected render(): React.ReactNode {
        return <div className='sh-dialog'>
            <p className='sh-muted'>UPnP 로 연 주소는 공인 IP 가 바뀌면 바뀝니다. 무료 DDNS(예: DuckDNS)를 쓰면 이름 주소가 고정됩니다.
                {' '}{'{ip}'} {'{token}'} {'{domain}'} 은 자동으로 채웁니다. 비우고 저장하면 끕니다.</p>
            <label className='sh-field'>갱신 주소
                <input className='theia-input sh-mono' value={this.v.ddnsUrl} spellCheck={false}
                    placeholder='https://www.duckdns.org/update?domains={domain}&token={token}&ip={ip}'
                    onChange={e => { this.v.ddnsUrl = e.target.value.trim(); this.update(); this.validate(); }} />
            </label>
            <label className='sh-field'>주소 이름(친구에게 보낼 주소)
                <input className='theia-input sh-mono' value={this.v.ddnsDomain} placeholder='myserver.duckdns.org'
                    onChange={e => { this.v.ddnsDomain = e.target.value.trim(); this.update(); }} />
            </label>
            <label className='sh-field'>토큰 {this.hasToken && <span className='sh-muted'>(저장돼 있음 — 바꿀 때만 입력)</span>}
                <input className='theia-input sh-mono' type='password' value={this.v.ddnsToken} autoComplete='off'
                    onChange={e => { this.v.ddnsToken = e.target.value.trim(); this.update(); }} />
            </label>
            <p className='sh-muted'>토큰은 이 PC 의 앱 데이터 폴더에만 저장되고 git 에는 들어가지 않습니다.</p>
        </div>;
    }
}

// ================================================================ 모드 확인(서버 ↔ 인스턴스)
const FIX_LABEL: Record<string, string> = {
    toServer: '인스턴스 → 서버로 복사', toClient: '서버 → 인스턴스로 복사',
    removeServer: '서버에서 빼기(휴지통, 다음 시작 때 다시 넣지 않음)', unexclude: '다시 넣기(다음 시작 때 복사·받기)',
};

/** 서버·인스턴스 모드 차이를 오류 코드와 함께 보여 주고, 고를 것을 골라 고친다. 값 = 고칠 항목 */
export class ModCheckDialog extends ReactDialog<ModIssue[]> {
    protected picked: Set<number>;

    constructor(protected readonly check: ModCheck, protected readonly serverName: string) {
        super({ title: `모드 확인 — ${serverName}` });
        this.picked = new Set(check.issues.map((i, n) => (i.pick ?? (i.fix && i.code !== 'MOD-107')) ? n : -1).filter(n => n >= 0));
        if (check.issues.length) {
            this.appendAcceptButton('고른 것 고치기');
        }
        this.appendCloseButton(check.issues.length ? '취소' : '닫기');
    }

    get value(): ModIssue[] {
        return this.check.issues.filter((_, n) => this.picked.has(n));
    }

    protected override isValid(): string {
        return this.check.issues.length && !this.picked.size ? '고칠 항목을 고르세요.' : '';
    }

    protected render(): React.ReactNode {
        const c = this.check;
        if (c.message) {
            return <div className='sh-dialog'><p>{c.message}</p></div>;
        }
        return <div className='sh-dialog sh-modcheck'>
            <p className='sh-small'>인스턴스(참가자가 쓰는 쪽) 모드 {c.client.length}개 · 서버 모드 {c.server.length}개를 비교하고,
                서버 로그·크래시 리포트에서 오류를 일으킨 모드를 찾았습니다.{c.issues.length ? ' 고칠 것:' : ''}</p>
            {!c.issues.length && <p><b>모두 일치합니다.</b> 그래도 못 들어오면 참가자의 모드 목록이 이 인스턴스와 같은지 확인하세요.</p>}
            <ul className='sh-issues'>
                {c.issues.map((i, n) => <li key={n}>
                    <label>
                        <input type='checkbox' disabled={!i.fix} checked={this.picked.has(n)}
                            onChange={e => { if (e.target.checked) { this.picked.add(n); } else { this.picked.delete(n); } this.update(); }} />
                        <span className='sh-code-chip'>{i.code}</span> <b>{i.name ?? i.id}</b> — {i.title}
                    </label>
                    <div className='sh-muted sh-small'>
                        {i.clientFile && <>인스턴스: {i.clientFile}{i.clientVersion ? ` (${i.clientVersion})` : ''} </>}
                        {i.serverFile && <>· 서버: {i.serverFile}{i.serverVersion ? ` (${i.serverVersion})` : ''}</>}
                        {i.fix && <> · 고치기: {FIX_LABEL[i.fix]}</>}
                    </div>
                    {i.evidence && <pre className='sh-mono sh-small sh-evidence' title='서버 로그에서 찾은 근거'>{i.evidence}</pre>}
                </li>)}
            </ul>
            <p className='sh-muted sh-small'>LOG- 로 시작하는 것은 서버 로그로 찾은 것입니다(‘원인일 수 있음’은 기본으로 고르지 않음).
                서버에서 뺀 모드는 기억해서 다음 시작 때 다시 복사·다운로드하지 않습니다(MOD-107 에서 다시 넣기).
                서버 쪽을 바꾸면 다음 시작부터 적용됩니다. 지운 파일은 휴지통으로 갑니다.
                참가자도 인스턴스와 같은 모드여야 들어올 수 있습니다(클라이언트 전용 모드는 달라도 됨).</p>
        </div>;
    }
}
