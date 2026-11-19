package com.deskmaster.coreui.fabric;

import com.deskmaster.coreui.api.UiViewer;
import com.deskmaster.coreui.core.UiPlatform;
import com.deskmaster.coreui.fabric.net.UiPayloads;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;

/** 코어 → Fabric: 화면 정의를 패킷으로 보낸다. */
final class FabricPlatform implements UiPlatform {
    private final Logger log;

    FabricPlatform(Logger log) { this.log = log; }

    @Override
    public void sendOpen(UiViewer viewer, int sessionId, String json) {
        ServerPlayer p = FabricViewer.playerOf(viewer);
        if (p == null) return;
        if (!ServerPlayNetworking.canSend(p, UiPayloads.OpenScreen.TYPE)) {
            // 바닐라 클라이언트: 나중에 상자 GUI 렌더러를 붙일 자리
            viewer.sendMessage("이 화면을 보려면 클라이언트에도 Core UI 모드가 필요합니다.");
            return;
        }
        ServerPlayNetworking.send(p, new UiPayloads.OpenScreen(sessionId, json));
    }

    @Override
    public void sendClose(UiViewer viewer) {
        ServerPlayer p = FabricViewer.playerOf(viewer);
        if (p != null && ServerPlayNetworking.canSend(p, UiPayloads.CloseScreen.TYPE)) {
            ServerPlayNetworking.send(p, UiPayloads.CloseScreen.INSTANCE);
        }
    }

    @Override public void info(String message) { log.info(message); }
    @Override public void warn(String message) { log.warn(message); }
}
