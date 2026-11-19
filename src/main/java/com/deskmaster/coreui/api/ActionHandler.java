package com.deskmaster.coreui.api;

/**
 * 버튼·토글 같은 컴포넌트가 실행하는 액션.
 * 액션 문자열은 "종류:인자" 형식이다. 예) "open:shop", "command:spawn", "demo:count"
 */
@FunctionalInterface
public interface ActionHandler {
    void run(ActionContext ctx, String argument);
}
