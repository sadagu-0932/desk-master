import { injectable } from '@theia/core/shared/inversify';
import { ShellLayoutRestorer, WidgetDescription } from '@theia/core/lib/browser/shell/shell-layout-restorer';
import { Widget } from '@theia/core/lib/browser/widgets';

/**
 * 앱을 켤 때 메모리를 많이 쓰는 탭은 되살리지 않는다(사용자 요청 2026-11-27 "램 줄이기").
 * - 코드 편집기 탭: 파일마다 편집기 모델을 메모리에 올린다 → 파일은 필요할 때 다시 연다
 * - 리소스팩 편집기(Texel): 웹사이트 하나를 통째로 띄운다
 * 패널 배치·크기·사이드바 같은 나머지 화면 상태는 그대로 되살린다.
 */
export const SKIP_ON_START = new Set([
    'code-editor-opener',      // @theia/editor EditorWidgetFactory.ID
    'editor-preview-widget',   // @theia/editor-preview 미리 보기 탭
    'studio-texel',            // resourcepack-editor TexelWidget.ID
]);

@injectable()
export class LightStartLayoutRestorer extends ShellLayoutRestorer {
    protected override async convertToWidget(desc: WidgetDescription, context: ShellLayoutRestorer.InflateContext): Promise<Widget | undefined> {
        if (desc.constructionOptions && SKIP_ON_START.has(desc.constructionOptions.factoryId)) {
            return undefined;   // 되살리지 않음(Theia 가 빈 자리는 걸러 낸다)
        }
        return super.convertToWidget(desc, context);
    }
}
