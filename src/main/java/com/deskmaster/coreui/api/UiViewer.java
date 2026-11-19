package com.deskmaster.coreui.api;

import java.util.UUID;

/**
 * 화면을 보는 플레이어. 플랫폼(Fabric, 나중에 Paper)이 구현한다.
 * 코어와 파츠는 이 인터페이스만 써서 플랫폼에 묶이지 않는다.
 */
public interface UiViewer {
    UUID uuid();
    String name();
    void sendMessage(String message);
    /** 플레이어 본인의 권한으로 명령어 실행 (앞의 / 는 없어도 됨). */
    void runCommand(String command);
    /** 관리자(OP) 권한이 있는지. */
    boolean isAdmin();
}
