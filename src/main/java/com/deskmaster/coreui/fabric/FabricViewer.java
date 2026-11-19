package com.deskmaster.coreui.fabric;

import com.deskmaster.coreui.api.UiViewer;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.permissions.Permissions;

import java.util.UUID;

/** {@link UiViewer}의 Fabric 구현. 마인크래프트 기능이 필요한 파츠는 {@link #player()}로 꺼내 쓴다. */
public record FabricViewer(ServerPlayer player) implements UiViewer {

    @Override public UUID uuid() { return player.getUUID(); }
    @Override public String name() { return player.getScoreboardName(); }
    @Override public void sendMessage(String message) { player.sendSystemMessage(Component.literal(message)); }

    @Override
    public void runCommand(String command) {
        var server = player.level().getServer();
        if (server == null) return;
        server.getCommands().performPrefixedCommand(player.createCommandSourceStack(), command);
    }

    @Override
    public boolean isAdmin() {
        return player.permissions().hasPermission(Permissions.COMMANDS_GAMEMASTER);
    }

    /** 파츠 코드에서: {@code FabricViewer.playerOf(ctx.viewer())}. Fabric이 아니면 null. */
    public static ServerPlayer playerOf(UiViewer viewer) {
        return viewer instanceof FabricViewer fv ? fv.player() : null;
    }
}
