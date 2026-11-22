import { ContainerModule } from '@theia/core/shared/inversify';
import { CommandContribution } from '@theia/core/lib/common/command';
import { ServiceConnectionProvider } from '@theia/core/lib/browser/messaging/service-connection-provider';
import { LAUNCHER_SERVICE_PATH, LauncherService } from '../common/index.js';
import { InstanceManager, LauncherClientImpl } from './instance-manager.js';
import { LauncherCommandContribution } from './launcher-commands.js';

export default new ContainerModule(bind => {
    bind(LauncherClientImpl).toSelf().inSingletonScope();
    bind(LauncherService).toDynamicValue(ctx => {
        const client = ctx.container.get(LauncherClientImpl);
        return ServiceConnectionProvider.createProxy<LauncherService>(ctx.container, LAUNCHER_SERVICE_PATH, client);
    }).inSingletonScope();
    bind(InstanceManager).toSelf().inSingletonScope();
    bind(LauncherCommandContribution).toSelf().inSingletonScope();
    bind(CommandContribution).toService(LauncherCommandContribution);
});
