package com.deskmaster.coreui.core;

import com.deskmaster.coreui.api.UiViewer;

/**
 * 코어가 플랫폼에 부탁하는 일. Fabric 모드는 패킷으로, 나중에 붙일 Paper 플러그인은
 * 상자 GUI나 다이얼로그로 구현하면 된다.
 */
public interface UiPlatform {
    /** 화면을 띄운다. json은 {@link ScreenJson#toJson} 형식. */
    void sendOpen(UiViewer viewer, int sessionId, String json);
    void sendClose(UiViewer viewer);
    void info(String message);
    void warn(String message);
}
