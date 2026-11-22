; 통합 작업실 설치 파일: 이미 설치돼 있으면 업데이트로 안내한다.
; electron-builder는 같은 appId면 기존 설치 위치에 덮어쓰고(이전 버전 제거 후 설치), 사용자 데이터는 지우지 않는다.
!macro customInit
  ReadRegStr $0 HKCU "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion"
  StrCmp $0 "" studio_check_hklm studio_found
  studio_check_hklm:
    ReadRegStr $0 HKLM "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion"
    StrCmp $0 "" studio_done studio_found
  studio_found:
    StrCmp $0 "${VERSION}" studio_same
    MessageBox MB_OKCANCEL|MB_ICONINFORMATION "통합 작업실 $0 이(가) 이미 설치되어 있습니다.$\r$\n$\r$\n${VERSION}(으)로 업데이트합니다. 인스턴스, 월드, 설정은 그대로 남습니다.$\r$\n앱이 실행 중이면 닫아 주세요." IDOK studio_done
    Quit
  studio_same:
    MessageBox MB_OKCANCEL|MB_ICONQUESTION "같은 버전(${VERSION})이 이미 설치되어 있습니다. 다시 설치할까요?" IDOK studio_done
    Quit
  studio_done:
!macroend
