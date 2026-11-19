package com.deskmaster.coreui.fabric;

import com.deskmaster.coreui.api.UiPart;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import com.mojang.brigadier.suggestion.SuggestionProvider;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.commands.SharedSuggestionProvider;
import net.minecraft.commands.arguments.EntityArgument;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.permissions.Permissions;

/**
 * /ui open <화면> [대상]   화면 열기 (대상 지정은 관리자만)
 * /ui close               닫기
 * /ui list                열 수 있는 화면 목록
 * /ui parts               파츠 목록 (관리자)
 * /ui reload              설정·파츠 다시 읽기 (관리자)
 */
final class UiCommands {
    private UiCommands() {}

    private static final SuggestionProvider<CommandSourceStack> SCREENS = (ctx, builder) -> {
        boolean admin = isAdmin(ctx.getSource());
        return SharedSuggestionProvider.suggest(
                CoreUiMod.service().screens().entrySet().stream()
                        .filter(e -> admin || e.getValue().openable())
                        .map(e -> e.getKey()), builder);
    };

    static void register(CommandDispatcher<CommandSourceStack> d) {
        d.register(Commands.literal("ui")
                .then(Commands.literal("open")
                        .then(Commands.argument("screen", StringArgumentType.string()).suggests(SCREENS)
                                .executes(UiCommands::openSelf)
                                .then(Commands.argument("targets", EntityArgument.players())
                                        .requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
                                        .executes(UiCommands::openOthers))))
                .then(Commands.literal("close").executes(ctx -> {
                    CoreUiMod.service().close(new FabricViewer(ctx.getSource().getPlayerOrException()));
                    return 1;
                }))
                .then(Commands.literal("list").executes(UiCommands::list))
                .then(Commands.literal("parts")
                        .requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
                        .executes(UiCommands::parts))
                .then(Commands.literal("reload")
                        .requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
                        .executes(ctx -> {
                            CoreUiMod.parts().reload();
                            ctx.getSource().sendSuccess(() -> Component.literal("Core UI 설정과 파츠를 다시 읽었습니다."), true);
                            return 1;
                        })));
    }

    private static boolean isAdmin(CommandSourceStack src) {
        return src.permissions().hasPermission(Permissions.COMMANDS_GAMEMASTER);
    }

    private static int openSelf(CommandContext<CommandSourceStack> ctx) throws CommandSyntaxException {
        ServerPlayer p = ctx.getSource().getPlayerOrException();
        return CoreUiMod.service().openByPlayer(new FabricViewer(p), StringArgumentType.getString(ctx, "screen")) ? 1 : 0;
    }

    private static int openOthers(CommandContext<CommandSourceStack> ctx) throws CommandSyntaxException {
        String screen = StringArgumentType.getString(ctx, "screen");
        if (!CoreUiMod.service().screens().containsKey(screen)) {
            ctx.getSource().sendFailure(Component.literal("없는 화면입니다: " + screen));
            return 0;
        }
        int n = 0;
        for (ServerPlayer p : EntityArgument.getPlayers(ctx, "targets")) {
            if (CoreUiMod.service().open(new FabricViewer(p), screen)) n++;
        }
        int count = n;
        ctx.getSource().sendSuccess(() -> Component.literal(count + "명에게 '" + screen + "' 화면을 열었습니다."), true);
        return n;
    }

    private static int list(CommandContext<CommandSourceStack> ctx) {
        boolean admin = isAdmin(ctx.getSource());
        StringBuilder sb = new StringBuilder("화면 목록:");
        CoreUiMod.service().screens().forEach((id, e) -> {
            if (admin || e.openable()) {
                sb.append("\n - ").append(id).append(" [").append(e.partId()).append("]");
                if (admin && !e.openable()) sb.append(" (관리자만)");
            }
        });
        ctx.getSource().sendSuccess(() -> Component.literal(sb.toString()), false);
        return 1;
    }

    private static int parts(CommandContext<CommandSourceStack> ctx) {
        StringBuilder sb = new StringBuilder("파츠 목록 (config/coreui/parts.json 에서 켜고 끔):");
        for (UiPart p : CoreUiMod.parts().parts()) {
            sb.append("\n ").append(CoreUiMod.parts().isEnabled(p) ? "[켜짐] " : "[꺼짐] ")
                    .append(p.id()).append(" - ").append(p.description());
        }
        sb.append("\n액션: ").append(String.join(", ", CoreUiMod.service().actionTypes()));
        ctx.getSource().sendSuccess(() -> Component.literal(sb.toString()), false);
        return 1;
    }
}
