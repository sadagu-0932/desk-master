# 통합 작업실 (Integrated Studio)

마인크래프트 실행 · 데이터팩 · 모드 · 리소스팩 — Eclipse Theia 기반 **개인용** 데스크톱 앱(배포하지 않음).
작업 지시는 [CLAUDE.md](CLAUDE.md)를 따른다.

## 필요한 것 (내 PC)

설치 파일의 "함께 설치할 프로그램" 화면에서 Python 3(없으면 필수로 체크·고정)과 Prism Launcher(없으면 체크, 끌 수 있음)를 winget 으로 함께 설치한다.


| 도구 | 용도 |
|---|---|
| Node.js 22~24 (권장 24), npm | 앱 빌드 |
| Python 3.10 이상 | 게임 설치·실행 사이드카 (`minecraft-launcher-lib`) — 첫 실행 때 가상환경을 자동으로 만든다 |
| git | 인스턴스마다 저장소 생성 |
| Visual Studio Build Tools (C++ 데스크톱 개발) | native 모듈 빌드 (Windows) |
| `claude` CLI 로그인 | Claude 패널 (Agent SDK는 앱에 포함) |
| JDK 25 (`JAVA_HOME`) | Fabric 모드 빌드(F7)만. 게임 실행용 자바는 자동으로 받는다 |

Linux에서 빌드할 때는 `libxkbfile-dev libx11-dev libsecret-1-dev pkg-config`도 필요하다.

## 실행 (개발용)

```
npm install                 # 의존성 + Open VSX에서 CommandCrafter·한국어 팩 확장 받기
npm run rebuild:native      # native 모듈을 Electron용으로 재빌드
npm run build
npm start
```

- 확장을 다시 받으려면 `npm run download:plugins -- --force`
- 데이터 폴더: 개발 중에는 저장소의 `data/`(git 제외), 패키징된 앱은 `~/.integrated-studio/data`.
  `INTEGRATED_STUDIO_DATA` 환경 변수로 바꿀 수 있다.

## 설치 파일 받기

설치 파일은 **요청할 때만** 만든다(push로는 만들지 않음).
GitHub 저장소 → **Actions** → "통합 작업실 Windows 설치 파일" → **Run workflow** → 끝나면 아래 **Artifacts**의
`IntegratedStudio-Setup-0.1.<번호>`를 내려받는다.

- Python 미포함판이다. PC에 Python 3이 있어야 하고, 첫 실행 때 필요한 패키지를 자동으로 설치한다.
- 버전은 실행할 때마다 올라간다(0.1.<실행 번호>). 홈 화면 위쪽에 지금 버전이 보인다.
- **이미 설치돼 있으면 업데이트로 설치된다**: 설치 파일이 기존 버전을 찾아 안내하고 같은 위치에 덮어쓴다.
  인스턴스·월드·설정(`~/.integrated-studio`)은 지우지 않는다.
- 서명이 없어서 처음 설치할 때 SmartScreen 경고가 뜬다 — "추가 정보 → 실행".

## 직접 패키징 (내 PC에서)

```
npm run package               # Python 미포함 설치 파일
npm run package:with-python   # Python 포함 설치 파일 (Windows에서만)
```

결과는 `applications/electron/dist/`에 생긴다.

## 쓰는 법

