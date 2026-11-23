import '../../src/browser/style/p2p.css';

import { ContainerModule } from '@theia/core/shared/inversify';
import { bindViewContribution, FrontendApplicationContribution, WidgetFactory } from '@theia/core/lib/browser';
import { ServiceConnectionProvider } from '@theia/core/lib/browser/messaging/service-connection-provider';
import { P2P_SERVICE_PATH, P2PService } from '../common/index.js';
import { P2PClientImpl, P2PStore } from './p2p-store.js';
import { P2PWidget } from './p2p-widget.js';
import { P2PContribution } from './p2p-contribution.js';

export default new ContainerModule(bind => {
    bind(P2PClientImpl).toSelf().inSingletonScope();
    bind(P2PService).toDynamicValue(ctx => {
        const client = ctx.container.get(P2PClientImpl);
        return ServiceConnectionProvider.createProxy<P2PService>(ctx.container, P2P_SERVICE_PATH, client);
    }).inSingletonScope();
    bind(P2PStore).toSelf().inSingletonScope();
    // 위젯은 매번 새로 만든다(닫았다 다시 열 때 빈 화면 방지 — WidgetManager 가 살아 있는 것을 캐시)
    bind(P2PWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({ id: P2PWidget.ID, createWidget: () => ctx.container.get(P2PWidget) })).inSingletonScope();
    bindViewContribution(bind, P2PContribution);
    bind(FrontendApplicationContribution).toService(P2PContribution);
});
