import '../../src/browser/style/resourcepack.css';

import { ContainerModule, inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry, CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { BaseWidget, Message } from '@theia/core/lib/browser/widgets/widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { WidgetFactory, WidgetManager } from '@theia/core/lib/browser/widget-manager';
import { ApplicationShell } from '@theia/core/lib/browser/shell/application-shell';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { FileDialogService } from '@theia/filesystem/lib/browser/file-dialog/file-dialog-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { InstanceManager, reportErrors } from 'integrated-studio-launcher-core/lib/browser';
import { TaskCommandIds } from 'integrated-studio-launcher-core/lib/common';

const CATEGORY = '통합 작업실';
const TEXEL_URL = 'https://texel-neontree.vercel.app/';
const CC_RELOAD_RESOURCES = 'commandcrafter.reloadResources';

export namespace ResourcepackCommands {
    export const OPEN: Command = { id: 'studio.resourcepack.open', category: CATEGORY, label: '리소스팩 편집기(Texel) 열기' };
    export const NEW: Command = { id: 'studio.resourcepack.new', category: CATEGORY, label: '새 리소스팩 만들기' };
    export const IMPORT: Command = { id: 'studio.resourcepack.import', category: CATEGORY, label: '리소스팩 .zip 가져오기' };
    export const APPLY: Command = { id: TaskCommandIds.RESOURCEPACK_APPLY, category: CATEGORY, label: '리소스팩 적용 후 다시 불러오기' };
}

/**
 * Texel 리소스팩 편집기. 소스를 받기 전까지는 웹 페이지를 그대로 띄우고,
 * Texel에서 내보낸 .zip 을 "가져오기"로 인스턴스 resourcepacks/ 에 넣는다.
 */
@injectable()
class TexelWidget extends BaseWidget {
    static readonly ID = 'studio-texel';

    @inject(CommandService) protected readonly commands: CommandService;

    @postConstruct()
    protected init(): void {
        this.id = TexelWidget.ID;
        this.title.label = '리소스팩';
        this.title.caption = '리소스팩 편집기 (Texel)';
        this.title.iconClass = codicon('symbol-color');
        this.title.closable = true;
        this.addClass('studio-texel');

        const bar = document.createElement('div');
        bar.className = 'studio-texel-bar';
        const info = document.createElement('span');
        info.className = 'studio-texel-info';
        info.textContent = 'Texel에서 만든 뒤 .zip으로 내보내고 “가져오기”를 누르세요. Claude 제안은 원본을 덮지 않고 새 파일로 만듭니다.';
        const mk = (label: string, cmd: string, primary = false) => {
            const b = document.createElement('button');
            b.className = 'theia-button' + (primary ? '' : ' secondary');
            b.textContent = label;
            b.addEventListener('click', () => this.commands.executeCommand(cmd));
            return b;
        };
        const unload = document.createElement('button');
        unload.className = 'theia-button secondary';
        unload.textContent = '메모리 비우기';
        unload.title = 'Texel 페이지를 내려놓아 메모리를 비웁니다. 내보내지 않은 작업은 사라집니다.';
        unload.addEventListener('click', () => this.unloadFrame());
        bar.append(info, mk('.zip 가져오기', ResourcepackCommands.IMPORT.id, true), mk('적용 후 다시 불러오기 (F8)', ResourcepackCommands.APPLY.id), unload);

        this.placeholder = document.createElement('div');
        this.placeholder.className = 'studio-texel-placeholder';
        const again = document.createElement('button');
        again.className = 'theia-button';
        again.textContent = 'Texel 다시 열기';
        again.addEventListener('click', () => this.loadFrame());
        const note = document.createElement('p');
        note.textContent = '메모리를 아끼려고 Texel 페이지를 내려놓았습니다.';
        this.placeholder.append(note, again);
        this.node.append(bar, this.placeholder);
    }

    protected frame: HTMLIFrameElement | undefined;
    protected placeholder: HTMLDivElement;

    /** 웹 페이지 하나를 통째로 띄우므로(수백 MB) 탭이 처음 보일 때 불러온다 */
    protected override onAfterShow(msg: Message): void {
        super.onAfterShow(msg);
        if (!this.frame && !this.placeholder.dataset.unloaded) {
            this.loadFrame();
        }
    }

    protected loadFrame(): void {
        if (this.frame) {
            return;
        }
        const frame = document.createElement('iframe');
        frame.className = 'studio-texel-frame';
        frame.src = TEXEL_URL;
        frame.title = 'Texel 리소스팩 편집기';
        frame.setAttribute('allow', 'clipboard-read; clipboard-write');
        this.frame = frame;
        delete this.placeholder.dataset.unloaded;
        this.placeholder.replaceWith(frame);
    }

    protected unloadFrame(): void {
        if (!this.frame) {
            return;
        }
        this.frame.src = 'about:blank';   // 페이지를 먼저 비워 메모리를 돌려받는다
        this.placeholder.dataset.unloaded = '1';
        this.frame.replaceWith(this.placeholder);
        this.frame = undefined;
    }
}

@injectable()
class ResourcepackTools implements CommandContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(FileDialogService) protected readonly fileDialog: FileDialogService;
    @inject(WidgetManager) protected readonly widgets: WidgetManager;
    @inject(ApplicationShell) protected readonly shell: ApplicationShell;
    @inject(CommandRegistry) protected readonly registry: CommandRegistry;

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(ResourcepackCommands.OPEN, { execute: () => this.openEditor() });
        registry.registerCommand(ResourcepackCommands.NEW, { execute: () => this.guard(() => this.newPack()) });
        registry.registerCommand(ResourcepackCommands.IMPORT, { execute: () => this.guard(() => this.importZip()) });
        registry.registerCommand(ResourcepackCommands.APPLY, { execute: () => this.guard(() => this.apply()) });
    }

    protected guard(fn: () => Promise<unknown>): Promise<void> {
        return reportErrors(this.messages, fn);
    }

    protected async openEditor(): Promise<void> {
        const w = await this.widgets.getOrCreateWidget(TexelWidget.ID);
        if (!w.isAttached) {
            await this.shell.addWidget(w, { area: 'main' });
        }
        await this.shell.activateWidget(w.id);
    }

    protected async newPack(): Promise<void> {
        const inst = this.manager.current;
        if (!inst) { this.messages.info('먼저 인스턴스를 만드세요.'); return; }
        const name = await this.quickInput.input({
            prompt: '리소스팩 폴더 이름 (소문자·숫자·_)', placeHolder: 'my_textures',
            validateInput: async v => /^[a-z0-9_][a-z0-9_.-]*$/.test(v) ? undefined : '소문자·숫자·_ . - 만 쓸 수 있습니다',
        });
        if (!name) { return; }
        const res = await this.manager.call<{ path: string }>('resourcepack_new', { id: inst.id, name });
        this.messages.info(`리소스팩을 만들었습니다: ${res.path}`);
    }

    protected async importZip(): Promise<void> {
        const inst = this.manager.current;
        if (!inst) { this.messages.info('먼저 인스턴스를 만드세요.'); return; }
        const uri = await this.fileDialog.showOpenDialog({
            title: 'Texel에서 내보낸 리소스팩 .zip', canSelectFiles: true, canSelectFolders: false,
            filters: { '리소스팩 (.zip)': ['zip'] },
        });
        if (!uri) { return; }
        const res = await this.manager.call<{ name: string }>('resourcepack_import', { id: inst.id, zip_path: FileUri.fsPath(uri) });
        const a = await this.messages.info(`'${res.name}' 리소스팩을 가져왔습니다.`, '지금 적용');
        if (a) {
            await this.apply(res.name);
        }
    }

    protected async apply(packName?: string): Promise<void> {
        const inst = this.manager.current;
        if (!inst) { this.messages.info('먼저 인스턴스를 만드세요.'); return; }
        let pack = packName;
        if (!pack) {
            const packs = await this.manager.call<string[]>('list_resourcepacks', { id: inst.id });
            if (!packs.length) {
                this.messages.info('resourcepacks/ 에 리소스팩이 없습니다. Texel에서 내보낸 .zip을 가져오세요.');
                return;
            }
            pack = packs.length === 1 ? packs[0]
                : (await this.quickInput.showQuickPick(packs.map(label => ({ label })), { placeholder: '적용할 리소스팩' }))?.label;
        }
        if (!pack) { return; }
        await this.manager.call('resourcepack_apply', { id: inst.id, pack });
        const running = this.manager.isRunning(inst.id);
        if (running && inst.ccEnabled && this.registry.getCommand(CC_RELOAD_RESOURCES)) {
            await this.registry.executeCommand(CC_RELOAD_RESOURCES);
            this.manager.log(inst.id, `리소스팩 '${pack}' 적용 → 리소스 다시 불러오기 보냄`, 'info', 'studio');
        } else {
            this.messages.info(running
                ? `'${pack}'을(를) 켰습니다. 게임에서 F3+T로 리소스를 다시 불러오세요.`
                : `'${pack}'을(를) 켰습니다. 다음 실행부터 적용됩니다.`);
        }
    }
}

export default new ContainerModule(bind => {
    bind(TexelWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({ id: TexelWidget.ID, createWidget: () => ctx.container.get(TexelWidget) })).inSingletonScope();
    bind(ResourcepackTools).toSelf().inSingletonScope();
    bind(CommandContribution).toService(ResourcepackTools);
});
