package com.deskmaster.coreui.fabric.parts;

import com.deskmaster.coreui.api.PartContext;
import com.deskmaster.coreui.api.UiPart;
import com.deskmaster.coreui.api.UiScreen;
import com.deskmaster.coreui.fabric.FabricViewer;
import net.minecraft.server.level.ServerPlayer;

/**
 * 마인크래프트 정보를 쓰는 파츠 예제. {@link FabricViewer#playerOf}로 ServerPlayer를 꺼내
 * 체력·배고픔·좌표를 동적 화면으로 보여준다. 플랫폼 전용 파츠는 이렇게 만든다.
 */
public final class StatusPart implements UiPart {
    @Override public String id() { return "status"; }
    @Override public String description() { return "내 상태 (체력, 배고픔, 좌표)"; }

    @Override
    public void enable(PartContext ctx) {
        ctx.placeholder("health", (v, arg) -> {
            ServerPlayer p = FabricViewer.playerOf(v);
            return p == null ? "?" : String.format("%.1f / %.0f", p.getHealth(), p.getMaxHealth());
        });
        ctx.placeholder("food", (v, arg) -> {
            ServerPlayer p = FabricViewer.playerOf(v);
            return p == null ? "?" : String.valueOf(p.getFoodData().getFoodLevel());
        });
        ctx.placeholder("pos", (v, arg) -> {
            ServerPlayer p = FabricViewer.playerOf(v);
            return p == null ? "?" : p.blockPosition().getX() + ", " + p.blockPosition().getY() + ", " + p.blockPosition().getZ();
        });

        ctx.screen(UiScreen.builder("status")
                .title("내 상태")
                .size(9, 4)
                .openable(true)
                .icon(0, 0, "minecraft:golden_apple")
                .label(1, 0, 8, "체력: {health}")
                .icon(0, 1, "minecraft:cooked_beef")
                .label(1, 1, 8, "배고픔: {food} / 20")
                .icon(0, 2, "minecraft:compass")
                .label(1, 2, 8, "좌표: {pos}")
                .button("refresh", 0, 3, 3, "새로고침", "refresh")
                .button("back", 6, 3, 3, "뒤로", "back")
                .build());
    }
}
