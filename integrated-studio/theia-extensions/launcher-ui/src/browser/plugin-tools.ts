import { inject, injectable } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry, CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { OpenerService, open } from '@theia/core/lib/browser/opener-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { InstanceManager, reportErrors } from 'integrated-studio-launcher-core/lib/browser';
import { Instance, TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';

const CATEGORY = '통합 작업실';
/** server-host 확장의 서버 패널 열기 명령(ServerHostCommands.TOGGLE) */
const SERVER_PANEL_TOGGLE = 'studio.serverHost.toggle';

export namespace PluginCommands {
    export const NEW: Command = { id: 'studio.plugin.newTemplate', category: CATEGORY, label: 'Paper 플러그인 템플릿 만들기' };
    export const BUILD_TEST: Command = { id: TaskCommandIds.PLUGIN_BUILD_TEST, category: CATEGORY, label: 'Paper 플러그인 빌드 후 서버에 넣기' };
    export const OPEN_EXTERNAL: Command = { id: 'studio.plugin.openExternal', category: CATEGORY, label: '플러그인 폴더를 외부 IDE(IntelliJ 등)로 열기' };
}

/**
 * Paper 플러그인 개발(사용자 결정 2026-11-27: Paper 만). 모드(F7)와 같은 흐름:
 * 템플릿(plugins-src/<이름>, Gradle·paper-api·plugin.yml) → F9 = ./gradlew build → 그 인스턴스의 Paper 서버 plugins/ 에 넣고
 * 켜져 있는 서버는 다시 시작. Paper 서버는 서버 패널 [서버 열기] → 전용 서버 → Paper 로 만든다(EULA 는 사용자가 직접 동의).
 */
@injectable()
export class PluginTools implements CommandContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(OpenerService) protected readonly openers: OpenerService;
    @inject(CommandService) protected readonly commands: CommandService;

    protected building = false;

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(PluginCommands.NEW, { execute: () => this.guard(() => this.newPlugin()) });
        registry.registerCommand(PluginCommands.BUILD_TEST, { execute: () => this.guard(() => this.buildAndTest()) });
        registry.registerCommand(PluginCommands.OPEN_EXTERNAL, { execute: () => this.guard(() => this.openExternal()) });
    }

    protected guard(fn: () => Promise<unknown>): Promise<void> {
        return reportErrors(this.messages, fn);
    }

    protected instance(): Instance | undefined {
        const inst = this.manager.current;
        if (!inst) {
            this.messages.info('먼저 인스턴스를 만들고 작업실에서 여세요(그 게임 버전의 Paper 로 플러그인을 시험합니다).');
        }
        return inst;
    }

    protected async pickProject(inst: Instance): Promise<string | undefined> {
        const list = await this.manager.call<string[]>('list_plugin_projects', { id: inst.id });
        if (!list.length) {
            const a = await this.messages.info('plugins-src/ 에 플러그인 프로젝트가 없습니다.', '템플릿 만들기');
            if (a) { await this.newPlugin(); }
            return undefined;
        }
        if (list.length === 1) { return list[0]; }
        return (await this.quickInput.showQuickPick(list.map(label => ({ label })), { placeholder: '플러그인 프로젝트' }))?.label;
    }

    protected async newPlugin(): Promise<void> {
        const inst = this.instance();
        if (!inst) { return; }
        const name = await this.quickInput.input({
            title: 'Paper 플러그인 템플릿 (1/2)', prompt: '플러그인 이름 (영문자로 시작, 영문·숫자·_·-)', placeHolder: 'CampsitePlugin',
            validateInput: async v => /^[A-Za-z][A-Za-z0-9_-]{1,63}$/.test(v) ? undefined : '영문자로 시작, 영문·숫자·_·- 2~64자',
        });
        if (!name) { return; }
        const group = await this.quickInput.input({
            title: 'Paper 플러그인 템플릿 (2/2)', prompt: '패키지(그룹) 이름', value: 'com.example',
            validateInput: async v => /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/.test(v) ? undefined : 'com.example 같은 패키지 이름',
        });
        if (!group) { return; }
        const res = await this.manager.call<{ open: string; paperApi: string; java: number }>('plugin_new', { id: inst.id, name, group });
        await open(this.openers, FileUri.create(res.open));
        this.messages.info(`Paper 플러그인 템플릿을 만들었습니다 — paper-api ${res.paperApi}, Java ${res.java}. `
            + 'F9 로 빌드하면 이 인스턴스의 Paper 서버에 넣습니다. JDK 가 필요합니다.');
    }

    /** F9: ./gradlew build → Paper 서버 plugins/ 에 넣기(켜져 있으면 다시 시작) */
    protected async buildAndTest(): Promise<void> {
        const inst = this.instance();
        if (!inst) { return; }
        if (this.building) {
            this.messages.info('이미 빌드 중입니다.');
            return;
        }
        const name = await this.pickProject(inst);
        if (!name) { return; }
        this.building = true;
        const progress = await this.messages.showProgress({ text: `${name} 빌드 중 (./gradlew build)` });
        try {
            const res = await this.manager.call<{ jar: string; servers: string[]; restarted: string[]; message: string }>(
                'plugin_build', { id: inst.id, name });
            progress.cancel();
            this.manager.log(inst.id, `플러그인 빌드: ${res.jar}`, 'info', 'build');
            if (res.servers.length) {
                this.messages.info(res.message);
            } else {
                const make = '서버 패널 열기';
                if (await this.messages.warn(res.message, make) === make) {
                    await this.commands.executeCommand(SERVER_PANEL_TOGGLE);
                }
            }
        } finally {
            progress.cancel();
            this.building = false;
        }
    }

    protected async openExternal(): Promise<void> {
        const inst = this.instance();
        if (!inst) { return; }
        const name = await this.pickProject(inst);
        if (!name) { return; }
        await this.manager.call('open_external', { id: inst.id, rel: `plugins-src/${name}` });
    }
}
