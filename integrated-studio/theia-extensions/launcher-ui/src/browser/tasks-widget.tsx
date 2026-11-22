import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { CommandRegistry } from '@theia/core/lib/common/command';
import { InstanceManager } from 'integrated-studio-launcher-core/lib/browser';
import { TaskCommandIds } from './studio-command-ids.js';

interface TaskItem {
    label: string;
    command: string;
    key: string;
}

const TASKS: TaskItem[] = [
    { label: '로컬 서버 실행', command: TaskCommandIds.SERVER_TOGGLE, key: 'F6' },
    { label: '모드 빌드 후 테스트 실행', command: TaskCommandIds.MOD_BUILD_TEST, key: 'F7' },
    { label: '리소스팩 적용 후 다시 불러오기', command: TaskCommandIds.RESOURCEPACK_APPLY, key: 'F8' },
    { label: '데이터팩 .zip 내보내기', command: TaskCommandIds.DATAPACK_ZIP, key: '' },
    { label: '데이터팩을 월드로 동기화', command: TaskCommandIds.DATAPACK_SYNC, key: '' },
];

/** 사이드바 "작업" 뷰 */
@injectable()
export class TasksWidget extends ReactWidget {
    static readonly ID = 'studio-tasks';

    @inject(CommandRegistry) protected readonly commands: CommandRegistry;
    @inject(InstanceManager) protected readonly manager: InstanceManager;

    @postConstruct()
    protected init(): void {
        this.id = TasksWidget.ID;
        this.title.label = '작업';
        this.title.caption = '작업';
        this.title.closable = false;
        this.addClass('studio-tasks');
        this.toDispose.push(this.manager.onDidChange(() => this.update()));
        this.update();
    }

    protected render(): React.ReactNode {
        const server = this.manager.state(this.manager.current?.id).server;
        return <div className='studio-list'>
            {TASKS.map(t => {
                const label = t.command === TaskCommandIds.SERVER_TOGGLE && server ? '로컬 서버 중지' : t.label;
                const available = this.commands.getCommand(t.command) !== undefined;
                return <button key={t.command} className='studio-task' disabled={!available}
                    onClick={() => this.commands.executeCommand(t.command)}>
                    <span>{label}</span>
                    {t.key && <kbd>{t.key}</kbd>}
                </button>;
            })}
        </div>;
    }
}
