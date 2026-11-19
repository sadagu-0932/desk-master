package com.deskmaster.coreui.client;

import com.deskmaster.coreui.api.UiComponent;

/**
 * 컴포넌트 종류 하나를 화면에 그리는 방법.
 * 새 위젯 종류를 만드는 파츠(클라이언트 모드)는 {@link WidgetRegistry#register}로 등록한다.
 */
@FunctionalInterface
public interface WidgetFactory {
    /**
     * @param screen 위젯을 붙일 화면. {@link PartScreen#addWidget}, {@link PartScreen#bindValue},
     *               {@link PartScreen#click} 등을 쓴다.
     * @param x,y,w,h 격자를 픽셀로 바꾼 영역
     */
    void create(PartScreen screen, UiComponent component, int x, int y, int w, int h);
}
