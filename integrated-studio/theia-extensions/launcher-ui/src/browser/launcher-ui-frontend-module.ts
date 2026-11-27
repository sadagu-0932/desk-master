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
import { PluginTools } from './plugin-tools.js';
import { StudioFilterContribution } from './studio-filter.js';
import { FilterContribution } from '@theia/core/lib/common/contribution-filter';
import { ShellLayoutRestorer } from '@theia/core/lib/browser/shell/shell-layout-restorer';
import { LightStartLayoutRestorer } from './light-start-restorer.js';
import { WorkspaceService } from '@theia/workspace/lib/browser/workspace-service';
import { HostedPluginSupport } from '@theia/plugin-ext/lib/hosted/browser/hosted-plugin';
import { StudioHostedPluginSupport, StudioWorkspaceService } from './studio-mode.js';

/**
 * 위젯은 매번 새로 만든다(싱글톤 금지). WidgetManager 가 살아 있는 것을 캐시하고, 탭을 닫아 dispose 되면
 * 캐시에서 빼고 다시 createWidget 을 부른다 — 싱글톤이면 이미 dispose 된 빈 위젯이 돌아와 빈 화면이 된다.
 */
function widget(bind: interfaces.Bind, id: string, cls: interfaces.Newable<object>): void {
    bind(cls).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({ id, createWidget: () => ctx.container.get(cls) })).inSingletonScope();
}

export default new ContainerModule((bind, _unbind, _isBound, rebind) => {
    // 켤 때 편집기·Texel 탭은 되살리지 않는다(메모리)
    bind(LightStartLayoutRestorer).toSelf().inSingletonScope();
    rebind(ShellLayoutRestorer).toService(LightStartLayoutRestorer);
    // 런처 모드 ↔ 작업실 모드(앱을 켜면 런처, 확장 실행기는 작업실에서만)
    bind(StudioWorkspaceService).toSelf().inSingletonScope();
    rebind(WorkspaceService).toService(StudioWorkspaceService);
    bind(StudioHostedPluginSupport).toSelf().inSingletonScope();
    rebind(HostedPluginSupport).toService(StudioHostedPluginSupport);

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

    bind(PluginTools).toSelf().inSingletonScope();
    bind(CommandContribution).toService(PluginTools);

    bind(ClaudeIntegration).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(ClaudeIntegration);
    bind(CommandContribution).toService(ClaudeIntegration);
    bind(TabBarToolbarContribution).toService(ClaudeIntegration);
});
