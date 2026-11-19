package com.deskmaster.coreui.core;

import com.deskmaster.coreui.api.ActionContext;
import com.deskmaster.coreui.api.ActionHandler;
import com.deskmaster.coreui.api.PlaceholderResolver;
import com.deskmaster.coreui.api.ScreenProvider;
import com.deskmaster.coreui.api.UiComponent;
import com.deskmaster.coreui.api.UiController;
import com.deskmaster.coreui.api.UiScreen;
import com.deskmaster.coreui.api.UiViewer;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 코어의 중심. 화면·액션·자리표시자 등록부와 플레이어별 화면 기록(세션)을 관리한다.
 * 서버 스레드에서만 호출한다고 가정한다.
 */
public final class UiService implements UiController {
    public record ScreenEntry(String partId, boolean openable, ScreenProvider provider) {}
    private record ActionEntry(String partId, String type, ActionHandler handler) {}
    private record PlaceholderEntry(String partId, PlaceholderResolver resolver) {}

    /** 플레이어가 지금 보고 있는 화면과 뒤로 가기 기록. */
    private static final class Session {
        int id;
        String screenId;
        UiScreen screen;
        final Deque<String> history = new ArrayDeque<>();
    }

    private static final Pattern PLACEHOLDER = Pattern.compile("\\{([a-z0-9_]+)(?::([^{}]*))?}");
    private static final int MAX_HISTORY = 16;
    private static final int MAX_VALUE_LENGTH = 256;
    private static final int MAX_DEPTH = 8;

    private final UiPlatform platform;
    private final Map<String, ScreenEntry> screens = new LinkedHashMap<>();
    private final List<ActionEntry> actions = new ArrayList<>();
    private final Map<String, PlaceholderEntry> placeholders = new HashMap<>();
    private final Map<UUID, Session> sessions = new HashMap<>();
    private int nextSessionId = 1;
    private int actionDepth = 0;

    public UiService(UiPlatform platform) {
        this.platform = platform;
    }

    public UiPlatform platform() { return platform; }

    // ------------------------------------------------------------------ 등록

    public void registerScreen(String partId, String screenId, boolean openable, ScreenProvider provider) {
        ScreenEntry old = screens.put(screenId, new ScreenEntry(partId, openable, provider));
        if (old != null) platform.warn("화면 '" + screenId + "'를 파츠 '" + partId + "'가 덮어씀 (원래 '" + old.partId() + "')");
    }

    public void registerAction(String partId, String type, ActionHandler handler) {
        actions.removeIf(a -> {
            if (!a.type().equals(type)) return false;
            platform.warn("액션 '" + type + "'를 파츠 '" + partId + "'가 덮어씀 (원래 '" + a.partId() + "')");
            return true;
        });
        actions.add(new ActionEntry(partId, type, handler));
        // "demo:count"와 "demo"가 둘 다 있으면 긴 쪽부터 맞춰 본다
        actions.sort(Comparator.comparingInt((ActionEntry a) -> a.type().length()).reversed());
    }

    public void registerPlaceholder(String partId, String name, PlaceholderResolver resolver) {
        placeholders.put(name, new PlaceholderEntry(partId, resolver));
    }

    /** 파츠가 꺼질 때 그 파츠가 등록한 것을 전부 지운다. */
    public void unregisterPart(String partId) {
        screens.values().removeIf(e -> e.partId().equals(partId));
        actions.removeIf(e -> e.partId().equals(partId));
        placeholders.values().removeIf(e -> e.partId().equals(partId));
    }

    public Map<String, ScreenEntry> screens() { return screens; }

    public Collection<String> actionTypes() {
        return actions.stream().map(ActionEntry::type).sorted().toList();
    }

    // ------------------------------------------------------------------ 화면 열기·닫기

    @Override
    public boolean open(UiViewer viewer, String screenId) {
        return show(viewer, screenId, true);
    }

