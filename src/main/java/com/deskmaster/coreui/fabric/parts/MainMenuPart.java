package com.deskmaster.coreui.fabric.parts;

import com.deskmaster.coreui.api.PartContext;
import com.deskmaster.coreui.api.UiPart;
import com.deskmaster.coreui.api.UiScreen;
import com.deskmaster.coreui.core.UiService;
import com.deskmaster.coreui.fabric.CoreUiMod;

import java.util.List;
import java.util.Map;

/**
 * 메인 메뉴 ("main"). 다른 파츠가 등록한 openable 화면을 자동으로 버튼으로 모아 보여준다.
 * 새 파츠를 붙이면 아무것도 고치지 않아도 메뉴에 나타난다. 단축키 U로 연다.
 */
public final class MainMenuPart implements UiPart {
    public static final String SCREEN_ID = "main";
    private static final int COLUMNS = 9, BUTTON_W = 3, PER_ROW = COLUMNS / BUTTON_W, MAX_ROWS = 5;

    @Override public String id() { return "menu"; }
    @Override public String description() { return "메인 메뉴 (열 수 있는 화면을 자동으로 모음)"; }

    @Override
    public void enable(PartContext ctx) {
        ctx.screen(SCREEN_ID, true, viewer -> {
            List<Map.Entry<String, UiService.ScreenEntry>> targets = CoreUiMod.service().screens().entrySet().stream()
                    .filter(e -> e.getValue().openable() && !e.getKey().equals(SCREEN_ID))
                    .limit((long) PER_ROW * MAX_ROWS)
                    .toList();
            int rows = Math.max(1, (targets.size() + PER_ROW - 1) / PER_ROW);
            UiScreen.Builder b = UiScreen.builder(SCREEN_ID)
                    .title("메인 메뉴")
                    .size(COLUMNS, rows + 2)
                    .openable(true)
                    .label(0, 0, COLUMNS, "{player}님, 무엇을 할까요?");
            if (targets.isEmpty()) b.label(0, 1, COLUMNS, "아직 열 수 있는 화면이 없어요.");
            for (int i = 0; i < targets.size(); i++) {
                String id = targets.get(i).getKey();
                String title = titleOf(id, viewer);
                b.button("go_" + i, (i % PER_ROW) * BUTTON_W, 1 + i / PER_ROW, BUTTON_W, title, "open:" + id);
            }
            b.button("close", COLUMNS - BUTTON_W, rows + 1, BUTTON_W, "닫기", "close");
            return b.build();
        });
    }

    /** 버튼 글자: 화면 제목을 쓰고, 만들 수 없으면 ID. */
    private static String titleOf(String screenId, com.deskmaster.coreui.api.UiViewer viewer) {
        try {
            String t = CoreUiMod.service().screens().get(screenId).provider().create(viewer).title();
            if (t == null || t.isBlank()) return screenId;
            return t.length() > 14 ? t.substring(0, 13) + "…" : t;
        } catch (RuntimeException ex) {
            return screenId;
        }
    }
}
