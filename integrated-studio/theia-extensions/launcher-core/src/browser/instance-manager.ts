import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { Emitter } from '@theia/core/lib/common/event';
import { MessageService } from '@theia/core/lib/common/message-service';
import { Progress } from '@theia/core/lib/common/message-service-protocol';
import { StorageService } from '@theia/core/lib/browser/storage-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { WorkspaceService } from '@theia/workspace/lib/browser/workspace-service';
import { ConfirmDialog } from '@theia/core/lib/browser/dialogs';
import { WindowService } from '@theia/core/lib/browser/window/window-service';
import {
    ConfirmEvent, CreateInstanceOptions, GameVersion, LoaderVersions, Instance, LauncherClient, LauncherService, Loader, LogEvent, ProgressEvent,
    ServerStartResult, StateEvent, WorkMode
} from '../common/index.js';
import { errorMessage } from './report-errors.js';

export interface RunState {
    game: boolean;
    server: boolean;
}

const TARGET_KEY = 'integrated-studio.runTarget';
const MAX_LOG_LINES = 5000;

/** 브라우저 쪽에서 백엔드 알림을 받아 InstanceManager로 넘긴다 */
@injectable()
export class LauncherClientImpl implements LauncherClient {
    protected readonly emitter = new Emitter<{ method: string; params: unknown }>();
    readonly onNotification = this.emitter.event;
    onSidecarNotification(method: string, params: unknown): void {
        this.emitter.fire({ method, params });
    }
}

@injectable()
export class InstanceManager {
    @inject(LauncherService) protected readonly service: LauncherService;
    @inject(LauncherClientImpl) protected readonly client: LauncherClientImpl;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(StorageService) protected readonly storage: StorageService;
    @inject(WorkspaceService) protected readonly workspace: WorkspaceService;
    @inject(WindowService) protected readonly windowService: WindowService;

    protected _instances: Instance[] = [];
    protected _running = new Map<string, RunState>();
    protected _targetId: string | undefined;
    protected _logs: LogEvent[] = [];
    protected _progress = new Map<string, Progress>();
    protected refreshTimer: ReturnType<typeof setTimeout> | undefined;
    protected _workspaceInstanceId: string | undefined;
    protected _ready: Promise<void>;
    protected _error: string | undefined;
    protected _confirms = new Map<string, ConfirmDialog>();

    protected readonly onDidChangeEmitter = new Emitter<void>();
    readonly onDidChange = this.onDidChangeEmitter.event;
    protected readonly onLogEmitter = new Emitter<LogEvent>();
    readonly onLog = this.onLogEmitter.event;
    protected readonly onDidClearLogsEmitter = new Emitter<void>();
    readonly onDidClearLogs = this.onDidClearLogsEmitter.event;
    protected readonly onStateEmitter = new Emitter<StateEvent>();
    readonly onState = this.onStateEmitter.event;

    @postConstruct()
    protected init(): void {
        this.client.onNotification(n => this.handleNotification(n.method, n.params));
        this._ready = this.load();
        this.workspace.onWorkspaceChanged(() => { this.updateWorkspaceInstance(); this.fire(); });
    }

    protected async load(): Promise<void> {
        this._targetId = await this.storage.getData<string>(TARGET_KEY);
        await this.refreshPrism();
        await this.refresh();
        try {
            const running = await this.service.call<{ game: string[]; server: string[] }>('running');
            running.game.forEach(id => this.setRunning(id, 'game', true));
            running.server.forEach(id => this.setRunning(id, 'server', true));
        } catch {
            // 사이드카 오류는 refresh에서 이미 표시됨
        }
        this.fire();
    }

    get ready(): Promise<void> { return this._ready; }
    get instances(): readonly Instance[] { return this._instances; }
    get error(): string | undefined { return this._error; }
    get logs(): readonly LogEvent[] { return this._logs; }

    protected _prism: { found: boolean; exe?: string | null; root?: string | null } | undefined;
    /** Prism 상태(모르면 undefined) */
    get prism(): { found: boolean; exe?: string | null; root?: string | null } | undefined { return this._prism; }
    /**
     * 런처 기능(홈 인스턴스·인스턴스 목록·실행·작업·서버)을 보여 줄지(사용자 결정 2026-11-27: Prism 이 없으면 런처 부분을 숨긴다).
     * 사이드카가 아직 답하지 않았으면 보여 준다.
     */
    get launcherEnabled(): boolean { return this._prism?.found ?? true; }

    /** Prism 이 설치돼 있는지 다시 확인(설치 뒤 등). 바뀌면 화면을 다시 그린다 */
    async refreshPrism(): Promise<void> {
        try {
            const before = this._prism?.found;
            this._prism = await this.service.call('prism_status');
            if (before !== this._prism?.found) {
                document.body.classList.toggle('studio-no-launcher', !this.launcherEnabled);
                this.fire();
            }
        } catch {
            // 사이드카 오류는 refresh 에서 표시
        }
    }

