import { inject, injectable } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { FrontendApplication } from '@theia/core/lib/browser/frontend-application';
import { ApplicationShell } from '@theia/core/lib/browser/shell/application-shell';
import { WidgetManager } from '@theia/core/lib/browser/widget-manager';
import { ViewContainer } from '@theia/core/lib/browser/view-container';
import { KeybindingRegistry } from '@theia/core/lib/browser/keybinding';
import { StatusBar, StatusBarAlignment } from '@theia/core/lib/browser/status-bar/status-bar';
import { OpenerService, open } from '@theia/core/lib/browser/opener-service';
import { PreferenceService, PreferenceScope } from '@theia/core/lib/common/preferences';
import { Command, CommandContribution, CommandRegistry, CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { WindowService } from '@theia/core/lib/browser/window/window-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { Widget } from '@theia/core/lib/browser/widgets';
import { EXPLORER_VIEW_CONTAINER_ID } from '@theia/navigator/lib/browser/navigator-widget-factory';
import { errorMessage, InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { Instance, TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';
import { InstancesWidget, loaderLabel } from './instances-widget.js';
import { TasksWidget } from './tasks-widget.js';
import { GameLogWidget } from './game-log-widget.js';
import { CommandConsoleWidget } from './command-console-widget.js';
import { RunTargetBar } from './run-target-bar.js';
import { HomeWidget } from './home-widget.js';
import { workFolderInUrl } from './studio-mode.js';

const CATEGORY = '통합 작업실';
const CC_ADDRESS_PREF = 'CommandCrafter.MinecraftAddress';
const CC_RELOAD = 'commandcrafter.reload';
const CC_RUN = 'commandcrafter.runCommand';

export namespace UiCommands {
    export const HOME: Command = { id: TaskCommandIds.HOME_OPEN, category: CATEGORY, label: '홈 열기' };
    export const GAME_LOG: Command = { id: TaskCommandIds.GAME_LOG_TOGGLE, category: CATEGORY, label: '게임 로그 보기' };
    export const CONSOLE: Command = { id: TaskCommandIds.CONSOLE_TOGGLE, category: CATEGORY, label: '명령어 콘솔 보기' };
    export const SERVER: Command = { id: TaskCommandIds.SERVER_TOGGLE, category: CATEGORY, label: '로컬 서버 실행/중지' };
    export const RELOAD: Command = { id: TaskCommandIds.GAME_RELOAD, category: CATEGORY, label: '게임에 /reload 보내기' };
    export const RUN_COMMAND: Command = { id: TaskCommandIds.GAME_RUN_COMMAND, category: CATEGORY, label: '게임에 명령 보내기' };
}

@injectable()
export class StudioUiContribution implements FrontendApplicationContribution, CommandContribution {
    @inject(ApplicationShell) protected readonly shell: ApplicationShell;
    @inject(WidgetManager) protected readonly widgets: WidgetManager;
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(StatusBar) protected readonly statusBar: StatusBar;
    @inject(KeybindingRegistry) protected readonly keybindings: KeybindingRegistry;
    @inject(CommandRegistry) protected readonly commandRegistry: CommandRegistry;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(PreferenceService) protected readonly preferences: PreferenceService;
    @inject(OpenerService) protected readonly openers: OpenerService;
    @inject(WindowService) protected readonly windows: WindowService;

    // ---------- 레이아웃 ----------
    initialize(): void {
        // 탐색기(파일 트리) 아래에 "인스턴스"와 "작업" 뷰를 붙인다
        this.widgets.onWillCreateWidget(event => {
            if (event.factoryId === EXPLORER_VIEW_CONTAINER_ID && event.widget instanceof ViewContainer) {
                const container = event.widget;
                event.waitUntil((async () => {
                    const instances = await this.widgets.getOrCreateWidget(InstancesWidget.ID);
                    const tasks = await this.widgets.getOrCreateWidget(TasksWidget.ID);
                    container.addWidget(instances, { order: 10, weight: 30, canHide: true });
                    container.addWidget(tasks, { order: 11, weight: 18, canHide: true });
                })());
            }
        });
    }

    async onDidInitializeLayout(_app: FrontendApplication): Promise<void> {
        const bar = await this.widgets.getOrCreateWidget<RunTargetBar>(RunTargetBar.ID);
        if (!bar.isAttached) {
            await this.shell.addWidget(bar, { area: 'top' });
        }
        // 기본(네이티브) 메뉴를 쓰면 Theia가 위쪽 패널을 숨기므로 실행 대상 막대를 위해 보이게 한다
        this.shell.topPanel.show();
        this.overrideDebugKeys();
        await this.manager.ready;
        if (workFolderInUrl()) {
            // 작업실 모드: 파일 트리를 바로 보여 준다(파일을 누르면 코드 편집기)
            await this.shell.revealWidget('explorer-view-container');
        } else if (!this.manager.workspaceInstance) {
            this.openHome();
        }
        this.syncCommandCrafterAddress();
    }

    async initializeLayout(): Promise<void> {
        await this.openGameLog(false);
        await this.shell.revealWidget('explorer-view-container');
    }

    onStart(): void {
        this.manager.onDidChange(() => this.updateStatusBar());
        this.manager.onState(ev => {
            if (ev.running && ev.source === 'game') {
                this.openGameLog(true);
                this.syncCommandCrafterAddress();
            }
        });
        this.updateStatusBar();
    }

    protected async openHome(): Promise<void> {
        const home = await this.widgets.getOrCreateWidget<HomeWidget>(HomeWidget.ID);
        if (!home.isAttached) {
            await this.shell.addWidget(home, { area: 'main' });
        }
        await this.shell.activateWidget(home.id);
    }

    protected async openBottom(id: string, activate: boolean): Promise<Widget> {
        const w = await this.widgets.getOrCreateWidget(id);
        if (!w.isAttached) {
            await this.shell.addWidget(w, { area: 'bottom' });
        }
        if (activate) {
            await this.shell.activateWidget(w.id);
        } else {
            await this.shell.revealWidget(w.id);
        }
        return w;
    }

    protected async openGameLog(activate: boolean): Promise<void> {
        await this.openBottom(CommandConsoleWidget.ID, false);
        await this.openBottom(GameLogWidget.ID, activate);
    }

    // ---------- 상태 표시줄 ----------
    protected updateStatusBar(): void {
        const cur = this.manager.current;
        if (cur) {
            const running = this.manager.isRunning(cur.id);
            this.statusBar.setElement('studio-instance', {
                text: `$(${running ? 'circle-filled' : 'circle-outline'}) ${cur.name} · Java ${cur.version} · ${loaderLabel(cur)}`,
                tooltip: running ? '실행 중 — 클릭해서 실행 대상 바꾸기' : '실행 대상 바꾸기',
                alignment: StatusBarAlignment.LEFT,
                priority: 1000,
                command: StudioCommands.SELECT_TARGET.id,
            });
        } else {
            this.statusBar.setElement('studio-instance', {
                text: '$(add) 새 인스턴스',
                alignment: StatusBarAlignment.LEFT,
                priority: 1000,
                command: StudioCommands.CREATE.id,
            });
        }
    }

    // ---------- CommandCrafter 연결 ----------
    /** 작업 공간 설정에 현재 인스턴스의 CommandCrafter 포트를 쓴다(인스턴스마다 다른 포트). */
    protected async syncCommandCrafterAddress(): Promise<void> {
        const inst = this.manager.workspaceInstance;
        if (!inst || inst.loader !== 'fabric') {
            return;
        }
        const address = `localhost:${inst.ccPort}`;
        if (this.preferences.get(CC_ADDRESS_PREF) !== address) {
            await this.preferences.set(CC_ADDRESS_PREF, address, PreferenceScope.Workspace);
        }
    }

    protected ccAvailable(inst: Instance | undefined): boolean {
        return !!inst && inst.loader === 'fabric' && inst.ccEnabled && this.manager.isRunning(inst.id)
            && this.manager.workspaceInstance?.id === inst.id;
    }

    // ---------- 명령 ----------
    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(UiCommands.HOME, { execute: () => this.openHome() });
        registry.registerCommand(UiCommands.GAME_LOG, { execute: () => this.openBottom(GameLogWidget.ID, true) });
        registry.registerCommand(UiCommands.CONSOLE, { execute: () => this.openBottom(CommandConsoleWidget.ID, true) });
        registry.registerCommand(UiCommands.SERVER, { execute: () => this.toggleServer() });
        registry.registerCommand(UiCommands.RELOAD, { execute: () => this.reload() });
        registry.registerCommand(UiCommands.RUN_COMMAND, { execute: (cmd: string) => this.runGameCommand(cmd) });
    }

    /** 실행 중인 게임(CommandCrafter) → 로컬 서버 순서로 /reload 를 보낸다 */
    async reload(): Promise<boolean> {
        const inst = this.manager.current;
        if (!inst) {
            return false;
        }
        // 작업용 원본(datapacks/)을 월드로 먼저 동기화한다
        if (this.commandRegistry.getCommand('studio.datapack.syncAll')) {
            await this.commands.executeCommand('studio.datapack.syncAll');
        }
        if (this.ccAvailable(inst) && this.commandRegistry.getCommand(CC_RELOAD)) {
            await this.commands.executeCommand(CC_RELOAD);
            this.manager.log(inst.id, '/reload 보냄 (CommandCrafter)', 'info', 'studio');
            return true;
        }
        if (this.manager.state(inst.id).server) {
            await this.manager.serverCommand(inst.id, 'reload');
            this.manager.log(inst.id, '/reload 보냄 (로컬 서버)', 'info', 'studio');
            return true;
        }
        if (this.manager.isRunning(inst.id)) {
            this.messages.warn('게임에 연결할 수 없습니다. Fabric 인스턴스에서 CommandCrafter를 켜고, 그 인스턴스를 작업실에서 연 상태여야 /reload를 보낼 수 있습니다. 게임 안에서 /reload 를 직접 입력해도 됩니다.');
        } else {
            this.messages.info('실행 중인 게임이나 로컬 서버가 없습니다. 다음에 월드를 열면 변경 사항이 적용됩니다.');
        }
        return false;
    }

    async runGameCommand(cmd: string): Promise<string | undefined> {
        const inst = this.manager.current;
        if (!inst || !cmd) {
            return undefined;
        }
        if (this.ccAvailable(inst) && this.commandRegistry.getCommand(CC_RUN)) {
            await this.commands.executeCommand(CC_RUN, cmd);
            return '게임(CommandCrafter)';
        }
        if (this.manager.state(inst.id).server) {
            await this.manager.serverCommand(inst.id, cmd);
            return '로컬 서버';
        }
        return undefined;
    }

    protected async toggleServer(): Promise<void> {
        const inst = this.manager.current;
        if (!inst) {
            this.messages.info('먼저 인스턴스를 만드세요.');
            return;
        }
        try {
            if (this.manager.state(inst.id).server) {
                await this.manager.serverStop(inst.id);
                return;
            }
            const worlds = await this.manager.call<string[]>('list_worlds', { id: inst.id }).catch(() => [] as string[]);
            const world = worlds[0];
            const res = await this.manager.serverStart(inst.id, world);
            if (res.needsEula) {
                const read = 'EULA 읽기';
                const edit = 'eula.txt 열기';
                const a = await this.messages.warn(
                    '로컬 서버를 실행하려면 마인크래프트 EULA에 직접 동의해야 합니다. EULA를 읽고 동의하면 eula.txt의 eula=false 를 eula=true 로 바꾼 뒤 다시 실행하세요.',
                    read, edit);
                if (a === read && res.eulaUrl) {
                    this.windows.openNewWindow(res.eulaUrl, { external: true });
                } else if (a === edit && res.eulaPath) {
                    await open(this.openers, FileUri.create(res.eulaPath));
                }
                return;
            }
            this.openGameLog(true);
            this.messages.info(`로컬 서버 시작${world ? ` (월드: ${world})` : ''} — 접속 주소 localhost`);
        } catch (e) {
            this.messages.error(errorMessage(e));
        }
    }

    // ---------- 단축키 (VS Code와 같게) ----------
    /** 디버그의 F5/Shift+F5 대신 게임 실행/중지. 모든 기여가 등록된 뒤에 덮어쓴다. */
    protected overrideDebugKeys(): void {
        this.keybindings.unregisterKeybinding('f5');
        this.keybindings.unregisterKeybinding('shift+f5');
        this.keybindings.unregisterKeybinding('f6');
        this.keybindings.unregisterKeybinding('f7');
        this.keybindings.unregisterKeybinding('f8');
        this.keybindings.registerKeybindings(
            { command: StudioCommands.LAUNCH.id, keybinding: 'f5' },
            { command: StudioCommands.STOP.id, keybinding: 'shift+f5' },
            { command: TaskCommandIds.SERVER_TOGGLE, keybinding: 'f6' },
            { command: TaskCommandIds.MOD_BUILD_TEST, keybinding: 'f7' },
            { command: TaskCommandIds.RESOURCEPACK_APPLY, keybinding: 'f8' },
            { command: TaskCommandIds.HOME_OPEN, keybinding: 'alt+home' },
        );
    }
}
