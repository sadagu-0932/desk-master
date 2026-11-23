---
name: datapack
description: 마인크래프트 데이터팩(함수·발전과제·레시피·루트테이블·태그·프레디케이트·월드 생성)을 만들거나 고칠 때 쓴다. mc-tools 로 그 버전의 문법·ID 를 조회하고, 검사·적용까지 끝낸다.
---

# 데이터팩 만들기

## 순서 (건너뛰지 않는다)
1. **자료 준비**: 처음이면 `prepare_version_data` (그 인스턴스 버전의 명령어 트리·ID·바닐라 JSON).
2. **뼈대**: 새 팩이면 `scaffold_datapack(name, namespace)` — pack.mcmeta 형식 번호와 load·tick 태그가 맞게 만들어진다. pack.mcmeta 를 직접 쓰지 않는다.
3. **조회하며 작성**: 명령어 한 줄을 쓰기 전에
   - 모르는 명령어 구조 → `command_syntax("execute if")` 처럼 한 단계씩
   - 쓴 줄 확인 → `check_command`
   - 블록·아이템·엔티티·효과·인챈트 ID → `registry_search`, 블록 상태 → `block_states`
   - 발전과제·레시피·루트테이블·태그 JSON → `vanilla_file` 로 바닐라 예시를 보고 같은 모양으로
4. **검사**: `validate_datapack("datapacks/<팩>")` — 오류가 0개가 될 때까지 고친다. 파일을 고칠 때마다 훅이 자동으로 검사한다.
5. **적용**: `apply_changes([바뀐 파일들])` → `status` 확인.
   - `log_errors` 가 있으면 그 줄을 읽고 고친 뒤 다시 검사·적용한다.
   - `needs_confirmation` 이 있으면 사용자에게 묻고 `confirm: true` 로 다시 부른다.
6. **보고**: 무엇을 만들었는지, 상태(바로 적용됨 / 월드 재접속 필요 / 재시작 필요), 게임에서 확인하는 법.

## 빠짐없이 만들 것
요청이 게임에서 실제로 동작하려면 필요한 파일을 전부 만든다:
- 매 틱 확인이 필요하면 tick 함수와 `minecraft:tick` 함수 태그, 처음 한 번 준비(스코어보드 목표 만들기 등)는 load 함수와 `minecraft:load` 태그
- 함수가 부르는 다른 함수, 쓰는 스코어보드 목표·저장소, 발전과제의 rewards 함수
- 아이템·블록을 조건으로 쓰면 필요한 태그, 보상 루트테이블 등

## 폴더 규칙
- `data/<네임스페이스>/<종류>/…` — 종류 폴더 이름은 그 버전 바닐라와 같아야 한다(`validate_datapack` 이 구버전 이름을 잡는다). 확실하지 않으면 `vanilla_file("")` 로 바닐라 폴더 목록을 본다.
- 이름은 소문자·숫자·`_ . - /` 만. 대문자·공백·한글 불가.
- 네임스페이스로 `minecraft` 를 쓰지 않는다(단, `minecraft:load`·`minecraft:tick` 함수 태그는 `data/minecraft/tags/function/` 에 둔다).
- 작업 원본은 `datapacks/<팩>/`. `saves/<월드>/datapacks/` 를 직접 고치지 않는다(적용 때 동기화됨).

## 자주 틀리는 점
- 함수 파일 명령어 앞에 `/` 를 붙임
- `@e` 를 type·tag·distance 로 좁히지 않아 매 틱 무거움
- 하나만 받는 자리에 `@a`·`@e` 를 씀 → `@p`, `@s`, `@e[limit=1]`
- 매크로 줄(`$`)에 `$(변수)` 가 없음, 또는 변수 없이 매크로 함수를 부름
- 월드 생성·차원·인챈트 같은 데이터는 `/reload` 로 바뀌지 않음 → `apply_changes` 가 "월드 재접속 필요"를 알려 준다. 월드 생성은 새로 생기는 청크부터 바뀐다는 것도 함께 알린다.

## 완료 조건
`validate_datapack` 오류 0개 + `apply_changes` 의 `log_errors` 없음 + 상태를 사용자에게 알림.
