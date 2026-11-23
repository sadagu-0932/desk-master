import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common/command';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { Instance, LOADER_LABELS } from 'integrated-studio-launcher-core/lib/common';

export const loaderLabel = (i: Instance) => LOADER_LABELS[i.loader] ?? i.loader;

/** 사이드바 아래쪽 "인스턴스" 뷰 */
@injectable()
export class InstancesWidget extends ReactWidget {
    static readonly ID = 'studio-instances';

    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(CommandService) protected readonly commands: CommandService;

    @postConstruct()
    protected init(): void {
        this.id = InstancesWidget.ID;
        this.title.label = '인스턴스';
        this.title.caption = '인스턴스';
        this.title.closable = false;
        this.addClass('studio-instances');
        this.toDispose.push(this.manager.onDidChange(() => this.update()));
        this.update();
    }

    protected render(): React.ReactNode {
        const { instances, error } = this.manager;
        const target = this.manager.target;
        if (error) {
            return <div className='studio-empty studio-error'>
                <div>사이드카 오류</div>
                <div className='studio-muted'>{error}</div>
                <button className='theia-button secondary' onClick={() => this.manager.refresh()}>다시 시도</button>
            </div>;
        }
        if (instances.length === 0) {
            return <div className='studio-empty'>
                <div className='studio-muted'>아직 인스턴스가 없습니다.</div>
                <button className='theia-button' onClick={() => this.commands.executeCommand(StudioCommands.CREATE.id)}>+ 새 인스턴스</button>
            </div>;
        }
        return <div className='studio-list' role='list' aria-label='인스턴스'>
            {instances.map(i => {
                const running = this.manager.isRunning(i.id);
                const server = this.manager.state(i.id).server;
                const sub = running ? `실행 중 · ${loaderLabel(i)}` : `Java ${i.version} · ${loaderLabel(i)}${i.installed ? '' : ' · 설치 전'}`;
                return <div key={i.id} role='listitem'
                    className={'studio-row' + (target?.id === i.id ? ' active' : '')}
                    onClick={() => this.manager.setTarget(i.id)}
                    onDoubleClick={() => this.commands.executeCommand(StudioCommands.OPEN_WORKSPACE.id, i.id)}
                    title={i.path}>
                    <span className={'studio-dot' + (running ? ' on' : '') + (server ? ' server' : '')} aria-hidden='true' />
                    <span className='studio-row-text'>
                        <span className='studio-row-name'>{i.name}</span>
                        <span className='studio-row-sub'>{sub}{server ? ' · 서버' : ''}</span>
                    </span>
                    <button className='studio-icon-btn codicon codicon-play' aria-label={`${i.name} 실행 (공식 런처)`} disabled={running}
                        title={running ? '실행 중 — 게임 창을 닫으면 종료됩니다' : '실행 (F5) — 공식 런처로'}
                        onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.LAUNCH.id, i.id); }} />
                    <button className='studio-icon-btn codicon codicon-folder-opened' aria-label={`${i.name} 작업실에서 열기`} title='작업실에서 열기'
                        onClick={e => { e.stopPropagation(); this.commands.executeCommand(StudioCommands.OPEN_WORKSPACE.id, i.id); }} />
                </div>;
            })}
        </div>;
    }
}
