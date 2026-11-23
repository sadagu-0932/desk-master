<!-- mc-tools:start — 통합 작업실이 관리하는 부분입니다. 이 표시 사이는 자동으로 다시 쓰입니다. -->
# 이 인스턴스에서 일하는 규칙 (통합 작업실)

| 항목 | 값 |
|---|---|
| 게임 버전 | {{VERSION}} |
| 로더 | {{LOADER}} |
| 선택된 월드 | {{WORLD}} |
| 데이터팩 작업 원본 | `datapacks/<팩>/` (적용하면 `saves/<월드>/datapacks/` 로 동기화됨) |
| 리소스팩 | `resourcepacks/<팩>/` |
| Fabric 모드 프로젝트 | `mods-src/<모드ID>/` (빌드 결과는 `mods/`) |

## 반드시 지킬 것
1. **이 인스턴스 폴더 밖은 읽거나 고치지 않는다.** 파일을 지울 때는 휴지통으로 보낸다.
2. **명령어·ID·JSON 형식을 기억으로 쓰지 않는다.** 버전마다 바뀐다. 반드시 `mc-tools` 로 조회한다.
   - 명령어 문법: `command_syntax`, 쓰기 전 확인: `check_command`
   - ID: `registry_search`, 블록 상태: `block_states`, JSON 모양: `vanilla_file`
3. **요청이 끝까지 동작하는 데 필요한 파일은 빠짐없이 전부 만든다.**
   함수·함수 태그(load/tick)·발전과제·레시피·루트테이블·태그·언어 파일·텍스처·모델·블록상태·아이템 정의 등.
4. 작업 순서: `scaffold_*` → 파일 작성 → `validate_*` (오류면 고치고 다시) → `apply_changes` → 결과의 `log_errors` 확인.
5. **validate 와 apply_changes 가 통과하기 전에는 "완료"라고 말하지 않는다.**
   - `apply_changes` 의 `needs_confirmation` 이 있으면(월드 재접속·게임 재시작·새 팩 켜기) 사용자에게 묻고, 허락하면 `confirm: true` 로 다시 부른다.
6. **작업 끝에 적용 상태를 사용자에게 알린다:** "바로 적용됨" / "월드 재접속 필요" / "재시작 필요" (`apply_changes` 의 `status`).
   - `bridge_missing` 이면 사용자가 게임에서 직접 해야 할 일(`notes`)을 그대로 알려 준다.
7. 바닐라 원본 에셋을 리소스팩에 그대로 복사해 넣지 않는다(바꾼 파일만).
8. 사용자에게 보이는 문구는 한국어로 쓴다.

자세한 순서는 `.claude/skills/` 의 datapack · fabric-mod · resourcepack 스킬을 따른다.
<!-- mc-tools:end -->
