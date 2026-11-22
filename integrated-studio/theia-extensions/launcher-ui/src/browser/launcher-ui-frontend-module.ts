import '../../src/browser/style/launcher-ui.css';

import { ContainerModule, interfaces } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { WidgetFactory } from '@theia/core/lib/browser/widget-manager';
import { CommandContribution } from '@theia/core/lib/common/command';
import { TabBarToolbarContribution } from '@theia/core/lib/browser/shell/tab-bar-toolbar';
import { InstancesWidget } from './instances-widget.js';
import { TasksWidget } from './tasks-widget.js';
import { GameLogWidget } from './game-log-widget.js';
import { CommandConsoleWidget } from './command-console-widget.js';
import { RunTargetBar } from './run-target-bar.js';
import { HomeWidget } from './home-widget.js';
import { StudioUiContribution } from './studio-ui-contribution.js';
import { ClaudeIntegration } from './claude-integration.js';
import { ModTools } from './mod-tools.js';
import { StudioFilterContribution } from './studio-filter.js';
import { FilterContribution } from '@theia/core/lib/common/contribution-filter';

/**
 * 위젯은 매번 새로 만든다(싱글톤 금지). WidgetManager 가 살아 있는 것을 캐시하고, 탭을 닫아 dispose 되면
 * 캐시에서 빼고 다시 createWidget 을 부른다 — 싱글톤이면 이미 dispose 된 빈 위젯이 돌아와 빈 화면이 된다.
 */
function widget(bind: interfaces.Bind, id: string, cls: interfaces.Newable<object>): void {
    bind(cls).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({ id, createWidget: () => ctx.container.get(cls) })).inSingletonScope();
}

export default new ContainerModule(bind => {
    widget(bind, InstancesWidget.ID, InstancesWidget);
    widget(bind, TasksWidget.ID, TasksWidget);
    widget(bind, GameLogWidget.ID, GameLogWidget);
    widget(bind, CommandConsoleWidget.ID, CommandConsoleWidget);
    widget(bind, RunTargetBar.ID, RunTargetBar);
    widget(bind, HomeWidget.ID, HomeWidget);

    bind(StudioUiContribution).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(StudioUiContribution);
    bind(CommandContribution).toService(StudioUiContribution);

    bind(StudioFilterContribution).toSelf().inSingletonScope();
    bind(FilterContribution).toService(StudioFilterContribution);

    bind(ModTools).toSelf().inSingletonScope();
    bind(CommandContribution).toService(ModTools);

    bind(ClaudeIntegration).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(ClaudeIntegration);
    bind(CommandContribution).toService(ClaudeIntegration);
    bind(TabBarToolbarContribution).toService(ClaudeIntegration);
});
