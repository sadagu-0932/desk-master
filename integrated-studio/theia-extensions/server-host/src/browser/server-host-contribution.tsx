import { inject, injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution } from '@theia/core/lib/browser/shell/view-contribution';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { ApplicationShell } from '@theia/core/lib/browser/shell/application-shell';
import { WidgetManager } from '@theia/core/lib/browser/widget-manager';
import { CommandRegistry, CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { WindowService } from '@theia/core/lib/browser/window/window-service';
import { InstanceManager, reportErrors, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { CreateServerOptions, E4mcPrepare, ServerKind } from '../common/index.js';
import { ServerHostStore } from './server-host-store.js';
import { ServerHostWidget } from './server-host-widget.js';
import { ImportWidget } from './import-widget.js';
import { ServerHostCommands } from './server-host-commands.js';
import { ChoiceDialog, DdnsDialog, EulaDialog, ModCheckDialog, OpenServerDialog } from './server-host-dialogs.js';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { OpenerService, open } from '@theia/core/lib/browser/opener-service';
import { FileUri } from '@theia/core/lib/common/file-uri';

@injectable()
export class ServerHostContribution extends AbstractViewContribution<ServerHostWidget> implements FrontendApplicationContribution {
    @inject(ServerHostStore) protected readonly store: ServerHostStore;
    @inject(InstanceManager) protected readonly instances: InstanceManager;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(WindowService) protected readonly windows: WindowService;
    @inject(CommandService) protected readonly commandService: CommandService;
    @inject(WidgetManager) protected readonly widgets: WidgetManager;
    @inject(ApplicationShell) protected readonly appShell: ApplicationShell;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(OpenerService) protected readonly openers: OpenerService;

    constructor() {
        super({
            widgetId: ServerHostWidget.ID,
            widgetName: ServerHostWidget.LABEL,
            defaultWidgetOptions: { area: 'left', rank: 600 },
            toggleCommandId: ServerHostCommands.TOGGLE.id,
        });
    }

    /** 왼쪽 막대에 패널 탭이 늘 있게(이전 화면 배치에 없어도). */
    async onDidInitializeLayout(): Promise<void> {
        await this.openView({ activate: false, reveal: false });
    }

    override registerCommands(registry: CommandRegistry): void {
        // 기본 "View: Toggle …" 대신 한국어 명령으로 등록
        registry.registerCommand(ServerHostCommands.TOGGLE, { execute: () => this.openView({ activate: true, reveal: true }) });
        registry.registerCommand(ServerHostCommands.OPEN_SERVER, { execute: (kind?: ServerKind) => this.guard(() => this.openServer({ kind })) });
        registry.registerCommand(ServerHostCommands.HOST_INSTANCE, { execute: (id: string) => this.guard(() => this.openServer({ instanceId: id })) });
        registry.registerCommand(ServerHostCommands.OPEN_LAN, { execute: (port: number, motd?: string) => this.guard(() => this.openLan(port, motd)) });
        registry.registerCommand(ServerHostCommands.IMPORT, { execute: () => this.guard(() => this.openImport()) });
        registry.registerCommand(ServerHostCommands.START, { execute: (id: string) => this.guard(() => this.start(id)) });
        registry.registerCommand(ServerHostCommands.EULA, { execute: (id: string) => this.guard(() => this.eula(id)) });
        registry.registerCommand(ServerHostCommands.DDNS, { execute: () => this.guard(() => this.ddns()) });
        registry.registerCommand(ServerHostCommands.MEMORY, { execute: (id: string) => this.guard(() => this.serverMemory(id)) });
        registry.registerCommand(ServerHostCommands.MOD_CHECK, { execute: (id: string) => this.guard(() => this.modCheck(id)) });
        registry.registerCommand(ServerHostCommands.FIREWALL, { execute: (id: string) => this.guard(() => this.firewall(id)) });
        registry.registerCommand(ServerHostCommands.JAVA_INSTALL, { execute: () => this.guard(() => this.javaInstall()) });
    }

    /** 모드 확인(사용자 요청 2026-11-27): 서버·인스턴스 모드 비교 → 고른 것 복사·빼기 */
    protected async modCheck(id: string): Promise<void> {
        const s = this.store.snapshot.servers.find(x => x.id === id);
        const check = await this.store.service.modCheck(id);
        const items = await new ModCheckDialog(check, s?.name ?? '서버').open();
        if (!items?.length) {
            return;
        }
        const res = await this.store.service.modFix(id, items);
        const left = res.check.issues.length;
        if (res.failed.length) {
            this.messages.error(`모드 ${res.done}개를 고쳤고 ${res.failed.length}개는 실패했습니다: `
                + res.failed.map(f => `${f.name ?? f.id}(${f.error})`).join(', '));
        } else {
            this.messages.info(`모드 ${res.done}개를 맞췄습니다.${left ? ` 남은 차이 ${left}개 — [모드 확인]으로 다시 보세요.` : ' 이제 모두 일치합니다.'}`
                + (s && !['stopped', 'error', 'needs-eula'].includes(s.state) ? ' 서버를 다시 시작하면 적용됩니다.' : ''));
        }
    }

    protected async firewall(id: string): Promise<void> {
        const st = await this.store.service.firewallAllow(id);
        if (st.ok) {
            this.messages.info('Windows 방화벽에서 서버를 허용했습니다. 친구에게 다시 들어와 보라고 해 주세요.');
        } else if (st.message) {
            this.messages.warn(st.message);
        }
    }

    protected async javaInstall(): Promise<void> {
        const r = await this.instances.call<{ ok: boolean; message: string; url?: string }>('java_install', {});
        if (r.ok) {
            this.messages.info(r.message);
        } else if (r.url) {
            const open = '내려받기 페이지';
            if (await this.messages.warn(r.message, open) === open) {
                this.windows.openNewWindow(r.url, { external: true });
            }
        } else {
            this.messages.info(r.message);
        }
    }

    /** 전용 서버 최대 메모리(다음 시작부터). 비우면 기본값(보통 2GB) */
    protected async serverMemory(id: string): Promise<void> {
        const s = this.store.snapshot.servers.find(x => x.id === id);
        const cur = s?.memoryMb ? String(Math.round(s.memoryMb / 102.4) / 10) : '';
        const gb = await this.quickInput.input({
            prompt: `서버 최대 메모리(GB, 다음 시작부터). 비우면 기본값(보통 2GB). 게임과 같이 켜면 둘의 합이 PC 메모리를 넘지 않게 하세요.`,
            value: cur,
            validateInput: async v => (!v.trim() || (/^\d+(\.\d+)?$/.test(v.trim()) && Number(v) >= 0.5 && Number(v) <= 64)) ? undefined : '0.5 ~ 64 사이 숫자(GB)',
        });
        if (gb === undefined) {
            return;
        }
        await this.store.service.setServerMemory(id, gb.trim() ? Math.round(Number(gb) * 1024) : null);
        this.messages.info(`서버 메모리: ${gb.trim() ? gb + 'GB' : '기본값'} (다음 시작부터)`);
    }

    protected guard(fn: () => Promise<unknown>): Promise<void> {
        return reportErrors(this.messages, fn);
    }

    protected async openImport(): Promise<void> {
        const w = await this.widgets.getOrCreateWidget(ImportWidget.ID);
        if (!w.isAttached) {
            await this.appShell.addWidget(w, { area: 'main' });
        }
        await this.appShell.activateWidget(w.id);
    }

    // ---------- [서버 열기] ----------
    protected async openServer(pre: { kind?: ServerKind; instanceId?: string }): Promise<void> {
        await this.instances.ready;
        const opts = await new OpenServerDialog({
            instances: this.instances.instances, currentId: pre.instanceId ?? this.instances.current?.id,
            kind: pre.kind ?? (this.instances.instances.length ? 'lan' : 'external'),
            listWorlds: id => this.instances.call<string[]>('list_worlds', { id }),
            lanGames: () => this.store.snapshot.lanGames,
            ping: port => this.store.service.ping(port),
        }).open();
        if (!opts) {
            return;
        }
        await this.create(opts);
    }

    protected async openLan(port: number, motd?: string): Promise<void> {
        await this.create({ kind: 'external', port, name: motd });
    }

    protected async create(opts: CreateServerOptions): Promise<void> {
        await this.openView({ activate: true, reveal: true });
        const created = await this.store.service.createServer(opts);
        if (created.kind === 'lan') {
            await this.prepareLan(created.id, created.instanceId!);
        }
        await this.start(created.id);
    }

    /** 싱글 LAN: e4mc 준비(충돌 모드 선택, 바닐라는 e4mc 없이). 실패하면 UPnP 로 넘어간다고 안내. */
    protected async prepareLan(id: string, instanceId: string): Promise<void> {
        const inst = this.instances.find(instanceId);
        if (inst?.loader === 'vanilla') {
            // 실행이 Prism 이라(2026-11-27) 바닐라 인스턴스엔 e4mc(Fabric 모드)를 넣지 않는다 → UPnP·playit
            this.messages.info('바닐라 인스턴스라 e4mc 없이 UPnP 로 엽니다. e4mc 를 쓰려면 같은 버전의 Fabric 인스턴스로 여세요.');
            await this.store.service.prepareE4mc(id, 'skip');
            return;
        }
        let res: E4mcPrepare = await this.store.service.prepareE4mc(id, 'ask');
        if (res.needsChoice) {
            const choice = await new ChoiceDialog('e4mc 와 부딪칠 수 있는 모드',
                <div><p>이 인스턴스에 네트워크를 바꾸는 모드가 있어 e4mc 와 함께 쓰면 문제가 날 수 있습니다.</p>
                    <ul>{(res.conflicts ?? []).map(c => <li key={c.file}><b>{c.name}</b> — {c.why} <span className='sh-muted'>({c.file})</span></li>)}</ul></div>,
                [{ id: 'disable_once', label: '이번만 끄기', description: '게임을 끄면 되살립니다(.disabled 로 이름만 바꿈)', primary: true },
                    { id: 'proceed', label: '그대로 진행', description: '둘 다 켠 채로' },
                    { id: 'skip', label: 'e4mc 대신 UPnP', description: '모드를 건드리지 않음' }]).open();
            if (!choice) {
                return;
            }
            res = await this.store.service.prepareE4mc(id, choice);
        }
        if (res.ambiguous) {
            this.messages.warn(`${res.reason} — e4mc 대신 UPnP 로 엽니다.`);
            await this.store.service.prepareE4mc(id, 'skip');
            return;
        }
        if (!res.ok) {
            if (res.reason) {
                this.messages.info(res.reason);
            }
            return;
        }
        if (inst && this.instances.isRunning(inst.id)) {
            this.messages.warn('게임이 이미 켜져 있어 e4mc 는 다음 실행부터 적용됩니다. 이번에는 UPnP·playit 으로 엽니다(게임을 다시 켜면 e4mc).');
        }
    }

    protected async start(id: string): Promise<void> {
        const v = await this.store.service.startServer(id);
        if (v.state === 'needs-eula') {
            await this.eula(id);
        } else if (v.kind === 'lan' && v.instanceId && v.state === 'waiting-lan') {
            const running = this.instances.isRunning(v.instanceId);
            const inst = this.instances.find(v.instanceId);
            const action = running ? undefined : await this.messages.info(
                `${inst?.name ?? '인스턴스'}에서 월드를 열고 [ESC] → [LAN에 공개]를 누르면 자동으로 주소가 열립니다. 지금 게임을 실행할까요?`, '게임 실행');
            if (action) {
                await this.instances.setTarget(v.instanceId);
                await this.commandService.executeCommand(StudioCommands.LAUNCH.id, v.instanceId);
            }
        }
    }

    protected async eula(id: string): Promise<void> {
        const v = this.store.snapshot.servers.find(s => s.id === id);
        const url = v?.eulaUrl ?? 'https://aka.ms/MinecraftEULA';
        const ok = await new EulaDialog(url, u => this.windows.openNewWindow(u, { external: true })).open();
        if (ok) {
            await this.store.service.acceptEula(id);
        }
    }

    protected async ddns(): Promise<void> {
        const cur = this.store.snapshot.upnp;
        const v = await new DdnsDialog(cur).open();
        if (!v) {
            return;
        }
        await this.store.service.setUpnpSettings(v);
        this.messages.info(v.ddnsUrl ? 'DDNS 를 저장했습니다. 다음에 UPnP 로 열 때부터 고정 주소를 씁니다.' : 'DDNS 를 껐습니다.');
    }
}
