package com.deskmaster.coreui.fabric.parts;

import com.deskmaster.coreui.api.PartContext;
import com.deskmaster.coreui.api.UiPart;
import com.deskmaster.coreui.api.UiScreen;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 파츠 만드는 법을 보여주는 예제. 마인크래프트 코드를 쓰지 않아서 Paper에서도 그대로 동작할 수 있다.
 *
 * <ul>
 *   <li>고정 화면 등록</li>
 *   <li>직접 만든 액션 ("demo:add")</li>
 *   <li>직접 만든 자리표시자 ({demo_clicks})</li>
 * </ul>
 */
public final class DemoPart implements UiPart {
    private final Map<UUID, Integer> clicks = new HashMap<>();

    @Override public String id() { return "demo"; }
    @Override public String description() { return "예제: 카운터 화면, 커스텀 액션·자리표시자"; }

    @Override
    public void enable(PartContext ctx) {
        ctx.placeholder("demo_clicks", (viewer, arg) -> String.valueOf(clicks.getOrDefault(viewer.uuid(), 0)));

        // "demo:add:5" → 인자 "5"
        ctx.action("demo:add", (c, arg) -> {
            int n = arg.isEmpty() ? 1 : Integer.parseInt(arg);
            clicks.merge(c.viewer().uuid(), n, Integer::sum);
            c.ui().refresh(c.viewer());
        });
        ctx.action("demo:reset", (c, arg) -> {
            clicks.remove(c.viewer().uuid());
            c.ui().refresh(c.viewer());
        });

        ctx.screen(UiScreen.builder("demo/counter")
                .title("카운터 (예제 파츠)")
                .size(9, 3)
                .openable(true)
                .icon(0, 0, "minecraft:redstone")
                .label(1, 0, 8, "누른 횟수: {demo_clicks}")
                .button("plus", 0, 1, 3, "+1", "demo:add:1")
                .button("plus10", 3, 1, 3, "+10", "demo:add:10")
                .button("reset", 6, 1, 3, "초기화", "demo:reset")
                .button("back", 6, 2, 3, "뒤로", "back")
                .build());
        ctx.log("카운터 화면 등록됨 (/ui open demo/counter)");
    }

    @Override
    public void disable() {
        clicks.clear();
    }
}
