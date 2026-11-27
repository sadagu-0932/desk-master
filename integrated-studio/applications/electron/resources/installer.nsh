; 통합 작업실 설치 파일
; 1) 이미 설치돼 있으면 업데이트로 안내한다(같은 appId 면 기존 위치에 덮어쓰고 사용자 데이터는 지우지 않는다).
; 2) "함께 설치할 프로그램" 화면(사용자 결정 2026-11-27):
;    - Python 3.11+ : 앱 기능 대부분이 파이썬 사이드카로 돈다. 이미 있으면 체크 해제, 없으면 체크된 채 고정(해제 불가).
;    - Prism Launcher: 인스턴스 만들기·실행. 이미 있으면 체크 해제, 없으면 체크(해제 가능 — 해제하면 앱의 런처 부분이 숨겨진다).
;    설치는 winget(Windows 패키지 관리자, 설치 파일 해시를 확인)으로 사용자 범위에. 실패하면 내려받기 페이지를 안내한다.
;    - Java(JDK 25, Eclipse Temurin): 서버(Forge 계열 run.bat 포함)·모드·플러그인 빌드용(사용자 요청 2026-11-27 "자바가 없어서 오류").
;      JDK 25 이상이 있으면 체크 해제, 없으면 체크(해제 가능). Temurin 은 컴퓨터 전체 설치라(winget 목록 Scope: machine) 관리자 확인 창이 뜬다.
;      winget 목록의 설치 옵션 ADDLOCAL=ALL 로 PATH·JAVA_HOME 도 설정된다.
;    조용한 설치(/S)에서는 화면 없이 "없는 것만 설치"한다.

!macro customHeader
  !ifndef BUILD_UNINSTALLER
    !include "nsDialogs.nsh"
    !include "LogicLib.nsh"
    Var StudioPyFound
    Var StudioPrismFound
    Var StudioInstallPy
    Var StudioInstallPrism
    Var StudioPyBox
    Var StudioPrismBox
    Var StudioJavaFound
    Var StudioInstallJava
    Var StudioJavaBox

    ; Python 3.11 이상이 있으면 1. py 런처 → python(가짜 Store 별칭은 실패) → 표준 설치 폴더 순서로 본다.
    Function StudioDetectPython
      StrCpy $StudioPyFound 0
      nsExec::ExecToStack 'cmd /c py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"'
      Pop $0
      Pop $1
      ${If} $0 == 0
        StrCpy $StudioPyFound 1
        Return
      ${EndIf}
      nsExec::ExecToStack 'cmd /c python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"'
      Pop $0
      Pop $1
      ${If} $0 == 0
        StrCpy $StudioPyFound 1
        Return
      ${EndIf}
      ${ForEach} $2 11 15 + 1
        ${If} ${FileExists} "$LOCALAPPDATA\Programs\Python\Python3$2\python.exe"
        ${OrIf} ${FileExists} "$PROGRAMFILES64\Python3$2\python.exe"
          StrCpy $StudioPyFound 1
          Return
        ${EndIf}
      ${Next}
    FunctionEnd

    Function StudioDetectPrism
      StrCpy $StudioPrismFound 0
      ${If} ${FileExists} "$LOCALAPPDATA\Programs\PrismLauncher\prismlauncher.exe"
      ${OrIf} ${FileExists} "$PROGRAMFILES64\PrismLauncher\prismlauncher.exe"
      ${OrIf} ${FileExists} "$PROGRAMFILES\PrismLauncher\prismlauncher.exe"
        StrCpy $StudioPrismFound 1
        Return
      ${EndIf}
      nsExec::ExecToStack 'cmd /c where prismlauncher'
      Pop $0
      Pop $1
      ${If} $0 == 0
        StrCpy $StudioPrismFound 1
      ${EndIf}
    FunctionEnd

    ; JDK 25 이상(javac 가 있는 것)이 있으면 1. 표준 설치 폴더 → JAVA_HOME → PATH 의 javac 버전 순서로 본다.
    Function StudioDetectJava
      StrCpy $StudioJavaFound 0
      ${ForEach} $2 25 30 + 1
        ${If} ${FileExists} "$PROGRAMFILES64\Eclipse Adoptium\jdk-$2*"
        ${OrIf} ${FileExists} "$PROGRAMFILES64\Microsoft\jdk-$2*"
        ${OrIf} ${FileExists} "$PROGRAMFILES64\Java\jdk-$2*"
        ${OrIf} ${FileExists} "$PROGRAMFILES64\Zulu\zulu-$2*"
          StrCpy $StudioJavaFound 1
          Return
        ${EndIf}
      ${Next}
      nsExec::ExecToStack 'cmd /c javac -version'
      Pop $0
      Pop $1
      ${If} $0 == 0
        StrCpy $2 $1 2 6          ; "javac 25.0.5" → "25"
        IntCmp $2 25 studio_java_ok studio_java_old studio_java_ok
        studio_java_ok:
          StrCpy $StudioJavaFound 1
        studio_java_old:
      ${EndIf}
    FunctionEnd

    Function StudioDepsPage
      !insertmacro MUI_HEADER_TEXT "함께 설치할 프로그램" "통합 작업실에 필요한 프로그램을 고르세요."
      nsDialogs::Create 1018
      Pop $0
      ${If} $0 == error
        Abort
      ${EndIf}
      ${NSD_CreateLabel} 0 0 100% 28u "체크한 프로그램을 winget(Windows 패키지 관리자)으로 함께 설치합니다. 이미 설치된 것은 체크가 꺼져 있습니다."
      Pop $0

      ${If} $StudioPyFound == 1
        ${NSD_CreateCheckbox} 0 34u 100% 12u "Python 3 (이미 설치됨 — 다시 설치하려면 체크)"
        Pop $StudioPyBox
        ${NSD_Uncheck} $StudioPyBox
      ${Else}
        ${NSD_CreateCheckbox} 0 34u 100% 12u "Python 3 (필수 — 없어서 함께 설치합니다)"
        Pop $StudioPyBox
        ${NSD_Check} $StudioPyBox
        EnableWindow $StudioPyBox 0
      ${EndIf}
      ${NSD_CreateLabel} 12u 47u 95% 20u "앱 기능 대부분(인스턴스·데이터팩 도구·서버 열기)이 파이썬으로 동작합니다."
      Pop $0

      ${If} $StudioPrismFound == 1
        ${NSD_CreateCheckbox} 0 72u 100% 12u "Prism Launcher (이미 설치됨 — 다시 설치하려면 체크)"
        Pop $StudioPrismBox
        ${NSD_Uncheck} $StudioPrismBox
      ${Else}
        ${NSD_CreateCheckbox} 0 72u 100% 12u "Prism Launcher (인스턴스 만들기·실행)"
        Pop $StudioPrismBox
        ${NSD_Check} $StudioPrismBox
      ${EndIf}
      ${NSD_CreateLabel} 12u 85u 95% 28u "로그인·자바·게임 파일 받기를 Prism 이 맡습니다. 설치하지 않으면 런처 부분(인스턴스 목록·실행)을 숨기고 코드 편집기·데이터팩 도구만 씁니다. 나중에 앱에서 설치할 수 있습니다."
      Pop $0

      ${If} $StudioJavaFound == 1
        ${NSD_CreateCheckbox} 0 116u 100% 12u "Java 25 JDK (이미 설치됨 — 다시 설치하려면 체크)"
        Pop $StudioJavaBox
        ${NSD_Uncheck} $StudioJavaBox
      ${Else}
        ${NSD_CreateCheckbox} 0 116u 100% 12u "Java 25 JDK (Eclipse Temurin — 서버·모드·플러그인 빌드)"
        Pop $StudioJavaBox
        ${NSD_Check} $StudioJavaBox
      ${EndIf}
      ${NSD_CreateLabel} 12u 129u 95% 20u "서버 실행과 모드·플러그인 빌드에 씁니다. 컴퓨터 전체에 설치돼 관리자 확인 창이 뜹니다."
      Pop $0
      nsDialogs::Show
    FunctionEnd

    Function StudioDepsLeave
      ${NSD_GetState} $StudioPyBox $StudioInstallPy
      ${NSD_GetState} $StudioPrismBox $StudioInstallPrism
      ${NSD_GetState} $StudioJavaBox $StudioInstallJava
      ${If} $StudioPyFound != 1
        StrCpy $StudioInstallPy ${BST_CHECKED}   ; 없으면 반드시 설치
      ${EndIf}
    FunctionEnd

    ; winget 으로 설치. $0 = 패키지 id, $1 = 이름, $2 = 직접 받을 페이지, $4 = 범위 인자(--scope user 또는 빈 값)
    Function StudioWinget
      DetailPrint "$1 설치 중(winget)…"
      nsExec::ExecToLog 'winget install --id $0 --exact --silent $4 --accept-package-agreements --accept-source-agreements'
      Pop $3
      ${If} $3 != 0
        MessageBox MB_YESNO|MB_ICONEXCLAMATION "$1 을(를) 자동으로 설치하지 못했습니다(winget 결과 $3).$\r$\n$\r$\n내려받기 페이지를 열까요? 설치한 뒤 통합 작업실을 다시 켜면 됩니다." IDNO +2
        ExecShell "open" "$2"
      ${Else}
        DetailPrint "$1 설치 완료"
      ${EndIf}
    FunctionEnd
  !endif
