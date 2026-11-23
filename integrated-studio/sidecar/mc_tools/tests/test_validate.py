"""validate_datapack 이 정상 팩은 통과시키고 틀린 팩의 오류를 모두 잡는지."""
from mc_tools.validate import validate_datapack


def test_good_pack_passes(env):
    rep = validate_datapack(env.vd, env.copy_pack("good_pack"))
    assert rep.ok, rep.summary()
    assert rep.checked_files >= 10


def test_bad_pack_catches_everything(env):
    rep = validate_datapack(env.vd, env.copy_pack("bad_pack"))
    text = rep.summary()
    assert not rep.ok

    def has(file_part, msg_part):
        return any(file_part in p.file and msg_part in p.message for p in rep.errors)

    assert has("pack.mcmeta", "min_format"), text                     # 이 버전 pack.mcmeta 형식
    assert has("pack.mcmeta", "pack_format 48"), text                 # 형식 번호 불일치
    assert has("data/bad/functions", "구버전 폴더 이름"), text          # 구버전 폴더 이름
    assert has("main.mcfunction", "알 수 없는 명령어: 'giv'") or has("main.mcfunction", "알 수 없는 명령어입니다: 'giv'"), text
    assert has("main.mcfunction", "없는 ID 입니다(item): minecraft:diamon"), text   # 없는 ID
    assert has("main.mcfunction", "true 또는 false"), text            # 인자 형식
    assert has("main.mcfunction", "괄호가 닫히지"), text                # 괄호
    assert has("main.mcfunction", "'/'"), text                        # 슬래시
    assert has("main.mcfunction", "없는 함수를 부릅니다: bad:missing"), text  # 없는 함수 참조
    assert has("tags/function/load.json", "bad:nope"), text           # 태그가 없는 함수 참조
    assert has("broken.json", "JSON 문법 오류"), text                  # 깨진 JSON
    assert has("tags/item/wrong.json", "not_an_item"), text           # 태그 안의 없는 ID
    assert has("UpperCase.mcfunction", "소문자"), text                 # 대문자 파일 이름


def test_line_numbers(env):
    rep = validate_datapack(env.vd, env.copy_pack("bad_pack"))
    lines = {p.line for p in rep.errors if p.file.endswith("main.mcfunction")}
    assert {2, 3, 4, 5, 6, 7} <= lines
    assert all(p.text().startswith(p.file) for p in rep.errors)


def test_world_kinds_folder_known(env):
    pack = env.copy_pack("good_pack", "wg")
    f = pack / "data" / "wg" / "worldgen" / "biome" / "hot.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"temperature": 2.0}', "utf-8")
    assert validate_datapack(env.vd, pack).ok
