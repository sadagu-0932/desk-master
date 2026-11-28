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
- 실행은 처음에 오프라인 테스트 모드로 만들었다가, **지금은 공식 런처로만 한다(M8-1 결정)**. 인스턴스마다 게임 폴더(`gameDir`)를 분리한다.
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
- 상태: 지금은 진행하지 않는다. 게임 실행은 공식 런처로만 한다(아래 M8-1, 오프라인 실행은 제거됨). 나중에 Azure 앱 등록과 Mojang 신청서(https://aka.ms/mce-reviewappid) 승인이 나면 사용자가 알려준다. 그 전에는 로그인 관련 코드를 만들지 않는다(설정 화면에 "MS 로그인: 준비 중" 자리만).
- Azure 앱은 **공개 클라이언트(데스크톱)**: 개인 Microsoft 계정, 리디렉션 URI는 루프백(`http://localhost:<포트>`), 클라이언트 시크릿을 앱에 넣지 않는다.
- `minecraft-launcher-lib`의 보안 로그인 흐름: `get_secure_login_data()`(PKCE + state) → 브라우저 로그인 → `parse_auth_code_url()` → `complete_login(..., code_verifier)` → refresh token 저장. 승인 전에는 `AzureAppNotPermitted`가 난다.
- Client ID는 설정 파일에 두되 비밀이 아니다. 토큰은 OS 자격 증명 저장소(`keyring`)에, 평문 파일 금지.
- 로그인 기능을 만들게 되면 정품 계정으로 실행한다. 그 전까지 실행은 공식 런처로만(M8-1).

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
- **결정(2026-11-22, 사용자): 게임 클라이언트 실행은 항상 공식 런처로만.** 사이드카의 오프라인 실행(`launch`/`stop`)은 없앴다.
  - F5·▶·카드 '실행'·상단 실행 버튼 = `studio.instance.launch` → (필요하면 게임 설치) → 공식 런처 확인·설치 → 등록(같은 내용으로 이미 등록돼 있으면 묻지 않음) → CommandCrafter 포트 설정 → 로그 따라 읽기 → 런처 열기.
  - 실행 상태는 latest.log로 안다(`Setting user:`/`Loading Minecraft` = 켜짐, `Stopping!`/`Game crashed!` = 꺼짐). 우리 프로세스가 아니라서 중지·재시작은 없다(Shift+F5는 안내만). F7은 모드를 넣고 꺼져 있으면 실행, 켜져 있으면 다시 켜라고 안내.
  - 명령 팔레트: 공식 런처 열기 / 설치 / 등록 해제. 시험: `scripts/e2e/t13-official.js`(가짜 공식 런처로).
- **결정(2026-11-22, 사용자): 설정은 항상 동기화** — `sidecar/sync.py`(시험 `tests/test_sync.py`).
  - 게임 설정 `options.txt`·서버 목록 `servers.dat`: 모든 인스턴스 + 공식 `.minecraft`가 같게. 가장 최근에 바뀐 파일이 기준, 쓴 파일의 수정 시각을 기준과 같게(왕복 방지). 리소스팩 목록(`resourcePacks`, `incompatibleResourcePacks`)은 인스턴스별이라 맞추지 않는다. 실행 중인 인스턴스엔 쓰지 않는다. 공식 `.minecraft` 파일은 덮기 전에 `data/sync-backups/`에 백업(최근 20개).
  - 공식 런처 항목: 처음 등록만 묻고, 이후 이름·버전·폴더가 바뀌면 확인 없이 갱신. 인스턴스 삭제 시 항목도 삭제, 앱에 없는 인스턴스의 우리 항목은 정리. `launcher_profiles.json` 쓰기는 잠금으로 하나씩.
  - 언제: 사이드카 시작, 30초마다, 실행 직전, 게임이 닫힌 뒤(3초 뒤), 이름 바꾼 뒤. 수동: 명령 팔레트 "설정 지금 동기화"(RPC `sync_now`).
- 상태(2026-11-22): 모듈·RPC·UI·동기화 완료. **아직 남은 것**: 실제 Windows PC 확인(설치 감지·winget 출력·.minecraft 위치·등록 항목 표시·Fabric 실행·로그 교체).

### M10. 서버 열기 + 인스턴스 불러오기 (포트포워딩 없이, 친구는 주소만)
- 결정(2026-11-23, 사용자): 지난 P2P 방식(hyperdht·참가 코드·참가 전용 앱)은 **없앴다**. 호스트는 [서버 열기] 한 번, 친구는 마인크래프트
  멀티플레이에 주소만 넣는다. 친구 쪽엔 프로그램·모드가 필요 없다(호스트 월드에 콘텐츠 모드가 있을 때만 같은 모드). 보안 설정(비밀번호·화이트리스트)은 넣지 않는다.
- 같은 날 추가 요청: **Forge 계열(NeoForge·Forge)도 된다** — 불러오기·실행·전용 서버·e4mc(정확히 맞는 파일이 있을 때).
- 코드
  - `sidecar/modrinth.py` — Modrinth 에서 받는 건 **전부** 여기로(모드팩·모드 추가·CommandCrafter·e4mc). 게임 버전·로더가 **정확히** 맞는 파일만(가까운 버전 대체 금지),
    26.1+ Fabric 은 "modern" 파일 우선(e4mc 실제 응답: `e4mc-fabric-6.2.3-modern.jar`), 보조 jar(-sources 등) 제외, 그래도 여럿이면 `Ambiguous`(사용자 선택).
    sha512(없으면 sha1)로 검증 후 실패면 버림, required 의존만 자동 설치·optional 은 안내, `identify`(POST /version_files)로 여러 파일 해시 식별, `check_mods`.
  - `sidecar/importers/` — `__init__`(기존 모드팩·Prism zip), `launchers.py`(감지, 읽기 전용), `local.py`(복사/연결, 사용 중 확인).
    - Prism/MultiMC(`prismlauncher.cfg InstanceDir`, instance.cfg, mmc-pack.json components), CurseForge(`minecraftinstance.json`),
      Modrinth App(`%APPDATA%\ModrinthApp\app.db`: 2026-06 이후 `instances`+`instance_content_sets`+`instance_launch_overrides`, 그 전 `profiles` — modrinth/code 소스로 확인. DB 는 임시 복사본을 읽기 전용으로),
      공식 런처(launcher_profiles.json, 우리 항목 제외), 폴더 직접 선택, 압축(.mrpack·CurseForge zip·Prism 내보내기 zip).
    - 복사: mods·config·saves·resourcepacks·shaderpacks·datapacks·kubejs·defaultconfigs·schematics·options*.txt·servers.dat 만. 원본 무수정.
      연결: `instance.json` 의 `linkedDir` = 원본 게임 폴더(`store.game_dir`), 우리 파일은 원본에 쓰지 않음, 설정 동기화 제외, 실행 전 `import_in_use`(session.lock·이 폴더로 켠 java·최근 로그·다른 런처 프로세스).
    - 계정·토큰 파일(accounts.json, launcher_accounts*, launcher_msa_credentials* 등)은 열지도 복사하지도 않는다(`is_account_file`).
    - 불러온 뒤 버전·로더 설치(없을 때만, 실패해도 인스턴스는 남기고 실행 때 다시), 메모리·자바 인자 → `jvmArgs`.
  - `sidecar/server_runner.py`
    - 방식 A 전용 서버 `ServerRunner`: `servers/<srv_id>/`, 바닐라 jar(downloads.server, sha1 검증)·Fabric 서버 런처·**NeoForge(`--install-server`)·Forge(`--installServer`) 공식 메이븐 설치기(.sha256 검증)**
      → `java @user_jvm_args.txt @libraries/<group>/<버전>/win_args.txt nogui`. 버전: NeoForge = 메이븐 메타데이터에서 `<mc 세 자리>.` 로 시작(26.3 → 26.3.0.x), Forge = promotions_slim `<mc>-recommended`.
      EULA 창(자동 동의 금지), server-ip 비움(UPnP 로 LAN 주소에서 들어옴), 빈 포트, online-mode 선택, 월드 복사, Done 감지, 콘솔, 서버에서도 도는 모드만 서버 mods/ 로.
    - 모드 분석: fabric.mod.json environment / quilt.mod.json / mods.toml(displayTest IGNORE_*·clientSideOnly) → "참가자도 같은 모드 필요" 목록. 목록·충돌 후보는 `sidecar/server_host_mods.json`.
    - e4mc `E4mcHost`: modrinth.py 로 설치(바닐라는 같은 버전 Fabric "(호스트용)" 공식 런처 항목 `integrated-studio-<id>-host`, 원래 인스턴스 그대로), 충돌 모드 선택(이번만 끄기/그대로/UPnP·playit),
      끄기는 `.disabled`(삭제 금지), e4mc 탓 크래시(crash-reports·latest.log)면 다음 실행부터 자동으로 끔.
  - `theia-extensions/server-host/` — `lan-watcher`(방식 B, e4mc `Domain assigned: {}` 실제 로그), `lan-discovery`(방식 C, 224.0.2.60:4445 `[MOTD]…[/MOTD][AD]포트[/AD]` — 26.3 client.jar LanServerPinger 확인),
    `slp`(Server List Ping), `upnp`(@runonflux/nat-upnp 2.2.0 고정, 사설·CGNAT 거부, 만료 1시간·20분 갱신, 725/718 처리, 닫을 때·앱 끌 때 삭제, 공인 IP 변경 감지, 선택 DDNS — `data/server-host/ddns.json`),
    `playit`(GitHub 릴리스 `playit-windows-x86_64-signed.exe` sha256 digest 검증·사용자 확인 후 받기, claim 코드 → playit.gg/claim/<코드>, API `/tunnels/*` Agent-Key, 서버마다 고정 터널, 에이전트 자동 켜고 끄기 — playit-agent 2.0.x 소스로 확인),
    `host-manager`(주소 자동 선택: 싱글 LAN e4mc → UPnP → playit, 전용·외부 UPnP → playit, 실패 이유·고정/매번 바뀜·중계 안내, C 는 열기 전 상태 조회·3번 무응답이면 닫음), 패널·불러오기 화면.
  - 연결 코드: `instances.py`(로더 5종, `linkedDir`), `runner.py`(로더별 설치, NeoForge 26.x 는 minecraft-launcher-lib 8.0 이 버전 형식을 몰라 메이븐에서 직접 고른 뒤 설치기 실행),
    `official_launcher.py`(Forge 계열 설치기가 만든 라이브러리 = 주소 없는 것 → 공식 .minecraft 로 복사), `official_rpc.py`(호스트용 항목), `sync.py`(연결 인스턴스 제외), `main.py`(RPC),
    launcher-core(Loader 타입·로더 이름, 연결 인스턴스 사용 중 확인, 새 인스턴스 창 NeoForge·Forge·Quilt).
- 시험: `pytest tests/test_modrinth.py tests/test_launchers.py tests/test_server_runner.py tests/test_official_launcher.py`,
  `npm test -w integrated-studio-server-host`(가짜 공유기·playit API·마인크래프트 상태 응답·LAN 신호로 16개), e2e `scripts/e2e/t14-server.js`.
- 남은 것: 실제 Windows PC 두 대(한 대는 휴대폰 핫스팟)에서 공유기 UPnP·e4mc·playit·Forge 서버 설치기 확인.
- 결정(2026-11-23, 사용자): **다른 곳의 인스턴스는 폴더를 그대로 두고 여기서 실행·관리**(불러오기 기본 = 연결, 새 인스턴스 창의 Prism 폴더도 연결).
  연결 인스턴스 삭제 = 목록에서만 지움(원래 폴더 그대로). 인스턴스 관리 메뉴(카드 … ·오른쪽 클릭): 실행·폴더 열기(파일 탐색기)·작업실·이름 바꾸기·
  복제(계정 파일 제외)·메모리 설정(jvmArgs -Xmx)·모드 추가·서버로 열기·CommandCrafter·등록 해제·삭제. RPC `duplicate_instance`·`set_instance_memory`·`open_instance_folder`.
- 결정(2026-11-23, 사용자): **연결한 외부 인스턴스는 이 앱에 아무것도 설치하지 않는다.** Prism·MultiMC 인스턴스는 그 런처로 바로 실행
  (`launch_external`: `<exe> --dir <데이터 폴더> --launch <인스턴스 폴더 이름>`, 포터블·설치판·PATH 에서 exe 찾기 — 공식 런처 전용 규칙의 예외).
  공식 런처 항목은 이미 있는 버전이면 설치 안 함. CurseForge·Modrinth App 은 외부 실행 방법이 없어 공식 런처로(없는 버전만 실행할 때 설치).
  예전에 연결한 인스턴스는 시작할 때 `migrate_linked` 로 정보 채움. 인스턴스가 바뀌면 사이드카 `instances_changed` 알림 → 목록 즉시 새로고침.
  새 인스턴스 창 [인스턴스 폴더 연결]: 어느 런처 폴더든(Prism·MultiMC·CurseForge·Modrinth 프로필·Prism 안의 minecraft·그냥 .minecraft) 연결,
  버전은 로그(`Loading Minecraft X with Fabric Loader Y`·`--fml.mcVersion`/`--fml.neoForgeVersion`)에서, 못 찾으면 입력. 공식 .minecraft 에
  그 버전이 있으면 설치된 것으로 표시(받지 않음). e2e 는 `THEIA_ELECTRON_DISABLE_NATIVE_ELEMENTS=1` 로 Theia 파일 대화 상자를 써서 자동화.
- 결정(2026-11-25, 사용자): **연결 = 원래 폴더 경로를 항상 저장(`sourceDir`) + 그 폴더 안에 실행 파일 `통합 작업실 실행.cmd` 생성(`launchFile`)**.
  [실행] = 그 파일 실행(`launch_linked`, 없어졌으면 다시 만듦). 파일이 원래 런처를 연다(`importers/launchfile.py`): Prism·MultiMC `--dir … --launch …`,
  CurseForge·Modrinth App 은 앱을 연다(못 찾으면 curseforge:// · modrinth://), 공식·그냥 폴더는 공식 런처(등록 후). CurseForge·Modrinth 도 이제 받지 않음.
  파일 첫 줄 표식이 있는 것만 우리 것(같은 이름 남의 파일은 안 덮음), 목록에서 지우면 그 파일만 지움. 탐색기에서 더블클릭해도 같다.
  만들기·불러오기·복제 뒤 `InstanceManager.ensureVisible`(사용자 요청 2026-11-25): 1초·3초 뒤 다시 읽고, 10초 뒤에도 목록·화면에 없으면 창 다시 불러오기
  (앱 재시작과 같은 효과, 백엔드·사이드카·게임 로그는 그대로). 보이면 아무것도 안 함.
- 결정(2026-11-26, 사용자): **연결 인스턴스 실행 = 그 인스턴스 안의 .minecraft 로 마크 바로 실행**(원래 런처를 거치지 않음, 계정은 공식 런처).
  실행 파일은 인스턴스 폴더가 아니라 **게임 폴더(.minecraft) 안**. 공식 런처 항목 gameDirectory = 그 .minecraft, 실행 직전 `official_touch`(lastUsed=지금)로
  그 항목이 선택된 채 열림 → [플레이]만. 그 버전이 공식 런처에 없으면 처음 실행 때 한 번 설치(사용자 동의). 예전 연결은 시작할 때 이렇게 바꾸고 예전 파일은 지움.
- 결정(2026-11-26, 사용자, 위를 고침): **연결한 Prism·MultiMC 인스턴스는 앱이 그 런처의 [실행]을 누르는 것과 같게** — 실행 파일(.minecraft 안)이
  `prismlauncher --dir <데이터> --launch <인스턴스>` 를 부른다(Prism 계정·자바·로더, 다운로드 없음). 그 밖의 연결(CurseForge·Modrinth·폴더)은 .minecraft 로 공식 런처.
  앱 자체 MS 로그인은 M8(Azure 앱 + Mojang 승인 필요) 전까지 없음 — 다른 런처의 앱 번호를 빌려 쓰지 않는다.
- 고침(2026-11-26): **사이드카가 띄운 프로그램(PowerShell·git·설치기)이 표준 입력(=앱 요청 통로)을 물려받아 요청을 삼키거나 멈추던 문제** —
  만들기·불러오기·실행이 멈추고 껐다 켜야 보이던 원인. `rpc.py` 가 시작할 때 프로토콜을 복제한 설명자로 떼어 내고 표준 입력=빈 입력,
  표준 출력=로그로 바꿈(Windows 는 SetStdHandle 까지). 시험 `tests/test_rpc_isolation.py`(고치기 전 코드로는 실패 확인). git 은 서명·후크·프롬프트 끄고 시간 제한.
  RPC 인자 이름 점검 시험 `tests/test_rpc_args.py`(프런트·백엔드의 `.call('이름', {…})` ↔ 사이드카 핸들러) — 'iid'/'id' 불일치로 연결 실행이 통째로 안 되던 문제 재발 방지.
- 고침(2026-11-27): 코드 점검으로 찾은 4가지. ① 실행 파일을 `cmd /d /s /c ""경로""`(문자열)로 실행 — 예전 `cmd /c "경로"` 는 경로에 `( ) &` 가 있으면
  따옴표가 떼어져 실패(대체 이름 `통합 작업실 실행 (통합 작업실).cmd` 는 항상 해당). rem 줄의 이름은 `%`→`%%`. ② 연결 인스턴스 복제: `installed`/`versionId` 는
  공식 .minecraft 에 그 버전이 실제로 있을 때만(아니면 첫 실행 때 설치), 우리 실행 파일은 복사하지 않음, Prism 연결 복제면 "공식 런처로 실행" 안내.
  ③ Prism 데이터 폴더 찾기: 위로 올라가며 + 알려진 데이터 폴더(·exe 옆 포터블)의 cfg `InstanceDir` 비교. 그래도 없으면 실행 때 `[launcher-root]` 오류 →
  프런트가 폴더 고르기 → RPC `set_launcher_root(id, path)`(그 데이터 폴더의 인스턴스 목록에 있어야 함). 시작 때 `migrate_linked` 가 빈 root 를 다시 찾음.
  ④ 사용 중 확인: 게임 폴더와 원래 인스턴스 폴더(`sourceDir`, Prism java 의 `<인스턴스>/natives`)를 `/`·`\`·대소문자 무시로 비교, Prism·MultiMC 는 실행 뒤 30초 다시 실행 막음.
- 정리(2026-11-27, 사용자 요청 "최적화·알아보기 쉽게"): 안 쓰는 함수·변수·import 제거(vulture·pyflakes·tsc --noUnusedLocals 로 찾고 사용처 확인),
  인터넷 요청·다운로드는 `sidecar/net.py` 하나로(네 모듈에 따로 있던 복사본 제거, 시험 `tests/test_net.py`) — **새 코드도 urllib 을 직접 쓰지 말고 net.py 를 쓴다**.
  명령 오류 알림은 launcher-core `reportErrors`/`errorMessage` 하나로(다섯 확장에 같은 코드가 있었음). README 에 "코드 구조" 절 추가.
- 최적화(2026-11-27, 사용자 요청 "기본 최적화 + 기능·용량 영향 없으면 파일 나누기"):
  사이드카 시작 0.17→0.08초(`lazy.py`: minecraft-launcher-lib 를 설치·등록할 때 불러옴). 30초 동기화는 파일 상태(경로·수정 시각·크기·쓰기 가능)가
  지난번과 같으면 읽지 않음(`sync_now(force=False)`, 수동·실행 직전·게임 종료 뒤는 항상). 사용 중 확인은 필요한 프로세스만 WMI `-Filter` 로,
  스크립트는 `-EncodedCommand`(따옴표 안전), 이미 막을 이유가 있으면 조회 생략. Theia 기본 확장은 전부 plugin-ext(CommandCrafter) 의존이라 그대로.
  파일 나누기: `server_runner.py` → `server_mods.py`(모드 분석)·`e4mc_host.py`(e4mc). official_launcher·importers/__init__·host-manager.ts 는
  한 클래스·한 주제이고 시험이 모듈 함수를 바꿔 끼우는 곳이 많아 나누지 않음(나누면 시험이 엉뚱한 걸 검사하게 될 위험).
- 램 줄이기 + 앱 두 개처럼(2026-11-27, 사용자 요청 "램 줄이기 다 해봐", "앱 2개 느낌으로, 작업실을 열면 코드 편집기가 나오게"):
  **런처 모드 ↔ 작업실 모드**(`launcher-ui/studio-mode.ts`). 창 주소 #뒤에 폴더가 있으면 작업실, 없으면 런처. 앱을 새로 켜면 지난 작업실을 열지 않고 런처
  (`StudioWorkspaceService.doGetDefaultWorkspaceUri`). VS Code 확장 실행기(CommandCrafter)는 작업실에서만 시작(`StudioHostedPluginSupport.onStart`,
  런처에서는 시작 자체를 안 해 대기 훅도 없음 — CommandCrafter 명령은 원래 `getCommand` 로 있을 때만 부름). 상단 막대 [작업실 열기]/[런처로](작업 공간 닫기 = 주소 비우고 다시 불러오기).
  e2e `scripts/e2e/t15-modes.js`(앱을 인자 없이 켠 뒤): 켤 때 확장 실행기 0개·시험 확장 미실행 → 작업실 1개·실행 → 런처로 0개, 작업실에서 앱을 꺼도 다시 켜면 런처.
  그 밖: 켤 때 코드 편집기·Texel 탭은 되살리지 않음(`LightStartLayoutRestorer`), `files.watcherExclude`(saves·logs·crash-reports·서버 월드·빌드),
  Texel 은 탭이 처음 보일 때 불러오기 + [메모리 비우기](자동으로 내리면 내보내지 않은 작업이 사라질 수 있어 수동), LAN 감시는 latest.log 를 1MB 조각으로(StringDecoder),
  자동완성 자료는 지금 버전만, `sidecar/memory.py`(게임 메모리 추천: 모드 수·Forge 계열·PC 메모리 절반 이하 / 서버 메모리 설정, 기본 2GB·작은 PC 는 1/4 /
  명령 "메모리 사용량 보기": 앱 프로세스 트리 + 게임을 종류별로 합산, Windows).
- **결정(2026-11-27, 사용자): 런처 부분은 Prism Launcher 로 — 공식 런처 실행은 없앤다**(M8-1 "공식 런처로만"을 대체).
  - 인스턴스 = Prism 인스턴스. `InstanceStore.create` 가 `make_prism_instance`(main.py 연결, `sidecar/prism.py`)로 Prism 인스턴스 폴더
    (`instance.cfg` + `mmc-pack.json`, 의존 구성 요소는 Prism 이 채움)를 만들고 연결(`linkedDir`=그 minecraft, `launchKind`=prism, `managed`=True).
    게임·로더 파일은 Prism 이 실행할 때 받는다(앱은 설치하지 않음 — `install` RPC 없앰). 모드팩 가져오기·복제도 같은 길로 Prism 인스턴스가 된다.
    시험 등 `make_prism_instance` 가 없으면 예전처럼 앱 폴더에 만든다.
  - 실행 = `launch_linked` → `prismlauncher --dir <데이터> --launch <폴더>`. 게임 로그·상태는 `game_log.py`(`game_tail_log`), 확인 창도 여기(`confirm_reply`).
  - 이름·메모리는 Prism `instance.cfg` 에도 쓴다(name, OverrideMemory/MaxMemAlloc, JvmArgs). 지우기 = Prism 인스턴스 폴더째 휴지통(목록이 Prism 과 연동이라).
  - 자동 연동 `prism_sync.PrismSync`(5초마다, 폴더 이름·instance.cfg·mmc-pack.json 수정 시각이 바뀐 때만 읽음): Prism 에 생긴 것 연결(남의 폴더엔 파일 안 씀),
    지운 것 목록에서 빼기, 이름·버전·로더 맞추기. Prism 찾기: exe(설치판·포터블·PATH) → 데이터(포터블이면 exe 폴더, 아니면 %APPDATA%\PrismLauncher) → cfg InstanceDir.
  - 불러오기: Prism·MultiMC = 연결, 그 밖(CurseForge·Modrinth·공식·폴더) = 새 Prism 인스턴스로 복사. 예전 인스턴스(앱 폴더·공식 런처 연결 등)는
    `prism_migrate`(확인 창 뒤, 켤 때 하루 한 번 물음): 새 Prism 인스턴스로 복사(월드·모드·git·전용 서버 설정·메모리), 예전 앱 폴더는 휴지통, 연결 원본은 그대로.
  - 게임 내용(데이터팩·리소스팩·모드·로컬 서버)은 `store.game_dir`(예전엔 앱 폴더 `dir_of` 를 써서 연결 인스턴스에서 엉뚱한 곳에 썼음). 전용 서버 설정은 앱 폴더 그대로.
  - 설정 동기화는 통합 작업실이 만든(`managed`) 인스턴스끼리만, 공식 런처 부분 없앰. e4mc: 바닐라는 넣지 않고 UPnP·playit 으로(호스트용 공식 런처 항목 없앰).
  - **Prism 을 설치하지 않으면 런처 창은 아예 안 뜨고 작업실만**(사용자 결정 2026-11-27 "설치를 안 하면 런처창이 안 뜨도록 작업실만"):
    `InstanceManager.launcherEnabled` 가 false 면 홈·실행 막대·서버 패널 탭·게임 로그·인스턴스/작업 뷰·상태 표시줄 인스턴스를 띄우지 않고 파일 탐색기만.
    결과를 localStorage `studio.launcherEnabled` 에 기억해, 다음에 켤 때는 보통 편집기처럼 지난 작업 폴더를 다시 열고 확장 실행기도 바로 켠다(`launcherOff`).
    Prism 을 나중에 설치하면 명령 팔레트 `Prism Launcher 설치`/`인스턴스 목록 새로고침` 으로 런처가 돌아온다. Prism 이 필요한 작업의 `[prism-missing]` 오류면 설치를 권한다.
  - 설치 파일(`applications/electron/resources/installer.nsh`) "함께 설치할 프로그램" 화면: Python 3.11+ 은 있으면 체크 해제·없으면 체크 고정(해제 불가),
    Prism 은 있으면 체크 해제·없으면 체크(해제 가능). winget 으로 사용자 범위 설치, 실패하면 내려받기 페이지. 조용한 설치(/S)는 없는 것만. `makensis -WX` 로 문법 확인.
    앱은 PATH 에 아직 없는 새 Python 도 표준 위치(%LOCALAPPDATA%\Programs\Python\Python3xx 등)에서 찾는다(`findSystemPython`, WindowsApps 별칭 제외).
  - 시험: `tests/test_prism.py`(형식·찾기·만들기/지우기·자동 연동·옮기기), `test_launchers.py`·`test_sync.py` 새 규칙으로. 공식 런처 모듈·시험(`official_launcher.py`·`official_rpc.py`·t13) 삭제.
- **Paper 플러그인 개발**(사용자 결정 2026-11-27: "페이퍼만 다룰거야" — Spigot·Velocity 는 하지 않음):
  - 템플릿 `packs.plugin_new` → `<게임 폴더>/plugins-src/<이름>`: Gradle(코틀린 DSL) + `compileOnly("io.papermc.paper:paper-api:<mc>.build.+")`(1.x 는 `<mc>-R0.1-SNAPSHOT`),
    저장소 `repo.papermc.io/repository/maven-public/`, 자바 툴체인 25(1.x 는 21), `plugin.yml`(name·version·main·api-version '<mc>') — docs.papermc.io(project-setup·plugin-yml)·
    paper-api 메이븐 메타데이터로 확인(2026-11, 26.3 은 `26.3.build.263-stable` 형식). 예제: 접속하면 인사(Adventure Component). 실제 Gradle 빌드로 jar 확인함.
  - Paper 서버 = 전용 서버 종류 `software="paper"`(서버 패널 [서버 열기] → 전용 서버 → "Paper 서버(플러그인)" 체크, 인스턴스 로더와 상관없이 같은 게임 버전).
    jar 는 Fill v3 API(`fill.papermc.io/v3/projects/paper/versions/<mc>/builds`)에서 가장 새 STABLE(없으면 가장 새 것), `downloads["server:default"]`
    의 sha256 검증, 주소는 fill-data.papermc.io 만, `data/server-jars/paper/` 에 두고 다시 씀. EULA 는 지금처럼 사용자가 직접 동의(자동 동의 금지).
  - F9(작업 뷰 "Paper 플러그인 빌드 후 서버에 넣기") = `plugin_build`: `./gradlew build` → 그 인스턴스의 모든 Paper 서버 `plugins/` 에 넣고(같은 이름의 예전 버전은 휴지통),
    켜져 있던 서버는 다시 시작(Paper 는 /reload 를 권하지 않음). Paper 서버가 없으면 만들라고 안내. Claude 작업 종류 "Paper 플러그인"(`plugins-src/` 만, `./gradlew build` 만).
  - 시험: `tests/test_plugins.py`(템플릿·이름 검사·STABLE 고르기·해시·주소 검사·plugins/ 넣기·다시 시작·EULA 자동 동의 안 함).
- **인스턴스 그룹(폴더)**(사용자 요청 2026-11-27 "인스턴스를 폴더 형식으로 묶어 정리"): Prism 그룹과 같게 — Prism 인스턴스 폴더의 `instgroups.json`
  (`{"formatVersion":"1","groups":{"<그룹>":{"hidden":false,"instances":["<폴더>"]}}}`)에 쓰고(`prism.set_group`, 빈 그룹은 지움), Prism 에서 바꾼 그룹은
  `PrismSync` 가 읽어 맞춘다(서명에 instgroups.json 수정 시각 포함). RPC `set_instance_group(id, group)`·`rename_group(old, new)`(new 없으면 풀기).
  화면: 사이드바 인스턴스 목록·홈이 그룹별 접히는 폴더(가나다순, "그룹 없음" 맨 뒤, 그룹이 하나도 없으면 예전처럼 한 줄 목록), 머리에 개수·이름 바꾸기·풀기,
  인스턴스(줄·카드)를 폴더 머리로 끌어다 놓으면 그 그룹으로, 관리 메뉴 "그룹(폴더) 지정"(있는 그룹/새 그룹/빼기). 접힘은 화면마다 localStorage.
  시험 `tests/test_prism.py::test_groups_follow_prism_both_ways`. e2e 에서 Playwright 마우스 끌기는 이 Electron(CDP 연결)에서 HTML 끌기 이벤트를
  만들지 않아, 끌기 이벤트를 직접 보내 확인함(놓으면 그룹·instgroups.json 바뀜).
- **서버 열기 보강**(사용자 요청 2026-11-27 "서버 여는 쪽이 부실 · 모드 복사가 이상 · 주소 연결이 잘 안 됨 · 자바가 없어서 오류"):
  - 자바: 설치 파일에 "Java 25 JDK" 체크박스(Temurin, winget `EclipseAdoptium.Temurin.25.JDK` — 목록에서 확인: Scope machine·ADDLOCAL=ALL,
    있으면 체크 해제·없으면 체크·해제 가능, 관리자 확인 창). `sidecar/java_find.py`: JAVA_HOME·PATH·표준 폴더에서 `release` 파일로 버전 읽기,
    빌드(F7·F9)는 JDK 25 를 찾아 JAVA_HOME 으로 맞춤, 명령 "Java 25 JDK 설치"(`java_install`). 서버 자바(`runner._runtime_java`):
    받아 둔 Mojang 런타임 → PC 의 같은 주 버전 자바 → Mojang 런타임만 받기(예전엔 게임 전체를 설치했음). 서버 폴더 `run.bat` 은 앱이 고른 자바의
    전체 경로로 다시 씀(Forge 설치기의 run.bat 이 PATH 의 자바 8 로 `@user_jvm_args.txt` 오류).
  - 모드 복사 규칙(`ServerRunner._sync_server_mods`): 클라이언트 전용(environment=client·clientSideOnly)·e4mc 만 빼고 넣음(정보를 못 읽는 jar 도 넣음 — 라이브러리),
    앱이 복사한 목록 `.studio-mods.json`(서버 폴더)으로 **사용자가 서버에 직접 넣은 jar 는 지우지 않음**, 같은 모드 id 의 옛 파일은 휴지통,
    config·defaultconfigs·kubejs 는 서버에 없거나 인스턴스 쪽이 더 새 파일만.
  - [모드 확인](`ds_mod_check`/`ds_mod_fix`): MOD-101 서버에 없음 · 102 인스턴스에 없음(참가자 필요) · 103 버전 다름 · 104 클라이언트 전용이 서버에 ·
    105 서버에 중복 · 106 로더 다름 → 골라서 복사(인스턴스↔서버)·빼기(휴지통). 서버가 켜져 있으면 서버 쪽은 안 바꿈.
  - 오류 코드(`sidecar/server_errors.py`): 서버 로그를 보고 JAVA-101/102 · EULA-101 · MOD-104/105/110/201/301 · NET-101 · WORLD-101 · MEM-101 · CRASH-101,
    아무것도 못 찾고 비정상 종료면 EXIT-<코드>, 시작 실패는 사이드카 오류 앞의 `[코드]`(JAVA-001). 카드에 코드·설명·관련 줄, [모드 확인]·[Java 설치]·[오류 복사].
  - 주소: UPnP 로 열면 Windows 방화벽 확인(`firewall.py`, NET-201 차단/202 규칙 없음) → [방화벽 허용](관리자 확인 창, 프로그램 기준 규칙
    "통합 작업실 - 마인크래프트 서버"), 같은 공유기용 사설 주소 표시(집 안에서는 공인 주소로 안 되는 공유기가 많음), [친구가 못 들어와요] = 지금 방식을 닫고 다음 방식으로.
  - playit 연결 풀림: API 가 키를 거부하면(401·403·Auth) 키 파일을 `playit.toml.invalid-<시각>` 으로 옮기고 에이전트를 꺼 '연결 안 됨'으로 →
    [playit 다시 연결](`claim(force)`, 쓰던 서버가 있으면 새 키로 에이전트 다시 켬)·[연결 확인](`verify`, 앱을 켤 때도 한 번). 오류 코드 PLAYIT-401.
  - 전용 서버 카드 [폴더](`ds_open_folder`).
- **playit "Agent is offline" 고침**(사용자 질문 2026-11-28, playit-agent 2.0.2 소스 bddcbed 로 비교):
  - 계정 연결(claim/setup → claim/exchange → `secret_key` TOML 저장, `Agent-Key` 헤더)은 공식과 같았다. 제어 채널·ping·데이터 중계는 공식 데몬이 하므로
    프로토콜을 직접 만들지 않는다.
  - 원인 ① 계정 연결 뒤 에이전트를 켜지 않음(서버가 playit 주소를 열 때만) ② 2.0 의 `playit.exe` 는 CLI 라 공식 Windows 서비스가 있으면 그쪽(다른 키)에 붙음
    ③ 에이전트 출력 pipe 를 읽지 않아 버퍼가 차면 멈출 수 있음.
  - 지금: 데몬 자산 `playitd-windows-x86_64-signed.exe`(Linux `playit-linux-*` = 데몬, 2.0.2 릴리스에 있는 것 확인)를 받아
    `--secret-path <키> --socket-path \\.\pipe\integrated-studio-playitd-<pid>` 로 실행. 계정이 연결돼 있으면 앱이 켜진 동안 계속 켜 둠(앱 시작·연결 직후 켬,
    서버가 안 써도 끄지 않음, 앱 종료·연결 해제 때만 끔), 꺼지면 2초부터 최대 60초 간격으로 다시 켬. 출력은 줄 단위로 읽어
    "playit connected; tunnels loaded" = 온라인(패널 "에이전트 온라인"), 키 거부 = 연결 해제(PLAYIT-401), 에이전트 수 초과 = PLAYIT-LIMIT,
    "failed to start playit agent" = PLAYIT-CONNECT. 모든 단계(받기·계정 연결 상태·키 교환·시작 인자·데몬 출력·종료 코드·API 실패)는
    `<앱 데이터>/server-host/playit/agent.log` 와 서버 콘솔에, 패널 [기록 보기]. 예전 `playit.exe` 만 있으면 "새로 받아야 함" → [playit 준비].
  - 실제 데몬 실행은 이 개발 환경에서 막혀 시험하지 못함(가짜 데몬 출력으로 시험). Windows 에서 확인 필요.
- **playit "거부" 고침**(사용자 2026-11-28 "플레이잇이 거부한다 · 무료 플랜이라 터널 만드는 게 막힘", 공식 api_client 2.0.2 로 확인):
  - 앱이 터널을 origin `default`(계정의 기본 에이전트)로 만들어, 앱이 연결한 자기 관리(self-managed) 에이전트 키로는
    `SelfManagedAgentCanOnlyAffectSelf`/`DefaultAgentNotSupported` 로 거부됨 → `/agents/rundata` 로 이 에이전트 id 를 얻어
    origin `{type:"agent", data:{agent_id, local_ip, local_port}}` 로 만들고, 업데이트에도 agent_id.
  - 거부를 '키 무효'로 잘못 봐서 키를 떼던 것: 오류 형식 `{type:"auth", message:<AuthError>}` 를 읽어 공식 데몬과 같게
    `InvalidAgentKey`·`NoLongerValid` 만 연결 해제. JSON 아닌 401·403 은 망 차단으로 안내(PLAYIT-HTTP403). 오류 이름은 한국어 표(`PLAYIT_ERRORS`).
  - 무료 플랜 등으로 앱이 못 만들면(`RequiresPlayitPremium`·`RequiresVerifiedAccount`·한도·권한) 사용자가 playit.gg 웹사이트에서 이 에이전트에
    만든 Minecraft Java 터널(다른 서버가 안 쓰는 것)을 찾아 쓰고 로컬 포트를 서버에 맞춤(못 바꾸면 "Local Port 를 N 으로" 안내).
    없으면 [PLAYIT-CREATE] 로 웹사이트에서 만드는 방법 안내.
  - 터널 이름은 ASCII 만(사용자 로그 2026-11-28: `/tunnels/create` HTTP 400 validation "Tunnel name can only contain ASCII characters" —
    예전 이름 "통합 작업실 · <한글 서버 이름>"). `tunnelName(name, 서버 id)` = "studio <서버 이름의 ASCII 부분 | game-server> <서버 id 끝 8자>"(최대 60자,
    악센트는 기본 글자로, 그 밖의 비 ASCII 는 뺌). 가짜 API 도 실제처럼 비 ASCII 이름을 400 으로 거부. 시험: `parts.test.mjs` "playit 무료 플랜"(가짜 API 가 실제처럼 자기 에이전트 터널만 허용).
  - 시험: `tests/test_server_tools.py`, server-host `npm test` 20개(연결 풀림·다른 방식·오류 코드 추가), Windows 스모크(방화벽 PowerShell·자바 찾기).
- **playit 뺌 → 전용 서버는 주소 모드로**(사용자 결정 2026-11-28 "playit 은 너무 안 됨 · 모드 서버는 모드를 추가해서, Minekube Connect, playit 빼기"):
  - playit 코드·시험·UI·명령을 모두 지움(예전 저장 설정 `preference: "playit"` 은 자동으로). 위의 playit 관련 결정 기록은 지난 이력이다.
  - 전용 서버를 켤 때 `ServerRunner._ensure_address_mod` 가 Modrinth 에서 그 버전에 정확히 맞는 파일을 넣는다(실패해도 서버는 켜고 UPnP 로):
    바닐라·Fabric·NeoForge·Forge = **e4mc**(서버 mods/, Fabric 은 Fabric API 의존 자동) — 소스(vgskye/e4mc-minecraft-architectury 93ce8a8)로
    전용 서버에서도 `startTcpServerListener` 에 붙어 동작함을 확인, 로그 "Domain assigned: <주소>"(매번 바뀜), 참가자는 e4mc 필요 없음.
    바닐라 전용 서버는 Fabric 서버(+Fabric API+e4mc)로 켠다(서버 쪽 모드뿐이라 참가자는 바닐라). Paper = **Minekube Connect**
    (Modrinth "minekube-connect", 26.3 = connect-spigot.jar, plugins/) — 소스(minekube/connect-java 01970af)로 로그 "Your public address: <이름>.play.minekube.net",
    이름은 plugins/connect/config.yml endpoint 라 고정 주소. 서버 설정 `addressMod: false`(ds_update address_mod)면 넣지 않음.
  - 사이드카가 로그에서 주소를 읽어 `ds_address {id, provider: e4mc|minekube, address}` 알림 → host-manager 가 그 주소로 연다.
    순서: 전용 = 주소 모드(최대 45초 기다림) → UPnP, 싱글 LAN = e4mc → UPnP, 외부 = UPnP. 주소가 늦게 오면 UPnP 에서 바꾸고 매핑은 닫음.
    [친구가 못 들어와요] = 주소 모드 ↔ UPnP 전환.
  - 시험: 사이드카 `tests/test_server_tools.py`(서버 종류별 모드·플러그인, 실패 시 바닐라로, 로그 문구), `tests/conftest.py`(다른 시험이 인터넷에서 모드를 받지 않게),
    server-host `npm test` 18개(e4mc 주소·UPnP 전환·Minekube 고정 주소·늦게 온 주소).
- **고침(2026-11-28, 사용자 "모드 확인에서 고친 뒤 다시 시작해도 같은 오류 · 지워진 모드가 다시 받아짐 · 로그를 보고 고치게 · 포트 25565 기본")**:
  - 원인: 서버를 켤 때마다 `_sync_server_mods` 가 인스턴스 모드를 다시 복사하고, `_ensure_address_mod` 가 e4mc(·Fabric API)를 다시 받았다.
    [모드 확인]도 뺀 모드를 MOD-101 로 다시 권해 되돌리는 순환이 있었다.
  - 지금: [모드 확인]의 "서버에서 빼기"는 `.studio-mods.json` 의 `excluded {ids, files}` 에 기억 → 복사·다운로드 안 함(e4mc 를 뺐거나
    Fabric 서버에서 Fabric API 를 뺐으면 e4mc 를 넣지 않고 UPnP 로). 뺀 모드는 MOD-107(기본으로 안 고름) "다시 넣기"(`unexclude`)로 되돌림.
    "인스턴스 → 서버로 복사"를 고르면 기억을 지움.
  - 서버 로그로 원인 찾기(`sidecar/server_log_mods.py`): logs/latest.log 끝부분 + 가장 새 crash-reports 를 읽어
    LOG-201 없는 의존 모드(Fabric "requires … which is missing!", NeoForge "Mod ID: 'y', Requested by: 'x'" → 인스턴스에 있으면 서버로 복사),
    LOG-104 클라이언트 코드 호출("invalid dist DEDICATED_SERVER" 등 → 근처 Mixin 설정·스택 패키지로 jar 찾아 빼기),
    LOG-301 오류에 이름이 나온 모드("Mod File:", "Failure message:", "-- MOD id --", Mixin, "from mod" → 원인일 수 있음, 기본으로 안 고름).
    각 항목에 근거 로그 줄(evidence). jar 비교로 이미 찾은 것엔 근거만 붙임. 카드의 오류 칸에 [모드 확인(로그로 원인 찾기)].
  - 포트: 새 서버·포트가 막혔을 때 25565 먼저(`default_port`), 이 앱이 이미 켠 다른 서버의 포트는 피함(동시에 켤 때).
  - 시험: `tests/test_server_tools.py`(뺀 모드 유지·다시 넣기, e4mc 다시 안 받음, 기본 포트, 로그로 찾기).
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
- **수정하면 항상 EXE 를 올린다**(사용자 결정 2026-11-27): 커밋·푸시 뒤 `integrated-studio-windows.yml` 을 실행한다.
  이전 빌드가 아직 돌고 있으면 그 빌드를 취소하고 새로 실행한다.
- 외부 라이브러리 버전은 추측하지 말고 설치 시점의 최신 안정판을 확인해서 쓴다. Theia·CommandCrafter·minecraft-launcher-lib는 빠르게 바뀐다.
