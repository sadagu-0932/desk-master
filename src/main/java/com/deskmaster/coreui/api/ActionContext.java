package com.deskmaster.coreui.api;

import java.util.Map;

/**
 * 액션이 실행될 때 받는 정보.
 *
 * @param viewer    누른 플레이어
 * @param screen    지금 열려 있는 화면
 * @param component 누른 컴포넌트
 * @param values    화면 안 입력칸·토글의 현재 값 (컴포넌트 ID → 값)
 * @param ui        다른 화면을 열거나 닫을 때 쓰는 서비스
 */
public record ActionContext(UiViewer viewer, UiScreen screen, UiComponent component, Map<String, String> values, UiController ui) {

    public String value(String componentId, String def) {
        return values.getOrDefault(componentId, def);
    }
}
