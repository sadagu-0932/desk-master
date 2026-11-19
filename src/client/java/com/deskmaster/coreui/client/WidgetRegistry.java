package com.deskmaster.coreui.client;

import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.components.StringWidget;
import net.minecraft.client.gui.components.Tooltip;
import net.minecraft.network.chat.Component;

import java.util.HashMap;
import java.util.Map;

/** 컴포넌트 종류 → 그리는 방법. 기본 위젯: label, button, toggle, input, icon. */
public final class WidgetRegistry {
    private static final Map<String, WidgetFactory> FACTORIES = new HashMap<>();

    private WidgetRegistry() {}

    public static void register(String type, WidgetFactory factory) {
        FACTORIES.put(type, factory);
    }

    public static WidgetFactory get(String type) {
        return FACTORIES.get(type);
    }

    static void registerDefaults() {
        register("label", (s, c, x, y, w, h) -> {
            var font = s.font();
            int ty = y + (h - font.lineHeight) / 2;
            s.addWidget(new StringWidget(x + 2, ty, w - 4, font.lineHeight, Component.literal(c.str("text", "")), font)
                    .setMaxWidth(w - 4));
        });

        register("button", (s, c, x, y, w, h) -> {
            boolean hasIcon = c.props().has("icon");
            // 아이콘이 있으면 왼쪽 18px를 비워 두고 아이콘을 그 위에 그린다
            String text = c.str("text", "");
            Button b = Button.builder(Component.literal(text), btn -> s.click(c.id()))
                    .bounds(x, y, w, h)
                    .build();
            tooltip(b, c.str("tooltip", null));
            s.addWidget(b);
            if (hasIcon) s.addIcon(c.str("icon", ""), x + 2, y + (h - 16) / 2);
        });

        register("toggle", (s, c, x, y, w, h) -> {
            String text = c.str("text", "");
            boolean[] state = {Boolean.parseBoolean(c.str("value", "false"))};
            Button b = Button.builder(toggleLabel(text, state[0]), btn -> {
                state[0] = !state[0];
                btn.setMessage(toggleLabel(text, state[0]));
                s.click(c.id());
            }).bounds(x, y, w, h).build();
            tooltip(b, c.str("tooltip", null));
            s.bindValue(c.id(), () -> String.valueOf(state[0]));
            s.addWidget(b);
        });

        register("input", (s, c, x, y, w, h) -> {
            EditBox box = new EditBox(s.font(), x + 1, y + 1, w - 2, h - 2, Component.literal(c.str("hint", "")));
            box.setMaxLength(Math.min(256, c.integer("max", 256)));
            box.setValue(c.str("value", ""));
            String hint = c.str("hint", "");
            if (!hint.isEmpty()) box.setHint(Component.literal(hint));
            s.bindValue(c.id(), box::getValue);
            s.addWidget(box);
        });

        register("icon", (s, c, x, y, w, h) -> s.addIcon(c.str("item", "minecraft:barrier"), x + (w - 16) / 2, y + (h - 16) / 2));
    }

    private static Component toggleLabel(String text, boolean on) {
        return Component.literal(text + ": " + (on ? "§a켜짐" : "§c꺼짐"));
    }

    private static void tooltip(Button b, String text) {
        if (text != null && !text.isEmpty()) b.setTooltip(Tooltip.create(Component.literal(text)));
    }
}
