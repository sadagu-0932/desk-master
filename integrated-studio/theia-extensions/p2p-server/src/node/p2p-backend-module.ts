import { ContainerModule, inject, injectable } from '@theia/core/shared/inversify';
import { ConnectionHandler, RpcConnectionHandler } from '@theia/core/lib/common/messaging';
import { BackendApplicationContribution } from '@theia/core/lib/node/backend-application';
import { SidecarProcess } from 'integrated-studio-launcher-core/lib/node/sidecar-process.js';
import { CreateHostOptions, HostView, JoinView, P2P_SERVICE_PATH, P2PClient, P2PService, P2PSnapshot } from '../common/index.js';
import { P2PManager } from './p2p-manager.js';

export const P2PManagerToken = Symbol('P2PManager');

/** 창(연결)마다 하나. 터널·서버는 앱 전체에서 하나의 P2PManager 가 관리한다. */
@injectable()
class P2PServiceImpl implements P2PService {
    @inject(P2PManagerToken) protected readonly manager: P2PManager;
    protected client: P2PClient | undefined;
    protected onSnap = (s: P2PSnapshot): void => this.client?.onSnapshot(s);
    protected onConsole = (id: string, line: string): void => this.client?.onConsole(id, line);

    setClient(client: P2PClient | undefined): void {
        this.dispose();
        this.client = client;
        if (client) {
            this.manager.on('snapshot', this.onSnap);
            this.manager.on('console', this.onConsole);
        }
    }

    dispose(): void {
        this.manager.off('snapshot', this.onSnap);
        this.manager.off('console', this.onConsole);
    }

    async snapshot(): Promise<P2PSnapshot> { return this.manager.snapshot(); }
    createHost(o: CreateHostOptions): Promise<HostView> { return this.manager.createHost(o); }
    startHost(id: string): Promise<HostView> { return this.manager.startHost(id); }
    stopHost(id: string): Promise<HostView> { return this.manager.stopHost(id); }
    deleteHost(id: string): Promise<void> { return this.manager.deleteHost(id); }
    regenerateCode(id: string): Promise<HostView> { return this.manager.regenerateCode(id); }
    acceptEula(id: string): Promise<HostView> { return this.manager.acceptEula(id); }
    exportKey(id: string, filePath: string): Promise<{ path: string; code: string }> { return this.manager.exportKey(id, filePath); }
    importKey(id: string, filePath: string): Promise<HostView> { return this.manager.importKey(id, filePath); }
    command(id: string, command: string): Promise<void> { return this.manager.command(id, command); }
    setWorld(id: string, world: string): Promise<HostView> { return this.manager.setWorld(id, world); }
    async console(id: string): Promise<string[]> { return this.manager.console(id); }
    join(code: string): Promise<JoinView> { return this.manager.join(code); }
    leave(id: string): Promise<void> { return this.manager.leave(id); }
    addToServerList(joinId: string, instanceId: string): Promise<{ name: string; ip: string }> {
        return this.manager.addToServerList(joinId, instanceId);
    }
}

@injectable()
class P2PLifecycle implements BackendApplicationContribution {
    @inject(P2PManagerToken) protected readonly manager: P2PManager;
    async onStop(): Promise<void> {
        await this.manager.dispose();
    }
}

export default new ContainerModule(bind => {
    bind(P2PManagerToken).toDynamicValue(ctx => new P2PManager(ctx.container.get(SidecarProcess))).inSingletonScope();
    bind(P2PLifecycle).toSelf().inSingletonScope();
    bind(BackendApplicationContribution).toService(P2PLifecycle);
    bind(P2PServiceImpl).toSelf();
    bind(ConnectionHandler).toDynamicValue(ctx =>
        new RpcConnectionHandler<P2PClient>(P2P_SERVICE_PATH, client => {
            const service = ctx.container.get(P2PServiceImpl);
            service.setClient(client);
            client.onDidCloseConnection(() => service.dispose());
            return service;
        })
    ).inSingletonScope();
});