    /** 작업 공간으로 열려 있는 인스턴스 → 없으면 실행 대상 선택기의 값 → 없으면 첫 번째 */
    get current(): Instance | undefined {
        return this.find(this._workspaceInstanceId) ?? this.target;
    }
    get target(): Instance | undefined {
        return this.find(this._targetId) ?? this._instances[0];
    }
    get workspaceInstance(): Instance | undefined {
        return this.find(this._workspaceInstanceId);
    }

    find(id: string | undefined): Instance | undefined {
        return id ? this._instances.find(i => i.id === id) : undefined;
    }

    state(id: string | undefined): RunState {
        return (id && this._running.get(id)) || { game: false, server: false };
    }

    isRunning(id: string | undefined): boolean {
        return this.state(id).game;
    }

    async setTarget(id: string): Promise<void> {
        this._targetId = id;
        await this.storage.setData(TARGET_KEY, id);
        this.fire();
    }

    /**
     * 만들기·불러오기 뒤 새 인스턴스가 목록·화면에 꼭 보이게(사용자 요청 2026-11-25):
     * 1초·3초 뒤 다시 읽고, 10초 뒤에도 목록이나 화면에 없으면 창을 다시 불러온다(앱 재시작과 같은 효과, 사이드카·게임 로그는 그대로).
     */
    ensureVisible(id: string, name?: string): void {
        const shown = (): boolean => {
            const inList = this._instances.some(i => i.id === id);
            const label = name ?? this.find(id)?.name;
            const els = [...document.querySelectorAll('.studio-row-name, .studio-inst-card h3')];
            const onScreen = !els.length || !label || els.some(e => (e.textContent ?? '').includes(label));
            return inList && onScreen;
        };
        const wait = (ms: number) => new Promise(r => setTimeout(r, ms));
        (async () => {
            for (const ms of [1000, 2000]) {
                await wait(ms);
                await this.refresh();
                if (shown()) {
                    return;
                }
            }
            await wait(7000);
            await this.refresh();
            if (!shown()) {
                this.messages.info('새 인스턴스가 목록에 안 보여서 창을 다시 불러옵니다.');
                await wait(800);
                this.windowService.reload();
            }
        })().catch(() => undefined);
    }

    async refresh(): Promise<void> {
        try {
            this._instances = await this.service.call<Instance[]>('list_instances');
            this._error = undefined;
        } catch (e) {
            this._error = errorMessage(e);
        }
        this.updateWorkspaceInstance();
        this.fire();
    }

    protected updateWorkspaceInstance(): void {
        const roots = this.workspace.tryGetRoots();
        const rootPaths = roots.map(r => FileUri.fsPath(r.resource));
        const norm = (p: string) => p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
        const match = this._instances.find(i => rootPaths.some(r => norm(r) === norm(i.path)));
        this._workspaceInstanceId = match?.id;
        if (match && this._targetId !== match.id) {
            this._targetId = match.id;
            this.storage.setData(TARGET_KEY, match.id);
        }
    }

    protected fire(): void {
        this.onDidChangeEmitter.fire();
    }

    protected setRunning(id: string, source: 'game' | 'server', running: boolean): void {
        const s = { ...this.state(id) };
        s[source] = running;
        this._running.set(id, s);
    }

    protected handleNotification(method: string, params: unknown): void {
        switch (method) {
            case 'log': {
                const ev = params as LogEvent;
                this._logs.push(ev);
                if (this._logs.length > MAX_LOG_LINES) {
                    this._logs.splice(0, this._logs.length - MAX_LOG_LINES);
                }
                this.onLogEmitter.fire(ev);
                break;
            }
            case 'state': {
                const ev = params as StateEvent;
                this.setRunning(ev.id, ev.source, ev.running);
                if (!ev.running && ev.exitCode !== undefined && ev.exitCode !== 0 && ev.source === 'game') {
                    const name = this.find(ev.id)?.name ?? ev.id;
                    this.messages.warn(`${name}이(가) 비정상 종료되었습니다(코드 ${ev.exitCode}). 게임 로그를 확인하세요.`);
                }
                this.onStateEmitter.fire(ev);
                this.fire();
                break;
            }
            case 'progress':
                this.handleProgress(params as ProgressEvent);
                break;
            case 'instances_changed':
                // 만들기·불러오기·복제·삭제(서버 패널의 불러오기 포함) → 껐다 켜지 않아도 바로 목록에 반영
                clearTimeout(this.refreshTimer);
                this.refreshTimer = setTimeout(() => this.refresh(), 150);
                break;
            case 'confirm':
                this.handleConfirm(params as ConfirmEvent);
                break;
            case 'confirm_cancel':
                // 사이드카 쪽에서 시간 초과로 취소됨 → 열린 창을 닫는다
                this._confirms.get((params as { token: string }).token)?.close();
                break;
            case 'sidecar_exit':
                this._confirms.forEach(d => d.close());
                this._running.clear();
                this.fire();
                break;
        }
    }

