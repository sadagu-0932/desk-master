import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { BaseWidget, Message } from '@theia/core/lib/browser/widgets/widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { InstanceManager } from 'integrated-studio-launcher-core/lib/browser';
import { LogEvent } from 'integrated-studio-launcher-core/lib/common';

const MAX_DOM_LINES = 3000;

/** 하단 패널 "게임 로그" 탭. 현재 실행 대상의 로그만 레벨별 색으로 보여준다. */
@injectable()
export class GameLogWidget extends BaseWidget {
    static readonly ID = 'studio-game-log';
    static readonly LABEL = '게임 로그';

    @inject(InstanceManager) protected readonly manager: InstanceManager;

    protected header: HTMLDivElement;
    protected body: HTMLDivElement;
    protected filterInput: HTMLInputElement;
    protected shownId: string | undefined;
    protected stickToBottom = true;

    @postConstruct()
    protected init(): void {
        this.id = GameLogWidget.ID;
        this.title.label = GameLogWidget.LABEL;
        this.title.caption = GameLogWidget.LABEL;
        this.title.iconClass = codicon('output');
        this.title.closable = true;
        this.addClass('studio-log');

        this.header = document.createElement('div');
        this.header.className = 'studio-log-header';
        this.filterInput = document.createElement('input');
        this.filterInput.className = 'theia-input studio-log-filter';
        this.filterInput.placeholder = '로그 필터';
        this.filterInput.setAttribute('aria-label', '로그 필터');
        this.filterInput.addEventListener('input', () => this.rerender());
        const clear = document.createElement('button');
        clear.className = 'studio-icon-btn ' + codicon('clear-all');
        clear.title = '로그 지우기';
        clear.setAttribute('aria-label', '로그 지우기');
        clear.addEventListener('click', () => this.manager.clearLogs());
        this.header.append(this.filterInput, clear);

        this.body = document.createElement('div');
        this.body.className = 'studio-log-body';
        this.body.setAttribute('role', 'log');
        this.body.tabIndex = 0;
        this.body.addEventListener('scroll', () => {
            this.stickToBottom = this.body.scrollTop + this.body.clientHeight >= this.body.scrollHeight - 8;
        });
        this.node.append(this.header, this.body);

        this.toDispose.push(this.manager.onLog(ev => this.append(ev)));
        this.toDispose.push(this.manager.onDidClearLogs(() => this.rerender()));
        this.toDispose.push(this.manager.onDidChange(() => {
            if (this.manager.current?.id !== this.shownId) {
                this.rerender();
            }
        }));
        this.rerender();
    }

    protected matches(ev: LogEvent): boolean {
        const id = this.manager.current?.id;
        if (id && ev.id && ev.id !== id) {
            return false;
        }
        const f = this.filterInput.value.trim().toLowerCase();
        return !f || ev.line.toLowerCase().includes(f);
    }

    protected lineNode(ev: LogEvent): HTMLDivElement {
        const div = document.createElement('div');
        div.className = `studio-log-line level-${ev.level} source-${ev.source}`;
        div.textContent = ev.line;
        return div;
    }

    protected append(ev: LogEvent): void {
        if (!this.matches(ev)) {
            return;
        }
        this.body.appendChild(this.lineNode(ev));
        while (this.body.childElementCount > MAX_DOM_LINES) {
            this.body.firstElementChild?.remove();
        }
        if (this.stickToBottom) {
            this.body.scrollTop = this.body.scrollHeight;
        }
    }

    protected rerender(): void {
        this.shownId = this.manager.current?.id;
        const frag = document.createDocumentFragment();
        const lines = this.manager.logs.filter(ev => this.matches(ev)).slice(-MAX_DOM_LINES);
        lines.forEach(ev => frag.appendChild(this.lineNode(ev)));
        this.body.replaceChildren(frag);
        if (lines.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'studio-muted studio-log-empty';
            empty.textContent = '게임을 실행하면 로그가 여기에 나옵니다 (F5).';
            this.body.appendChild(empty);
        }
        this.body.scrollTop = this.body.scrollHeight;
    }

    protected onActivateRequest(msg: Message): void {
        super.onActivateRequest(msg);
        this.body.focus();
    }
}
