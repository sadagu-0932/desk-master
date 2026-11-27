import * as path from 'path';
import { ContainerModule, inject, injectable } from '@theia/core/shared/inversify';
import { ConnectionHandler, RpcConnectionHandler } from '@theia/core/lib/common/messaging';
import { BackendApplicationContribution } from '@theia/core/lib/node/backend-application';
import { SidecarProcess } from 'integrated-studio-launcher-core/lib/node/sidecar-process.js';
import {
    CreateServerOptions, DetectedInstance, E4mcPrepare, FirewallStatus, HostSnapshot, ImportPreview, ImportResult, ModCheck, ModIssue,
    PingResult, PlayitStatus, ProviderId, SERVER_HOST_PATH, ServerHostClient, ServerHostService, ServerView, UpnpSettings,
} from '../common/index.js';
import { HostManager } from './host-manager.js';
import { LanDiscovery } from './lan-discovery.js';
import { PlayitManager } from './playit.js';
import { UpnpManager, natUpnpClient } from './upnp.js';

export const HostManagerToken = Symbol('HostManager');

function makeManager(sidecar: SidecarProcess): HostManager {
    const factory = natUpnpClient();
    let manager: HostManager | undefined;
    const upnp = new UpnpManager(factory, { ddns: () => manager?.ddns() });
    const playit = new PlayitManager({ dir: path.join(sidecar.dataDir, 'server-host', 'playit') });
    manager = new HostManager(sidecar, { upnp, playit, lan: new LanDiscovery() });
    return manager;
}

/** 창(연결)마다 하나. 서버·주소는 앱 전체에서 하나의 HostManager 가 관리한다. */
@injectable()
class ServerHostServiceImpl implements ServerHostService {
    @inject(HostManagerToken) protected readonly manager: HostManager;
    @inject(SidecarProcess) protected readonly sidecar: SidecarProcess;
    protected client: ServerHostClient | undefined;
    protected onSnap = (s: HostSnapshot): void => this.client?.onSnapshot(s);
    protected onConsole = (id: string, line: string): void => this.client?.onConsole(id, line);

    async setClient(client: ServerHostClient | undefined): Promise<void> {
        await this.dispose();
        this.client = client;
        if (client) {
            const m = this.manager;
            m.on('snapshot', this.onSnap);
            m.on('console', this.onConsole);
        }
    }

    async dispose(): Promise<void> {
        const m = this.manager;
        m.off('snapshot', this.onSnap);
        m.off('console', this.onConsole);
    }

    protected async m(): Promise<HostManager> { return this.manager; }

    async snapshot(): Promise<HostSnapshot> { return (await this.m()).snapshot(); }
    async createServer(o: CreateServerOptions): Promise<ServerView> { return (await this.m()).createServer(o); }
    async startServer(id: string): Promise<ServerView> { return (await this.m()).startServer(id); }
    async stopServer(id: string): Promise<ServerView> { return (await this.m()).stopServer(id); }
    async deleteServer(id: string): Promise<void> { return (await this.m()).deleteServer(id); }
    async acceptEula(id: string): Promise<ServerView> { return (await this.m()).acceptEula(id); }
    async command(id: string, command: string): Promise<void> { return (await this.m()).command(id, command); }
    async console(id: string): Promise<string[]> { return (await this.m()).console(id); }
    async openAddress(id: string): Promise<ServerView> { return (await this.m()).openAddress(id); }
    async closeAddress(id: string): Promise<ServerView> { return (await this.m()).closeAddress(id); }
    async setPreference(id: string, pref: 'auto' | ProviderId): Promise<ServerView> { return (await this.m()).setPreference(id, pref); }
    async setServerMemory(id: string, memoryMb: number | null): Promise<ServerView> { return (await this.m()).setServerMemory(id, memoryMb); }
    async ping(port: number): Promise<PingResult> { return (await this.m()).ping(port); }
    async prepareE4mc(id: string, choice: string): Promise<E4mcPrepare> { return (await this.m()).prepareE4mc(id, choice); }
    async playitStatus(): Promise<PlayitStatus> {
        return (await this.m()).playit!.status();
    }
    async playitInstall(): Promise<PlayitStatus> { return (await this.m()).playit!.install(); }
    async playitClaim(force?: boolean): Promise<PlayitStatus> { return (await this.m()).playit!.claim(!!force); }
    async playitVerify(): Promise<PlayitStatus> { return (await this.m()).playit!.verify(); }
    async nextProvider(id: string): Promise<ServerView> { return (await this.m()).nextProvider(id); }
    async modCheck(id: string): Promise<ModCheck> { return (await this.m()).modCheck(id); }
    async modFix(id: string, items: ModIssue[]): Promise<{ done: number; failed: Array<ModIssue & { error: string }>; check: ModCheck }> {
        return (await this.m()).modFix(id, items);
    }
    async openFolder(id: string): Promise<string> { return (await this.m()).openFolder(id); }
    async firewallCheck(id: string): Promise<FirewallStatus> { return (await this.m()).checkFirewall(id); }
    async firewallAllow(id: string): Promise<FirewallStatus> { return (await this.m()).allowFirewall(id); }
    async setUpnpSettings(s: { ddnsUrl?: string; ddnsDomain?: string; ddnsToken?: string }): Promise<UpnpSettings> {
        return (await this.m()).setUpnpSettings(s);
    }
    importDetect(): Promise<DetectedInstance[]> { return this.sidecar.call('import_detect'); }
    importInspectFolder(p: string): Promise<DetectedInstance[]> { return this.sidecar.call('import_inspect_folder', { path: p }); }
    importPreview(keys: string[], mode: 'copy' | 'link'): Promise<ImportPreview> { return this.sidecar.call('import_preview', { keys, mode }); }
    importRun(entries: Array<{ key: string; name?: string; version?: string }>, mode: 'copy' | 'link'): Promise<ImportResult> {
        return this.sidecar.call('import_run', { entries, mode });
    }
}

@injectable()
class ServerHostLifecycle implements BackendApplicationContribution {
    @inject(HostManagerToken) protected readonly manager: HostManager;
    async onStop(): Promise<void> {
        await this.manager.dispose();   // 공유기 UPnP 매핑 지우기·playit 에이전트 끄기
    }
}

export default new ContainerModule(bind => {
    bind(HostManagerToken).toDynamicValue(ctx => makeManager(ctx.container.get(SidecarProcess))).inSingletonScope();
    bind(ServerHostLifecycle).toSelf().inSingletonScope();
    bind(BackendApplicationContribution).toService(ServerHostLifecycle);
    bind(ServerHostServiceImpl).toSelf();
    bind(ConnectionHandler).toDynamicValue(ctx =>
        new RpcConnectionHandler<ServerHostClient>(SERVER_HOST_PATH, client => {
            const service = ctx.container.get(ServerHostServiceImpl);
            service.setClient(client);
            client.onDidCloseConnection(() => service.dispose());
            return service;
        })
    ).inSingletonScope();
});
