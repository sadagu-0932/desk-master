package com.deskmaster.coreui.client;

import com.deskmaster.coreui.api.UiComponent;
import com.deskmaster.coreui.api.UiScreen;
import com.deskmaster.coreui.fabric.net.UiPayloads;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * 서버가 보낸 {@link UiScreen}을 그리는 화면.
 * 격자 칸 하나 = CELL_W × CELL_H 픽셀. 화면이 좁으면 칸 너비를 줄인다.
 */
public final class PartScreen extends Screen {
    private static final int CELL_W = 26, CELL_H = 22, PAD = 8, TITLE_H = 14, MIN_CELL_W = 16;
    private static final int PANEL_BG = 0xE0101418, PANEL_BORDER = 0xFF5A6370, TITLE_COLOR = 0xFFFFFFFF;

    private final int session;
    private final UiScreen def;
    private final Map<String, Supplier<String>> values = new LinkedHashMap<>();
    private final List<Icon> icons = new ArrayList<>();
    private int left, top, panelW, panelH;
    /** 서버가 새 화면을 보내서 바뀌는 경우엔 닫힘 알림을 보내지 않는다. */
    private boolean replacedByServer = false;

    private record Icon(ItemStack stack, int x, int y) {}

    public PartScreen(int session, UiScreen def) {
        super(Component.literal(def.title()));
        this.session = session;
        this.def = def;
    }

    @Override
    protected void init() {
        values.clear();
        icons.clear();
        int cellW = Math.max(MIN_CELL_W, Math.min(CELL_W, (width - PAD * 2 - 8) / def.columns()));
        panelW = def.columns() * cellW + PAD * 2;
        panelH = def.rows() * CELL_H + PAD * 2 + TITLE_H;
        left = (width - panelW) / 2;
        top = Math.max(4, (height - panelH) / 2);

        for (UiComponent c : def.components()) {
            WidgetFactory f = WidgetRegistry.get(c.type());
            int x = left + PAD + c.x() * cellW + 1;
            int y = top + PAD + TITLE_H + c.y() * CELL_H + 1;
            int w = c.w() * cellW - 2;
            int h = c.h() * CELL_H - 2;
            if (f == null) {
                // 모르는 종류: 서버 쪽 파츠만 있고 클라이언트 위젯이 없는 경우
                WidgetRegistry.get("label").create(this, c.withProp("text", "§c[" + c.type() + "?]"), x, y, w, h);
                continue;
            }
            f.create(this, c, x, y, w, h);
        }
    }

    // ------------------------------------------------------------ 위젯 팩토리가 쓰는 도구

    public Font font() { return font; }

    public UiScreen definition() { return def; }

    public <T extends AbstractWidget> T addWidget(T widget) {
        return addRenderableWidget(widget);
    }

    /** 이 컴포넌트의 값을 클릭 때 서버로 보낸다 (입력칸, 토글 등). */
    public void bindValue(String componentId, Supplier<String> value) {
        if (componentId != null && !componentId.isEmpty()) values.put(componentId, value);
    }

    /** 아이템 아이콘을 (x, y)에 16×16으로 그린다. 위젯 위에 그려진다. */
    public void addIcon(String itemId, int x, int y) {
        Identifier id = Identifier.tryParse(itemId);
        var item = id == null ? null : BuiltInRegistries.ITEM.getOptional(id).orElse(null);
        icons.add(new Icon(new ItemStack(item == null ? Items.BARRIER : item), x, y));
    }

    /** 컴포넌트를 눌렀다고 서버에 알린다. 실제 동작은 서버가 정한다. */
    public void click(String componentId) {
        if (componentId == null || componentId.isEmpty()) return;
        Map<String, String> out = new HashMap<>();
        values.forEach((k, v) -> out.put(k, v.get()));
        ClientPlayNetworking.send(new UiPayloads.Click(session, componentId, out));
    }

    // ------------------------------------------------------------ 그리기

    @Override
    public void extractBackground(GuiGraphicsExtractor g, int mouseX, int mouseY, float delta) {
        super.extractBackground(g, mouseX, mouseY, delta);
        g.fill(left, top, left + panelW, top + panelH, PANEL_BG);
        g.outline(left, top, panelW, panelH, PANEL_BORDER);
    }

    @Override
    public void extractRenderState(GuiGraphicsExtractor g, int mouseX, int mouseY, float delta) {
        super.extractRenderState(g, mouseX, mouseY, delta);
        g.text(font, title, left + (panelW - font.width(title)) / 2, top + PAD, TITLE_COLOR, true);
        for (Icon i : icons) g.item(i.stack(), i.x(), i.y());
    }

    @Override
    public boolean isPauseScreen() {
        return false;
    }

    // ------------------------------------------------------------ 닫기

    void markReplacedByServer() {
        replacedByServer = true;
    }

    @Override
    public void onClose() {
        if (!replacedByServer && ClientPlayNetworking.canSend(UiPayloads.ClientClosed.TYPE)) {
            ClientPlayNetworking.send(new UiPayloads.ClientClosed(session));
        }
        super.onClose();
    }
}
