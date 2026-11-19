# Core UI

파츠를 붙여서 확장하는 마인크래프트 UI 시스템 (Fabric 모드, Minecraft Java 26.3).

화면은 **서버가 정의**하고 **클라이언트가 그립니다**. 핵심 로직(`api`, `core` 패키지)에는 마인크래프트 코드가 없습니다. 그래서 나중에 Paper 플러그인 렌더러(상자 GUI)를 붙여도 파츠를 그대로 쓸 수 있습니다.

```
[파츠]  메인 메뉴, 내 상태, 카운터 예제, JSON 설정 화면 ...
   │  "버튼 3개, 입력칸 1개" 처럼 선언만 함
   ▼
[코어]  화면 등록, 액션 실행, 자리표시자, 뒤로 가기 기록, 클릭 검증
   │
   ├─▶ Fabric 클라이언트 화면   ← 지금 있음
   └─▶ Paper 상자 GUI           ← 나중에 (UiPlatform 구현만 추가)
```

## 실행

준비물: **JDK 25**, IntelliJ IDEA 2025.3 이상

```bash
./gradlew runClient     # 게임 실행 → 월드 접속 → U 키 (또는 /ui open main)
./gradlew runServer     # 전용 서버
./gradlew test          # 코어 로직 테스트 (게임 없이)
./gradlew runClientGameTest   # 실제 게임을 띄워 화면 흐름 확인 + 스크린샷
./gradlew build         # build/libs/coreui-0.1.0.jar
```

서버와 클라이언트 **둘 다** 이 모드와 Fabric API가 필요합니다.

## 명령어

| 명령어 | 설명 |
|---|---|
| `/ui open <화면> [대상]` | 화면 열기. 대상 지정은 관리자만 |
| `/ui list` | 열 수 있는 화면 목록 |
| `/ui close` | 닫기 |
| `/ui parts` | 파츠와 액션 목록 (관리자) |
| `/ui reload` | 설정·파츠 다시 읽기 (관리자) |

## 들어 있는 파츠

| 파츠 | 화면 | 설명 |
|---|---|---|
| `core` | - | 기본 액션: `open:<화면>` `back` `close` `refresh` `command:<명령어>` `message:<글자>` |
| `menu` | `main` | 열 수 있는 화면을 **자동으로** 버튼으로 모음. 새 파츠를 붙이면 알아서 나타남 |
| `status` | `status` | 체력·배고픔·좌표. 마인크래프트 정보를 쓰는 파츠 예제 |
| `demo` | `demo/counter` | 커스텀 액션·자리표시자 예제 |
| (설정) | `example` | `config/coreui/screens/example.json` 에서 읽은 화면 |

파츠는 `config/coreui/parts.json` 에서 켜고 끕니다.

## 화면 만들기 ① JSON 파일 (코딩 없이)

`config/coreui/screens/` 에 `.json` 파일을 넣고 `/ui reload`.

```json
{
  "id": "shop",
  "title": "상점",
  "columns": 9,
  "rows": 3,
  "openable": true,
  "components": [
    {"type": "label",  "x": 0, "y": 0, "w": 9, "text": "{player}님 어서오세요"},
    {"type": "button", "id": "buy", "x": 0, "y": 1, "w": 3, "text": "다이아", "icon": "minecraft:diamond",
     "tooltip": "다이아 1개", "action": "command:give @s diamond"},
    {"type": "input",  "id": "msg", "x": 0, "y": 2, "w": 6, "hint": "할 말"},
    {"type": "button", "id": "say", "x": 6, "y": 2, "w": 3, "text": "말하기", "action": ["command:say {input:msg}", "close"]},
    {"type": "toggle", "id": "rain", "x": 3, "y": 1, "w": 3, "text": "비", "value": false,
     "on": "rain", "off": "clear", "action": "command:weather {value}"}
  ]
}
```

