import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { CommandService } from '@theia/core/lib/common/command';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { ApplicationServer } from '@theia/core/lib/common/application-protocol';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { groupInstances, Instance } from 'integrated-studio-launcher-core/lib/common';
import { loaderLabel } from './instances-widget.js';

const BANNERS = ['#c95a1c', '#4f7a2a', '#3a6a8a', '#6a5a8a', '#8a6a2a', '#2a7a6a'];
const banner = (i: Instance) => i.icon || BANNERS[parseInt(i.id.slice(5, 7), 16) % BANNERS.length];

/** 홈 화면: 인스턴스 카드 목록, 빠른 시작, 알림 */
@injectable()
export class HomeWidget extends ReactWidget {
    static readonly ID = 'studio-home';
    static readonly LABEL = '홈';

    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(ApplicationServer) protected readonly appServer: ApplicationServer;

    protected appVersion = '';

    protected query = '';

    @postConstruct()
    protected init(): void {
        this.id = HomeWidget.ID;
        this.title.label = HomeWidget.LABEL;
        this.title.caption = '통합 작업실 홈';
        this.title.iconClass = codicon('home');
        this.title.closable = true;
        this.addClass('studio-home');
        this.node.tabIndex = 0;
        this.toDispose.push(this.manager.onDidChange(() => this.update()));
        this.appServer.getApplicationInfo().then(i => { this.appVersion = i?.version ?? ''; this.update(); }).catch(() => undefined);
        this.update();
    }

    protected run(id: string, ...args: unknown[]): void {
        this.commands.executeCommand(id, ...args);
    }

    static readonly DRAG_TYPE = 'application/x-studio-instance';
    protected dropTarget: string | null = null;

