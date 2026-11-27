import { MessageService } from '@theia/core/lib/common/message-service';

/** 오류 객체에서 사용자에게 보일 문구만 꺼낸다. */
export function errorMessage(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
}

/**
 * 명령 실행 중 오류가 나면 앱이 조용히 실패하지 않고 알림으로 보여 준다.
 * 모든 확장의 명령(`guard`)이 이 함수 하나를 쓴다.
 */
export async function reportErrors(messages: MessageService, fn: () => Promise<unknown>): Promise<void> {
    try {
        await fn();
    } catch (e) {
        messages.error(errorMessage(e));
    }
}