- **격자**: `x`, `y`, `w`, `h`는 칸 단위. 9열 기준이라 상자 GUI와 1칸 = 1슬롯으로 맞습니다.
- **컴포넌트**: `label`, `button`(+`icon`, `tooltip`), `toggle`(+`on`/`off`), `input`(+`hint`, `max`), `icon`(+`item`)
- **액션**: 문자열 하나 또는 배열. 위에서부터 차례로 실행.
- **자리표시자**: `{player}`, `{input:입력칸ID}`, `{value}`(누른 토글 값), 그리고 파츠가 등록한 것(`{health}`, `{demo_clicks}` …)
- `command:` 는 **플레이어 본인 권한**으로 실행됩니다. 일반 플레이어 화면에 관리자 명령어를 넣으면 실행되지 않습니다.

## 화면 만들기 ② 파츠 (자바 코드)

```java
public final class ShopPart implements UiPart {
    @Override public String id() { return "shop"; }

    @Override
    public void enable(PartContext ctx) {
        ctx.placeholder("coins", (viewer, arg) -> String.valueOf(Bank.get(viewer.uuid())));

        ctx.action("shop:buy", (c, item) -> {          // 버튼 action: "shop:buy:diamond"
            Bank.take(c.viewer().uuid(), 10);
            c.viewer().runCommand("give @s " + item);
            c.ui().refresh(c.viewer());
        });

        ctx.screen(UiScreen.builder("shop")
                .title("상점").size(9, 3).openable(true)
                .label(0, 0, 9, "가진 돈: {coins}")
                .iconButton("diamond", 0, 1, 3, "minecraft:diamond", "다이아 (10)", "shop:buy:diamond")
                .button("back", 6, 2, 3, "뒤로", "back")
                .build());
    }
}
```

- **이 모드 안에서**: `CoreUiMod.collectParts()` 목록에 추가
- **다른 모드에서**: 그 모드의 `fabric.mod.json`에 entrypoint 추가

  ```json
  "entrypoints": { "coreui:part": ["com.example.ShopPart"] }
  ```
- 플레이어마다 내용이 다른 화면: `ctx.screen("id", true, viewer -> UiScreen.builder(...)...build())`
- 마인크래프트 기능이 필요하면: `ServerPlayer p = FabricViewer.playerOf(ctx.viewer());`

## 새 위젯 종류 만들기 (클라이언트)

```java
WidgetRegistry.register("progress", (screen, c, x, y, w, h) -> {
    // c.integer("value", 0) 같은 속성을 읽어 위젯을 만들고 screen.addWidget(...)
});
```

그 뒤 화면 JSON에서 `{"type": "progress", "value": 70, ...}` 로 씁니다. 클라이언트에 위젯이 없으면 `[progress?]`로 표시됩니다.

## 보안

- 클라이언트는 "이 컴포넌트를 눌렀다"만 보냅니다. **무엇을 실행할지는 서버가 정합니다.**
- 서버는 세션 번호로 지금 열린 화면을 확인합니다. 오래된 화면, 남의 화면, 보내지 않은 버튼에서 온 클릭은 무시합니다.
- 입력값은 256자로 자르고, 줄바꿈과 제어 문자를 지웁니다.
- `openable: false` 화면은 관리자만 직접 열 수 있습니다. 파츠나 액션이 여는 것은 됩니다.

## 구조

```
src/main/java/com/deskmaster/coreui/
  api/      UiScreen, UiComponent, UiPart, PartContext, UiViewer ...   ← 마인크래프트 코드 없음
  core/     UiService(세션·액션·자리표시자), PartManager, ScreenJson   ← 마인크래프트 코드 없음
  fabric/   CoreUiMod, 패킷, 명령어, FabricViewer, parts/
src/client/java/.../client/   PartScreen(그리기), WidgetRegistry(위젯 종류)
src/test/java/                코어 단위 테스트
src/gametest/java/            실제 클라이언트 테스트 (스크린샷)
```

## 다음 할 일 후보

- Paper 플러그인 렌더러 (`api`/`core`를 `common` 모듈로 분리 → 상자 GUI로 그리기)
- 위젯 추가: 목록/페이지, 슬라이더, 탭, 진행 바
- 여러 칸 아이템 슬롯 (실제 아이템 넣고 빼기)
