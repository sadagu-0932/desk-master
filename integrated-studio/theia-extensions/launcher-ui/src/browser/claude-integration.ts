import { inject, injectable } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { StatusBar, StatusBarAlignment } from '@theia/core/lib/browser/status-bar/status-bar';
import { QuickInputService, QuickPickItem } from '@theia/core/lib/browser/quick-input';
import { TabBarToolbarContribution, TabBarToolbarRegistry } from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import { Widget } from '@theia/core/lib/browser/widgets';
import { Command, CommandContribution, CommandRegistry, CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { PreferenceService, PreferenceScope } from '@theia/core/lib/common/preferences';
import { ChatService } from '@theia/ai-chat/lib/common/chat-service';
import { InstanceManager } from 'integrated-studio-launcher-core/lib/browser';
import { LauncherService, TaskCommandIds, WorkMode } from 'integrated-studio-launcher-core/lib/common';

const CATEGORY = '통합 작업실';
const CHAT_VIEW_ID = 'chat-view-widget';
const CHAT_TOGGLE = 'aiChat:toggle';
const SDK_PATH_PREF = 'ai-features.claudeCode.executablePath';
const DEFAULT_AGENT_PREF = 'ai-features.chat.defaultChatAgent';

const MODES: { id: WorkMode; label: string; detail: string }[] = [
    { id: 'datapack', label: '데이터팩', detail: 'datapacks/ 안만 수정 · 셸 명령 금지' },
    { id: 'mod', label: 'Fabric 모드', detail: 'mods-src/ 안만 수정 · ./gradlew build 만 허용' },
    { id: 'resourcepack', label: '리소스팩', detail: 'resourcepacks/ 안만 수정 · 원본 대신 "Claude 제안" 새 파일' },
];

export namespace ClaudeCommands {
    export const OPEN: Command = { id: 'studio.claude.open', category: CATEGORY, label: 'Claude 패널 열기' };
    export const APPLY_RELOAD: Command = { id: TaskCommandIds.CLAUDE_APPLY_RELOAD, category: CATEGORY, label: 'Claude 변경 적용 후 /reload', iconClass: 'codicon codicon-check-all' };
    export const WORK_MODE: Command = { id: TaskCommandIds.CLAUDE_WORK_MODE, category: CATEGORY, label: 'Claude 작업 종류 바꾸기' };
}

/**
 * Claude 패널(@theia/ai-claude-code) 연동.
 * - 작업 디렉터리: Theia가 작업 공간 첫 루트를 쓰므로 "작업실에서 열기"로 인스턴스 폴더를 열면 그 폴더가 된다.
 * - 작업 종류 칩: 인스턴스의 .claude/settings.json(허용 도구)과 .claude/studio-mode.md(추가 지시)를 바꾼다.
 */
@injectable()
export class ClaudeIntegration implements FrontendApplicationContribution, CommandContribution, TabBarToolbarContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(LauncherService) protected readonly launcher: LauncherService;
    @inject(PreferenceService) protected readonly preferences: PreferenceService;
    @inject(StatusBar) protected readonly statusBar: StatusBar;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(ChatService) protected readonly chat: ChatService;

    protected sdkFound: boolean | undefined;

    async onStart(): Promise<void> {
        this.manager.onDidChange(() => this.updateStatus());
        await this.preferences.ready;
        if (!this.preferences.get<string>(SDK_PATH_PREF)) {
            const cli = await this.launcher.bundledClaudeSdkCli();
            this.sdkFound = !!cli;
            if (cli) {
                await this.preferences.set(SDK_PATH_PREF, cli, PreferenceScope.User);
            }
        } else {
            this.sdkFound = true;
        }
        if (!this.preferences.get<string>(DEFAULT_AGENT_PREF)) {
            await this.preferences.set(DEFAULT_AGENT_PREF, 'ClaudeCode', PreferenceScope.User);
        }
        this.updateStatus();
    }

    protected modeOf(id: WorkMode | undefined) {
        return MODES.find(m => m.id === id) ?? MODES[0];
    }

    protected updateStatus(): void {
        const inst = this.manager.workspaceInstance;
        const mode = this.modeOf(inst?.workMode);
        this.statusBar.setElement('studio-claude', {
            text: this.sdkFound === false ? '$(warning) Claude: SDK 없음' : `$(sparkle) Claude: ${inst ? mode.label : '대기 중'}`,
            tooltip: this.sdkFound === false
                ? 'Claude Agent SDK를 찾지 못했습니다. npm install 을 다시 실행하거나 설정에서 경로를 지정하세요.'
                : inst ? `작업 폴더: ${inst.path}\n클릭해서 작업 종류 바꾸기` : '인스턴스를 작업실에서 열면 그 폴더에서 Claude가 작업합니다.',
            alignment: StatusBarAlignment.RIGHT,
            priority: 200,
            command: inst ? ClaudeCommands.WORK_MODE.id : ClaudeCommands.OPEN.id,
        });
    }

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(ClaudeCommands.OPEN, {
            execute: async () => {
                if (!this.manager.workspaceInstance) {
                    this.messages.info('Claude는 열려 있는 작업 공간 폴더에서 작업합니다. 인스턴스를 "작업실에서 열기"로 먼저 여는 것을 권장합니다.');
                }
                await this.commands.executeCommand(CHAT_TOGGLE);
            }
        });
        registry.registerCommand(ClaudeCommands.WORK_MODE, { execute: () => this.pickMode() });
        registry.registerCommand(ClaudeCommands.APPLY_RELOAD, {
            execute: () => this.applyAndReload(),
            isVisible: (w?: Widget) => !w || w.id === CHAT_VIEW_ID,
        });
    }

    registerToolbarItems(registry: TabBarToolbarRegistry): void {
        registry.registerItem({
            id: 'studio.claude.workMode.toolbar',
            command: ClaudeCommands.WORK_MODE.id,
            text: '$(layers) 작업 종류',
            tooltip: '작업 종류: 데이터팩 / Fabric 모드 / 리소스팩',
            isVisible: (w: Widget) => w.id === CHAT_VIEW_ID,
            priority: 0,
        });
        registry.registerItem({
            id: 'studio.claude.applyReload.toolbar',
            command: ClaudeCommands.APPLY_RELOAD.id,
            text: '$(check-all) 적용 후 /reload',
            tooltip: 'Claude 변경 사항을 모두 적용하고 게임에 /reload 보내기',
            isVisible: (w: Widget) => w.id === CHAT_VIEW_ID,
            priority: 1,
        });
    }

    protected async pickMode(): Promise<void> {
        const inst = this.manager.workspaceInstance;
        if (!inst) {
            this.messages.info('작업 종류는 인스턴스를 작업실에서 연 뒤에 바꿀 수 있습니다.');
            return;
        }
        const items = MODES.map(m => ({ label: m.label, description: m.detail, id: m.id, picked: m.id === inst.workMode }));
        const picked = await this.quickInput.showQuickPick<QuickPickItem & { id: WorkMode }>(items, {
            placeholder: `지금: ${this.modeOf(inst.workMode).label} — Claude가 수정할 수 있는 범위`,
        });
        if (picked) {
            await this.manager.setWorkMode(inst.id, picked.id);
            this.messages.info(`Claude 작업 종류: ${picked.label}. 새 대화부터 적용됩니다.`);
        }
    }

    /** 대기 중인 변경 묶음(change set)을 모두 적용하고 게임에 /reload 를 보낸다 */
    protected async applyAndReload(): Promise<void> {
        const session = this.chat.getActiveSession();
        let applied = 0;
        if (session) {
            for (const el of session.model.changeSet.getElements()) {
                if (el.state === 'pending' && el.apply) {
                    await el.apply();
                    applied++;
                }
            }
        }
        const inst = this.manager.current;
        if (inst) {
            this.manager.log(inst.id, `Claude 변경 ${applied}개 적용`, 'info', 'studio');
        }
        const workMode = this.manager.workspaceInstance?.workMode;
        if (workMode === 'resourcepack') {
            await this.commands.executeCommand(TaskCommandIds.RESOURCEPACK_APPLY);
        } else {
            await this.commands.executeCommand(TaskCommandIds.GAME_RELOAD);
        }
    }
}
