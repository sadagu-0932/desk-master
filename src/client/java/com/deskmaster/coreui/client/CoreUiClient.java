package com.deskmaster.coreui.client;

import com.deskmaster.coreui.core.ScreenJson;
import com.deskmaster.coreui.fabric.CoreUiMod;
import com.deskmaster.coreui.fabric.net.UiPayloads;
import com.deskmaster.coreui.fabric.parts.MainMenuPart;
import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keymapping.v1.KeyMappingHelper;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.KeyMapping;
import net.minecraft.network.chat.Component;

public final class CoreUiClient implements ClientModInitializer {
    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(CoreUiMod.id("main"));
    private static KeyMapping openMenu;

    @Override
    public void onInitializeClient() {
        WidgetRegistry.registerDefaults();

        openMenu = KeyMappingHelper.registerKeyMapping(
                new KeyMapping("key.coreui.open_menu", InputConstants.Type.KEYBOARD, InputConstants.KEY_U, CATEGORY));

        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            while (openMenu.consumeClick()) {
                if (client.player != null && ClientPlayNetworking.canSend(UiPayloads.RequestOpen.TYPE)) {
                    ClientPlayNetworking.send(new UiPayloads.RequestOpen(MainMenuPart.SCREEN_ID));
                }
            }
        });

        ClientPlayNetworking.registerGlobalReceiver(UiPayloads.OpenScreen.TYPE, (payload, ctx) -> {
            try {
                var def = ScreenJson.fromJson(payload.json());
                if (ctx.client().gui.screen() instanceof PartScreen old) old.markReplacedByServer();
                ctx.client().gui.setScreen(new PartScreen(payload.session(), def));
            } catch (RuntimeException ex) {
                CoreUiMod.LOG.error("서버가 보낸 화면을 읽지 못함", ex);
                if (ctx.player() != null) ctx.player().sendSystemMessage(Component.literal("§c화면을 표시하지 못했습니다: " + ex.getMessage()));
            }
        });

        ClientPlayNetworking.registerGlobalReceiver(UiPayloads.CloseScreen.TYPE, (payload, ctx) -> {
            if (ctx.client().gui.screen() instanceof PartScreen s) {
                s.markReplacedByServer();
                ctx.client().gui.setScreen(null);
            }
        });
    }
}
