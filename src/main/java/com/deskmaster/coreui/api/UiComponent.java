package com.deskmaster.coreui.api;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

/**
 * 화면에 놓이는 컴포넌트 하나.
 *
 * <p>위치와 크기는 격자 칸 단위(x, y, w, h)다. 9열 격자를 기준으로 설계해서,
 * 나중에 상자 GUI 렌더러(Paper)를 붙이면 칸 하나가 슬롯 하나가 된다.
 *
 * <p>종류별 속성(text, action, icon 등)은 {@code props}에 들어간다.
 * 새 컴포넌트 종류를 추가하는 파츠는 자기 속성을 마음대로 정의할 수 있다.
 */
public final class UiComponent {
    private final String type;
    private final String id;
    private final int x, y, w, h;
    private final JsonObject props;

    public UiComponent(String type, String id, int x, int y, int w, int h, JsonObject props) {
        if (type == null || type.isBlank()) throw new IllegalArgumentException("컴포넌트 type이 비어 있음");
        if (w < 1 || h < 1) throw new IllegalArgumentException("w, h는 1 이상이어야 함: " + type + " " + id);
        this.type = type;
        this.id = id == null ? "" : id;
        this.x = x;
        this.y = y;
        this.w = w;
        this.h = h;
        this.props = props == null ? new JsonObject() : props;
    }

    public String type() { return type; }
    public String id() { return id; }
    public int x() { return x; }
    public int y() { return y; }
    public int w() { return w; }
    public int h() { return h; }

    /** 속성 원본. 수정하지 말고 읽기만 한다. */
    public JsonObject props() { return props; }

    public String str(String key, String def) {
        JsonElement e = props.get(key);
        return e != null && e.isJsonPrimitive() ? e.getAsString() : def;
    }

    public int integer(String key, int def) {
        JsonElement e = props.get(key);
        try {
            return e != null && e.isJsonPrimitive() ? e.getAsInt() : def;
        } catch (NumberFormatException ex) {
            return def;
        }
    }

    public boolean bool(String key, boolean def) {
        JsonElement e = props.get(key);
        return e != null && e.isJsonPrimitive() ? e.getAsBoolean() : def;
    }

    /** props의 문자열 값만 바꾼 복사본 (자리표시자 치환에 쓴다). */
    public UiComponent withProp(String key, String value) {
        JsonObject copy = props.deepCopy();
        copy.add(key, new JsonPrimitive(value));
        return new UiComponent(type, id, x, y, w, h, copy);
    }
}
