import { inject, injectable } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { ConfirmDialog } from '@theia/core/lib/browser/dialogs';
import { Instance } from '../common/index.js';
import { CreateInstanceDialog, CreateInstanceResult, CreateInstanceServices } from './create-instance-dialog.js';
import { AddModsDialog } from './add-mods-dialog.js';
import { FileDialogService } from '@theia/filesystem/lib/browser/file-dialog/file-dialog-service';
import { WindowService } from '@theia/core/lib/browser/window/window-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { InstanceManager } from './instance-manager.js';

const CATEGORY = '통합 작업실';

export namespace StudioCommands {
    export const CREATE: Command = { id: 'studio.instance.create', category: CATEGORY, label: '새 인스턴스 만들기' };
    export const INSTALL: Command = { id: 'studio.instance.install', category: CATEGORY, label: '인스턴스 설치(게임 파일 받기)' };
    export const LAUNCH: Command = { id: 'studio.instance.launch', category: CATEGORY, label: '실행' };
    export const STOP: Command = { id: 'studio.instance.stop', category: CATEGORY, label: '중지' };
    export const RESTART: Command = { id: 'studio.instance.restart', category: CATEGORY, label: '재시작' };
    export const SELECT_TARGET: Command = { id: 'studio.instance.selectTarget', category: CATEGORY, label: '실행 대상 바꾸기' };
    export const OPEN_WORKSPACE: Command = { id: 'studio.instance.openWorkspace', category: CATEGORY, label: '작업실에서 열기' };
    export const RENAME: Command = { id: 'studio.instance.rename', category: CATEGORY, label: '인스턴스 이름 바꾸기' };
    export const DELETE: Command = { id: 'studio.instance.delete', category: CATEGORY, label: '인스턴스 삭제(휴지통)' };
    export const TOGGLE_CC: Command = { id: 'studio.instance.toggleCommandCrafter', category: CATEGORY, label: 'CommandCrafter 모드 켜기/끄기' };
    export const REFRESH: Command = { id: 'studio.instance.refresh', category: CATEGORY, label: '인스턴스 목록 새로고침' };
    export const ADD_MODS: Command = { id: 'studio.mods.add', category: CATEGORY, label: '모드 추가 (Modrinth·CurseForge)' };
    export const CF_KEY: Command = { id: 'studio.curseforge.key', category: CATEGORY, label: 'CurseForge API 키 지우기' };
    export const SIDECAR_STATUS: Command = { id: 'studio.sidecar.status', category: CATEGORY, label: '사이드카 상태 보기' };
}

interface ImportReport {
    instance: Instance;
    downloaded: number;
    extracted: number;
    failed: string[];
    manual: string[];
}

/** 명령 인자는 인스턴스 id(문자열)이거나 없으면 현재 인스턴스 */
type IdArg = string | undefined;

