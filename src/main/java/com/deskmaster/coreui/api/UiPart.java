package com.deskmaster.coreui.api;

/**
 * 코어에 붙는 파츠.
 *
 * <p>다른 모드도 파츠를 만들 수 있다. fabric.mod.json에 다음처럼 적으면 된다:
 * <pre>
 * "entrypoints": { "coreui:part": ["com.example.MyPart"] }
 * </pre>
 * 각 파츠는 config/coreui/parts.json에서 켜고 끌 수 있다.
 */
public interface UiPart {
    /** 파츠 ID. 소문자. 액션·화면 이름 앞에 붙이는 걸 권장한다 ("shop:buy", "shop/main"). */
    String id();

    /** 짧은 설명 (/ui parts 목록에 표시). */
    default String description() { return ""; }

    /** 파츠가 켜질 때 한 번. 여기서 화면·액션·자리표시자를 등록한다. */
    void enable(PartContext ctx);

    /** 파츠가 꺼질 때 (리로드 포함). 등록한 것들은 코어가 알아서 지운다. */
    default void disable() {}
}
