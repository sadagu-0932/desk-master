import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common/command';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';

/** 상단 막대: /reload, 실행 대상 선택기 + 실행(공식 런처), 안내 */
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
                <button className='studio-target-btn codicon codicon-play' aria-label='실행 (공식 런처)' disabled={!t || running}
                    title={running ? '실행 중 — 게임 창을 닫으면 종료됩니다' : '실행 (F5) — 공식 런처로'}
                    onClick={() => this.run(StudioCommands.LAUNCH.id, t?.id)} />
            </div>
            <div className='studio-account' title='로그인은 공식 마인크래프트 런처에서 합니다. 이 앱은 계정 정보를 다루지 않습니다.'>
                <span className='codicon codicon-globe' aria-hidden='true' />공식 런처로 실행
            </div>
        </div>;
    }
}
