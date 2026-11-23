---
name: resourcepack
description: 마인크래프트 리소스팩(텍스처·모델·블록상태·아이템 정의·언어·소리)을 만들거나 고칠 때 쓴다. 바꾼 파일만 넣고, 검사 후 게임에 적용한다.
---

# 리소스팩 만들기

## 순서
1. **뼈대**: 새 팩이면 `scaffold_resourcepack(name)` — 그 버전 형식 번호로 pack.mcmeta 를 만든다.
2. **어디를 바꿀지 찾기**: 바꿀 대상의 ID 는 `registry_search` (item·block), 블록 상태별 모양은 `block_states`.
   바닐라 에셋 경로는 `assets/minecraft/…` 와 같은 경로에 **바꾼 파일만** 넣는다. 바닐라 원본을 통째로 복사하지 않는다.
3. **파일 작성**
   - 텍스처: `assets/<ns>/textures/block|item/<이름>.png` — 정사각형(16×16 기본). 애니메이션은 세로로 이어 붙이고 `<이름>.png.mcmeta`
   - 모델: `models/…json` 의 `parent`·`textures` 가 실제로 있는 파일을 가리켜야 한다
   - 블록상태·아이템 정의(`items/…json`)의 `model` 도 실제 모델을 가리켜야 한다
   - 언어: `lang/ko_kr.json`
4. **검사**: `validate_resourcepack("resourcepacks/<팩>")` — 오류 0개까지.
5. **적용**: `apply_changes([바뀐 파일])` — options.txt 에 팩을 켜고 리소스를 다시 불러온다.
   게임이 켜진 상태에서 처음 켠 팩이면 "재시작 필요"(또는 옵션 → 리소스팩에서 켜기)가 나온다.
6. **보고**: 바꾼 것, 상태, 게임에서 확인하는 법.

## 자주 틀리는 점
- 파일 이름 대문자·공백 → 게임이 못 읽음
- 텍스처 크기가 정사각형이 아님
- 모델이 없는 텍스처를 가리킴(보라·검정 체크무늬)
- pack.mcmeta 형식 번호가 버전과 맞지 않음 → 직접 쓰지 말고 scaffold 로

## 완료 조건
`validate_resourcepack` 오류 0개 + `apply_changes` 오류 없음 + 상태를 사용자에게 알림.
