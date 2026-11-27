import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandService } from '@theia/core/lib/common/command';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';
import { WorkspaceService } from '@theia/workspace/lib/browser/workspace-service';
import { workFolderInUrl } from './studio-mode.js';

/** 상단 막대: 홈, 작업실 열기/런처로, /reload, 실행 대상 선택기 + 실행(Prism), 안내 */
@injectable()
export class RunTargetBar extends ReactWidget {
    static readonly ID = 'studio-run-target-bar';

    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(WorkspaceService) protected readonly workspace: WorkspaceService;

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
            <button className='studio-bar-btn studio-home-btn' title='홈 (Alt+Home)' aria-label='홈'
                onClick={() => this.run(TaskCommandIds.HOME_OPEN)}>
                <span className='codicon codicon-home' aria-hidden='true' />홈
            </button>
            {workFolderInUrl()
                ? <button className='studio-bar-btn' title='작업실을 닫고 가벼운 런처로 돌아갑니다(코드 편집기·확장 실행기를 꺼서 메모리를 아낌)'
                    onClick={() => this.workspace.close()}>
                    <span className='codicon codicon-arrow-left' aria-hidden='true' />런처로
                </button>
                : <button className='studio-bar-btn' disabled={!t} title={t ? `'${t.name}' 폴더를 작업실로 엽니다(코드 편집기·데이터팩 도구·Claude)` : '먼저 인스턴스를 고르세요'}
                    onClick={() => t && this.manager.openInWorkspace(t.id)}>
                    <span className='codicon codicon-code' aria-hidden='true' />작업실 열기
                </button>}
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
                <button className='studio-target-btn codicon codicon-play' aria-label='실행 (Prism)' disabled={!t || running}
                    title={running ? '실행 중 — 게임 창을 닫으면 종료됩니다' : '실행 (F5) — Prism 으로'}
                    onClick={() => this.run(StudioCommands.LAUNCH.id, t?.id)} />
            </div>
            <div className='studio-account' title='로그인은 Prism Launcher 에서 합니다. 이 앱은 계정 정보를 다루지 않습니다.'>
                <span className='codicon codicon-globe' aria-hidden='true' />Prism 으로 실행
            </div>
        </div>;
    }
}
