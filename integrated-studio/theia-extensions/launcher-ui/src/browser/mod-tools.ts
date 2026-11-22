import { inject, injectable } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { OpenerService, open } from '@theia/core/lib/browser/opener-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { InstanceManager } from 'integrated-studio-launcher-core/lib/browser';
import { Instance, TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';

const CATEGORY = '통합 작업실';

export namespace ModCommands {
    export const NEW: Command = { id: 'studio.mod.newTemplate', category: CATEGORY, label: 'Fabric 모드 템플릿 만들기' };
    export const BUILD_TEST: Command = { id: TaskCommandIds.MOD_BUILD_TEST, category: CATEGORY, label: '모드 빌드 후 테스트 실행' };
    export const OPEN_EXTERNAL: Command = { id: 'studio.mod.openExternal', category: CATEGORY, label: '모드 폴더를 외부 IDE(IntelliJ 등)로 열기' };
}

@injectable()
export class ModTools implements CommandContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(OpenerService) protected readonly openers: OpenerService;

    protected building = false;

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(ModCommands.NEW, { execute: () => this.guard(() => this.newMod()) });
        registry.registerCommand(ModCommands.BUILD_TEST, { execute: () => this.guard(() => this.buildAndTest()) });
        registry.registerCommand(ModCommands.OPEN_EXTERNAL, { execute: () => this.guard(() => this.openExternal()) });
    }

    protected async guard(fn: () => Promise<unknown>): Promise<void> {
        try {
            await fn();
        } catch (e) {
            this.messages.error(e instanceof Error ? e.message : String(e));
        }
    }

    protected fabricInstance(): Instance | undefined {
        const inst = this.manager.current;
        if (!inst) {
            this.messages.info('먼저 Fabric 인스턴스를 만들고 작업실에서 여세요(모드 테스트 인스턴스로 씀).');
            return undefined;
        }
        if (inst.loader !== 'fabric') {
            this.messages.info(`'${inst.name}'은(는) 바닐라 인스턴스입니다. 모드는 Fabric 인스턴스에서 만드세요.`);
            return undefined;
        }
        return inst;
    }

    protected async pickProject(inst: Instance): Promise<string | undefined> {
        const list = await this.manager.call<string[]>('list_mod_projects', { id: inst.id });
        if (!list.length) {
            const a = await this.messages.info('mods-src/ 에 모드 프로젝트가 없습니다.', '템플릿 만들기');
            if (a) { await this.newMod(); }
            return undefined;
        }
        if (list.length === 1) { return list[0]; }
        return (await this.quickInput.showQuickPick(list.map(label => ({ label })), { placeholder: '모드 프로젝트' }))?.label;
    }

    protected async newMod(): Promise<void> {
        const inst = this.fabricInstance();
        if (!inst) { return; }
        const modid = await this.quickInput.input({
            title: 'Fabric 모드 템플릿 (1/2)', prompt: '모드 ID (소문자로 시작, 소문자·숫자·_)', placeHolder: 'campsite_mod',
            validateInput: async v => /^[a-z][a-z0-9_]{1,63}$/.test(v) ? undefined : '소문자로 시작, 소문자·숫자·_ 2~64자',
        });
        if (!modid) { return; }
        const name = await this.quickInput.input({ title: 'Fabric 모드 템플릿 (2/2)', prompt: '모드 표시 이름', value: modid });
        if (name === undefined) { return; }
        const res = await this.manager.call<{ open: string; versions: Record<string, string | boolean> }>(
            'mod_new', { id: inst.id, modid, name: name || modid });
        await open(this.openers, FileUri.create(res.open));
        const v = res.versions;
        this.messages.info(`모드 템플릿을 만들었습니다 — Loader ${v.loader}, Fabric API ${v.fabric_api}, Loom ${v.loom}, Gradle ${v.gradle}`
            + `${v.checked ? '' : ' (오프라인이라 기본값)'}. F7로 빌드 후 테스트합니다. JDK 25가 필요합니다.`);
    }

    /** F7: ./gradlew build → jar 를 테스트 인스턴스 mods/ 에 복사 → 재시작(꺼져 있으면 실행) */
    protected async buildAndTest(): Promise<void> {
        const inst = this.fabricInstance();
        if (!inst) { return; }
        if (this.building) {
            this.messages.info('이미 빌드 중입니다.');
            return;
        }
        const modid = await this.pickProject(inst);
        if (!modid) { return; }
        this.building = true;
        const progress = await this.messages.showProgress({ text: `${modid} 빌드 중 (./gradlew build)` });
        try {
            const res = await this.manager.call<{ jar: string }>('mod_build', { id: inst.id, modid });
            progress.cancel();
            this.manager.log(inst.id, `테스트 인스턴스에 넣음: ${res.jar}`, 'info', 'build');
            await this.manager.restart(inst.id);
        } finally {
            progress.cancel();
            this.building = false;
        }
    }

    protected async openExternal(): Promise<void> {
        const inst = this.fabricInstance();
        if (!inst) { return; }
        const modid = await this.pickProject(inst);
        if (!modid) { return; }
        await this.manager.call('open_external', { id: inst.id, rel: `mods-src/${modid}` });
    }
}
