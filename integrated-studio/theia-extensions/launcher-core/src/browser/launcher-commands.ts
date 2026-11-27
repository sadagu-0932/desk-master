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
import { InstanceManager } from './instance-manager.js';
import { TaskCommandIds } from '../common/command-ids.js';
import { errorMessage, reportErrors } from './report-errors.js';

/** 사이드카 local.py NEED_ROOT_TAG 와 같아야 한다 */
const NEED_ROOT_TAG = '[launcher-root]';

interface PrismInfo { found: boolean; exe?: string | null; root?: string | null; instanceDir?: string | null }
interface PrismResult { ok: boolean; message: string; cancelled?: boolean; already?: boolean; url?: string }
/** 사이드카 prism.py MISSING_TAG / importers.local NEEDS_PRISM_TAG 와 같아야 한다 */
const PRISM_MISSING_TAG = '[prism-missing]';
const NEEDS_PRISM_TAG = '[needs-prism]';
/** 사이드카 오류 문구 끝의 "(파일:줄, 요청)"·표식을 떼고 사용자에게 보인다 */
function plain(msg: string): string {
    return msg.replace(PRISM_MISSING_TAG, '').replace(NEEDS_PRISM_TAG, '').replace(/\s*\([^()]*\.py:\d+[^()]*\)\s*$/, '').trim();
}

const CATEGORY = '통합 작업실';

