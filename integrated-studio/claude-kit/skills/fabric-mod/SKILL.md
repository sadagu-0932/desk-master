---
name: fabric-mod
description: Fabric 모드(아이템·블록·기능)를 만들거나 고칠 때 쓴다. 프로젝트 뼈대·에셋은 mc-tools 로 만들고, 빌드해서 컴파일 오류를 없앤 뒤 테스트 인스턴스에 넣는다.
---

# Fabric 모드 만들기

## 순서
1. **뼈대**: 새 모드면 `scaffold_fabric_mod(name, mod_id, version, items, blocks)`.
   gradle 설정·메인 클래스·fabric.mod.json·언어 파일·에셋 폴더가 만들어진다(라이브러리 버전은 만들 때 최신 안정판을 확인).
   이미 있는 모드에 아이템·블록을 더하면 `add_mod_content(project_path, items, blocks)`.
2. **아이템·블록을 추가할 때 함께 생기는 것**(빠지면 게임에서 보라·검정 텍스처, 이름 대신 키가 보인다):
   - Java 등록 코드(ModItems / ModBlocks, 메인 클래스 onInitialize 에서 init 호출)
   - 16×16 텍스처(`assets/<모드>/textures/item|block/<id>.png`) — 임시 그림이니 사용자가 원하면 바꾼다
   - 모델(`models/item`, `models/block`), 아이템 정의(`items/<id>.json`), 블록상태(`blockstates/<id>.json`)
   - 블록 루트테이블(`data/<모드>/loot_table/blocks/<id>.json`), 언어 키(en_us·ko_kr)
3. **코드 작성**: 기능을 더할 때 클래스·메서드 이름을 기억으로 확정하지 않는다. 빌드해서 컴파일러로 확인한다.
   JSON(레시피·태그·루트테이블)은 `vanilla_file` 로 바닐라 예시를 보고 같은 모양으로.
4. **빌드**: `build_mod("mods-src/<모드ID>")` — 오류가 나오면 그 파일·줄을 고치고 다시 빌드. 0개가 될 때까지.
5. **적용**: `apply_changes(["mods-src/<모드ID>/…"])` → 빌드·검사 후 jar 를 `mods/` 에 넣는다. 상태는 "재시작 필요".
   게임이 켜져 있으면 `needs_confirmation` 의 재시작을 사용자에게 묻는다.
6. **확인**: 다음 실행 뒤 `apply_changes` 결과나 게임 로그에서 모드 오류(크래시, 누락된 텍스처·모델 경고)를 확인한다.
7. **보고**: 만든 것, 상태("재시작 필요"), 게임에서 얻는 법(예: `/give @s <모드ID>:<id>`).

## 규칙
- 모드 ID·아이템 ID 는 소문자·숫자·`_` 만.
- 리소스 경로 이름은 소문자. `assets/<모드ID>/…`, `data/<모드ID>/…`.
- 빌드는 JDK 25(JAVA_HOME) 가 필요하다. 빌드 오류가 JDK 문제면 사용자에게 알린다.
- 모드 프로젝트 밖(다른 인스턴스·홈 폴더)을 고치지 않는다.

## 완료 조건
`build_mod` 성공(컴파일 오류 0) + `apply_changes` 오류 없음 + 상태("재시작 필요")와 확인 방법을 사용자에게 알림.
