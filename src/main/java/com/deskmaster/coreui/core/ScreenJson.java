package com.deskmaster.coreui.core;

import com.deskmaster.coreui.api.UiComponent;
import com.deskmaster.coreui.api.UiScreen;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 화면 정의 ↔ JSON. 설정 파일과 네트워크 전송에 같은 형식을 쓴다.
 *
 * <pre>
 * {
 *   "id": "main", "title": "메인 메뉴", "columns": 9, "rows": 3, "openable": true,
 *   "components": [
 *     {"type": "label", "x": 0, "y": 0, "w": 9, "text": "안녕하세요 {player}님"},
 *     {"type": "button", "id": "go", "x": 0, "y": 1, "w": 3, "text": "이동", "action": "open:shop"}
 *   ]
 * }
 * </pre>
 * 컴포넌트의 type, id, x, y, w, h 외의 키는 전부 그 컴포넌트의 속성(props)이 된다.
 */
public final class ScreenJson {
    private static final Gson PRETTY = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();
    private static final Gson COMPACT = new GsonBuilder().disableHtmlEscaping().create();
    private static final Set<String> LAYOUT_KEYS = Set.of("type", "id", "x", "y", "w", "h");

    private ScreenJson() {}

    public static String toJson(UiScreen screen, boolean pretty) {
        JsonObject o = new JsonObject();
        o.addProperty("id", screen.id());
        o.addProperty("title", screen.title());
        o.addProperty("columns", screen.columns());
        o.addProperty("rows", screen.rows());
        o.addProperty("openable", screen.openable());
        JsonArray arr = new JsonArray();
        for (UiComponent c : screen.components()) {
            JsonObject co = new JsonObject();
            co.addProperty("type", c.type());
            if (!c.id().isEmpty()) co.addProperty("id", c.id());
            co.addProperty("x", c.x());
            co.addProperty("y", c.y());
            co.addProperty("w", c.w());
            if (c.h() != 1) co.addProperty("h", c.h());
            for (var e : c.props().entrySet()) co.add(e.getKey(), e.getValue());
            arr.add(co);
        }
        o.add("components", arr);
        return (pretty ? PRETTY : COMPACT).toJson(o);
    }

    public static UiScreen fromJson(String json) {
        JsonElement root = JsonParser.parseString(json);
        if (!root.isJsonObject()) throw new IllegalArgumentException("화면 JSON은 { } 객체여야 함");
        JsonObject o = root.getAsJsonObject();
        List<UiComponent> comps = new ArrayList<>();
        JsonArray arr = o.has("components") ? o.getAsJsonArray("components") : new JsonArray();
        for (JsonElement e : arr) {
            JsonObject co = e.getAsJsonObject();
            JsonObject props = new JsonObject();
            for (var entry : co.entrySet()) {
                if (!LAYOUT_KEYS.contains(entry.getKey())) props.add(entry.getKey(), entry.getValue());
            }
            comps.add(new UiComponent(
                    str(co, "type", null), str(co, "id", ""),
                    num(co, "x", 0), num(co, "y", 0), num(co, "w", 1), num(co, "h", 1), props));
        }
        return new UiScreen(str(o, "id", null), str(o, "title", ""),
                num(o, "columns", 9), num(o, "rows", 3),
                o.has("openable") && o.get("openable").getAsBoolean(), comps);
    }

    private static String str(JsonObject o, String k, String def) {
        return o.has(k) && o.get(k).isJsonPrimitive() ? o.get(k).getAsString() : def;
    }

    private static int num(JsonObject o, String k, int def) {
        return o.has(k) && o.get(k).isJsonPrimitive() ? o.get(k).getAsInt() : def;
    }
}