| 동작 | 방법 |
|---|---|
| 홈 | 상단 막대 왼쪽 “홈” 버튼 또는 Alt+Home (홈 탭을 닫아도 다시 열림) |
| 인스턴스 만들기 | 홈의 “+ 새 인스턴스” 또는 명령 팔레트 `통합 작업실: 새 인스턴스 만들기` |
| 실행 | F5, 카드의 “실행”, 인스턴스 뷰의 ▶, 상단 실행 막대 — **Prism Launcher 로**: 인스턴스는 Prism 인스턴스이고, 실행하면 Prism 이 바로 켠다(로그인·자바·게임 파일 받기는 Prism). 게임 로그는 이 앱에 나온다 |
| 런처 ↔ 작업실 | 앱을 켜면 가벼운 **런처**(홈·인스턴스·실행·서버). 상단 [작업실 열기](또는 인스턴스의 폴더 버튼)를 누르면 그 인스턴스 폴더가 열린 **작업실**이 되고 코드 편집기·데이터팩 도구·CommandCrafter·Claude 를 쓴다. [런처로]를 누르면 편집기 쪽을 꺼서 메모리를 돌려받는다 |
| 메모리 | 명령 팔레트 `메모리 사용량 보기`(무엇이 얼마나 쓰는지), 인스턴스 … → 메모리 설정(모드 수로 고른 추천값), 서버 카드 [메모리] |
| 로컬 서버 | F6 (EULA는 `server/eula.txt`를 직접 읽고 true로 바꿔야 한다) |
| 모드 빌드 후 테스트 | F7 (`mods-src/<모드>`를 `./gradlew build` → `mods/`에 복사 → 재시작) |
| 리소스팩 적용 | F8 |
| Paper 플러그인 | 명령 팔레트 `Paper 플러그인 템플릿 만들기` → `plugins-src/<이름>`. 서버 패널에서 전용 서버를 "Paper 서버(플러그인)"로 만들어 두면 **F9** 가 빌드해서 그 서버 `plugins/` 에 넣고, 켜져 있으면 다시 시작한다. JDK 25 필요 |
| 설정 동기화 | 자동(시작·30초마다·실행 직전·게임 종료 뒤). 통합 작업실이 만든 인스턴스끼리 게임 설정(options.txt, 리소스팩 목록 제외)과 서버 목록을 같게 유지한다(Prism 에 원래 있던 인스턴스는 건드리지 않음). 수동: 명령 팔레트 `설정 지금 동기화` |
| 서버 열기(친구와 같이) | 왼쪽 막대 “서버” → [서버 열기]: 싱글 LAN 공개 / 전용 서버(바닐라·Fabric·NeoForge·Forge) / 외부 서버(다른 런처로 연 월드). 주소는 자동으로 e4mc → UPnP → playit 순서로 열고 [복사]. 친구는 멀티플레이 → 서버 추가에 주소만 넣으면 됨(프로그램 불필요, 콘텐츠 모드가 있으면 같은 모드만) |
| 그룹(폴더) | 인스턴스 … → `그룹(폴더) 지정`, 또는 인스턴스를 폴더 머리로 끌어다 놓기. 폴더는 접을 수 있고 머리의 연필·X 로 이름 바꾸기·풀기. Prism 의 그룹과 같게 유지된다 |
| Prism 연동 | Prism 에서 만들거나 지우거나 이름·버전을 바꾼 인스턴스가 몇 초 안에 여기 반영된다. Prism 이 없으면 런처 부분(홈 인스턴스·목록·실행)을 숨기고 홈에 [Prism Launcher 설치]가 나온다. 예전 인스턴스는 켤 때 [Prism 으로 옮기기]를 묻는다 |
| 인스턴스 불러오기 | “서버” 패널 [인스턴스 불러오기] → Prism·MultiMC 는 폴더 그대로 연결, CurseForge·Modrinth App·공식 런처·폴더는 새 Prism 인스턴스로 복사. 계정 파일은 건드리지 않음 |
| /reload | 상단 `/reload` 버튼 — `datapacks/`를 최근 월드로 동기화한 뒤 CommandCrafter(또는 로컬 서버)로 보낸다 |
| 게임 꺼져 있을 때 자동완성 | 명령 팔레트 `게임 없이 쓸 자동완성 준비(데이터 생성기)` |
| Claude 작업 종류 | Claude 패널 위 “작업 종류” 또는 상태 표시줄 — 데이터팩 / Fabric 모드 / 리소스팩 |

## 코드 구조 (처음 보는 사람용)

화면(Theia, TypeScript)은 버튼만 받고, 실제 일은 **파이썬 사이드카**가 한다. 둘은 표준 입출력으로 JSON-RPC 를 주고받는다.

```
버튼 클릭 → launcher-core InstanceManager.call('이름', {인자})
         → node/sidecar-process.ts (사이드카 프로세스에 한 줄 JSON)
         → sidecar/main.py handlers['이름'](인자) → 각 모듈 → 결과 / 알림(progress·log·instances_changed)
```

