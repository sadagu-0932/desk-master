# 통합 작업실 (Integrated Studio)

마인크래프트 실행 · 데이터팩 · 모드 · 리소스팩 — Eclipse Theia 기반 **개인용** 데스크톱 앱(배포하지 않음).
작업 지시는 [CLAUDE.md](CLAUDE.md)를 따른다.

## 필요한 것 (내 PC)

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
| 인스턴스 만들기 | 홈의 “+ 새 인스턴스” 또는 명령 팔레트 `통합 작업실: 새 인스턴스 만들기` |
| 실행 / 중지 | F5 / Shift+F5, 사이드바 “인스턴스” 뷰의 ▶/■, 상단 실행 대상 막대 (오프라인 테스트 모드) |
| 온라인 플레이 | 홈 카드의 “공식 런처” 또는 인스턴스 뷰의 지구본 — 공식 런처에 “통합 작업실 · <이름>” 항목을 등록하고 연다. 로그인·플레이는 공식 런처에서, 게임 로그는 이 앱에 나온다 (Windows) |
| 작업실에서 열기 | 인스턴스 뷰의 폴더 버튼 — 그 인스턴스 폴더가 작업 공간이 되고 Claude도 그 폴더에서 일한다 |
| 로컬 서버 | F6 (EULA는 `server/eula.txt`를 직접 읽고 true로 바꿔야 한다) |
| 모드 빌드 후 테스트 | F7 (`mods-src/<모드>`를 `./gradlew build` → `mods/`에 복사 → 재시작) |
| 리소스팩 적용 | F8 |
| /reload | 상단 `/reload` 버튼 — `datapacks/`를 최근 월드로 동기화한 뒤 CommandCrafter(또는 로컬 서버)로 보낸다 |
| 게임 꺼져 있을 때 자동완성 | 명령 팔레트 `게임 없이 쓸 자동완성 준비(데이터 생성기)` |
| Claude 작업 종류 | Claude 패널 위 “작업 종류” 또는 상태 표시줄 — 데이터팩 / Fabric 모드 / 리소스팩 |

## 보안 메모

- CommandCrafter 모드는 서비스 포트(인스턴스마다 52853부터)를 **모든 네트워크 인터페이스**에 연다.
  공용 네트워크에서는 방화벽에서 이 포트의 외부 접속을 막아 둔다.
- MS 로그인은 보류(M8). 이 앱의 ‘실행’은 오프라인 테스트 모드(닉네임 Dev)다. 온라인은 공식 런처로 하며, 이 앱은 공식 런처의 로그인·토큰 파일을 읽지 않는다.
