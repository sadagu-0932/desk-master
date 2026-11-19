package com.deskmaster.coreui.test;

import com.deskmaster.coreui.client.PartScreen;
import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.fabricmc.fabric.api.client.gametest.v1.context.TestSingleplayerContext;

/**
 * 실제 클라이언트로 화면 흐름을 확인한다:
 * 메인 메뉴 열기 → 카운터 화면으로 이동 → +10 → 서버가 새로 보낸 화면에 10이 보이는지.
 */
public final class CoreUiClientTest implements FabricClientGameTest {
    @Override
    public void runTest(ClientGameTestContext ctx) {
        try (TestSingleplayerContext world = ctx.worldBuilder().create()) {
            world.getConnection().waitForChunksRender();

            world.getServer().runCommand("ui open main @a");
            ctx.waitForScreen(PartScreen.class);
            ctx.takeScreenshot("coreui-main-menu");

            ctx.clickScreenButton("카운터 (예제 파츠)");
            ctx.waitFor(mc -> mc.gui.screen() instanceof PartScreen s && s.definition().id().equals("demo/counter"));
            ctx.clickScreenButton("+10");
            ctx.waitFor(mc -> mc.gui.screen() instanceof PartScreen s
                    && s.definition().components().stream().anyMatch(c -> c.str("text", "").equals("누른 횟수: 10")));
            ctx.takeScreenshot("coreui-counter");

            ctx.clickScreenButton("뒤로");
            ctx.waitFor(mc -> mc.gui.screen() instanceof PartScreen s && s.definition().id().equals("main"));
            ctx.clickScreenButton("예제 화면 (config/c…");
            ctx.waitFor(mc -> mc.gui.screen() instanceof PartScreen s && s.definition().id().equals("example"));
            ctx.takeScreenshot("coreui-config-example");

            world.getServer().runCommand("ui open status @a");
            ctx.waitFor(mc -> mc.gui.screen() instanceof PartScreen s && s.definition().id().equals("status"));
            ctx.takeScreenshot("coreui-status");
        }
    }
}
