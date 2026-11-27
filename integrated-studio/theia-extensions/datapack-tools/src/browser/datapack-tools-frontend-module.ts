import * as monaco from '@theia/monaco-editor-core';
import { ContainerModule, inject, injectable } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { OpenerService, open } from '@theia/core/lib/browser/opener-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { InstanceManager, reportErrors } from 'integrated-studio-launcher-core/lib/browser';
import { Instance, TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';
import { CommandsData, MCFUNCTION_ID, createFallbackCompletion, registerMcfunctionLanguage } from './mcfunction-language.js';

const CATEGORY = '통합 작업실';

export namespace DatapackCommands {
    export const NEW: Command = { id: 'studio.datapack.new', category: CATEGORY, label: '새 데이터팩 만들기' };
    export const SYNC: Command = { id: TaskCommandIds.DATAPACK_SYNC, category: CATEGORY, label: '데이터팩을 월드로 동기화' };
    export const SYNC_ALL: Command = { id: 'studio.datapack.syncAll', category: CATEGORY, label: '모든 데이터팩을 최근 월드로 동기화' };
    export const ZIP: Command = { id: TaskCommandIds.DATAPACK_ZIP, category: CATEGORY, label: '데이터팩 .zip 내보내기' };
    export const PREPARE_COMPLETION: Command = { id: 'studio.datapack.prepareCompletion', category: CATEGORY, label: '게임 없이 쓸 자동완성 준비(데이터 생성기)' };
}

@injectable()
class DatapackTools implements CommandContribution, FrontendApplicationContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(OpenerService) protected readonly openers: OpenerService;

    protected commandsData = new Map<string, CommandsData>();

    onStart(): void {
        registerMcfunctionLanguage();
        monaco.languages.registerCompletionItemProvider(MCFUNCTION_ID, createFallbackCompletion(
            () => this.commandsData.get(this.manager.current?.version ?? ''),
            // 게임이 켜져 있고 CommandCrafter가 붙으면 그쪽 완성을 쓰므로 예비 완성은 끈다
            () => {
                const inst = this.manager.current;
                return !(inst && inst.ccEnabled && this.manager.isRunning(inst.id));
            },
        ));
        this.manager.ready.then(() => this.loadCached());
        this.manager.onDidChange(() => this.loadCached());
    }

    /** 이미 만들어 둔 commands.json 이 있으면 조용히 불러온다 */
    protected async loadCached(): Promise<void> {
        const version = this.manager.current?.version;
        if (!version || this.commandsData.has(version)) {
            return;
        }
        try {
            const status = await this.manager.call<{ data: string }>('ping');
            const dir = `${status.data}/reports/${version}`;
            const data = await this.manager.call<CommandsData>('read_commands', { reports_dir: dir });
            this.commandsData.set(version, data);
        } catch {
            // 아직 없음 — "자동완성 준비" 명령으로 만든다
        }
    }

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(DatapackCommands.NEW, { execute: () => this.guard(() => this.newPack()) });
        registry.registerCommand(DatapackCommands.SYNC, { execute: () => this.guard(() => this.sync()) });
        registry.registerCommand(DatapackCommands.SYNC_ALL, { execute: () => this.syncAll() });
        registry.registerCommand(DatapackCommands.ZIP, { execute: () => this.guard(() => this.zip()) });
        registry.registerCommand(DatapackCommands.PREPARE_COMPLETION, { execute: () => this.guard(() => this.prepare()) });
    }

    protected guard(fn: () => Promise<unknown>): Promise<void> {
        return reportErrors(this.messages, fn);
    }

    protected async instance(): Promise<Instance | undefined> {
        await this.manager.ready;
        const inst = this.manager.current;
        if (!inst) {
            this.messages.info('먼저 인스턴스를 만들고 작업실에서 여세요.');
        }
        return inst;
    }

    protected async pick(items: string[], placeholder: string): Promise<string | undefined> {
        if (items.length === 1) {
            return items[0];
        }
        const picked = await this.quickInput.showQuickPick(items.map(label => ({ label })), { placeholder });
        return picked?.label;
    }

    protected async newPack(): Promise<void> {
        const inst = await this.instance();
        if (!inst) { return; }
        const name = await this.quickInput.input({
            title: '새 데이터팩 (1/2)', prompt: '데이터팩 폴더 이름 (소문자·숫자·_)', placeHolder: 'campsite',
            validateInput: async v => /^[a-z0-9_][a-z0-9_.-]*$/.test(v) ? undefined : '소문자·숫자·_ . - 만 쓸 수 있습니다',
        });
        if (!name) { return; }
        const namespace = await this.quickInput.input({
            title: '새 데이터팩 (2/2)', prompt: '네임스페이스 (함수 이름 앞부분, 예: campsite:tick)', value: name.replace(/[^a-z0-9_]/g, '_'),
            validateInput: async v => /^[a-z0-9_.-]+$/.test(v) && v !== 'minecraft' ? undefined : '소문자·숫자·_ . - 만, minecraft 는 불가',
        });
        if (!namespace) { return; }
        const res = await this.manager.call<{ path: string; open: string }>('datapack_new', { id: inst.id, name, namespace });
        await open(this.openers, FileUri.create(res.open));
        this.messages.info(`데이터팩 '${name}'을(를) 만들었습니다. 월드에 넣으려면 "데이터팩을 월드로 동기화"를 쓰세요(/reload 버튼은 자동으로 동기화).`);
    }

    protected async sync(): Promise<void> {
        const inst = await this.instance();
        if (!inst) { return; }
        const packs = await this.manager.call<string[]>('list_datapacks', { id: inst.id });
        const worlds = await this.manager.call<string[]>('list_worlds', { id: inst.id });
        if (!packs.length) { this.messages.info('datapacks/ 에 데이터팩이 없습니다. 먼저 새 데이터팩을 만드세요.'); return; }
        if (!worlds.length) { this.messages.info('월드가 없습니다. 게임을 실행해 월드를 한 번 만드세요.'); return; }
        const pack = await this.pick(packs, '동기화할 데이터팩');
        if (!pack) { return; }
        const world = await this.pick(worlds, '대상 월드 (위쪽이 최근)');
        if (!world) { return; }
        const res = await this.manager.call<{ files: number }>('datapack_sync', { id: inst.id, pack, world });
        this.messages.info(`'${pack}' → '${world}' 동기화 완료(파일 ${res.files}개). 게임에서는 /reload 하세요.`);
    }

    /** /reload 전에 부르는 자동 동기화: 모든 팩 → 가장 최근에 연 월드. 동기화한 팩 수를 돌려준다. */
    async syncAll(): Promise<number> {
        const inst = this.manager.current;
        if (!inst) { return 0; }
        try {
            const packs = await this.manager.call<string[]>('list_datapacks', { id: inst.id });
            const worlds = await this.manager.call<string[]>('list_worlds', { id: inst.id });
            if (!packs.length || !worlds.length) { return 0; }
            for (const pack of packs) {
                await this.manager.call('datapack_sync', { id: inst.id, pack, world: worlds[0] });
            }
            this.manager.log(inst.id, `데이터팩 ${packs.length}개를 '${worlds[0]}' 월드로 동기화`, 'info', 'studio');
            return packs.length;
        } catch (e) {
            this.manager.log(inst.id, `데이터팩 동기화 실패: ${e instanceof Error ? e.message : e}`, 'warn', 'studio');
            return 0;
        }
    }

    protected async zip(): Promise<void> {
        const inst = await this.instance();
        if (!inst) { return; }
        const packs = await this.manager.call<string[]>('list_datapacks', { id: inst.id });
        if (!packs.length) { this.messages.info('datapacks/ 에 데이터팩이 없습니다.'); return; }
        const pack = await this.pick(packs, '내보낼 데이터팩');
        if (!pack) { return; }
        const res = await this.manager.call<{ path: string }>('datapack_zip', { id: inst.id, pack });
        this.messages.info(`내보냈습니다: ${res.path}`);
    }

    protected async prepare(): Promise<void> {
        const inst = await this.instance();
        if (!inst) { return; }
        const res = await this.manager.call<{ path: string }>('generate_reports', { version: inst.version });
        const data = await this.manager.call<CommandsData>('read_commands', { reports_dir: res.path });
        this.commandsData.set(inst.version, data);
        this.messages.info(`Java ${inst.version} 명령어 목록을 준비했습니다. 게임이 꺼져 있어도 .mcfunction 자동완성이 됩니다.`);
    }
}

export default new ContainerModule(bind => {
    bind(DatapackTools).toSelf().inSingletonScope();
    bind(CommandContribution).toService(DatapackTools);
    bind(FrontendApplicationContribution).toService(DatapackTools);
});