    /** 그룹(폴더) 한 칸: 머리(접기·이름·개수·이름 바꾸기·풀기) + 카드. 카드를 끌어다 놓으면 이 그룹으로 */
    protected renderSection(group: string | undefined, items: Instance[]): React.ReactNode {
        const name = group ?? '그룹 없음';
        const collapsed = this.manager.isGroupCollapsed('home', name);
        const key = group ?? '';
        return <section key={name} aria-label={name} className={'studio-home-group' + (this.dropTarget === key ? ' drop' : '')}
            onDragOver={e => {
                if (e.dataTransfer.types.includes(HomeWidget.DRAG_TYPE)) {
                    e.preventDefault();
                    if (this.dropTarget !== key) { this.dropTarget = key; this.update(); }
                }
            }}
            onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node) && this.dropTarget === key) { this.dropTarget = null; this.update(); } }}
            onDrop={e => {
                const id = e.dataTransfer.getData(HomeWidget.DRAG_TYPE);
                this.dropTarget = null;
                this.update();
                if (id) { e.preventDefault(); this.run(StudioCommands.SET_GROUP.id, id, group ?? null); }
            }}>
            <div className='studio-group-head' role='button' tabIndex={0} aria-expanded={!collapsed}
                onClick={() => this.manager.toggleGroup('home', name)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.manager.toggleGroup('home', name); } }}>
                <span className={'codicon ' + (collapsed ? 'codicon-chevron-right' : 'codicon-chevron-down')} aria-hidden='true' />
                <span className={'codicon ' + (group ? (collapsed ? 'codicon-folder' : 'codicon-folder-opened') : 'codicon-inbox')} aria-hidden='true' />
                <span className='studio-group-name'>{name}</span>
                <span className='studio-group-count'>{items.length}</span>
                {group && <>
                    <button className='studio-icon-btn codicon codicon-edit' aria-label={`${group} 이름 바꾸기`} title='그룹 이름 바꾸기'
                        onClick={e => { e.stopPropagation(); this.run(StudioCommands.RENAME_GROUP.id, group); }} />
                    <button className='studio-icon-btn codicon codicon-close' aria-label={`${group} 그룹 풀기`} title='그룹 풀기(인스턴스는 그대로)'
                        onClick={e => { e.stopPropagation(); this.run(StudioCommands.UNGROUP.id, group); }} />
                </>}
            </div>
            {!collapsed && <div className='studio-cards'>{items.map(i => this.renderCard(i))}</div>}
        </section>;
    }

    protected renderCard(i: Instance): React.ReactNode {
        const running = this.manager.isRunning(i.id);
        return <article key={i.id} className='studio-card studio-inst-card' draggable
            onDragStart={e => { e.dataTransfer.setData(HomeWidget.DRAG_TYPE, i.id); e.dataTransfer.effectAllowed = 'move'; }}
            onContextMenu={e => { e.preventDefault(); this.run(StudioCommands.MANAGE.id, i.id); }}>
            <div className='studio-card-banner' style={{ background: banner(i) }} aria-hidden='true' />
            <div className='studio-card-body'>
                <h3>{i.name}{running && <span className='studio-chip on'>실행 중</span>}</h3>
                <div className='studio-tags'>
                    {i.group && <span className='studio-chip'>{i.group}</span>}
                    <span className='studio-chip'>Java {i.version}</span>
                    <span className='studio-chip'>{loaderLabel(i)}{i.loaderVersion ? ` ${i.loaderVersion}` : ''}</span>
                    {!i.installed && <span className='studio-chip warn'>설치 전</span>}
                    {i.linkedDir && <span className='studio-chip' title={`원래 폴더를 그대로 씀: ${i.linkedDir}`}>연결됨</span>}
                    {i.loader === 'fabric' && <span className='studio-chip'>CommandCrafter {i.ccEnabled ? '켬' : '끔'}</span>}
                </div>
                <div className='studio-mono studio-muted studio-path' title={i.path}>{i.linkedDir ?? i.id}</div>
                <div className='studio-card-actions'>
                    <button className='theia-button' disabled={running} aria-label={`${i.name} 실행 (Prism)`}
                        title={running ? '실행 중 — 게임 창을 닫으면 종료됩니다' : 'Prism 으로 실행 — Prism 에 로그인한 Microsoft 계정으로 플레이'}
                        onClick={() => this.run(StudioCommands.LAUNCH.id, i.id)}>
                        <span className='codicon codicon-play' aria-hidden='true' /> {running ? '실행 중' : '실행'}</button>
                    <button className='theia-button secondary' title='작업실에서 열기' onClick={() => this.run(StudioCommands.OPEN_WORKSPACE.id, i.id)}>작업실</button>
                    <button className='theia-button secondary codicon codicon-folder' aria-label={`${i.name} 폴더 열기`} title='폴더 열기 (파일 탐색기)'
                        onClick={() => this.run(StudioCommands.OPEN_FOLDER.id, i.id)} />
                    <button className='theia-button secondary studio-more codicon codicon-ellipsis' aria-label={`${i.name} 관리`} title='관리 — 이름 바꾸기·복제·메모리·삭제 등'
                        onClick={() => this.more(i)} />
                </div>
            </div>
        </article>;
    }

    protected render(): React.ReactNode {
        const all = this.manager.instances;
        const q = this.query.trim().toLowerCase();
        const list = q ? all.filter(i => i.name.toLowerCase().includes(q)) : all;
        return <div className='studio-home-inner'>
            <header className='studio-home-hero'>
                <div className='studio-logo' aria-hidden='true' />
                <div>
                    <h1>통합 작업실</h1>
                    <p className='studio-muted'>마인크래프트 실행 · 데이터팩 · 모드 · 리소스팩{this.appVersion && ` · 버전 ${this.appVersion}`}</p>
                </div>
            </header>
            {!this.manager.launcherEnabled && <section className='studio-home-noprism'>
                <h2>런처 기능이 꺼져 있습니다</h2>
                <p className='studio-muted'>인스턴스 만들기·실행은 Prism Launcher 가 맡습니다. Prism 이 설치돼 있지 않아 런처 부분(인스턴스 목록·실행·작업)을 숨겼습니다.
                    코드 편집기·데이터팩 도구·Claude 는 [파일 → 폴더 열기]로 그대로 쓸 수 있습니다.</p>
                <div className='studio-home-noprism-actions'>
                    <button className='theia-button' onClick={() => this.commands.executeCommand('studio.prism.install')}>Prism Launcher 설치</button>
                    <button className='theia-button secondary' onClick={() => this.commands.executeCommand('studio.instance.refresh')}>다시 확인</button>
                </div>
            </section>}
            <div className='studio-home-columns'>
                <main className='studio-home-main'>
                    <div className='studio-home-toolbar'>
                        <h2>인스턴스</h2>
                        <span className='studio-muted'>{all.length}개</span>
                        <div className='studio-spacer' />
                        <label className='studio-search'>
                            <span className='codicon codicon-search' aria-hidden='true' />
                            <input type='text' placeholder='인스턴스 검색' aria-label='인스턴스 검색' value={this.query}
                                onChange={e => { this.query = e.target.value; this.update(); }} />
                        </label>
                        <button className='theia-button' onClick={() => this.run(StudioCommands.CREATE.id)}>+ 새 인스턴스</button>
                    </div>
                    {this.manager.error && <div className='studio-card studio-error'>사이드카 오류: {this.manager.error}</div>}
                    {(() => {
                        const sections = groupInstances([...list]);
                        const flat = sections.length === 1 && !sections[0].group;
                        return flat
                            ? <div className='studio-cards'>{sections[0].items.map(i => this.renderCard(i))}</div>
                            : sections.map(s => this.renderSection(s.group, s.items));
                    })()}
                    {list.length === 0 && !this.manager.error && <div className='studio-muted'>
                        {all.length ? '검색 결과가 없습니다.' : '아직 인스턴스가 없습니다. “+ 새 인스턴스”로 시작하세요.'}
                    </div>}
                </main>
                <aside className='studio-home-side'>
                    <section className='studio-card'>
                        <h2>무엇을 만들까?</h2>
                        <button className='studio-quick' onClick={() => this.run('studio.datapack.new')}>
                            <span className='studio-mono' style={{ color: '#c586c0' }}>fn</span>새 데이터팩 만들기</button>
                        <button className='studio-quick' onClick={() => this.run('studio.mod.newTemplate')}>
                            <span className='studio-mono' style={{ color: '#4fc1ff' }}>.j</span>Fabric 모드 템플릿 (빌드 + 테스트 인스턴스)</button>
                        <button className='studio-quick' onClick={() => this.run('studio.resourcepack.open')}>
                            <span className='studio-mono' style={{ color: '#e0a43a' }}>px</span>리소스팩 만들기</button>
                        <button className='studio-quick' onClick={() => this.run('studio.claude.open')}>
                            <span className='studio-mono' style={{ color: '#d99a6c' }}>AI</span>Claude에게 요청하기</button>
                    </section>
                    <section className='studio-card'>
                        <h2>알림</h2>
                        <div className='studio-note'><span className='studio-dot' aria-hidden='true' />
                            인스턴스는 Prism Launcher 인스턴스입니다. ‘실행’을 누르면 Prism 이 바로 켭니다(처음이면 게임 파일을 받습니다). 로그인은 Prism 에서 하고, 이 앱은 계정 정보를 다루지 않습니다. Prism 에서 만든 인스턴스도 여기 자동으로 보입니다.</div>
                        <div className='studio-note'><span className='studio-dot warn' aria-hidden='true' />
                            CommandCrafter 모드는 서비스 포트를 모든 네트워크 인터페이스에 엽니다. 공용 네트워크에서는 방화벽에서 이 포트(52853~)의 외부 접속을 막아 두세요.</div>
                    </section>
                </aside>
            </div>
        </div>;
    }

    protected async more(i: Instance): Promise<void> {
        await this.manager.setTarget(i.id);
        this.run(StudioCommands.MANAGE.id, i.id);
    }
}