!macroend

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
  ; 함께 설치할 프로그램: 기본값 = 없는 것만 설치(조용한 설치도 이 값으로)
  Call StudioDetectPython
  Call StudioDetectPrism
  Call StudioDetectJava
  ${If} $StudioJavaFound == 1
    StrCpy $StudioInstallJava 0
  ${Else}
    StrCpy $StudioInstallJava 1
  ${EndIf}
  ${If} $StudioPyFound == 1
    StrCpy $StudioInstallPy 0
  ${Else}
    StrCpy $StudioInstallPy 1
  ${EndIf}
  ${If} $StudioPrismFound == 1
    StrCpy $StudioInstallPrism 0
  ${Else}
    StrCpy $StudioInstallPrism 1
  ${EndIf}
!macroend

!macro customPageAfterChangeDir
  Page custom StudioDepsPage StudioDepsLeave
!macroend

!macro customInstall
  ${If} $StudioInstallPy == 1
    StrCpy $0 "Python.Python.3.13"
    StrCpy $1 "Python 3"
    StrCpy $2 "https://www.python.org/downloads/windows/"
    StrCpy $4 "--scope user"
    Call StudioWinget
  ${EndIf}
  ${If} $StudioInstallPrism == 1
    StrCpy $0 "PrismLauncher.PrismLauncher"
    StrCpy $1 "Prism Launcher"
    StrCpy $2 "https://prismlauncher.org/download/"
    StrCpy $4 "--scope user"
    Call StudioWinget
  ${EndIf}
  ${If} $StudioInstallJava == 1
    StrCpy $0 "EclipseAdoptium.Temurin.25.JDK"
    StrCpy $1 "Java 25 JDK"
    StrCpy $2 "https://adoptium.net/temurin/releases/?version=25"
    StrCpy $4 ""
    Call StudioWinget
  ${EndIf}
!macroend
