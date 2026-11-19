package com.deskmaster.coreui.api;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

import java.util.ArrayList;
import java.util.List;

/**
 * 화면 정의. 파츠가 자바 코드({@link #builder})로 만들거나
 * 설정 파일(config/coreui/screens/*.json)에서 읽는다.
 *
 * @param id        화면 ID ("main", "shop" ...)
 * @param title     창 제목
 * @param columns   격자 열 수 (상자 GUI 호환을 원하면 9 이하)
 * @param rows      격자 행 수
 * @param openable  true면 일반 플레이어가 /ui open 이나 단축키로 직접 열 수 있다
 */
public record UiScreen(String id, String title, int columns, int rows, boolean openable, List<UiComponent> components) {

    public UiScreen {
        if (id == null || !id.matches("[a-z0-9_./:-]+")) throw new IllegalArgumentException("화면 ID는 소문자·숫자·_./:- 만: " + id);
        if (columns < 1 || columns > 32) throw new IllegalArgumentException("columns는 1~32: " + id);
        if (rows < 1 || rows > 32) throw new IllegalArgumentException("rows는 1~32: " + id);
        components = List.copyOf(components);
        for (UiComponent c : components) {
            if (c.x() < 0 || c.y() < 0 || c.x() + c.w() > columns || c.y() + c.h() > rows) {
                throw new IllegalArgumentException("화면 '" + id + "'의 컴포넌트 '" + c.type() + ":" + c.id() + "'가 격자 밖으로 나감");
            }
        }
    }

    public UiComponent find(String componentId) {
        if (componentId == null || componentId.isEmpty()) return null;
        for (UiComponent c : components) if (c.id().equals(componentId)) return c;
        return null;
    }

    public static Builder builder(String id) {
        return new Builder(id);
    }

    /** 코드로 화면을 만드는 빌더. */
    public static final class Builder {
        private final String id;
        private String title = "";
        private int columns = 9, rows = 3;
        private boolean openable = false;
        private final List<UiComponent> components = new ArrayList<>();

        private Builder(String id) { this.id = id; }

        public Builder title(String title) { this.title = title; return this; }
        public Builder size(int columns, int rows) { this.columns = columns; this.rows = rows; return this; }
        public Builder openable(boolean openable) { this.openable = openable; return this; }

        /** 아무 종류나 직접 추가. 파츠가 만든 새 위젯 종류도 이걸로 넣는다. */
        public Builder add(UiComponent component) { components.add(component); return this; }

        public Builder label(int x, int y, int w, String text) {
            return add(new UiComponent("label", "", x, y, w, 1, props("text", text)));
        }

        public Builder button(String id, int x, int y, int w, String text, String action) {
            return add(new UiComponent("button", id, x, y, w, 1, props("text", text, "action", action)));
        }

        public Builder iconButton(String id, int x, int y, int w, String icon, String text, String action) {
            return add(new UiComponent("button", id, x, y, w, 1, props("text", text, "action", action, "icon", icon)));
        }

        public Builder icon(int x, int y, String itemId) {
            return add(new UiComponent("icon", "", x, y, 1, 1, props("item", itemId)));
        }

        public Builder toggle(String id, int x, int y, int w, String text, boolean value, String action) {
            JsonObject p = props("text", text, "action", action);
            p.addProperty("value", value);
            return add(new UiComponent("toggle", id, x, y, w, 1, p));
        }

        public Builder input(String id, int x, int y, int w, String hint) {
            return add(new UiComponent("input", id, x, y, w, 1, props("hint", hint)));
        }

        public UiScreen build() {
            return new UiScreen(id, title, columns, rows, openable, components);
        }

        /** "키", "값", "키", "값" ... 쌍으로 props를 만든다. null 값은 건너뛴다. */
        public static JsonObject props(String... kv) {
            JsonObject o = new JsonObject();
            for (int i = 0; i + 1 < kv.length; i += 2) {
                if (kv[i + 1] != null) o.add(kv[i], new JsonPrimitive(kv[i + 1]));
            }
            return o;
        }
    }

    /** 액션 목록: "action"이 문자열 하나거나 배열일 수 있다. */
    public static List<String> actionsOf(UiComponent c) {
        var e = c.props().get("action");
        if (e == null || e.isJsonNull()) return List.of();
        if (e.isJsonArray()) {
            List<String> out = new ArrayList<>();
            for (var a : (JsonArray) e) out.add(a.getAsString());
            return out;
        }
        return List.of(e.getAsString());
    }
}
