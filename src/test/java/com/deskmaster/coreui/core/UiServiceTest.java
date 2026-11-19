package com.deskmaster.coreui.core;

import com.deskmaster.coreui.api.PartContext;
import com.deskmaster.coreui.api.UiPart;
import com.deskmaster.coreui.api.UiScreen;
import com.deskmaster.coreui.api.UiViewer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class UiServiceTest {
    /** 보낸 화면·메시지·명령어를 기록하는 가짜 플랫폼. */
    static final class FakePlatform implements UiPlatform {
        final List<String> opened = new ArrayList<>();
        int lastSession;
        String lastJson;
        int closes;
        final List<String> warnings = new ArrayList<>();
        @Override public void sendOpen(UiViewer v, int s, String json) { lastSession = s; lastJson = json; opened.add(ScreenJson.fromJson(json).id()); }
        @Override public void sendClose(UiViewer v) { closes++; }
        @Override public void info(String m) {}
        @Override public void warn(String m) { warnings.add(m); }
    }

    static final class FakeViewer implements UiViewer {
        final UUID uuid = UUID.randomUUID();
        final List<String> messages = new ArrayList<>(), commands = new ArrayList<>();
        boolean admin;
        @Override public UUID uuid() { return uuid; }
        @Override public String name() { return "Steve"; }
        @Override public void sendMessage(String m) { messages.add(m); }
        @Override public void runCommand(String c) { commands.add(c); }
        @Override public boolean isAdmin() { return admin; }
    }

    @TempDir Path dir;
    FakePlatform platform;
    UiService service;
    FakeViewer steve;
    PartManager manager;

    /** 테스트용 파츠: 화면 두 개. */
    static final class TestPart implements UiPart {
        @Override public String id() { return "test"; }
        @Override public void enable(PartContext ctx) {
            ctx.placeholder("coins", (v, arg) -> "42");
            ctx.screen(UiScreen.builder("a").title("A {player}").openable(true)
                    .label(0, 0, 9, "{player} has {coins} coins")
                    .button("next", 0, 1, 3, "B", "open:b")
                    .input("msg", 3, 1, 3, "")
                    .button("say", 6, 1, 3, "say", "command:say {input:msg}")
                    .add(new com.deskmaster.coreui.api.UiComponent("toggle", "rain", 0, 2, 3, 1,
                            UiScreen.Builder.props("text", "rain", "action", "command:weather {value}", "on", "rain", "off", "clear")))
                    .build());
            ctx.screen(UiScreen.builder("b").title("B").openable(false)
                    .button("back", 0, 0, 3, "back", "back")
                    .button("x", 3, 0, 3, "x", "close")
                    .build());
        }
    }

    @BeforeEach
    void setUp() {
        platform = new FakePlatform();
        service = new UiService(platform);
        steve = new FakeViewer();
        manager = new PartManager(service, dir, List.of(new CorePart(), new TestPart()));
        manager.reload();
    }

    @Test
    void placeholdersAreResolvedBeforeSending() {
        assertTrue(service.open(steve, "a"));
        UiScreen sent = ScreenJson.fromJson(platform.lastJson);
        assertEquals("A Steve", sent.title());
        assertEquals("Steve has 42 coins", sent.components().get(0).str("text", ""));
        // 액션은 누를 때 바꾸므로 그대로
        assertEquals("command:say {input:msg}", sent.find("say").str("action", ""));
    }

    @Test
    void openBackAndClose() {
        service.open(steve, "a");
        service.handleClick(steve, platform.lastSession, "next", Map.of());
        assertEquals(List.of("a", "b"), platform.opened);
        service.handleClick(steve, platform.lastSession, "back", Map.of());
        assertEquals(List.of("a", "b", "a"), platform.opened);
        service.open(steve, "b");
        service.handleClick(steve, platform.lastSession, "x", Map.of());
        assertEquals(1, platform.closes);
    }

    @Test
    void inputValuesAreSubstitutedAndSanitized() {
        service.open(steve, "a");
        service.handleClick(steve, platform.lastSession, "say", Map.of("msg", "hi\nthere", "bogus", "x"));
        assertEquals(List.of("say hi there"), steve.commands);
    }

    @Test
    void toggleMapsOnOff() {
        service.open(steve, "a");
        service.handleClick(steve, platform.lastSession, "rain", Map.of("rain", "true"));
        service.handleClick(steve, platform.lastSession, "rain", Map.of("rain", "false"));
        assertEquals(List.of("weather rain", "weather clear"), steve.commands);
    }

    @Test
    void staleOrUnknownClicksAreIgnored() {
        service.open(steve, "a");
        int old = platform.lastSession;
        service.refresh(steve);
        service.handleClick(steve, old, "say", Map.of("msg", "x"));          // 오래된 세션
        service.handleClick(steve, platform.lastSession, "nope", Map.of());  // 없는 컴포넌트
        FakeViewer alex = new FakeViewer();
        service.handleClick(alex, platform.lastSession, "say", Map.of());    // 남의 세션
        assertTrue(steve.commands.isEmpty());
        assertTrue(alex.commands.isEmpty());
    }

    @Test
    void playersCannotOpenNonOpenableScreens() {
        assertFalse(service.openByPlayer(steve, "b"));
        steve.admin = true;
        assertTrue(service.openByPlayer(steve, "b"));
    }

    @Test
    void partsCanBeDisabledInConfig() throws Exception {
        Files.writeString(dir.resolve("parts.json"), "{\"test\": false}");
        manager.reload();
        assertFalse(service.screens().containsKey("a"));
        assertTrue(service.actionTypes().contains("open")); // core는 그대로
    }

    @Test
    void exampleConfigScreenIsWrittenAndLoaded() {
        assertTrue(Files.exists(dir.resolve("screens/example.json")));
        assertTrue(service.screens().containsKey("example"));
        assertTrue(platform.warnings.isEmpty(), platform.warnings.toString());
    }

    @Test
    void brokenConfigFileDoesNotBreakOthers() throws Exception {
        Files.writeString(dir.resolve("screens/broken.json"), "{ \"id\": \"broken\", \"components\": [ {\"type\":\"button\",\"x\":20} ] }");
        manager.reload();
        assertTrue(service.screens().containsKey("example"));
        assertFalse(service.screens().containsKey("broken"));
        assertEquals(1, platform.warnings.size());
    }

    @Test
    void jsonRoundTrip() {
        UiScreen s = UiScreen.builder("x").title("t").size(9, 2).openable(true)
                .iconButton("b", 0, 0, 3, "minecraft:stone", "text", "close").build();
        UiScreen back = ScreenJson.fromJson(ScreenJson.toJson(s, true));
        assertEquals(ScreenJson.toJson(s, false), ScreenJson.toJson(back, false));
    }
}
