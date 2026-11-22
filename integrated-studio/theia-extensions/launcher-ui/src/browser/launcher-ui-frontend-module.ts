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

function widget(bind: interfaces.Bind, id: string, cls: interfaces.Newable<object>): void {
    bind(cls).toSelf().inSingletonScope();
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

    bind(ModTools).toSelf().inSingletonScope();
    bind(CommandContribution).toService(ModTools);

    bind(ClaudeIntegration).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(ClaudeIntegration);
    bind(CommandContribution).toService(ClaudeIntegration);
    bind(TabBarToolbarContribution).toService(ClaudeIntegration);
});
