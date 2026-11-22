import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { CommandService } from '@theia/core/lib/common/command';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { ApplicationServer } from '@theia/core/lib/common/application-protocol';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { Instance } from 'integrated-studio-launcher-core/lib/common';
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

    protected run(id: string, arg?: unknown): void {
        this.commands.executeCommand(id, arg);
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
                    <div className='studio-cards'>
                        {list.map(i => {
                            const running = this.manager.isRunning(i.id);
                            return <article key={i.id} className='studio-card studio-inst-card'>
                                <div className='studio-card-banner' style={{ background: banner(i) }} aria-hidden='true' />
                                <div className='studio-card-body'>
                                    <h3>{i.name}{running && <span className='studio-chip on'>실행 중</span>}</h3>
                                    <div className='studio-tags'>
                                        {i.group && <span className='studio-chip'>{i.group}</span>}
                                        <span className='studio-chip'>Java {i.version}</span>
                                        <span className='studio-chip'>{loaderLabel(i)}{i.loaderVersion ? ` ${i.loaderVersion}` : ''}</span>
                                        {!i.installed && <span className='studio-chip warn'>설치 전</span>}
                                        {i.loader === 'fabric' && <span className='studio-chip'>CommandCrafter {i.ccEnabled ? '켬' : '끔'}</span>}
                                    </div>
                                    <div className='studio-mono studio-muted' title={i.path}>{i.id}</div>
                                    <div className='studio-card-actions'>
                                        <button className='theia-button' disabled={running} aria-label={`${i.name} 실행 (공식 런처)`}
                                            title={running ? '실행 중 — 게임 창을 닫으면 종료됩니다' : '공식 런처로 실행 — 내 MS 계정으로 플레이'}
                                            onClick={() => this.run(StudioCommands.LAUNCH.id, i.id)}>
                                            <span className='codicon codicon-play' aria-hidden='true' /> {running ? '실행 중' : '실행'}</button>
                                        <button className='theia-button secondary' title='작업실에서 열기' onClick={() => this.run(StudioCommands.OPEN_WORKSPACE.id, i.id)}>작업실</button>
                                        <button className='theia-button secondary studio-more codicon codicon-ellipsis' aria-label={`${i.name} 더보기`}
                                            onClick={() => this.more(i)} />
                                    </div>
                                </div>
                            </article>;
                        })}
                        {list.length === 0 && !this.manager.error && <div className='studio-muted'>
                            {all.length ? '검색 결과가 없습니다.' : '아직 인스턴스가 없습니다. “+ 새 인스턴스”로 시작하세요.'}
                        </div>}
                    </div>
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
                            게임은 공식 마인크래프트 런처로 실행됩니다. ‘실행’을 누르면 공식 런처에 이 인스턴스를 등록하고 열어 주니, 런처에서 ‘플레이’를 누르세요. 로그인은 공식 런처가 하고, 이 앱은 계정 정보를 다루지 않습니다.</div>
                        <div className='studio-note'><span className='studio-dot warn' aria-hidden='true' />
                            CommandCrafter 모드는 서비스 포트를 모든 네트워크 인터페이스에 엽니다. 공용 네트워크에서는 방화벽에서 이 포트(52853~)의 외부 접속을 막아 두세요.</div>
                    </section>
                </aside>
            </div>
        </div>;
    }

    protected async more(i: Instance): Promise<void> {
        await this.manager.setTarget(i.id);
        this.quickInput.open('>통합 작업실: ');
    }
}
