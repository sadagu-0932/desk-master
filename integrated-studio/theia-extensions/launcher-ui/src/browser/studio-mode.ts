import { injectable, interfaces } from '@theia/core/shared/inversify';
import { DEFAULT_WINDOW_HASH } from '@theia/core/lib/common/window';
import { WorkspaceService } from '@theia/workspace/lib/browser/workspace-service';
import { HostedPluginSupport } from '@theia/plugin-ext/lib/hosted/browser/hosted-plugin';

/**
 * 앱 두 개처럼(사용자 결정 2026-11-27): 런처 모드 ↔ 작업실 모드.
 *
 * - 런처 모드(앱을 켤 때): 홈·인스턴스·실행·서버만. VS Code 확장 실행기(CommandCrafter 등)를 켜지 않아 메모리를 아낀다.
 * - 작업실 모드([작업실에서 열기]): 그 인스턴스 폴더가 열린 상태. 코드 편집기·확장 실행기가 켜진다.
 *
 * 어느 모드인지는 창 주소의 #뒤(열린 폴더)로 정한다. [작업실에서 열기]는 주소에 폴더를 넣고 창을 다시 불러오고,
 * 앱을 새로 켜면 주소가 비어 있다(→ 런처). 창 다시 불러오기(F5·10초 새로고침)는 주소가 그대로라 모드도 그대로다.
 */
export function workFolderInUrl(): boolean {
    const h = window.location.hash;
    return h.length > 1 && h !== `#${DEFAULT_WINDOW_HASH}`;
}

/** 앱을 새로 켜면 지난번 작업실을 자동으로 열지 않는다(런처 모드로 시작) */
@injectable()
export class StudioWorkspaceService extends WorkspaceService {
    protected override async doGetDefaultWorkspaceUri(): Promise<string | undefined> {
        if (!workFolderInUrl()) {
            return undefined;
        }
        return super.doGetDefaultWorkspaceUri();
    }
}

/** 확장 실행기는 작업실 모드에서만 켠다. 런처 모드에서는 시작 자체를 하지 않아(대기 훅도 안 걸림) 멈출 일이 없다 */
@injectable()
export class StudioHostedPluginSupport extends HostedPluginSupport {
    override onStart(container: interfaces.Container): void {
        if (workFolderInUrl()) {
            super.onStart(container);
        }
    }
}
