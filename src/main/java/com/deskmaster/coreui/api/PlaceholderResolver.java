package com.deskmaster.coreui.api;

/**
 * 글자 안의 {이름} 또는 {이름:인자} 자리표시자를 값으로 바꾼다.
 * 모르는 자리표시자면 null을 돌려준다.
 */
@FunctionalInterface
public interface PlaceholderResolver {
    String resolve(UiViewer viewer, String argument);
}
