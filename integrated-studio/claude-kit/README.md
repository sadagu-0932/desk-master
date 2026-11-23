# claude-kit — Claude 패널의 제작·검증·적용 시스템

Claude 계정만 있으면 누구나 같은 결과가 나오도록, 필요한 것은 전부 앱에 들어 있다(사용자 계정의 스킬·플러그인을 쓰지 않음).

```
요청 → scaffold_* (필요한 파일 전부) → 작성 → validate_* (훅이 자동 검사, 오류면 Claude 가 고침)
     → apply_changes (종류별 자동 적용) → 게임 로그 오류 확인 → 상태 보고
```

| 파일 | 역할 | 인스턴스에 설치되는 위치 |
|---|---|---|
| `skills/datapack`, `skills/fabric-mod`, `skills/resourcepack` | 작업 순서·규칙(버전마다 다른 값은 적지 않고 도구로 조회) | `.claude/skills/` |
| `settings.json` | 훅(PostToolUse = 바뀐 팩 검사, Stop = 마무리 전 전체 검사·적용 확인), mc-tools 허용 | `.claude/settings.json` 에 합침 |
| `CLAUDE.instance.md` | 인스턴스 규칙(버전·로더·월드·경로·완료 조건) | `CLAUDE.md` 의 `mc-tools:start~end` 구간 |
| (생성) | MCP 서버 `mc-tools` 등록 | `.mcp.json` |

코드는 `sidecar/mc_tools/`:

| 모듈 | 내용 |
|---|---|
| `reports.py` | 버전별 정답 자료: 데이터 생성기(`--reports`) → `data/reports/<버전>/reports/`, 클라이언트 jar 의 `data/minecraft/**` → `data/vanilla/<버전>/`, pack_format(version.json), /reload 대상·월드 재접속 대상 목록(`reload_kinds.json`) |
| `commands.py` | commands.json 트리로 명령어 한 줄 검사(리터럴·인자·redirect, 숫자 범위, 좌표, 선택자, 블록 상태, ID) |
| `validate.py` | 데이터팩·리소스팩·모드 에셋 검사 → `파일:줄: 설명` |
| `scaffold.py` | 데이터팩·리소스팩·Fabric 모드 뼈대, 아이템·블록(등록 코드·16×16 텍스처·모델·아이템 정의·블록상태·루트테이블·언어 키) |
| `apply.py` | 종류별 적용, 월드 datapacks 백업, 확인이 필요한 동작, 적용 뒤 latest.log 오류 |
| `server.py` | MCP 서버(stdio, 의존 패키지 없음) |
| `hook.py` | Claude Code 훅(exec 형식: `python hook.py post|stop`) |
| `kit.py` | 인스턴스에 설치: `python -m mc_tools.kit install <인스턴스>` / `install-all` |

시험: `cd sidecar && python -m pytest mc_tools/tests` (게임·네트워크 없이, 실제 26.3 commands.json 일부로).

## 앱 쪽에 연결해야 하는 것 (이 브랜치 범위 밖 — 다른 폴더라 손대지 않음)

1. **인스턴스를 만들 때 키트 설치**: `instances.create` 끝(또는 사이드카 시작 때 모든 인스턴스)에서
   `mc_tools.kit.install(<인스턴스 폴더>, python=sys.executable)` 호출. 지금은 수동: `python -m mc_tools.kit install-all`.
2. **버전 자료 준비**: 인스턴스 설치(`runner.install`) 뒤 `VersionData(data, 버전).ensure()` 호출.
   지금은 MCP 도구가 처음 쓰일 때 자동으로 만든다(1~2분).
3. **게임 연결(브리지)**: 앱이 `<인스턴스>/.studio/bridge/requests/*.json` 을 지켜보고 처리한 뒤
   `responses/<id>.json` 에 `{"id","ok","message"}` 를 쓴다.
   - `reload` → `commandcrafter.reload` (로컬 서버면 `/reload`)
   - `reload_resources` → `commandcrafter.reloadResources`
   - `run_command` → `commandcrafter.runCommand(params.command)`
   - `rejoin_world`, `restart_game` → 사용자에게 안내(공식 런처가 켠 게임은 앱이 끌 수 없음)
   연결 전에는 apply_changes 가 `bridge_missing: true` 와 사람이 할 일("게임에서 /reload")을 돌려준다.
4. **설치 파일에 claude-kit 넣기**: `applications/electron/electron-builder.yml` 의 extraResources 에
   `../../claude-kit` → `sidecar/claude-kit` (kit.py 가 사이드카 옆에서도 찾는다).
5. **선택된 월드**: 앱에서 월드를 고르면 `<인스턴스>/.studio/selected_world` 에 이름을 쓴다(없으면 가장 최근 월드).

## 실제 Windows PC 에서 확인할 것

- [ ] `python -m mc_tools.kit install-all` 뒤 Claude 패널에서 `/mcp` 에 mc-tools 가 연결됨, 스킬 3개가 보임
- [ ] 처음 도구 호출 때 데이터 생성기가 돌아 `data/reports/<버전>` 과 `data/vanilla/<버전>` 이 생김(자바 런타임·서버 jar 받기 포함)
- [ ] 훅: 함수 파일에 틀린 줄을 쓰면 Claude 가 오류를 받고 스스로 고침(PostToolUse, 종료 코드 2), 경로에 공백·한글이 있어도 exec 형식으로 실행됨
- [ ] Stop 훅: 검사 오류·미적용 변경이 남으면 마무리하지 못하고 계속 고침, 4번 뒤에는 멈춤
- [ ] 데이터팩 함수만 바꿈 → 월드 datapacks 백업·동기화 → (브리지 연결 후) /reload → "바로 적용됨", 게임 로그 오류가 결과에 들어옴
- [ ] 새 데이터팩 → 확인 후 `/datapack enable "file/<팩>"`
- [ ] 월드 생성·인챈트 변경 → "월드 재접속 필요" + 확인 후 재접속, 새 청크부터 바뀌는지
- [ ] 리소스팩: options.txt 에 켜짐, 켜진 팩 수정은 리소스 다시 불러오기, 처음 켠 팩은 "재시작 필요"
- [ ] 모드: `build_mod` 가 JDK 25 로 빌드되고 컴파일 오류만 추려짐, jar 가 mods/ 로, "재시작 필요" → 재실행 후 아이템·블록 텍스처·이름(한국어) 확인
- [ ] 아이템·블록 등록 Java 코드가 26.3 + Fabric 에서 컴파일되는지(안 되면 build_mod 오류를 보고 Claude 가 고치는지)
- [ ] 게임이 켜져 있는지 판단(latest.log)이 공식 런처 실행과 맞는지
