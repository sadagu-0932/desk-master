import '@fontsource/noto-sans-kr/400.css';
import '@fontsource/noto-sans-kr/500.css';
import '@fontsource/noto-sans-kr/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/600.css';
import '../../src/browser/style/studio.css';

import { ContainerModule, inject, injectable } from '@theia/core/shared/inversify';
import { FrontendApplicationContribution } from '@theia/core/lib/browser/frontend-application-contribution';
import { MonacoThemingService } from '@theia/monaco/lib/browser/monaco-theming-service';
import { STUDIO_THEME_ID, STUDIO_THEME_JSON } from './studio-theme.js';

@injectable()
class StudioThemeContribution implements FrontendApplicationContribution {
    @inject(MonacoThemingService) protected readonly theming: MonacoThemingService;

    initialize(): void {
        this.theming.registerParsedTheme({
            id: STUDIO_THEME_ID,
            label: STUDIO_THEME_JSON.name,
            uiTheme: 'vs-dark',
            json: STUDIO_THEME_JSON,
        });
    }
}

export default new ContainerModule(bind => {
    bind(StudioThemeContribution).toSelf().inSingletonScope();
    bind(FrontendApplicationContribution).toService(StudioThemeContribution);
});
