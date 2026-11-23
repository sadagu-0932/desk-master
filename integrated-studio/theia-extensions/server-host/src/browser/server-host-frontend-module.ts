import '../../src/browser/style/server-host.css';

import { ContainerModule } from '@theia/core/shared/inversify';
import { bindViewContribution, FrontendApplicationContribution, WidgetFactory } from '@theia/core/lib/browser';
import { ServiceConnectionProvider } from '@theia/core/lib/browser/messaging/service-connection-provider';
import { SERVER_HOST_PATH, ServerHostService } from '../common/index.js';
import { ServerHostClientImpl, ServerHostStore } from './server-host-store.js';
import { ServerHostWidget } from './server-host-widget.js';
import { ImportWidget } from './import-widget.js';
import { ServerHostContribution } from './server-host-contribution.js';

export default new ContainerModule(bind => {
    bind(ServerHostClientImpl).toSelf().inSingletonScope();
    bind(ServerHostService).toDynamicValue(ctx => {
        const client = ctx.container.get(ServerHostClientImpl);
        return ServiceConnectionProvider.createProxy<ServerHostService>(ctx.container, SERVER_HOST_PATH, client);
    }).inSingletonScope();
    bind(ServerHostStore).toSelf().inSingletonScope();
    // 위젯은 매번 새로 만든다(닫았다 다시 열 때 빈 화면 방지)
    bind(ServerHostWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({ id: ServerHostWidget.ID, createWidget: () => ctx.container.get(ServerHostWidget) })).inSingletonScope();
    bind(ImportWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({ id: ImportWidget.ID, createWidget: () => ctx.container.get(ImportWidget) })).inSingletonScope();
    bindViewContribution(bind, ServerHostContribution);
    bind(FrontendApplicationContribution).toService(ServerHostContribution);
});
