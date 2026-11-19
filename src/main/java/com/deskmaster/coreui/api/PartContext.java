package com.deskmaster.coreui.api;

/** 파츠가 코어에 무언가를 등록할 때 쓰는 창구. */
public interface PartContext {
    String partId();

    /** 고정 화면 등록. */
    void screen(UiScreen screen);

    /** 동적 화면 등록. openable이 true면 일반 플레이어도 직접 열 수 있다. */
    void screen(String screenId, boolean openable, ScreenProvider provider);

    /** 액션 등록. type이 "shop:buy"면 버튼 action에 "shop:buy:diamond"처럼 쓴다. */
    void action(String type, ActionHandler handler);

    /** 자리표시자 등록. name이 "coins"면 글자에 {coins} 또는 {coins:인자}로 쓴다. */
    void placeholder(String name, PlaceholderResolver resolver);

    /** 화면을 열고 닫는 기능. */
    UiController ui();

    void log(String message);
}
