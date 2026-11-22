# 통합 작업실 — 마인크래프트 실행 · 데이터팩 · 모드 · 리소스팩

마인크래프트 Java 인스턴스를 관리·실행하고, 같은 창에서 데이터팩·Fabric 모드·리소스팩을 만들 수 있는
**VS Code 같은 데스크톱 앱**이다. Claude Code가 앱 안에 패널로 들어가 파일을 직접 만들고 고친다.

- 기획·동작 명세(전체): https://claude.ai/artifact/2X2sZPebRGrvKg7LQLk8EM
- 디자인 목업(작업실·리소스팩·홈 3화면): https://claude.ai/artifact/Hi8GPEAUbLWhcco7L6QM2r
- 대상 게임 버전: Java 26.x (현재 26.3), 로더는 Fabric 우선

**개인 사용 전용 앱이다(배포 계획 없음).** 이 파일은 이 저장소에서 일하는 Claude Code를 위한 지시서다. 아래 "작업 규칙"을 항상 지킨다.

---

## 1. 기술 스택 (확정)

| 영역 | 사용 기술 | 이유 |
|---|---|---|
| 앱 뼈대 | **Eclipse Theia** (데스크톱, electron-builder로 패키징) | VS Code 같은 화면(파일 트리, 탭, 명령 팔레트, 설정, 단축키)과 VS Code 확장 호환(Open VSX)을 그대로 얻는다 |
| Claude 패널 | **`@theia/ai-claude-code`** (Theia의 네이티브 Claude Code 연동) | 세션, 변경 묶음(change set), diff 보기가 이미 구현돼 있다. 사용자의 PC에 설치된 `claude` CLI를 쓴다 |
| 데이터팩 자동완성·디버거·게임 콘솔 | **CommandCrafter** VS Code 확장(Open VSX: `Papierkorb2292.commandcrafter`) + 같은 이름의 Fabric 모드 | 켜진 게임에 LSP/DAP로 붙어 그 버전 그대로의 문법을 쓴다. /reload, 리소스 다시 불러오기, 명령 실행, 로그 보기 포함. MIT |
| 게임 꺼져 있을 때 자동완성 | Spyglass 언어 서버(`@spyglassmc/language-server`) 또는 데이터 생성기의 `commands.json` 기반 자체 완성 | CommandCrafter는 게임이 켜져 있어야 동작한다 |
| 게임 설치·실행 | **Python 보조 프로세스** + `minecraft-launcher-lib` | 버전·Fabric 설치, 실행 명령 생성, (나중에) MS 로그인. Theia 백엔드가 자식 프로세스로 띄우고 stdin/stdout JSON-RPC로 통신 |
| 리소스팩 편집 | Texel(https://texel-neontree.vercel.app/)을 Theia 위젯으로 옮김 | 텍스처·텍스트·사운드·팩 설정 탭. 소스를 받기 전까지는 웹뷰로 띄운다 |

Theia 확장은 TypeScript로 작성한다. Python 쪽은 `sidecar/` 아래에만 둔다.

---

## 2. 폴더 구조 (목표)

```
/
  CLAUDE.md
  applications/electron/        Theia 데스크톱 앱 (branding, 번들 확장 목록, electron-builder 설정)
  theia-extensions/
    launcher-core/              인스턴스 모델, 사이드카 연결, 실행/중지, 로그 채널
    launcher-ui/                인스턴스 뷰, 실행 대상 선택기, 상태 표시줄, 홈 화면
    datapack-tools/             데이터팩 템플릿, 월드 동기화, .zip 내보내기
    resourcepack-editor/        Texel 위젯
    theme/                      색 테마(아래 4장)
  sidecar/
    main.py                     JSON-RPC 서버 (stdin/stdout)
    instances.py runner.py ...  minecraft-launcher-lib 래퍼
    requirements.txt
  data/ (실행 시 생성, git 제외)
    instances/<id>/             게임 폴더 (.git, CLAUDE.md, datapacks, mods, resourcepacks, saves)
    reports/<버전>/             데이터 생성기 결과 캐시
```

---

## 3. 단계별 작업 (순서대로, 단계마다 완료 조건 확인 후 커밋)

### M0. 뼈대
- **먼저 개발 도구 확인**(없으면 사용자에게 설치 방법을 안내하고 멈춘다): Node.js 22~24(권장 24), npm, Python 3, git 2.11 이상, Windows용 Visual Studio Build Tools(C++ 데스크톱 개발 워크로드 — native 모듈 빌드용, Node 버전에 맞는 것), `claude` CLI. 각 버전을 출력해서 보여준다.
- Theia 데스크톱 앱을 만들고 실행되게 한다. 제품 이름은 **통합 작업실**(영문 표기 Integrated Studio, 코드·패키지 이름은 `integrated-studio`). 부제: "마인크래프트 실행 · 데이터팩 · 모드 · 리소스팩".
- 기본 번들에서 쓰지 않는 확장은 뺀다.
- **완료 조건**: 앱이 뜨고, 폴더를 열면 파일 트리·에디터·명령 팔레트가 동작한다.

### M1. 사이드카와 인스턴스
- `sidecar/main.py`: `list_instances`, `create_instance(name, version, loader)`, `install(id)`, `launch(id)`, `stop(id)` 메서드. 진행률과 게임 로그는 알림 메시지로 흘려보낸다.
- 실행은 우선 **오프라인 테스트 모드**(가짜 닉네임)만. 인스턴스마다 `--gameDir`를 분리한다.
- 인스턴스 표시 이름과 폴더 이름을 분리한다(폴더는 `inst_<짧은 id>`). 특수문자 이름 오류 방지.
- **완료 조건**: 명령 팔레트에서 인스턴스를 만들고 바닐라와 Fabric 26.3을 실행·중지할 수 있다.

### M2. 작업실 UI
- 사이드바 아래쪽에 "인스턴스" 뷰: 실행 상태 점, ▶/■, 작업실에서 열기(그 인스턴스 폴더를 작업 공간으로).
- "작업" 뷰: 로컬 서버 실행(F6), 모드 빌드 후 테스트(F7), 리소스팩 적용(F8), 데이터팩 .zip 내보내기.
- 상단 실행 대상 선택기 + 재시작/중지, 하단 패널 "게임 로그" 탭(레벨별 색), 상태 표시줄(인스턴스·버전·로더, 오류 수, Claude 상태).
- 단축키는 VS Code와 같게: F5 실행, Shift+F5 중지, Ctrl+J 패널.
- **완료 조건**: 목업의 작업실 화면과 같은 배치로 실행·중지·로그가 동작한다.

### M3. CommandCrafter 연동
- CommandCrafter VS Code 확장을 앱에 번들한다.
- Fabric 인스턴스를 만들 때 CommandCrafter 모드를 Modrinth에서 버전에 맞게 받아 `mods/`에 넣는다(사용자에게 켜고 끌 수 있게).
- 인스턴스마다 서로 다른 서비스 포트를 config에 쓴다(기본 52853). 실행 중 인스턴스에 자동 연결.
- **보안**: 이 모드는 `ServerSocket(port)`로 모든 인터페이스에 연다. 사용자에게 알리고, 가능하면 localhost 바인딩 옵션을 업스트림에 기여하거나 방화벽 안내를 띄운다.
- 상단 /reload 버튼과 "명령어 콘솔"을 CommandCrafter의 `runCommand`·`reloadResources`에 연결한다.
- **완료 조건**: 게임을 켠 상태에서 `.mcfunction` 자동완성·오류 표시가 되고, 버튼으로 /reload가 들어간다.

### M4. Claude 패널
- `@theia/ai-claude-code`를 넣고 작업 디렉터리를 현재 인스턴스 폴더로 맞춘다.
- 인스턴스를 만들 때 `git init`하고, 그 폴더에 인스턴스용 `CLAUDE.md`(게임 버전, 로더, 데이터팩 경로 규칙, "datapacks 밖 수정 금지" 등)를 생성한다.
- 작업 종류 칩(데이터팩 / Fabric 모드 / 리소스팩)에 따라 허용 도구와 추가 지시를 바꾼다. Bash는 기본 금지, 모드는 `./gradlew build`만 허용.
- 변경 적용 후 "적용 후 /reload" 동작을 붙인다.
- **완료 조건**: 패널에 "모닥불 5칸 안에 5초 있으면 보상"을 요청하면 함수 파일이 생기고, diff 확인 → 적용 → 게임에서 /reload까지 이어진다.

### M5. 데이터팩 도구
- 새 데이터팩 템플릿(`pack.mcmeta` + `data/<ns>/function/`), 작업용 원본 → 선택한 월드 `saves/<월드>/datapacks/` 동기화, .zip 내보내기(루트에 pack.mcmeta).
- 게임이 꺼져 있을 때 쓸 예비 자동완성: 서버 jar 데이터 생성기(`java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar --reports`)의 `commands.json`·레지스트리로 완성 제공.

### M6. 리소스팩 탭 (Texel)
- Texel 소스를 받으면 위젯으로 옮기고 저장 위치를 인스턴스 `resourcepacks/<팩>/`으로 바꾼다. 받기 전에는 웹뷰로 띄우고 내보낸 .zip을 받아 적용.
- Claude 요청 결과는 원본을 덮지 않고 "Claude 제안" 새 레이어로.

### M7. 모드 개발
- Fabric 모드 템플릿 생성, F7 = `gradlew build` → jar를 테스트 인스턴스 `mods/`에 복사 → 재시작. Java 편집은 Theia의 Java 지원 또는 외부 IDE 열기 버튼.

### M8. MS 로그인 — **보류**
- 상태: 지금은 진행하지 않는다. 앱은 오프라인 테스트 모드로만 실행하고, 온라인 플레이는 공식 런처를 쓴다. 나중에 Azure 앱 등록과 Mojang 신청서(https://aka.ms/mce-reviewappid) 승인이 나면 사용자가 알려준다. 그 전에는 로그인 관련 코드를 만들지 않는다(설정 화면에 "MS 로그인: 준비 중" 자리만).
- Azure 앱은 **공개 클라이언트(데스크톱)**: 개인 Microsoft 계정, 리디렉션 URI는 루프백(`http://localhost:<포트>`), 클라이언트 시크릿을 앱에 넣지 않는다.
- `minecraft-launcher-lib`의 보안 로그인 흐름: `get_secure_login_data()`(PKCE + state) → 브라우저 로그인 → `parse_auth_code_url()` → `complete_login(..., code_verifier)` → refresh token 저장. 승인 전에는 `AzureAppNotPermitted`가 난다.
- Client ID는 설정 파일에 두되 비밀이 아니다. 토큰은 OS 자격 증명 저장소(`keyring`)에, 평문 파일 금지.
- 로그인 후에는 정품 계정으로 실행하고, 오프라인(가짜 닉네임) 모드는 개발·테스트용으로만 남긴다.

### M8-1. 공식 런처 연동 (온라인 플레이 대체 경로)
- 자체 MS 로그인 대신 온라인 플레이는 **공식 마인크래프트 런처에 맡긴다**(CurseForge 기본 방식과 같다). Windows 전용.
- 모듈: `sidecar/official_launcher.py`, 테스트: `sidecar/tests/test_official_launcher.py`(mock, pytest 28개).
  - `is_installed()` — Store/Xbox판(Appx `Microsoft.4297127D64EC6`)과 winget·MSI판(레지스트리·기본 경로) 확인, 종류 포함.
  - `install(confirm_callback, log_callback)` — 확인 후 `winget install --id Mojang.MinecraftLauncher --exact ...`, 실패하면 Store 페이지(`ms-windows-store://pdp/?productid=9PGW18NPBZV5`). 설치 후 런처가 스스로 업데이트된다고 안내.
  - `register_instance(instance, confirm_callback, minecraft_dir=None, app_minecraft_dir=None)` — 공식 런처 "설치" 항목 "통합 작업실 · <이름>"으로 등록·갱신. 키는 `integrated-studio-<인스턴스 id>` 고정(라이브러리가 무작위 키로 추가만 하므로 추가 직후 옮긴다). Fabric 버전 JSON은 공식 `.minecraft/versions`에 없으면 복사.
  - `unregister_instance(instance_id, confirm_callback)` — 우리 키 접두사 항목만 삭제.
  - `open_launcher()`, `tail_log(instance_dir, callback)`(latest.log 교체·재생성 처리, 파일을 열어두지 않음).
- 규칙:
  - `launcher_accounts*.json`, `launcher_msa_credentials*` 등 로그인·토큰 파일은 **절대 읽거나 수정하지 않는다**(`_guard_path`).
  - `launcher_profiles.json`은 수정 전 항상 백업(최근 10개), 실패 시 백업으로 복구. 설치·파일 수정은 확인 콜백을 거친다.
  - `.minecraft`는 `%APPDATA%\.minecraft`와 Store 가상화 경로(`%LOCALAPPDATA%\Packages\Microsoft.4297127D64EC6_8wekyb3d8bbwe\LocalCache\Roaming\.minecraft`) 중 launcher_profiles.json이 최근 수정된 쪽.
- RPC(`sidecar/official_rpc.py`, `main.py`에 등록): `official_is_installed`, `official_install(id?)`, `official_register_instance(id)`, `official_unregister_instance(id)`, `official_open_launcher`, `official_tail_log(id, from_start?)`, `official_tail_stop(id)`, `official_tailing`, `confirm_reply(token, ok)`.
  - 확인 콜백 = `confirm` 알림 {token, id, title, message} → 프런트(InstanceManager)가 확인 창 → `confirm_reply`. 10분 안에 답이 없으면 취소, `confirm_cancel` 알림으로 창을 닫는다.
  - 로그 = 기존 `log` 알림 형식, `source: "official"`. 설치 로그처럼 인스턴스와 상관없는 줄은 id를 비운다.
  - 시험: `sidecar/tests/test_official_rpc.py`(pytest 없이 실행, CI에서도 돈다).
- 상태(2026-11-22): 모듈·테스트·RPC 연결 완료(작업 브랜치에 합침). **아직 남은 것**: UI(인스턴스 뷰의 "공식 런처로 플레이" 등), 실제 Windows PC 확인(설치 감지·winget 출력·.minecraft 위치·등록 항목 표시·Fabric 실행·로그 교체).

### M9. 패키징 (내 PC용)
- electron-builder로 Windows 설치 파일 또는 압축 실행판을 만든다. **배포하지 않는다** — 개인 사용 전용.
- 서명이 없어서 SmartScreen 경고가 뜨는 건 그대로 둔다.

---

## 4. 디자인 토큰 (목업 기준, VS Code 색 테마 형식으로 만든다)

| 용도 | 색 |
|---|---|
| 제목 표시줄 | `#141613` |
| 활동 막대 | `#161815` |
| 에디터 배경 | `#1b1d1a` |
| 사이드바·패널 | `#1f221e` / 하단 패널 `#191b18` |
| 경계선 | `#2c302a` |
| 입력칸 배경 / 테두리 | `#232621` / `#3a4037` |
| 본문 글자 / 보조 글자 | `#d6dbd2` / `#9aa395` |
| 강조(버튼, 활성 탭 윗줄) | `#6cc04a`, 버튼 글자 `#10140e` |
| 선택 행 | `#2c3a26` |
| 상태 표시줄 | `#2f5d22`, 글자 `#e6f5dc` |
| 스크롤바 / 호버 | `#34502a` / `#5a9440` (흰색 기본 스크롤바 금지) |
| 문법: 명령어 / 선택자 / ID / 숫자 / 주석 | `#c586c0` / `#4fc1ff` / `#ce9178` / `#b5cea8` / `#7aa863` |

글꼴: UI `Noto Sans KR`, 코드 `JetBrains Mono`. 아이콘은 선 아이콘, 이모지 금지.

---

## 5. 작업 규칙

- 한 번에 한 단계(M0 → M9). 각 단계의 완료 조건을 실제로 실행해 확인한 뒤 커밋한다.
- 단계를 시작하기 전에 계획을 짧게 말하고, 큰 구조 변경은 먼저 물어본다.
- 사용자에게 보이는 문구는 한국어.
- 비밀값(토큰, API 키) 커밋 금지. `data/`는 `.gitignore`.
- 파일을 다루는 모든 코드는 경로를 정규화하고 인스턴스 폴더 밖이면 거부한다. 삭제는 휴지통으로.
- 로컬 서버의 EULA는 사용자가 직접 읽고 동의하게 한다(자동 동의 금지).
- 바닐라 원본 에셋을 리소스팩에 그대로 넣어 배포하지 않는다(수정한 파일만).
- 외부 라이브러리 버전은 추측하지 말고 설치 시점의 최신 안정판을 확인해서 쓴다. Theia·CommandCrafter·minecraft-launcher-lib는 빠르게 바뀐다.
