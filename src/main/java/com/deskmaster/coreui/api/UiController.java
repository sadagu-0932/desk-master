package com.deskmaster.coreui.api;

/** 파츠가 화면을 열고 닫을 때 쓰는 기능. */
public interface UiController {
    /** 화면을 연다. 지금 열린 화면은 '뒤로 가기' 기록에 쌓인다. */
    boolean open(UiViewer viewer, String screenId);
    /** 지금 화면을 다시 만들어 보낸다 (값이 바뀐 동적 화면 새로고침). */
    void refresh(UiViewer viewer);
    /** 이전 화면으로. 기록이 없으면 닫는다. */
    void back(UiViewer viewer);
    void close(UiViewer viewer);
}