    /** 일반 플레이어가 직접 열려고 할 때 (명령어·단축키). openable 화면만 허용. */
    public boolean openByPlayer(UiViewer viewer, String screenId) {
        ScreenEntry e = screens.get(screenId);
        if (e == null || (!e.openable() && !viewer.isAdmin())) {
            viewer.sendMessage("열 수 없는 화면입니다: " + screenId);
            return false;
        }
        return open(viewer, screenId);
    }

    @Override
    public void refresh(UiViewer viewer) {
        Session s = sessions.get(viewer.uuid());
        if (s != null) show(viewer, s.screenId, false);
    }

    @Override
    public void back(UiViewer viewer) {
        Session s = sessions.get(viewer.uuid());
        if (s == null || s.history.isEmpty()) {
            close(viewer);
            return;
        }
        String prev = s.history.pop();
        if (!show(viewer, prev, false)) close(viewer);
    }

    @Override
    public void close(UiViewer viewer) {
        sessions.remove(viewer.uuid());
        platform.sendClose(viewer);
    }

    /** 클라이언트가 ESC 등으로 창을 닫았을 때. */
    public void onClientClosed(UiViewer viewer, int sessionId) {
        Session s = sessions.get(viewer.uuid());
        if (s != null && s.id == sessionId) sessions.remove(viewer.uuid());
    }

    /** 서버가 꺼질 때. */
    public void clearSessions() {
        sessions.clear();
    }

    public void onDisconnect(UUID uuid) {
        sessions.remove(uuid);
    }

    private boolean show(UiViewer viewer, String screenId, boolean pushHistory) {
        ScreenEntry entry = screens.get(screenId);
        if (entry == null) {
            viewer.sendMessage("없는 화면입니다: " + screenId);
            return false;
        }
        UiScreen screen;
        try {
            screen = resolveTexts(viewer, entry.provider().create(viewer));
        } catch (RuntimeException ex) {
            platform.warn("화면 '" + screenId + "' 만들기 실패: " + ex);
            viewer.sendMessage("화면을 여는 중 오류가 났습니다: " + screenId);
            return false;
        }
        Session s = sessions.computeIfAbsent(viewer.uuid(), u -> new Session());
        if (pushHistory && s.screenId != null && !s.screenId.equals(screenId)) {
            s.history.push(s.screenId);
            while (s.history.size() > MAX_HISTORY) s.history.removeLast();
        }
        s.id = nextSessionId++;
        s.screenId = screenId;
        s.screen = screen;
        platform.sendOpen(viewer, s.id, ScreenJson.toJson(screen, false));
        return true;
    }

    // ------------------------------------------------------------------ 클릭 처리

    /**
     * 클라이언트에서 컴포넌트를 눌렀을 때.
     * 세션 번호와 컴포넌트를 서버가 보낸 화면과 대조해서, 보내지 않은 버튼은 실행하지 않는다.
     */
    public void handleClick(UiViewer viewer, int sessionId, String componentId, Map<String, String> rawValues) {
        Session s = sessions.get(viewer.uuid());
        if (s == null || s.id != sessionId) return; // 오래된 화면에서 온 클릭
        UiScreen screen = s.screen;
        UiComponent comp = screen.find(componentId);
        if (comp == null) return;

        Map<String, String> values = new HashMap<>();
        for (var e : rawValues.entrySet()) {
            if (screen.find(e.getKey()) == null) continue;
            String v = e.getValue().replaceAll("[\\r\\n\\u0000-\\u001f]", " ");
            values.put(e.getKey(), v.length() > MAX_VALUE_LENGTH ? v.substring(0, MAX_VALUE_LENGTH) : v);
        }
        runActions(viewer, screen, comp, values, UiScreen.actionsOf(comp));
    }