| 위치 | 하는 일 |
|---|---|
| `sidecar/main.py` | 요청 이름 → 함수 표(`handlers`). 새 기능은 여기에 이름을 등록한다 |
| `sidecar/rpc.py` | JSON-RPC 통로(자식 프로세스가 통로를 물려받지 않게 떼어 둠), 오류 기록 `data/logs/sidecar-errors.log` |
| `sidecar/net.py` | 인터넷 요청·다운로드(`.part` → 해시 확인 → 제자리) 공통. 다른 모듈은 직접 urllib 을 쓰지 않는다 |
| `sidecar/paths.py` | 경로 안전 검사·휴지통. 파일을 다루는 코드는 모두 여기를 거친다 |
| `sidecar/instances.py` | 인스턴스 저장(`instance.json`)·복제·삭제. 바뀌면 `instances_changed` 알림 |
| `sidecar/runner.py` | 게임·로더 설치, 로컬 서버, 데이터 생성기 |
| `sidecar/prism.py`, `prism_sync.py` | Prism 찾기·인스턴스 만들기(instance.cfg·mmc-pack.json)·설치(winget) / 목록 자동 연동·예전 인스턴스 옮기기 |
| `sidecar/game_log.py` | Prism 으로 켠 게임의 latest.log 따라 읽기·실행 상태, 사용자 확인 창(confirm) |
| `sidecar/sync.py` | 설정(options.txt·servers.dat) 동기화 |
| `sidecar/modrinth.py` | Modrinth 에서 받는 건 전부 여기(정확한 버전·해시 검증) |
| `sidecar/server_runner.py` | 전용 서버(바닐라·Fabric·NeoForge·Forge) |
| `sidecar/server_mods.py`, `e4mc_host.py` | 참가자도 필요한 모드 분석 / e4mc(싱글 LAN 공개 → 인터넷 주소) |
| `sidecar/lazy.py` | 무거운 라이브러리(minecraft-launcher-lib)를 처음 쓸 때 불러와 시작을 빠르게 |
| `sidecar/importers/` | 모드팩 가져오기(`__init__`), 다른 런처 감지(`launchers`), 복사·연결·사용 중 확인(`local`), 연결 인스턴스 실행 파일(`launchfile`) |
| `sidecar/mc_tools/` | 데이터팩·모드 검사 도구(Claude 후크용) |
| `theia-extensions/launcher-core` | 인스턴스 모델·사이드카 연결(`InstanceManager`)·명령(`launcher-commands.ts`)·새 인스턴스 창 |
| `theia-extensions/launcher-ui` | 홈·인스턴스 목록·게임 로그·작업·상단 실행 막대 |
| `theia-extensions/server-host` | 서버 열기 패널·불러오기 화면(browser), 주소 열기 e4mc/UPnP/playit(node) |
| `theia-extensions/datapack-tools`, `resourcepack-editor`, `theme` | 데이터팩 도구, 리소스팩 편집기, 색 테마 |

공통 규칙
- 명령의 오류는 `guard(...)`(= launcher-core `reportErrors`)로 감싸 알림으로 보여 준다.
- 사용자에게 보이는 문구는 한국어. 결정 사항과 이유는 `CLAUDE.md` 에 날짜와 함께 남긴다.

시험
```
cd sidecar && python -m pytest -q tests mc_tools/tests && python tests/test_official_rpc.py
npm test -w integrated-studio-server-host
```
`tests/test_windows_smoke.py` 는 Windows 에서만(GitHub Actions) 돈다.

## 보안 메모

- CommandCrafter 모드는 서비스 포트(인스턴스마다 52853부터)를 **모든 네트워크 인터페이스**에 연다.
  공용 네트워크에서는 방화벽에서 이 포트의 외부 접속을 막아 둔다.
- 게임은 Prism Launcher 로 실행한다(로그인은 Prism). 이 앱은 Prism·공식 런처의 로그인·토큰 파일을 읽지 않는다. 자체 MS 로그인(M8)은 보류.
