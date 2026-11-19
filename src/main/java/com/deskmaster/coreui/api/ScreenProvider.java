package com.deskmaster.coreui.api;

/**
 * 플레이어마다 내용이 달라지는 동적 화면. 열 때마다 호출된다.
 * 내용이 고정된 화면은 {@link PartContext#screen(UiScreen)}으로 등록하면 된다.
 */
@FunctionalInterface
public interface ScreenProvider {
    UiScreen create(UiViewer viewer);
}
