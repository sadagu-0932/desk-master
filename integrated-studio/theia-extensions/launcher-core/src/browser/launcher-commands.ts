import { inject, injectable } from '@theia/core/shared/inversify';
import { Command, CommandContribution, CommandRegistry } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { ConfirmDialog } from '@theia/core/lib/browser/dialogs';
import { Instance, LOADER_LABELS } from '../common/index.js';
import { CreateInstanceDialog, CreateInstanceResult, CreateInstanceServices } from './create-instance-dialog.js';
import { AddModsDialog } from './add-mods-dialog.js';
import { FileDialogService } from '@theia/filesystem/lib/browser/file-dialog/file-dialog-service';
import { WindowService } from '@theia/core/lib/browser/window/window-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { isWindows } from '@theia/core/lib/common/os';
import { InstanceManager } from './instance-manager.js';
import { TaskCommandIds } from '../common/command-ids.js';

interface OfficialInfo { installed: boolean; message: string }
interface OfficialResult { ok: boolean; message: string; method?: string | null; removed?: boolean; warnings?: string[] }

const CATEGORY = '통합 작업실';

export namespace StudioCommands {
    export const CREATE: Command = { id: 'studio.instance.create', category: CATEGORY, label: '새 인스턴스 만들기' };
    export const INSTALL: Command = { id: 'studio.instance.install', category: CATEGORY, label: '인스턴스 설치(게임 파일 받기)' };
    /** 게임 실행은 항상 공식 런처로(로그인·플레이는 공식 런처에서) */
    export const LAUNCH: Command = { id: 'studio.instance.launch', category: CATEGORY, label: '실행 (공식 런처)' };
    export const STOP: Command = { id: 'studio.instance.stop', category: CATEGORY, label: '중지' };
    export const SELECT_TARGET: Command = { id: 'studio.instance.selectTarget', category: CATEGORY, label: '실행 대상 바꾸기' };
    export const OPEN_WORKSPACE: Command = { id: 'studio.instance.openWorkspace', category: CATEGORY, label: '작업실에서 열기' };
    export const RENAME: Command = { id: 'studio.instance.rename', category: CATEGORY, label: '인스턴스 이름 바꾸기' };
    export const DELETE: Command = { id: 'studio.instance.delete', category: CATEGORY, label: '인스턴스 삭제(휴지통)' };
    export const OPEN_FOLDER: Command = { id: 'studio.instance.openFolder', category: CATEGORY, label: '인스턴스 폴더 열기 (파일 탐색기)' };
    export const DUPLICATE: Command = { id: 'studio.instance.duplicate', category: CATEGORY, label: '인스턴스 복제' };
    export const MEMORY: Command = { id: 'studio.instance.memory', category: CATEGORY, label: '인스턴스 메모리·자바 인자 설정' };
    export const MANAGE: Command = { id: 'studio.instance.manage', category: CATEGORY, label: '인스턴스 관리…' };
    export const TOGGLE_CC: Command = { id: 'studio.instance.toggleCommandCrafter', category: CATEGORY, label: 'CommandCrafter 모드 켜기/끄기' };
    export const REFRESH: Command = { id: 'studio.instance.refresh', category: CATEGORY, label: '인스턴스 목록 새로고침' };
    export const ADD_MODS: Command = { id: 'studio.mods.add', category: CATEGORY, label: '모드 추가 (Modrinth·CurseForge)' };
    export const CF_KEY: Command = { id: 'studio.curseforge.key', category: CATEGORY, label: 'CurseForge API 키 지우기' };
    export const OFFICIAL_UNREGISTER: Command = { id: 'studio.official.unregister', category: CATEGORY, label: '공식 런처에서 등록 해제' };
    export const OFFICIAL_OPEN: Command = { id: 'studio.official.open', category: CATEGORY, label: '공식 런처 열기' };
    export const OFFICIAL_INSTALL: Command = { id: 'studio.official.install', category: CATEGORY, label: '공식 런처 설치' };
    export const SYNC_NOW: Command = { id: 'studio.settings.syncNow', category: CATEGORY, label: '설정 지금 동기화 (게임 설정·서버 목록·공식 런처 항목)' };
    export const SIDECAR_STATUS: Command = { id: 'studio.sidecar.status', category: CATEGORY, label: '사이드카 상태 보기' };
}

