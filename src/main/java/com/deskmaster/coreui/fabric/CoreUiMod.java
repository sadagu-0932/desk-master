package com.deskmaster.coreui.fabric;

import com.deskmaster.coreui.api.UiPart;
import com.deskmaster.coreui.core.CorePart;
import com.deskmaster.coreui.core.PartManager;
import com.deskmaster.coreui.core.UiService;
import com.deskmaster.coreui.fabric.net.UiPayloads;
import com.deskmaster.coreui.fabric.parts.DemoPart;
import com.deskmaster.coreui.fabric.parts.MainMenuPart;
import com.deskmaster.coreui.fabric.parts.StatusPart;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.resources.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;

public final class CoreUiMod implements ModInitializer {
    public static final String MOD_ID = "coreui";
    /** 다른 모드가 파츠를 붙일 때 쓰는 entrypoint 이름. */
    public static final String PART_ENTRYPOINT = "coreui:part";
    public static final Logger LOG = LoggerFactory.getLogger("Core UI");

    private static UiService service;
    private static PartManager parts;

    public static Identifier id(String path) {
        return Identifier.fromNamespaceAndPath(MOD_ID, path);
    }

    public static UiService service() { return service; }
    public static PartManager parts() { return parts; }

    @Override
    public void onInitialize() {
        UiPayloads.register();
        service = new UiService(new FabricPlatform(LOG));
        parts = new PartManager(service, FabricLoader.getInstance().getConfigDir().resolve(MOD_ID), collectParts());

        ServerLifecycleEvents.SERVER_STARTING.register(server -> parts.reload());
        ServerLifecycleEvents.SERVER_STOPPED.register(server -> service.clearSessions());
        ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> service.onDisconnect(handler.player.getUUID()));

        ServerPlayNetworking.registerGlobalReceiver(UiPayloads.Click.TYPE, (payload, ctx) ->
                service.handleClick(new FabricViewer(ctx.player()), payload.session(), payload.componentId(), payload.values()));
        ServerPlayNetworking.registerGlobalReceiver(UiPayloads.ClientClosed.TYPE, (payload, ctx) ->
                service.onClientClosed(new FabricViewer(ctx.player()), payload.session()));
        ServerPlayNetworking.registerGlobalReceiver(UiPayloads.RequestOpen.TYPE, (payload, ctx) ->
                service.openByPlayer(new FabricViewer(ctx.player()), payload.screenId()));

        CommandRegistrationCallback.EVENT.register((dispatcher, buildContext, selection) -> UiCommands.register(dispatcher));
    }

    /** 기본 파츠 + 다른 모드가 entrypoint로 붙인 파츠. */
    private static List<UiPart> collectParts() {
        List<UiPart> list = new ArrayList<>(List.of(new CorePart(), new MainMenuPart(), new StatusPart(), new DemoPart()));
        for (var container : FabricLoader.getInstance().getEntrypointContainers(PART_ENTRYPOINT, UiPart.class)) {
            try {
                list.add(container.getEntrypoint());
                LOG.info("외부 파츠 발견: {} (모드 {})", container.getEntrypoint().id(), container.getProvider().getMetadata().getId());
            } catch (RuntimeException ex) {
                LOG.error("모드 {}의 파츠를 불러오지 못함", container.getProvider().getMetadata().getId(), ex);
            }
        }
        return list;
    }
}
