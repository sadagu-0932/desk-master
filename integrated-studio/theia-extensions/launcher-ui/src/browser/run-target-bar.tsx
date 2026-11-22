import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common/command';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { DEFAULT_USERNAME, TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';

/** 상단 막대: /reload, 실행 대상 선택기 + 실행/재시작/중지, 계정 표시 */
@injectable()
export class RunTargetBar extends ReactWidget {
    static readonly ID = 'studio-run-target-bar';

    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(CommandService) protected readonly commands: CommandService;

    @postConstruct()
    protected init(): void {
        this.id = RunTargetBar.ID;
        this.addClass('studio-run-bar');
        this.toDispose.push(this.manager.onDidChange(() => this.update()));
        this.update();
    }

    protected run(id: string, arg?: unknown): void {
        this.commands.executeCommand(id, arg);
    }

    protected render(): React.ReactNode {
        const t = this.manager.target;
        const running = this.manager.isRunning(t?.id);
        return <div className='studio-run-bar-inner'>
            <button className='studio-bar-btn' title='데이터팩 다시 불러오기 (/reload)' disabled={!t}
                onClick={() => this.run(TaskCommandIds.GAME_RELOAD)}>
                <span className='codicon codicon-refresh' aria-hidden='true' />/reload
            </button>
            <div className='studio-target' role='group' aria-label='실행 대상'>
                <button className='studio-target-pick' aria-label='실행 대상 바꾸기' title='실행 대상 바꾸기'
                    onClick={() => this.run(StudioCommands.SELECT_TARGET.id)}>
                    <span className={'studio-dot' + (running ? ' on' : '')} aria-hidden='true' />
                    {t ? `${t.name} · 게임` : '인스턴스 없음'}
                    <span className='codicon codicon-chevron-down' aria-hidden='true' />
                </button>
                {running
                    ? <>
                        <button className='studio-target-btn codicon codicon-debug-restart' aria-label='재시작' title='재시작'
                            onClick={() => this.run(StudioCommands.RESTART.id, t?.id)} />
                        <button className='studio-target-btn codicon codicon-debug-stop' aria-label='중지' title='중지 (Shift+F5)'
                            onClick={() => this.run(StudioCommands.STOP.id, t?.id)} />
                    </>
                    : <button className='studio-target-btn codicon codicon-play' aria-label='실행' title='실행 (F5)' disabled={!t}
                        onClick={() => this.run(StudioCommands.LAUNCH.id, t?.id)} />}
            </div>
            <div className='studio-account' title='MS 로그인: 준비 중 — 지금은 오프라인 테스트 모드로만 실행됩니다'>
                <span className='studio-avatar' aria-hidden='true' />오프라인 · {DEFAULT_USERNAME}
            </div>
        </div>;
    }
}
