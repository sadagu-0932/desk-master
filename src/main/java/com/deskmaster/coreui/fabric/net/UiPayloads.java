package com.deskmaster.coreui.fabric.net;

import com.deskmaster.coreui.fabric.CoreUiMod;
import io.netty.buffer.ByteBuf;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;

import java.util.HashMap;
import java.util.Map;

/** 서버 ↔ 클라이언트 패킷. 서버는 화면 정의(JSON)를 보내고, 클라이언트는 클릭을 보낸다. */
public final class UiPayloads {
    private UiPayloads() {}

    private static final int MAX_SCREEN_JSON = 262_144;
    private static final StreamCodec<ByteBuf, String> SHORT_STRING = ByteBufCodecs.stringUtf8(256);

    /** 서버 → 클라: 화면 열기. */
    public record OpenScreen(int session, String json) implements CustomPacketPayload {
        public static final Type<OpenScreen> TYPE = new Type<>(CoreUiMod.id("open_screen"));
        public static final StreamCodec<ByteBuf, OpenScreen> CODEC = StreamCodec.composite(
                ByteBufCodecs.VAR_INT, OpenScreen::session,
                ByteBufCodecs.stringUtf8(MAX_SCREEN_JSON), OpenScreen::json,
                OpenScreen::new);
        @Override public Type<OpenScreen> type() { return TYPE; }
    }

    /** 서버 → 클라: 화면 닫기. */
    public record CloseScreen() implements CustomPacketPayload {
        public static final CloseScreen INSTANCE = new CloseScreen();
        public static final Type<CloseScreen> TYPE = new Type<>(CoreUiMod.id("close_screen"));
        public static final StreamCodec<ByteBuf, CloseScreen> CODEC = StreamCodec.unit(INSTANCE);
        @Override public Type<CloseScreen> type() { return TYPE; }
    }

    /** 클라 → 서버: 컴포넌트를 눌렀음 + 화면 안 입력값들. */
    public record Click(int session, String componentId, Map<String, String> values) implements CustomPacketPayload {
        public static final Type<Click> TYPE = new Type<>(CoreUiMod.id("click"));
        public static final StreamCodec<ByteBuf, Click> CODEC = StreamCodec.composite(
                ByteBufCodecs.VAR_INT, Click::session,
                SHORT_STRING, Click::componentId,
                ByteBufCodecs.map(HashMap::new, SHORT_STRING, SHORT_STRING, 64), Click::values,
                Click::new);
        @Override public Type<Click> type() { return TYPE; }
    }

    /** 클라 → 서버: ESC 등으로 창을 닫았음. */
    public record ClientClosed(int session) implements CustomPacketPayload {
        public static final Type<ClientClosed> TYPE = new Type<>(CoreUiMod.id("client_closed"));
        public static final StreamCodec<ByteBuf, ClientClosed> CODEC =
                ByteBufCodecs.VAR_INT.map(ClientClosed::new, ClientClosed::session);
        @Override public Type<ClientClosed> type() { return TYPE; }
    }

    /** 클라 → 서버: 단축키로 화면을 열어 달라. */
    public record RequestOpen(String screenId) implements CustomPacketPayload {
        public static final Type<RequestOpen> TYPE = new Type<>(CoreUiMod.id("request_open"));
        public static final StreamCodec<ByteBuf, RequestOpen> CODEC =
                SHORT_STRING.map(RequestOpen::new, RequestOpen::screenId);
        @Override public Type<RequestOpen> type() { return TYPE; }
    }

    public static void register() {
        PayloadTypeRegistry.clientboundPlay().register(OpenScreen.TYPE, OpenScreen.CODEC);
        PayloadTypeRegistry.clientboundPlay().register(CloseScreen.TYPE, CloseScreen.CODEC);
        PayloadTypeRegistry.serverboundPlay().register(Click.TYPE, Click.CODEC);
        PayloadTypeRegistry.serverboundPlay().register(ClientClosed.TYPE, ClientClosed.CODEC);
        PayloadTypeRegistry.serverboundPlay().register(RequestOpen.TYPE, RequestOpen.CODEC);
    }
}
