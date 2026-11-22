import { injectable } from '@theia/core/shared/inversify';
import { ContributionFilterRegistry, FilterContribution } from '@theia/core/lib/common/contribution-filter';
import { TestViewContribution } from '@theia/test/lib/browser/view/test-view-contribution';
import { TestRunViewContribution } from '@theia/test/lib/browser/view/test-run-view-contribution';
import { TestResultViewContribution } from '@theia/test/lib/browser/view/test-result-view-contribution';
import { TestOutputViewContribution } from '@theia/test/lib/browser/view/test-output-view-contribution';
import { OutlineViewContribution } from '@theia/outline-view/lib/browser/outline-view-contribution';

/**
 * VS Code(Theia)에서 따라 들어왔지만 통합 작업실에는 필요 없는 화면을 뺀다.
 * - 테스트(Testing): 코드 테스트 실행기
 * - Outline: 코드 구조 보기(데이터팩에는 의미 없음)
 * 확장(Extensions) 목록은 앱 의존성에서 @theia/vsx-registry 를 빼서 없앴다(필요한 확장은 앱에 함께 넣는다).
 */
const HIDDEN_CONTRIBUTIONS: Function[] = [
    TestViewContribution, TestRunViewContribution, TestResultViewContribution, TestOutputViewContribution,
    OutlineViewContribution,
];
/** 이전 화면 배치에 남아 있어도 다시 만들어지지 않게 위젯 공장도 뺀다 */
const HIDDEN_WIDGET_IDS = new Set([
    'test-view-container', 'test-tree-widget', 'test-run-widget', 'test-result-widget', 'test-output-view', 'outline-view',
]);

@injectable()
export class StudioFilterContribution implements FilterContribution {
    registerContributionFilters(registry: ContributionFilterRegistry): void {
        registry.addFilters('*', [
            contrib => !HIDDEN_CONTRIBUTIONS.some(cls => contrib instanceof cls),
            contrib => {
                const id = (contrib as { id?: unknown }).id;
                const isFactory = typeof (contrib as { createWidget?: unknown }).createWidget === 'function';
                return !(isFactory && typeof id === 'string' && HIDDEN_WIDGET_IDS.has(id));
            },
        ]);
    }
}