    /** 사이드카의 확인 질문을 창으로 띄우고 답을 돌려준다. 창을 그냥 닫으면 '아니오'. */
    protected async handleConfirm(ev: ConfirmEvent): Promise<void> {
        const msg = document.createElement('div');
        msg.style.whiteSpace = 'pre-wrap';
        msg.textContent = ev.message;
        const name = ev.id ? this.find(ev.id)?.name : undefined;
        const dialog = new ConfirmDialog({
            title: name ? `${ev.title ?? '확인'} — ${name}` : (ev.title ?? '확인'),
            msg, ok: '예', cancel: '아니오',
        });
        this._confirms.set(ev.token, dialog);
        let ok = false;
        try {
            ok = (await dialog.open()) === true;
        } finally {
            this._confirms.delete(ev.token);
        }
        try {
            await this.service.call('confirm_reply', { token: ev.token, ok });
        } catch {
            // 사이드카가 이미 끝났으면 답할 곳이 없다
        }
    }

    protected async handleProgress(ev: ProgressEvent): Promise<void> {
        const key = ev.id || ev.stage;
        let progress = this._progress.get(key);
        if (ev.done) {
            progress?.cancel();
            this._progress.delete(key);
            return;
        }
        if (!progress) {
            const name = this.find(ev.id)?.name;
            progress = await this.messages.showProgress({ text: name ? `${name}: ${ev.text ?? ''}` : ev.text ?? '' });
            this._progress.set(key, progress);
        }
        const work = ev.max ? { done: ev.value ?? 0, total: ev.max } : undefined;
        progress.report({ message: ev.text, work });
    }

    protected closeProgress(id: string): void {
        this._progress.get(id)?.cancel();
        this._progress.delete(id);
    }

    clearLogs(): void {
        this._logs = [];
        this.onDidClearLogsEmitter.fire();
    }

    /** 앱 자체가 남기는 로그(빌드 등) */
    log(id: string, line: string, level: LogEvent['level'] = 'info', source: LogEvent['source'] = 'studio'): void {
        this.handleNotification('log', { id, line, level, source });
    }

    // ---------- 동작 ----------
    listVersions(snapshots = false): Promise<GameVersion[]> {
        return this.service.call<GameVersion[]>('list_versions', { snapshots });
    }

    listLoaderVersions(version: string, loader: Loader = 'fabric'): Promise<LoaderVersions> {
        return this.service.call<LoaderVersions>('list_loader_versions', { version, loader });
    }

    async create(opts: CreateInstanceOptions): Promise<Instance> {
        const inst = await this.service.call<Instance>('create_instance', {
            name: opts.name, version: opts.version, loader: opts.loader,
            loader_version: opts.loaderVersion ?? null, group: opts.group ?? null,
            icon: opts.icon ?? null, cc_enabled: opts.ccEnabled ?? null,
        });
        await this.refresh();
        await this.setTarget(inst.id);
        return inst;
    }

    async rename(id: string, name: string): Promise<void> {
        await this.service.call('rename_instance', { id, name });
        await this.refresh();
    }

    async delete(id: string): Promise<void> {
        await this.service.call('delete_instance', { id });
        await this.refresh();
    }

    async setCcEnabled(id: string, enabled: boolean): Promise<void> {
        await this.service.call('set_cc_enabled', { id, enabled });
        await this.refresh();
    }

    async setWorkMode(id: string, mode: WorkMode): Promise<void> {
        await this.service.call('set_work_mode', { id, mode });
        await this.refresh();
    }

    serverStart(id: string, world?: string): Promise<ServerStartResult> {
        return this.service.call<ServerStartResult>('server_start', { id, world });
    }

    serverStop(id: string): Promise<boolean> {
        return this.service.call<boolean>('server_stop', { id });
    }

    serverCommand(id: string, command: string): Promise<boolean> {
        return this.service.call<boolean>('server_command', { id, command });
    }

    call<T>(method: string, params?: object): Promise<T> {
        return this.service.call<T>(method, params);
    }

    /** 그 인스턴스 폴더를 작업 공간으로 연다(같은 창) */
    async openInWorkspace(id: string): Promise<void> {
        const inst = this.find(id);
        if (!inst) {
            return;
        }
        await this.setTarget(id);
        this.workspace.open(FileUri.create(inst.path), { preserveWindow: true });
    }
}
