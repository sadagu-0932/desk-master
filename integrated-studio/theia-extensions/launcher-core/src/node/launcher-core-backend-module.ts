import * as fs from 'fs';
import * as path from 'path';
import { ContainerModule, inject, injectable } from '@theia/core/shared/inversify';
import { ConnectionHandler, RpcConnectionHandler } from '@theia/core/lib/common/messaging';
import { BackendApplicationContribution } from '@theia/core/lib/node/backend-application';
import { LAUNCHER_SERVICE_PATH, LauncherClient, LauncherService, SidecarStatus } from '../common';
import { SidecarProcess } from './sidecar-process';

/** 창(연결)마다 하나. 사이드카 프로세스는 앱 전체에서 하나를 같이 쓴다. */
@injectable()
class LauncherServiceImpl implements LauncherService {
    @inject(SidecarProcess) protected readonly sidecar: SidecarProcess;
    protected client: LauncherClient | undefined;
    protected disposeListener: { dispose(): void } | undefined;

    setClient(client: LauncherClient | undefined): void {
        this.client = client;
        this.disposeListener?.dispose();
        this.disposeListener = client
            ? this.sidecar.onNotification(n => this.client?.onSidecarNotification(n.method, n.params))
            : undefined;
    }

    call<T>(method: string, params?: object): Promise<T> {
        return this.sidecar.call<T>(method, params);
    }

    async status(): Promise<SidecarStatus> {
        try {
            await this.sidecar.call('ping');
        } catch {
            // status()에 오류 메시지가 담긴다
        }
        return this.sidecar.status();
    }

    async bundledClaudeSdkCli(): Promise<string | undefined> {
        try {
            const pkg = require.resolve('@anthropic-ai/claude-agent-sdk/package.json');
            const cli = path.join(path.dirname(pkg), 'cli.js');
            const sdk = path.join(path.dirname(pkg), 'sdk.mjs');
            // Theia는 cli.js 옆의 sdk.mjs 를 불러온다
            return fs.existsSync(sdk) ? (fs.existsSync(cli) ? cli : sdk) : undefined;
        } catch {
            return undefined;
        }
    }

    dispose(): void {
        this.disposeListener?.dispose();
    }
}

@injectable()
class SidecarLifecycle implements BackendApplicationContribution {
    @inject(SidecarProcess) protected readonly sidecar: SidecarProcess;
    onStop(): void {
        this.sidecar.dispose();
    }
}

export default new ContainerModule(bind => {
    bind(SidecarProcess).toSelf().inSingletonScope();
    bind(SidecarLifecycle).toSelf().inSingletonScope();
    bind(BackendApplicationContribution).toService(SidecarLifecycle);
    bind(LauncherServiceImpl).toSelf();
    bind(ConnectionHandler).toDynamicValue(ctx =>
        new RpcConnectionHandler<LauncherClient>(LAUNCHER_SERVICE_PATH, client => {
            const service = ctx.container.get(LauncherServiceImpl);
            service.setClient(client);
            client.onDidCloseConnection(() => service.dispose());
            return service;
        })
    ).inSingletonScope();
});
