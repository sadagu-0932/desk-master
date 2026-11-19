package com.deskmaster.coreui.core;

import com.deskmaster.coreui.api.PartContext;
import com.deskmaster.coreui.api.UiPart;

/**
 * 기본 액션을 제공하는 파츠. 플랫폼과 무관하다.
 *
 * <ul>
 *   <li>{@code open:<화면ID>} 다른 화면 열기</li>
 *   <li>{@code back} 이전 화면 / {@code close} 닫기 / {@code refresh} 새로고침</li>
 *   <li>{@code command:<명령어>} 플레이어 본인 권한으로 명령어 실행</li>
 *   <li>{@code message:<글자>} 채팅창에 메시지</li>
 * </ul>
 */
public final class CorePart implements UiPart {
    @Override public String id() { return "core"; }
    @Override public String description() { return "기본 액션 (open, back, close, refresh, command, message)"; }

    @Override
    public void enable(PartContext ctx) {
        ctx.action("open", (c, arg) -> c.ui().open(c.viewer(), arg));
        ctx.action("back", (c, arg) -> c.ui().back(c.viewer()));
        ctx.action("close", (c, arg) -> c.ui().close(c.viewer()));
        ctx.action("refresh", (c, arg) -> c.ui().refresh(c.viewer()));
        ctx.action("command", (c, arg) -> c.viewer().runCommand(arg));
        ctx.action("message", (c, arg) -> c.viewer().sendMessage(arg));
    }
}