export namespace StudioCommands {
    export const CREATE: Command = { id: 'studio.instance.create', category: CATEGORY, label: '새 인스턴스 만들기' };
    /** 게임 실행은 Prism Launcher 로(로그인·자바·게임 파일 받기는 Prism, 사용자 결정 2026-11-27) */
    export const LAUNCH: Command = { id: 'studio.instance.launch', category: CATEGORY, label: '실행 (Prism)' };
    export const STOP: Command = { id: 'studio.instance.stop', category: CATEGORY, label: '중지' };
    export const SELECT_TARGET: Command = { id: 'studio.instance.selectTarget', category: CATEGORY, label: '실행 대상 바꾸기' };
    export const OPEN_WORKSPACE: Command = { id: 'studio.instance.openWorkspace', category: CATEGORY, label: '작업실에서 열기' };
    export const RENAME: Command = { id: 'studio.instance.rename', category: CATEGORY, label: '인스턴스 이름 바꾸기' };
    export const DELETE: Command = { id: 'studio.instance.delete', category: CATEGORY, label: '인스턴스 삭제(휴지통)' };
    export const OPEN_FOLDER: Command = { id: 'studio.instance.openFolder', category: CATEGORY, label: '인스턴스 폴더 열기 (파일 탐색기)' };
    export const DUPLICATE: Command = { id: 'studio.instance.duplicate', category: CATEGORY, label: '인스턴스 복제' };
    export const MEMORY: Command = { id: 'studio.instance.memory', category: CATEGORY, label: '인스턴스 메모리·자바 인자 설정' };
    export const MEMORY_USAGE: Command = { id: 'studio.memoryUsage', category: CATEGORY, label: '메모리 사용량 보기' };
    export const MANAGE: Command = { id: 'studio.instance.manage', category: CATEGORY, label: '인스턴스 관리…' };
    export const TOGGLE_CC: Command = { id: 'studio.instance.toggleCommandCrafter', category: CATEGORY, label: 'CommandCrafter 모드 켜기/끄기' };
    export const REFRESH: Command = { id: 'studio.instance.refresh', category: CATEGORY, label: '인스턴스 목록 새로고침' };
    export const ADD_MODS: Command = { id: 'studio.mods.add', category: CATEGORY, label: '모드 추가 (Modrinth·CurseForge)' };
    export const CF_KEY: Command = { id: 'studio.curseforge.key', category: CATEGORY, label: 'CurseForge API 키 지우기' };
    export const PRISM_OPEN: Command = { id: 'studio.prism.open', category: CATEGORY, label: 'Prism Launcher 열기' };
    export const PRISM_INSTALL: Command = { id: 'studio.prism.install', category: CATEGORY, label: 'Prism Launcher 설치' };
    export const PRISM_MIGRATE: Command = { id: 'studio.prism.migrate', category: CATEGORY, label: '예전 인스턴스를 Prism 으로 옮기기' };
    export const SYNC_NOW: Command = { id: 'studio.settings.syncNow', category: CATEGORY, label: '설정 지금 동기화 (게임 설정·서버 목록)' };
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
    prism: 'Prism Launcher', multimc: 'MultiMC', curseforge: 'CurseForge', modrinth: 'Modrinth App', official: '(옮기기 필요)',
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
        registry.registerCommand(StudioCommands.LAUNCH, {
            execute: (id: IdArg) => this.withInstance(id, i => this.play(i)),
        });
        registry.registerCommand(StudioCommands.STOP, {
            // Prism 이 켠 게임은 이 앱의 프로세스가 아니라서 끌 수 없다
            execute: () => this.messages.info('게임은 Prism Launcher 가 실행했습니다. 게임 창을 닫아 종료해 주세요.'),
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
                const copy = await this.manager.call<Instance & { notice?: string }>('duplicate_instance', { id: i.id, name });
                await this.manager.refresh();
                this.manager.ensureVisible(copy.id, copy.name);
                this.messages.info(`'${copy.name}'을(를) 만들었습니다.${copy.notice ? ' ' + copy.notice : ''}`);
            }),
        });
        registry.registerCommand(StudioCommands.MEMORY, {
            execute: (id: IdArg) => this.withInstance(id, async i => {
                const cur = /-Xmx(\d+)([MmGg])/.exec(i.jvmArgs ?? '');
                const curGb = cur ? (cur[2].toLowerCase() === 'g' ? Number(cur[1]) : Math.round(Number(cur[1]) / 1024 * 10) / 10) : undefined;
                // 모드 수·PC 메모리로 고른 추천값(너무 많이 주면 오히려 끊김이 길어진다)
                const adv = await this.manager.call<{ recommendedMb: number; reason: string; totalMb?: number }>('memory_advice', { id: i.id })
                    .catch(() => undefined);
                const recGb = adv ? Math.round(adv.recommendedMb / 102.4) / 10 : undefined;
                const recText = adv ? ` · 추천 ${recGb}GB (${adv.reason})` : '';
                const gb = await this.quickInput.input({
                    prompt: `최대 메모리(GB). 비우면 Prism 기본값. 지금: ${curGb ? curGb + 'GB' : '기본값'}${recText}`,
                    value: curGb ? String(curGb) : (recGb ? String(recGb) : ''),
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
        registry.registerCommand(StudioCommands.MEMORY_USAGE, { execute: () => this.guard(() => this.showMemoryUsage()) });
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
        registry.registerCommand(StudioCommands.PRISM_OPEN, {
            execute: () => this.guard(() => this.withPrism(() => this.manager.call('prism_open'))),
        });
        registry.registerCommand(StudioCommands.PRISM_INSTALL, { execute: () => this.guard(() => this.installPrism(true)) });
        registry.registerCommand(StudioCommands.PRISM_MIGRATE, { execute: () => this.guard(() => this.migrateToPrism(true)) });
        registry.registerCommand(StudioCommands.SYNC_NOW, {
            execute: () => this.guard(async () => {
                const r = await this.manager.call<{ options: string[]; servers: string[] }>('sync_now');
                const n = r.options.length + r.servers.length;
                this.messages.info(n ? `동기화했습니다 — 게임 설정 ${r.options.length}곳, 서버 목록 ${r.servers.length}곳.`
                    : '이미 모두 맞춰져 있습니다.');
            }),
        });
        registry.registerCommand(StudioCommands.REFRESH, {
            execute: async () => { await this.manager.call('prism_sync').catch(() => undefined); await this.manager.refreshPrism(); await this.manager.refresh(); },
        });
        this.manager.ready.then(() => this.startupCheck()).catch(() => undefined);
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

    /** 켤 때: Prism 이 있고 옮기지 않은 예전 인스턴스가 있으면 옮기기를 권한다(‘나중에’면 하루에 한 번만) */
    protected async startupCheck(): Promise<void> {
        if (!this.manager.prism?.found) {
            return;
        }
        const key = 'studio.prismMigrate.askedAt';
        let last = 0;
        try { last = Number(window.localStorage.getItem(key) ?? 0); } catch { /* 저장소를 못 쓰면 매번 묻는다 */ }
        if (Date.now() - last < 24 * 3600 * 1000) {
            return;
        }
        try { window.localStorage.setItem(key, String(Date.now())); } catch { /* 무시 */ }
        await this.migrateToPrism(false);
    }

    /** Prism 설치(확인 창은 사이드카가 confirm 알림으로 띄운다). 설치되면 true */
    protected async installPrism(explicit = false): Promise<boolean> {
        const before = await this.manager.call<PrismInfo>('prism_status');
        if (before.found) {
            if (explicit) {
                this.messages.info(`Prism Launcher 가 이미 설치돼 있습니다(${before.exe}).`);
            }
            return true;
        }
        const r = await this.manager.call<PrismResult>('prism_install', { id: this.manager.current?.id ?? '' });
        if (r.ok) {
            this.messages.info(r.message);
            await this.manager.refreshPrism();
            return true;
        }
        if (!r.cancelled) {
            const open = r.url ? '내려받기 페이지 열기' : undefined;
            const a = await this.messages.warn(r.message, ...(open ? [open] : []));
            if (a && r.url) {
                this.windows.openNewWindow(r.url, { external: true });
            }
        }
        return false;
    }

    /** Prism 이 필요한 작업: Prism 이 없다는 오류면 설치를 권하고, 설치되면 한 번 더 시도한다 */
    protected async withPrism<T>(fn: () => Promise<T>): Promise<T | undefined> {
        try {
            return await fn();
        } catch (e) {
            const msg = errorMessage(e);
            if (!msg.includes(PRISM_MISSING_TAG)) {
                throw e;
            }
            const install = 'Prism 설치';
            if (await this.messages.warn(plain(msg), install) === install && await this.installPrism()) {
                return fn();
            }
            return undefined;
        }
    }

    /** 예전 인스턴스(앱 폴더·공식 런처·CurseForge 등) → Prism 인스턴스로 옮기기(사용자 결정 2026-11-27) */
    async migrateToPrism(explicit = false, only?: string[]): Promise<void> {
        const all = await this.manager.call<Array<{ id: string; name: string; linked: boolean }>>('prism_migrate_candidates');
        const list = only ? all.filter(c => only.includes(c.id)) : all;
        if (!list.length) {
            if (explicit) {
                this.messages.info('옮길 예전 인스턴스가 없습니다. 모든 인스턴스가 Prism 인스턴스입니다.');
            }
            return;
        }
        const names = list.map(c => c.name).join(', ');
        const ok = await new ConfirmDialog({
            title: '예전 인스턴스를 Prism 으로 옮기기',
            msg: `이제 실행은 Prism Launcher 가 맡습니다. 아래 ${list.length}개를 Prism 인스턴스로 옮길까요?\n\n${names}\n\n`
                + '월드·모드·설정·데이터팩을 새 Prism 인스턴스로 복사합니다. 앱 폴더 안의 예전 것은 휴지통으로 가고(되살릴 수 있음), '
                + '다른 런처에서 연결한 것은 원래 폴더를 그대로 둡니다.',
            ok: '옮기기', cancel: '나중에',
        }).open();
        if (!ok) {
            return;
        }
        const res = await this.withPrism(() => this.manager.call<{ migrated: Array<{ to: string; name: string }>; failed: Array<{ id: string; error: string }> }>(
            'prism_migrate', { ids: list.map(c => c.id) }));
        if (!res) {
            return;
        }
        await this.manager.refresh();
        res.migrated.forEach(m => this.manager.ensureVisible(m.to, m.name));
        if (res.failed.length) {
            this.messages.warn(`${res.migrated.length}개를 옮겼고 ${res.failed.length}개는 실패했습니다: ${res.failed.map(f => plain(f.error)).join(' / ')}`);
        } else {
            this.messages.info(`${res.migrated.length}개를 Prism 인스턴스로 옮겼습니다. [실행]하면 Prism 이 게임 파일을 받고 켭니다.`);
        }
    }

    /** 실행 = Prism 의 [실행](--launch). 로그인·자바·게임 파일 받기는 Prism. 옮기지 않은 예전 인스턴스면 옮기기를 권한다 */
    protected async play(inst: Instance): Promise<void> {
        if (this.manager.isRunning(inst.id)) {
            this.messages.info(`${inst.name}은(는) 이미 실행 중입니다. 다시 켜려면 게임 창을 닫은 뒤 실행하세요.`);
            return;
        }
        if (inst.launchKind !== 'prism' && inst.launchKind !== 'multimc') {
            await this.migrateToPrism(true, [inst.id]);
            return;
        }
        await this.manager.call('sync_now').catch(() => undefined);  // 실행 직전에 게임 설정·서버 목록을 최신으로
        await this.linkedPlay(inst);
    }

    /** Prism·MultiMC 인스턴스: 그 게임 폴더 안의 실행 파일 → 그 런처가 이 인스턴스를 바로 켠다. 이 앱에는 아무것도 설치하지 않는다. */
    protected async linkedPlay(inst: Instance): Promise<void> {
        const use = await this.manager.call<{ busy: boolean; reasons: string[] }>('import_in_use', { id: inst.id });
        if (use.busy) {
            this.messages.warn(`${inst.name}: 이미 이 폴더로 게임이 켜져 있습니다. ${use.reasons.join(' ')}`);
            return;
        }
        let r: { launcher: string; kind: string; file: string };
        try {
            r = await this.manager.call<{ launcher: string; kind: string; file: string }>('launch_linked', { id: inst.id });
        } catch (e) {
            const msg = (e as Error).message ?? String(e);
            if (msg.includes(NEEDS_PRISM_TAG)) {
                await this.migrateToPrism(true, [inst.id]);
                return;
            }
            if (!msg.includes(NEED_ROOT_TAG)) {
                throw e;
            }
            // Prism·MultiMC 데이터 폴더를 못 찾음(설정에서 인스턴스 폴더를 옮긴 경우 등) → 사용자가 고르게 하고 다시 실행
            this.messages.warn(msg.replace(NEED_ROOT_TAG, '').replace(/\s*\([^()]*\.py:\d+[^()]*\)\s*$/, '').trim());
            const uri = await this.fileDialog.showOpenDialog({ title: '런처 데이터 폴더 고르기(prismlauncher.cfg 가 있는 폴더)',
                openLabel: '고르기', canSelectFiles: false, canSelectFolders: true });
            const one = Array.isArray(uri) ? uri[0] : uri;
            if (!one) {
                return;
            }
            await this.manager.call('set_launcher_root', { id: inst.id, path: FileUri.fsPath(one) });
            r = await this.manager.call<{ launcher: string; kind: string; file: string }>('launch_linked', { id: inst.id });
        }
        await this.manager.call('game_tail_log', { id: inst.id }).catch(() => undefined);   // 게임 로그·실행 상태
        await this.manager.setTarget(inst.id);
        await this.registry.executeCommand(TaskCommandIds.GAME_LOG_TOGGLE).catch(() => undefined);
        this.messages.info(`${r.launcher}(으)로 '${inst.name}'을(를) 켭니다. 처음이면 Prism 에서 Microsoft 계정 로그인과 게임 파일 받기가 먼저 진행됩니다.`);
    }

    /** 통합 작업실(화면·확장 실행기·Claude·사이드카·서버)과 게임이 지금 쓰는 메모리 */
    protected async showMemoryUsage(): Promise<void> {
        const r = await this.manager.call<{ supported: boolean; message?: string; items?: Array<{ label: string; mb: number; count: number }>;
            totalMb?: number; systemMb?: number }>('memory_usage');
        if (!r.supported || !r.items) {
            this.messages.info(r.message ?? '메모리 사용량을 읽지 못했습니다.');
            return;
        }
        const gb = (mb: number) => mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb}MB`;
        await this.quickInput.showQuickPick(r.items.map(it => ({
            label: it.label, description: gb(it.mb), detail: it.count > 1 ? `프로세스 ${it.count}개` : undefined,
        })), { placeholder: `합계 ${gb(r.totalMb ?? 0)}${r.systemMb ? ` / PC 메모리 ${gb(r.systemMb)}` : ''} — 큰 것부터` });
    }

    /** 인스턴스 관리 메뉴(카드의 … 버튼·오른쪽 클릭) */
    protected async manage(i: Instance): Promise<void> {
        const running = this.manager.isRunning(i.id);
        const items: Array<{ label: string; description?: string; cmd: string }> = [
            { label: '$(play) 실행', description: running ? '실행 중' : LAUNCH_KIND_NAME[i.launchKind ?? 'official'], cmd: StudioCommands.LAUNCH.id },
            { label: '$(folder) 폴더 열기', description: i.linkedDir ? `연결된 원래 폴더: ${i.path}` : i.path, cmd: StudioCommands.OPEN_FOLDER.id },
            ...(i.sourceDir ? [{ label: '$(file-symlink-file) 원래 인스턴스 폴더 열기', description: `실행 파일이 있는 곳: ${i.sourceDir}`, cmd: 'studio.instance.openSourceFolder' }] : []),
            { label: '$(window) 작업실에서 열기', cmd: StudioCommands.OPEN_WORKSPACE.id },
            { label: '$(edit) 이름 바꾸기', cmd: StudioCommands.RENAME.id },
            { label: '$(copy) 복제', description: '모드·설정·월드를 복사한 새 인스턴스', cmd: StudioCommands.DUPLICATE.id },
            { label: '$(dashboard) 메모리 설정', description: i.jvmArgs ?? 'Prism 기본값', cmd: StudioCommands.MEMORY.id },
            { label: '$(extensions) 모드 추가', cmd: StudioCommands.ADD_MODS.id },
            { label: '$(broadcast) 서버로 열기', cmd: 'studio.serverHost.hostInstance' },
            ...(i.loader === 'fabric' ? [{ label: '$(plug) CommandCrafter 켜기/끄기', description: i.ccEnabled ? '지금 켬' : '지금 끔', cmd: StudioCommands.TOGGLE_CC.id }] : []),
            ...(i.launchKind !== 'prism' && i.launchKind !== 'multimc'
                ? [{ label: '$(arrow-right) Prism 으로 옮기기', description: '옮겨야 실행할 수 있습니다', cmd: StudioCommands.PRISM_MIGRATE.id }] : []),
            { label: i.launchKind === 'prism' ? '$(trash) 삭제(휴지통, Prism 에서도)' : i.linkedDir ? '$(close) 목록에서 지우기' : '$(trash) 삭제(휴지통)',
                description: i.launchKind === 'prism' ? 'Prism 인스턴스 폴더째 휴지통(되살릴 수 있음)' : i.linkedDir ? '원래 폴더는 그대로' : '월드·데이터팩 포함',
                cmd: StudioCommands.DELETE.id },
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

    protected guard(fn: () => Promise<unknown>): Promise<void> {
        return reportErrors(this.messages, fn);
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
            const inst = await this.withPrism(() => this.manager.create(result.options));
            if (!inst) {
                return;
            }
            this.manager.ensureVisible(inst.id, inst.name);
            const action = await this.messages.info(
                `'${inst.name}' Prism 인스턴스를 만들었습니다. 처음 실행할 때 Prism 이 게임·로더 파일을 받습니다.`, '작업실에서 열기');
            if (action) {
                await this.manager.openInWorkspace(inst.id);
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
            const res = await this.withPrism(() => result.kind === 'file'
                ? this.manager.call<ImportReport>('import_file', { path: result.path, version: result.version ?? null, ...look })
                : result.kind === 'modrinth'
                    ? this.manager.call<ImportReport>('modrinth_install_modpack', { version_id: result.versionId, ...look })
                    : this.manager.call<ImportReport>('cf_install_modpack', { mod_id: result.modId, file_id: result.fileId, ...look }));
            progress.cancel();
            if (!res) {
                return;
            }
            await this.manager.refresh();
            this.manager.ensureVisible(res.instance.id, res.instance.name);
            await this.manager.setTarget(res.instance.id);
            const id = res.instance.id;
            for (const f of res.failed) { this.manager.log(id, `받지 못함: ${f}`, 'warn', 'studio'); }
            for (const m of res.manual) { this.manager.log(id, `직접 받아 mods/에 넣어야 함: ${m}`, 'warn', 'studio'); }
            const extra = [
                res.failed.length ? `받지 못한 파일 ${res.failed.length}개` : '',
                res.manual.length ? `직접 받아야 할 모드 ${res.manual.length}개(제작자가 외부 다운로드를 막음)` : '',
            ].filter(Boolean).join(', ');
            const msg = res.linked && res.instance.launchKind !== 'prism'
                ? `'${res.instance.name}'을(를) 연결했습니다 — 원래 폴더 그대로이고 아무것도 받지 않았습니다. [실행]하면 ${LAUNCH_KIND_NAME[res.instance.launchKind ?? 'official']}이(가) 켭니다.`
                : res.linked
                    ? `'${res.instance.name}' Prism 인스턴스를 연결했습니다 — 원래 폴더 그대로, [실행]하면 Prism 이 켭니다.`
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