    public void runActions(UiViewer viewer, UiScreen screen, UiComponent comp, Map<String, String> values, List<String> list) {
        if (actionDepth >= MAX_DEPTH) {
            platform.warn("액션이 너무 깊게 중첩됨 (무한 반복?): " + list);
            return;
        }
        actionDepth++;
        try {
            ActionContext ctx = new ActionContext(viewer, screen, comp, values, this);
            String own = ownValue(comp, values);
            for (String raw : list) {
                String action = resolve(viewer, raw, values, own);
                if (!dispatch(ctx, action)) {
                    platform.warn("알 수 없는 액션: '" + action + "' (화면 " + screen.id() + ")");
                }
            }
        } finally {
            actionDepth--;
        }
    }

    /** {value}: 누른 컴포넌트의 값. 토글에 "on"/"off" 속성이 있으면 그 글자로 바꾼다. */
    private static String ownValue(UiComponent comp, Map<String, String> values) {
        String v = values.getOrDefault(comp.id(), "");
        if ("true".equals(v) && comp.props().has("on")) return comp.str("on", v);
        if ("false".equals(v) && comp.props().has("off")) return comp.str("off", v);
        return v;
    }

    private boolean dispatch(ActionContext ctx, String action) {
        for (ActionEntry a : actions) {
            String arg;
            if (action.equals(a.type())) arg = "";
            else if (action.startsWith(a.type() + ":")) arg = action.substring(a.type().length() + 1);
            else continue;
            try {
                a.handler().run(ctx, arg);
            } catch (RuntimeException ex) {
                platform.warn("액션 '" + action + "' 실행 중 오류 (파츠 " + a.partId() + "): " + ex);
                ctx.viewer().sendMessage("작업 중 오류가 났습니다.");
            }
            return true;
        }
        return false;
    }

    // ------------------------------------------------------------------ 자리표시자

    /** 화면을 보내기 전에 글자 속성의 자리표시자를 바꾼다. action은 누를 때 바꾸므로 그대로 둔다. */
    private UiScreen resolveTexts(UiViewer viewer, UiScreen screen) {
        List<UiComponent> out = new ArrayList<>();
        for (UiComponent c : screen.components()) {
            UiComponent r = c;
            for (var e : c.props().entrySet()) {
                if (e.getKey().equals("action") || !e.getValue().isJsonPrimitive()) continue;
                if (!e.getValue().getAsJsonPrimitive().isString()) continue;
                String v = e.getValue().getAsString();
                String nv = resolve(viewer, v, Map.of(), null);
                if (!nv.equals(v)) r = r.withProp(e.getKey(), nv);
            }
            out.add(r);
        }
        return new UiScreen(screen.id(), resolve(viewer, screen.title(), Map.of(), null),
                screen.columns(), screen.rows(), screen.openable(), out);
    }

    /**
     * {player}, {input:컴포넌트ID}, {value}, 파츠가 등록한 {이름:인자}를 바꾼다.
     * values가 비어 있으면(화면 그릴 때) {input}·{value}는 그대로 남긴다.
     */
    public String resolve(UiViewer viewer, String text, Map<String, String> values, String ownValue) {
        if (text == null || text.indexOf('{') < 0) return text;
        Matcher m = PLACEHOLDER.matcher(text);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String name = m.group(1);
            String arg = m.group(2) == null ? "" : m.group(2);
            String rep = switch (name) {
                case "player" -> viewer.name();
                case "input" -> values.isEmpty() && ownValue == null ? null : values.getOrDefault(arg, "");
                case "value" -> ownValue;
                default -> {
                    PlaceholderEntry pe = placeholders.get(name);
                    if (pe == null) yield null;
                    try {
                        yield pe.resolver().resolve(viewer, arg);
                    } catch (RuntimeException ex) {
                        platform.warn("자리표시자 {" + name + "} 오류: " + ex);
                        yield "?";
                    }
                }
            };
            m.appendReplacement(sb, Matcher.quoteReplacement(rep == null ? m.group() : rep));
        }
        m.appendTail(sb);
        return sb.toString();
    }
}