@injectable()
export class LauncherCommandContribution implements CommandContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(FileDialogService) protected readonly fileDialog: FileDialogService;
    @inject(WindowService) protected readonly windows: WindowService;

    registerCommands(registry: CommandRegistry): void {
        registry.registerCommand(StudioCommands.CREATE, { execute: () => this.guard(() => this.create()) });
        registry.registerCommand(StudioCommands.INSTALL, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                await this.manager.install(i.id);
                this.messages.info(`${i.name} 설치가 끝났습니다.`);
            })
        });
        registry.registerCommand(StudioCommands.LAUNCH, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.launch(i.id)),
            isEnabled: (id: IdArg) => !this.manager.isRunning(this.resolve(id)?.id),
        });
        registry.registerCommand(StudioCommands.STOP, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.stop(i.id)),
            isEnabled: (id: IdArg) => this.manager.isRunning(this.resolve(id)?.id),
        });
        registry.registerCommand(StudioCommands.RESTART, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.restart(i.id)),
        });
        registry.registerCommand(StudioCommands.SELECT_TARGET, { execute: () => this.guard(() => this.selectTarget()) });
        registry.registerCommand(StudioCommands.OPEN_WORKSPACE, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.openInWorkspace(i.id))
        });
        registry.registerCommand(StudioCommands.RENAME, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                const name = await this.quickInput.input({ prompt: '새 이름', value: i.name });
                if (name) {
                    await this.manager.rename(i.id, name);
                }
            })
        });
        registry.registerCommand(StudioCommands.DELETE, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                if (this.manager.isRunning(i.id)) {
                    this.messages.warn('실행 중인 인스턴스는 삭제할 수 없습니다. 먼저 중지하세요.');
                    return;
                }
                const ok = await new ConfirmDialog({
                    title: '인스턴스 삭제',
                    msg: `'${i.name}' 인스턴스 폴더를 휴지통으로 옮길까요? (월드·데이터팩 포함)`,
                    ok: '휴지통으로', cancel: '취소',
                }).open();
                if (ok) {
                    await this.manager.delete(i.id);
                }
            })
        });
        registry.registerCommand(StudioCommands.TOGGLE_CC, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                if (i.loader !== 'fabric') {
                    this.messages.info('CommandCrafter 모드는 Fabric 인스턴스에서만 쓸 수 있습니다.');
                    return;
                }
                await this.manager.setCcEnabled(i.id, !i.ccEnabled);
                this.messages.info(`CommandCrafter 모드: ${!i.ccEnabled ? '켬' : '끔'} (다음 실행부터 적용)`);
            })
        });
        registry.registerCommand(StudioCommands.ADD_MODS, { execute: (id: IdArg) => this.guard(() => this.addMods(id)) });
        registry.registerCommand(StudioCommands.CF_KEY, {
            execute: () => this.guard(async () => {
                await this.manager.call('cf_set_key', { key: '' });
                this.messages.info('CurseForge API 키를 지웠습니다.');
            })
        });
        registry.registerCommand(StudioCommands.REFRESH, { execute: () => this.manager.refresh() });
        registry.registerCommand(StudioCommands.SIDECAR_STATUS, {
            execute: async () => {
                const s = await this.manager.call<{ version: string; data: string }>('ping').catch(e => e as Error);
                if (s instanceof Error) {
                    this.messages.error(`사이드카 오류: ${s.message}`);
                } else {
                    this.messages.info(`사이드카 ${s.version} 정상 · 데이터 폴더: ${s.data}`);
                }
            }
        });
    }

    resolve(id: IdArg): Instance | undefined {
        return typeof id === 'string' ? this.manager.find(id) : this.manager.current;
    }

    protected async withInstance(id: IdArg, fn: (inst: Instance) => Promise<unknown>): Promise<void> {
        await this.manager.ready;
        let inst = this.resolve(id);
        if (!inst) {
            if (this.manager.instances.length === 0) {
                this.messages.info('인스턴스가 없습니다. 먼저 새 인스턴스를 만드세요.', '새 인스턴스 만들기').then(a => {
                    if (a) { this.guard(() => this.create()); }
                });
                return;
            }
            inst = await this.pickInstance();
            if (!inst) {
                return;
            }
        }
        const target = inst;
        await this.guard(() => fn(target));
    }

    protected async guard(fn: () => Promise<unknown>): Promise<void> {
        try {
            await fn();
        } catch (e) {
            this.messages.error(e instanceof Error ? e.message : String(e));
        }
    }

    async pickInstance(placeholder = '인스턴스 선택'): Promise<Instance | undefined> {
        await this.manager.ready;
        const items = this.manager.instances.map(i => ({
            label: i.name,
            description: `Java ${i.version} · ${i.loader === 'fabric' ? 'Fabric' : '바닐라'}${this.manager.isRunning(i.id) ? ' · 실행 중' : ''}`,
            id: i.id,
        }));
        const picked = await this.quickInput.showQuickPick(items, { placeholder });
        return picked ? this.manager.find(picked.id) : undefined;
    }

    protected async selectTarget(): Promise<void> {
        const inst = await this.pickInstance('실행 대상 선택');
        if (inst) {
            await this.manager.setTarget(inst.id);
        }
    }

    protected get services(): CreateInstanceServices {
        return {
            pickFile: async () => {
                const uri = await this.fileDialog.showOpenDialog({
                    title: '가져올 모드팩 파일', canSelectFiles: true, canSelectFolders: false,
                    filters: { '모드팩 (.mrpack, .zip)': ['mrpack', 'zip'] },
                });
                return uri ? FileUri.fsPath(uri) : undefined;
            },
            pickFolder: async () => {
                const uri = await this.fileDialog.showOpenDialog({
                    title: 'Prism Launcher·MultiMC 인스턴스 폴더', canSelectFiles: false, canSelectFolders: true,
                });
                return uri ? FileUri.fsPath(uri) : undefined;
            },
            openUrl: url => this.windows.openNewWindow(url, { external: true }),
        };
    }

    /** 새 인스턴스 창(Prism Launcher의 "인스턴스 추가" 배치 참고) */
    protected async create(): Promise<void> {
        await this.manager.ready;
        const groups = [...new Set(this.manager.instances.map(i => i.group).filter((g): g is string => !!g))];
        const result = await new CreateInstanceDialog(this.manager, groups, this.services).open();
        if (!result) {
            return;
        }
        if (result.kind === 'custom') {
            const inst = await this.manager.create(result.options);
            if (result.installNow) {
                // 설치는 뒤에서 진행(진행률은 알림에 표시). 창을 막지 않는다
                this.manager.install(inst.id)
                    .then(() => this.messages.info(`'${inst.name}' 설치가 끝났습니다. F5로 실행하세요.`, '작업실에서 열기')
                        .then(a => a && this.manager.openInWorkspace(inst.id)))
                    .catch(e => this.messages.error(`'${inst.name}' 설치 실패: ${e instanceof Error ? e.message : e}`));
            } else {
                const action = await this.messages.info(`'${inst.name}' 인스턴스를 만들었습니다. 처음 실행할 때 게임 파일을 받습니다.`, '작업실에서 열기');
                if (action) {
                    await this.manager.openInWorkspace(inst.id);
                }
            }
            return;
        }
        this.runImport(result);
    }

    /** 가져오기는 뒤에서 진행하고 결과(받은 수, 실패, 직접 받아야 할 모드)를 알려 준다 */
    protected async runImport(result: Exclude<CreateInstanceResult, { kind: 'custom' }>): Promise<void> {
        const look = { name: result.look.name ?? null, group: result.look.group ?? null, icon: result.look.icon ?? null };
        const progress = await this.messages.showProgress({ text: '모드팩 가져오는 중…' });
        try {
            const res = result.kind === 'file'
                ? await this.manager.call<ImportReport>('import_file', { path: result.path, ...look })
                : result.kind === 'modrinth'
                    ? await this.manager.call<ImportReport>('modrinth_install_modpack', { version_id: result.versionId, ...look })
                    : await this.manager.call<ImportReport>('cf_install_modpack', { mod_id: result.modId, file_id: result.fileId, ...look });
            progress.cancel();
            await this.manager.refresh();
            await this.manager.setTarget(res.instance.id);
            const id = res.instance.id;
            for (const f of res.failed) { this.manager.log(id, `받지 못함: ${f}`, 'warn', 'studio'); }
            for (const m of res.manual) { this.manager.log(id, `직접 받아 mods/에 넣어야 함: ${m}`, 'warn', 'studio'); }
            const extra = [
                res.failed.length ? `받지 못한 파일 ${res.failed.length}개` : '',
                res.manual.length ? `직접 받아야 할 모드 ${res.manual.length}개(제작자가 외부 다운로드를 막음)` : '',
            ].filter(Boolean).join(', ');
            const msg = `'${res.instance.name}' 가져오기 완료 — 파일 ${res.downloaded}개 받음, ${res.extracted}개 풀어 넣음.`
                + (extra ? ` ${extra}: 목록은 게임 로그 탭에 있습니다.` : ' F5로 실행하면 게임 파일을 받습니다.');
            const open = '작업실에서 열기';
            const a = extra ? await this.messages.warn(msg, open) : await this.messages.info(msg, open);
            if (a === open) {
                await this.manager.openInWorkspace(id);
            }
        } catch (e) {
            progress.cancel();
            this.messages.error(`가져오기 실패: ${e instanceof Error ? e.message : e}`);
        }
    }

    protected async addMods(id: string | undefined): Promise<void> {
        await this.manager.ready;
        const inst = typeof id === 'string' ? this.manager.find(id) : this.manager.current;
        if (!inst) {
            this.messages.info('먼저 인스턴스를 만드세요.');
            return;
        }
        if (inst.loader !== 'fabric') {
            this.messages.info(`'${inst.name}'은(는) 바닐라 인스턴스라 모드를 넣을 수 없습니다. Fabric 인스턴스를 만드세요.`);
            return;
        }
        await new AddModsDialog(this.manager, inst, url => this.windows.openNewWindow(url, { external: true })).open();
    }
}
