import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { BaseWidget, Message } from '@theia/core/lib/browser/widgets/widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { CommandService } from '@theia/core/lib/common/command';
import { InstanceManager } from 'integrated-studio-launcher-core/lib/browser';
import { TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';

/** 하단 패널 "명령어 콘솔": 실행 중인 게임(CommandCrafter) 또는 로컬 서버에 명령을 보낸다. */
@injectable()
export class CommandConsoleWidget extends BaseWidget {
    static readonly ID = 'studio-command-console';
    static readonly LABEL = '명령어 콘솔';

    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(CommandService) protected readonly commands: CommandService;

    protected output: HTMLDivElement;
    protected input: HTMLInputElement;
    protected history: string[] = [];
    protected historyIndex = -1;

    @postConstruct()
    protected init(): void {
        this.id = CommandConsoleWidget.ID;
        this.title.label = CommandConsoleWidget.LABEL;
        this.title.caption = CommandConsoleWidget.LABEL;
        this.title.iconClass = codicon('terminal');
        this.title.closable = true;
        this.addClass('studio-console');

        this.output = document.createElement('div');
        this.output.className = 'studio-log-body';
        this.output.setAttribute('role', 'log');
        const hint = document.createElement('div');
        hint.className = 'studio-muted';
        hint.textContent = '게임이나 로컬 서버가 실행 중이면 명령을 보낼 수 있습니다. 예: time set day (앞의 / 는 생략해도 됩니다)';
        this.output.appendChild(hint);

        const row = document.createElement('div');
        row.className = 'studio-console-input';
        const prompt = document.createElement('span');
        prompt.className = 'studio-console-prompt';
        prompt.textContent = '/';
        this.input = document.createElement('input');
        this.input.className = 'theia-input';
        this.input.placeholder = '명령어 입력 후 Enter';
        this.input.setAttribute('aria-label', '명령어 입력');
        this.input.spellcheck = false;
        this.input.addEventListener('keydown', e => this.onKey(e));
        row.append(prompt, this.input);
        this.node.append(this.output, row);
    }

    protected onKey(e: KeyboardEvent): void {
        if (e.key === 'Enter') {
            const cmd = this.input.value.trim().replace(/^\//, '');
            if (cmd) {
                this.history.unshift(cmd);
                this.historyIndex = -1;
                this.input.value = '';
                this.send(cmd);
            }
        } else if (e.key === 'ArrowUp' && this.history.length) {
            this.historyIndex = Math.min(this.historyIndex + 1, this.history.length - 1);
            this.input.value = this.history[this.historyIndex];
            e.preventDefault();
        } else if (e.key === 'ArrowDown') {
            this.historyIndex = Math.max(this.historyIndex - 1, -1);
            this.input.value = this.historyIndex >= 0 ? this.history[this.historyIndex] : '';
            e.preventDefault();
        }
    }

    protected print(text: string, cls = ''): void {
        const div = document.createElement('div');
        div.className = 'studio-log-line ' + cls;
        div.textContent = text;
        this.output.appendChild(div);
        this.output.scrollTop = this.output.scrollHeight;
    }

    protected async send(cmd: string): Promise<void> {
        this.print('/' + cmd, 'studio-console-echo');
        try {
            const where = await this.commands.executeCommand<string>(TaskCommandIds.GAME_RUN_COMMAND, cmd);
            this.print(where ? `→ ${where}에 보냄 (결과는 게임 로그 탭)` : '보낼 곳이 없습니다: 게임이나 로컬 서버를 먼저 실행하세요.',
                where ? 'studio-muted' : 'level-warn');
        } catch (err) {
            this.print(err instanceof Error ? err.message : String(err), 'level-error');
        }
    }

    protected onActivateRequest(msg: Message): void {
        super.onActivateRequest(msg);
        this.input.focus();
    }
}