interface ImportReport {
    instance: Instance;
    downloaded: number;
    extracted: number;
    failed: string[];
    manual: string[];
    /** 연결한 폴더(받은 것 없음) */
    linked?: string;
}

const LAUNCH_KIND_NAME: Record<string, string> = {
    prism: 'Prism Launcher', multimc: 'MultiMC', curseforge: 'CurseForge', modrinth: 'Modrinth App', official: '공식 런처',
};

/** 명령 인자는 인스턴스 id(문자열)이거나 없으면 현재 인스턴스 */
type IdArg = string | undefined;

@injectable()
export class LauncherCommandContribution implements CommandContribution {
    @inject(InstanceManager) protected readonly manager: InstanceManager;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(FileDialogService) protected readonly fileDialog: FileDialogService;
    @inject(WindowService) protected readonly windows: WindowService;

    protected registry: CommandRegistry;

    registerCommands(registry: CommandRegistry): void {
        this.registry = registry;
        registry.registerCommand(StudioCommands.CREATE, { execute: () => this.guard(() => this.create()) });
        registry.registerCommand(StudioCommands.INSTALL, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                await this.manager.install(i.id);
                this.messages.info(`${i.name} 설치가 끝났습니다.`);
            })
        });
        registry.registerCommand(StudioCommands.LAUNCH, {
            execute: (id: IdArg) => this.withInstance(id, i => this.officialPlay(i)),
        });
        registry.registerCommand(StudioCommands.STOP, {
            // 공식 런처가 켠 게임은 이 앱의 프로세스가 아니라서 끌 수 없다
            execute: () => this.messages.info('게임은 공식 런처가 실행했습니다. 게임 창을 닫아 종료해 주세요.'),
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
                const ok = await new ConfirmDialog(i.linkedDir ? {
                    title: '목록에서 지우기',
                    msg: `'${i.name}'을(를) 통합 작업실 목록에서 지울까요? 연결해 둔 원래 폴더(${i.linkedDir})와 그 안의 월드·모드는 그대로 남습니다.`,
                    ok: '목록에서 지우기', cancel: '취소',
                } : {
                    title: '인스턴스 삭제',
                    msg: `'${i.name}' 인스턴스 폴더를 휴지통으로 옮길까요? (월드·데이터팩 포함)`,
                    ok: '휴지통으로', cancel: '취소',
                }).open();
                if (ok) {
                    await this.manager.delete(i.id);
                }
            })
        });
        registry.registerCommand(StudioCommands.OPEN_FOLDER, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.call('open_instance_folder', { id: i.id })),
        });
        registry.registerCommand(StudioCommands.DUPLICATE, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                const name = await this.quickInput.input({ prompt: '복제본 이름(모드·설정·월드를 복사합니다)', value: `${i.name} 복사본` });
                if (!name) {
                    return;
                }
                const copy = await this.manager.call<Instance>('duplicate_instance', { id: i.id, name });
                await this.manager.refresh();
                this.messages.info(`'${copy.name}'을(를) 만들었습니다.`);
            }),
        });
        registry.registerCommand(StudioCommands.MEMORY, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                const cur = /-Xmx(\d+)([MmGg])/.exec(i.jvmArgs ?? '');
                const curGb = cur ? (cur[2].toLowerCase() === 'g' ? Number(cur[1]) : Math.round(Number(cur[1]) / 1024 * 10) / 10) : undefined;
                const gb = await this.quickInput.input({
                    prompt: `최대 메모리(GB). 비우면 공식 런처 기본값. 지금: ${curGb ? curGb + 'GB' : '기본값'}`, value: curGb ? String(curGb) : '',
                    validateInput: async v => (!v.trim() || (/^\d+(\.\d+)?$/.test(v.trim()) && Number(v) >= 0.5 && Number(v) <= 64)) ? undefined : '0.5 ~ 64 사이 숫자(GB)',
                });
                if (gb === undefined) {
                    return;
                }
                await this.manager.call('set_instance_memory', { id: i.id, memory_mb: gb.trim() ? Math.round(Number(gb) * 1024) : null });
                await this.manager.refresh();
                this.messages.info(`${i.name}: 최대 메모리 ${gb.trim() ? gb + 'GB' : '기본값'} (다음 실행부터)`);
            }),
        });
        registry.registerCommand({ id: 'studio.instance.openSourceFolder' }, {
            execute: (id: IdArg) => this.withInstance(id, i => this.manager.call('open_instance_folder', { id: i.id, which: 'source' })),
        });
        registry.registerCommand(StudioCommands.MANAGE, { execute: (id: IdArg) => this.withInstance(id, i => this.manage(i)) });
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
        registry.registerCommand(StudioCommands.OFFICIAL_UNREGISTER, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                const r = await this.manager.call<OfficialResult>('official_unregister_instance', { id: i.id });
                this.messages.info(r.message);
            }),
        });
        registry.registerCommand(StudioCommands.OFFICIAL_OPEN, {
            execute: () => this.guard(async () => this.report(await this.manager.call<OfficialResult>('official_open_launcher'))),
        });
        registry.registerCommand(StudioCommands.OFFICIAL_INSTALL, {
            execute: () => this.guard(() => this.ensureOfficialLauncher(this.manager.current?.id ?? '', true)),
        });
        registry.registerCommand(StudioCommands.SYNC_NOW, {
            execute: () => this.guard(async () => {
                const r = await this.manager.call<{ options: string[]; servers: string[]; profiles: number }>('sync_now');
                const n = r.options.length + r.servers.length + r.profiles;
                this.messages.info(n ? `동기화했습니다 — 게임 설정 ${r.options.length}곳, 서버 목록 ${r.servers.length}곳, 공식 런처 항목 ${r.profiles}개.`
                    : '이미 모두 맞춰져 있습니다.');
            }),
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

    protected report(r: OfficialResult): void {
        if (r.ok) {
            this.messages.info(r.message);
        } else {
            this.messages.warn(r.message);
        }
    }

    /** 공식 런처가 있으면 true. 없으면 설치를 권한다(확인 창은 사이드카가 confirm 알림으로 띄운다). */
    protected async ensureOfficialLauncher(id: string, explicit = false): Promise<boolean> {
        let info = await this.manager.call<OfficialInfo>('official_is_installed');
        if (info.installed) {
            if (explicit) {
                this.messages.info(info.message);
            }
            return true;
        }
        if (!isWindows) {
            this.messages.warn(info.message);
            return false;
        }
        const r = await this.manager.call<OfficialResult>('official_install', { id });
        if (!r.ok || r.method !== 'winget') {
            this.report(r);  // 취소, 실패, 또는 Store 페이지에서 사용자가 직접 설치
            return false;
        }
        info = await this.manager.call<OfficialInfo>('official_is_installed');
        if (!info.installed) {
            this.messages.warn('공식 런처를 설치했지만 아직 찾지 못했습니다. 잠시 뒤 다시 눌러 주세요.');
        }
        return info.installed;
    }

    /**
     * 공식 런처로 플레이: (필요하면 게임 설치) → 공식 런처 확인·설치 → "설치" 항목 등록 → 로그 따라 읽기 → 런처 열기.
     * 로그인과 '플레이' 버튼은 공식 런처에서 사용자가 한다. 이 앱은 계정 정보를 다루지 않는다.
     */
    protected async officialPlay(inst: Instance): Promise<void> {
        if (this.manager.isRunning(inst.id)) {
            this.messages.info(`${inst.name}은(는) 이미 실행 중입니다. 다시 켜려면 게임 창을 닫은 뒤 실행하세요.`);
            return;
        }
        if (inst.linkedDir && inst.launchKind && inst.launchKind !== 'official') {
            await this.linkedPlay(inst);   // 원래 폴더의 실행 파일 → Prism·MultiMC·CurseForge·Modrinth App
            return;
        }
        if (inst.linkedDir) {
            // 다른 런처 폴더를 "연결"한 인스턴스: 그 런처나 게임이 이 폴더를 쓰는 중이면 실행하지 않는다(M10)
            const use = await this.manager.call<{ busy: boolean; reasons: string[]; warnings?: string[] }>('import_in_use', { id: inst.id });
            if (use.busy) {
                this.messages.warn(`${inst.name}: 다른 런처·게임이 이 폴더를 쓰고 있어 실행하지 않았습니다. ${use.reasons.join(' ')}`);
                return;
            }
            (use.warnings ?? []).forEach(w => this.messages.warn(w));
        }
        if (!await this.ensureOfficialLauncher(inst.id)) {
            return;
        }
        if (!inst.installed) {
            this.messages.info(`${inst.name}을(를) 먼저 설치합니다(게임 파일 받기).`);
            inst = await this.manager.install(inst.id);
        }
        const reg = await this.manager.call<OfficialResult & { unchanged?: boolean }>('official_register_instance', { id: inst.id });
        if (!reg.ok) {
            this.messages.info(reg.message);  // 사용자가 '아니오'
            return;
        }
        (reg.warnings ?? []).forEach(w => this.messages.warn(w));
        await this.manager.call('sync_now').catch(() => undefined);  // 실행 직전에 게임 설정·서버 목록을 최신으로
        await this.manager.call('official_tail_log', { id: inst.id });
        await this.manager.setTarget(inst.id);
        await this.registry.executeCommand(TaskCommandIds.GAME_LOG_TOGGLE).catch(() => undefined);
        // 연결한 인스턴스는 원래 폴더의 실행 파일로 공식 런처를 연다
        const open = inst.linkedDir
            ? await this.manager.call<{ ok: boolean }>('launch_linked', { id: inst.id }).then(() => ({ ok: true, message: '' }) as OfficialResult)
                .catch(e => ({ ok: false, message: e instanceof Error ? e.message : String(e) }) as OfficialResult)
            : await this.manager.call<OfficialResult>('official_open_launcher');
        if (open.ok) {
            this.messages.info(`공식 런처에서 '통합 작업실 · ${inst.name}'을(를) 고르고 '플레이'를 눌러 주세요. 게임 로그는 아래 '게임 로그' 탭에 나옵니다.`);
        } else {
            this.messages.warn(open.message);
        }
    }

    /** 연결한 인스턴스: 원래 인스턴스 폴더 안의 실행 파일을 실행 → 원래 런처가 연다. 이 앱에는 아무것도 설치하지 않는다. */
    protected async linkedPlay(inst: Instance): Promise<void> {
        const use = await this.manager.call<{ busy: boolean; reasons: string[] }>('import_in_use', { id: inst.id });
        if (use.busy) {
            this.messages.warn(`${inst.name}: 이미 이 폴더로 게임이 켜져 있습니다. ${use.reasons.join(' ')}`);
            return;
        }
        const r = await this.manager.call<{ launcher: string; kind: string; file: string }>('launch_linked', { id: inst.id });
        await this.manager.call('official_tail_log', { id: inst.id }).catch(() => undefined);   // 게임 로그·실행 상태
        await this.manager.setTarget(inst.id);
        await this.registry.executeCommand(TaskCommandIds.GAME_LOG_TOGGLE).catch(() => undefined);
        const direct = r.kind === 'prism' || r.kind === 'multimc';
        this.messages.info(direct
            ? `${r.launcher}(으)로 '${inst.name}'을(를) 켭니다(원래 폴더의 실행 파일: ${r.file}).`
            : `${r.launcher}을(를) 열었습니다. '${inst.name}'을(를) 골라 [플레이]를 눌러 주세요(원래 폴더의 실행 파일: ${r.file}).`);
    }

    /** 인스턴스 관리 메뉴(카드의 … 버튼·오른쪽 클릭) */
    protected async manage(i: Instance): Promise<void> {
        const running = this.manager.isRunning(i.id);
        const items: Array<{ label: string; description?: string; cmd: string }> = [
            { label: '$(play) 실행', description: running ? '실행 중' : i.launchFile ? `원래 폴더의 실행 파일로(${LAUNCH_KIND_NAME[i.launchKind ?? 'official']})` : '공식 런처로', cmd: StudioCommands.LAUNCH.id },
            { label: '$(folder) 폴더 열기', description: i.linkedDir ? `연결된 원래 폴더: ${i.path}` : i.path, cmd: StudioCommands.OPEN_FOLDER.id },
            ...(i.sourceDir ? [{ label: '$(file-symlink-file) 원래 인스턴스 폴더 열기', description: `실행 파일이 있는 곳: ${i.sourceDir}`, cmd: 'studio.instance.openSourceFolder' }] : []),
            { label: '$(window) 작업실에서 열기', cmd: StudioCommands.OPEN_WORKSPACE.id },
            { label: '$(edit) 이름 바꾸기', cmd: StudioCommands.RENAME.id },
            { label: '$(copy) 복제', description: '모드·설정·월드를 복사한 새 인스턴스', cmd: StudioCommands.DUPLICATE.id },
            { label: '$(dashboard) 메모리 설정', description: i.jvmArgs ?? '공식 런처 기본값', cmd: StudioCommands.MEMORY.id },
            { label: '$(extensions) 모드 추가', cmd: StudioCommands.ADD_MODS.id },
            { label: '$(broadcast) 서버로 열기', cmd: 'studio.serverHost.hostInstance' },
            ...(i.loader === 'fabric' ? [{ label: '$(plug) CommandCrafter 켜기/끄기', description: i.ccEnabled ? '지금 켬' : '지금 끔', cmd: StudioCommands.TOGGLE_CC.id }] : []),
            { label: '$(debug-disconnect) 공식 런처에서 등록 해제', cmd: StudioCommands.OFFICIAL_UNREGISTER.id },
            { label: i.linkedDir ? '$(close) 목록에서 지우기' : '$(trash) 삭제(휴지통)',
                description: i.linkedDir ? '원래 폴더는 그대로' : '월드·데이터팩 포함', cmd: StudioCommands.DELETE.id },
        ];
        const pick = await this.quickInput.showQuickPick(items, { placeholder: `${i.name} — ${i.version} · ${LOADER_LABELS[i.loader] ?? i.loader}${i.linkedDir ? ' · 연결됨' : ''}` });
        if (pick) {
            await this.registry.executeCommand(pick.cmd, i.id);
        }
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
            description: `Java ${i.version} · ${LOADER_LABELS[i.loader] ?? i.loader}${this.manager.isRunning(i.id) ? ' · 실행 중' : ''}`,
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
                    title: '연결할 인스턴스 폴더 (Prism·MultiMC·CurseForge·Modrinth·.minecraft)', canSelectFiles: false, canSelectFolders: true,
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
        const progress = await this.messages.showProgress({ text: result.kind === 'file' ? '가져오는 중…' : '모드팩 가져오는 중…' });
        try {
            const res = result.kind === 'file'
                ? await this.manager.call<ImportReport>('import_file', { path: result.path, version: result.version ?? null, ...look })
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
            const msg = res.linked
                ? `'${res.instance.name}'을(를) 연결했습니다 — 원래 폴더 그대로이고 아무것도 받지 않았습니다.`
                    + (res.instance.launchFile ? ` 원래 폴더에 실행 파일을 만들었습니다(${res.instance.launchFile}). [실행]하면 이 파일이 ${LAUNCH_KIND_NAME[res.instance.launchKind ?? 'official']}을(를) 엽니다.` : '')
                : `'${res.instance.name}' 가져오기 완료 — 파일 ${res.downloaded}개 받음, ${res.extracted}개 풀어 넣음.`
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
