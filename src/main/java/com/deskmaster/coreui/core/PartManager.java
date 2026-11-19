package com.deskmaster.coreui.core;

import com.deskmaster.coreui.api.ActionHandler;
import com.deskmaster.coreui.api.PartContext;
import com.deskmaster.coreui.api.PlaceholderResolver;
import com.deskmaster.coreui.api.ScreenProvider;
import com.deskmaster.coreui.api.UiComponent;
import com.deskmaster.coreui.api.UiController;
import com.deskmaster.coreui.api.UiPart;
import com.deskmaster.coreui.api.UiScreen;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

/**
 * 파츠를 켜고 끄고, 설정 폴더의 화면 JSON을 읽는다.
 *
 * <pre>
 * config/coreui/
 *   parts.json          파츠별 켜기/끄기  {"demo": true}
 *   screens/*.json      코딩 없이 만드는 화면들
 * </pre>
 */
public final class PartManager {
    /** 설정 파일에서 읽은 화면은 이 파츠 ID로 등록된다. */
    public static final String CONFIG_PART = "config";

    private final UiService service;
    private final Path configDir;
    private final List<UiPart> parts;
    private final List<UiPart> enabled = new ArrayList<>();

    public PartManager(UiService service, Path configDir, List<UiPart> parts) {
        this.service = service;
        this.configDir = configDir;
        this.parts = List.copyOf(parts);
    }

    public List<UiPart> parts() { return parts; }

    public boolean isEnabled(UiPart part) { return enabled.contains(part); }

    /** 전부 끄고 설정을 다시 읽어 켠다. 처음 시작할 때도 이걸 부른다. */
    public void reload() {
        for (UiPart p : enabled) {
            try {
                p.disable();
            } catch (RuntimeException ex) {
                service.platform().warn("파츠 '" + p.id() + "' 끄기 실패: " + ex);
            }
            service.unregisterPart(p.id());
        }
        enabled.clear();
        service.unregisterPart(CONFIG_PART);

        Map<String, Boolean> toggles = readToggles();
        for (UiPart p : parts) {
            if (!toggles.getOrDefault(p.id(), true)) {
                service.platform().info("파츠 꺼짐(설정): " + p.id());
                continue;
            }
            try {
                p.enable(new Ctx(p.id()));
                enabled.add(p);
            } catch (RuntimeException ex) {
                service.platform().warn("파츠 '" + p.id() + "' 켜기 실패: " + ex);
                service.unregisterPart(p.id());
            }
        }
        int loaded = loadConfigScreens();
        service.platform().info("파츠 " + enabled.size() + "/" + parts.size() + "개 켜짐, 설정 화면 " + loaded + "개 읽음");
    }

    private Map<String, Boolean> readToggles() {
        Path file = configDir.resolve("parts.json");
        Map<String, Boolean> map = new LinkedHashMap<>();
        try {
            if (Files.exists(file)) {
                JsonObject o = JsonParser.parseString(Files.readString(file, StandardCharsets.UTF_8)).getAsJsonObject();
                for (var e : o.entrySet()) map.put(e.getKey(), e.getValue().getAsBoolean());
            }
            // 새로 생긴 파츠는 켜진 상태로 파일에 추가해 둔다
            boolean changed = false;
            for (UiPart p : parts) {
                if (!map.containsKey(p.id())) {
                    map.put(p.id(), true);
                    changed = true;
                }
            }
            if (changed || !Files.exists(file)) {
                Files.createDirectories(configDir);
                JsonObject out = new JsonObject();
                map.forEach(out::addProperty);
                Files.writeString(file, new GsonBuilder().setPrettyPrinting().create().toJson(out), StandardCharsets.UTF_8);
            }
        } catch (IOException | RuntimeException ex) {
            service.platform().warn("parts.json 읽기 실패 (모든 파츠를 켭니다): " + ex);
        }
        return map;
    }

    private int loadConfigScreens() {
        Path dir = configDir.resolve("screens");
        int count = 0;
        try {
            if (!Files.isDirectory(dir)) {
                Files.createDirectories(dir);
                writeExample(dir.resolve("example.json"));
            }
            try (Stream<Path> files = Files.list(dir)) {
                for (Path f : files.filter(p -> p.toString().endsWith(".json")).sorted().toList()) {
                    try {
                        UiScreen screen = ScreenJson.fromJson(Files.readString(f, StandardCharsets.UTF_8));
                        service.registerScreen(CONFIG_PART, screen.id(), screen.openable(), v -> screen);
                        count++;
                    } catch (IOException | RuntimeException ex) {
                        service.platform().warn("화면 파일 오류 " + f.getFileName() + ": " + ex.getMessage());
                    }
                }
            }
        } catch (IOException ex) {
            service.platform().warn("screens 폴더를 읽지 못함: " + ex);
        }
        return count;
    }

    private void writeExample(Path file) throws IOException {
        UiScreen example = UiScreen.builder("example")
                .title("예제 화면 (config/coreui/screens/example.json)")
                .size(9, 4)
                .openable(true)
                .label(0, 0, 9, "이 화면은 JSON 파일로 만들었어요, {player}님")
                .iconButton("day", 0, 1, 3, "minecraft:sunflower", "낮으로", "command:time set day")
                .iconButton("night", 3, 1, 3, "minecraft:clock", "밤으로", "command:time set night")
                .button("back", 6, 1, 3, "뒤로", "back")
                .input("msg", 0, 2, 6, "할 말을 입력하세요")
                .button("say", 6, 2, 3, "말하기", "command:say {input:msg}")
                .add(new UiComponent("toggle", "rain", 0, 3, 4, 1, rainProps()))
                .build();
        String json = ScreenJson.toJson(example, true);
        Files.writeString(file, json, StandardCharsets.UTF_8);
    }

    /** 토글: 켜지면 {value}가 "rain", 꺼지면 "clear"가 된다. */
    private static JsonObject rainProps() {
        JsonObject p = UiScreen.Builder.props("text", "비", "action", "command:weather {value}", "on", "rain", "off", "clear");
        p.addProperty("value", false);
        return p;
    }

    private final class Ctx implements PartContext {
        private final String partId;

        Ctx(String partId) { this.partId = partId; }

        @Override public String partId() { return partId; }
        @Override public void screen(UiScreen screen) { service.registerScreen(partId, screen.id(), screen.openable(), v -> screen); }
        @Override public void screen(String id, boolean openable, ScreenProvider provider) { service.registerScreen(partId, id, openable, provider); }
        @Override public void action(String type, ActionHandler handler) { service.registerAction(partId, type, handler); }
        @Override public void placeholder(String name, PlaceholderResolver resolver) { service.registerPlaceholder(partId, name, resolver); }
        @Override public UiController ui() { return service; }
        @Override public void log(String message) { service.platform().info("[" + partId + "] " + message); }
    }
}
