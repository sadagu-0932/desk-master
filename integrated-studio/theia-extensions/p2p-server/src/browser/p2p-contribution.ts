import { inject, injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution } from '@theia/core/lib/browser/shell/view-contribution';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { CommandRegistry, CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { QuickInputService } from '@theia/core/lib/browser/quick-input';
import { WindowService } from '@theia/core/lib/browser/window/window-service';
import { InstanceManager, StudioCommands } from 'integrated-studio-launcher-core/lib/browser';
import { FileDialogService } from '@theia/filesystem/lib/browser/file-dialog/file-dialog-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { HostView } from '../common/index.js';
import { P2PStore } from './p2p-store.js';
import { P2PWidget } from './p2p-widget.js';
import { P2PCommands } from './p2p-commands.js';
import { EulaDialog, HostDialog, JoinDialog } from './p2p-dialogs.js';

@injectable()
export class P2PContribution extends AbstractViewContribution<P2PWidget> implements FrontendApplicationContribution {
    @inject(P2PStore) protected readonly store: P2PStore;
    @inject(InstanceManager) protected readonly instances: InstanceManager;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(QuickInputService) protected readonly quickInput: QuickInputService;
    @inject(WindowService) protected readonly windows: WindowService;
    @inject(CommandService) protected readonly commandService: CommandService;
    @inject(FileDialogService) protected readonly fileDialog: FileDialogService;

    constructor() {
        super({
            widgetId: P2PWidget.ID,
            widgetName: P2PWidget.LABEL,
            defaultWidgetOptions: { area: 'left', rank: 600 },
            toggleCommandId: P2PCommands.TOGGLE.id,
        });
    }

    /** 왼쪽 막대에 패널 탭이 늘 있게(이전 화면 배치에 없어도). */
    async onDidInitializeLayout(): Promise<void> {
        await this.openView({ activate: false, reveal: false });
    }

    override registerCommands(registry: CommandRegistry): void {
        // 기본 "View: Toggle …" 대신 한국어 명령으로 등록
        registry.registerCommand(P2PCommands.TOGGLE, { execute: () => this.openView({ activate: true, reveal: true }) });
        registry.registerCommand(P2PCommands.HOST, { execute: () => this.guard(() => this.host()) });
        registry.registerCommand(P2PCommands.JOIN, { execute: () => this.guard(() => this.join()) });
        registry.registerCommand(P2PCommands.START, { execute: (id: string) => this.guard(() => this.start(id)) });
        registry.registerCommand(P2PCommands.EULA, { execute: (id: string) => this.guard(() => this.eula(id)) });
        registry.registerCommand(P2PCommands.PLAY, { execute: (id: string) => this.guard(() => this.play(id)) });
        registry.registerCommand(P2PCommands.EXPORT_KEY, { execute: (id: string) => this.guard(() => this.exportKey(id)) });
        registry.registerCommand(P2PCommands.IMPORT_KEY, { execute: (id: string) => this.guard(() => this.importKey(id)) });
    }

    protected async guard(fn: () => Promise<unknown>): Promise<void> {
        try {
            await fn();
        } catch (e) {
            this.messages.error(e instanceof Error ? e.message : String(e));
        }
    }

    // ---------- 호스트: [서버 열기] ----------
    protected async host(): Promise<void> {
        await this.instances.ready;
        if (!this.instances.instances.length) {
            this.messages.info('인스턴스가 없습니다. 먼저 새 인스턴스를 만드세요.');
            return;
        }
        const opts = await new HostDialog({
            instances: this.instances.instances, currentId: this.instances.current?.id,
            listWorlds: id => this.instances.call<string[]>('list_worlds', { id }),
        }).open();
        if (!opts) {
            return;
        }
        await this.openView({ activate: true, reveal: true });
        const created = await this.store.service.createHost(opts);
        await this.start(created.id);
    }

    protected async start(id: string): Promise<void> {
        const v: HostView = await this.store.service.startHost(id);
        if (v.state === 'needs-eula') {
            await this.eula(id);
        } else if (v.kind === 'lan') {
            const inst = this.instances.find(v.instanceId);
            const running = this.instances.isRunning(v.instanceId);
            const action = running ? undefined : await this.messages.info(
                `${inst?.name ?? '인스턴스'}에서 월드를 열고 [ESC] → [LAN에 공개]를 누르면 자동으로 열립니다. 지금 게임을 실행할까요?`, '게임 실행');
            if (action) {
                await this.instances.setTarget(v.instanceId);
                await this.commandService.executeCommand(StudioCommands.LAUNCH.id, v.instanceId);
            }
        }
    }

    protected async eula(id: string): Promise<void> {
        const v = this.store.snapshot.hosts.find(h => h.id === id);
        const url = v?.eulaUrl ?? 'https://aka.ms/MinecraftEULA';
        const ok = await new EulaDialog(url, u => this.windows.openNewWindow(u, { external: true })).open();
        if (ok) {
            await this.store.service.acceptEula(id);
        }
    }

    // ---------- 서버 키 백업 ----------
    protected async exportKey(id: string): Promise<void> {
        const v = this.store.snapshot.hosts.find(h => h.id === id);
        const name = (v?.name ?? 'server').replace(/[\\/:*?"<>|]/g, '_');
        const uri = await this.fileDialog.showSaveDialog({
            title: '서버 키 내보내기', saveLabel: '저장', inputValue: `${name}.iskey`,
            filters: { '통합 작업실 서버 키': ['iskey'] },
        });
        if (!uri) {
            return;
        }
        const r = await this.store.service.exportKey(id, FileUri.fsPath(uri));
        this.messages.info(`서버 키를 저장했습니다: ${r.path}. 이 파일이 있으면 재설치나 다른 PC 에서도 같은 참가 코드를 씁니다. `
            + '파일을 가진 사람은 이 서버인 척할 수 있으니 남에게 보내거나 공유 폴더·git 에 올리지 마세요.');
    }

    protected async importKey(id: string): Promise<void> {
        const ok = await this.messages.warn('키를 가져오면 이 서버의 참가 코드가 파일에 든 코드로 바뀝니다. 지금 참가한 사람은 끊깁니다.', '가져오기');
        if (!ok) {
            return;
        }
        const uri = await this.fileDialog.showOpenDialog({
            title: '서버 키 가져오기', openLabel: '가져오기', canSelectFiles: true, canSelectFolders: false,
            filters: { '통합 작업실 서버 키': ['iskey'] },
        });
        const one = Array.isArray(uri) ? uri[0] : uri;
        if (!one) {
            return;
        }
        const v = await this.store.service.importKey(id, FileUri.fsPath(one));
        this.messages.info(`키를 가져왔습니다. 참가 코드: ${v.code}`);
    }

    // ---------- 참가: [참가] ----------
    protected async join(): Promise<void> {
        const code = await new JoinDialog().open();
        if (!code) {
            return;
        }
        await this.openView({ activate: true, reveal: true });
        const v = await this.store.service.join(code);
        if (v.state === 'error' || v.state === 'closed') {
            this.messages.error(v.message ?? '참가하지 못했습니다.');
            return;
        }
        await this.play(v.id);
    }

    /** 호스트 버전과 맞는 인스턴스를 고르고(없으면 만들기 제안) 서버 목록에 넣은 뒤 공식 런처로 실행. */
    protected async play(joinId: string): Promise<void> {
        await this.store.refresh();
        const j = this.store.snapshot.joins.find(x => x.id === joinId);
        if (!j?.info || !j.localPort) {
            throw new Error('먼저 참가 연결이 되어야 합니다.');
        }
        const info = j.info;
        const addr = `127.0.0.1:${j.localPort}`;
        await this.instances.ready;
        const loader = info.loader === 'fabric' ? 'fabric' : 'vanilla';
        const same = this.instances.instances.filter(i => i.version === info.version);
        same.sort((a, b) => (b.loader === loader ? 1 : 0) - (a.loader === loader ? 1 : 0));
        const items = [
            ...same.map(i => ({ label: i.name, description: `${i.version} · ${i.loader === 'fabric' ? 'Fabric' : '바닐라'}`, id: i.id })),
            { label: `$(add) 새 인스턴스 만들기 — ${info.version} ${loader === 'fabric' ? 'Fabric' : '바닐라'}`, description: '호스트와 같은 버전', id: '__new' },
            { label: '$(clippy) 주소만 복사하고 직접 접속', description: addr, id: '__copy' },
        ];
        const pick = await this.quickInput.showQuickPick(items, {
            placeholder: same.length
                ? `호스트 버전 ${info.version} — 어느 인스턴스로 들어갈까요?`
                : `호스트 버전 ${info.version} 과 맞는 인스턴스가 없습니다. 새로 만들까요?`,
        });
        if (!pick) {
            return;
        }
        if (pick.id === '__copy') {
            await navigator.clipboard?.writeText(addr);
            this.messages.info(`주소 ${addr} 를 복사했습니다. 마인크래프트 → 멀티플레이 → 직접 연결에 붙여 넣으세요.`);
            return;
        }
        let instanceId = pick.id;
        if (pick.id === '__new') {
            const inst = await this.instances.create({ name: `${info.name} 참가`.slice(0, 40), version: info.version, loader });
            instanceId = inst.id;
        }
        const added = await this.store.service.addToServerList(joinId, instanceId);
        await this.instances.setTarget(instanceId);
        await this.commandService.executeCommand(StudioCommands.LAUNCH.id, instanceId);
        this.messages.info(`공식 런처에서 플레이를 누른 뒤 [멀티플레이] → '${added.name}' 을(를) 고르세요(주소 ${addr}).`);
    }
}
