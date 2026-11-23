"""명령어 트리 검사(샘플: 실제 26.3 commands.json 일부)."""
import pytest

from mc_tools.commands import CommandChecker


@pytest.fixture
def ck(env):
    vd = env.vd
    return CommandChecker(vd.commands, vd.registry_ids, vd.blocks, lambda r, i: i in vd.tag_ids(r))


@pytest.mark.parametrize("line", [
    "say hello world",
    "give @p minecraft:diamond 5",
    "give @a diamond",
    "execute as @a at @s if block ~ ~-1 ~ minecraft:campfire[lit=true] run effect give @s minecraft:regeneration 5 1 true",
    "execute if entity @e[type=zombie,distance=..5] run say near",
    "scoreboard objectives add timer dummy",
    "scoreboard players add @s timer 1",
    "tellraw @a {text:\"hi\",color:\"green\"}",
    "setblock ~ ~1 ~ stone",
    "summon minecraft:zombie ~ ~ ~ {NoAI:1b}",
    "schedule function mypack:tick 1s",
    "gamerule keep_inventory true",
    "tp @s ~ ~1 ~",
    "particle minecraft:flame ~ ~1 ~ 0.1 0.1 0.1 0.01 10",
    "reload",
    "datapack enable \"file/my_pack\"",
    "return run function mypack:x",
])
def test_ok(ck, line):
    r = ck.check(line)
    assert r.ok, r.issues


@pytest.mark.parametrize("line,expect", [
    ("giv @s diamond", "알 수 없는 명령어"),
    ("give @p diamond_swrod 1", "없는 ID"),
    ("give @e diamond", "플레이어만"),
    ("give @p diamond 0", "1 이상"),
    ("effect give @s minecraft:speedy 5", "없는 ID"),
    ("execute if block ~ ~-1 ~ campfire[lit=maybe] run say hi", "'lit' 값"),
    ("execute if block ~ ~-1 ~ campfire[litt=true] run say hi", "'litt' 상태가 없습니다"),
    ("kill @e[type=minecraft:zombi]", "없는 ID"),
    ("tellraw @a {text:\"hi\"", "괄호가 닫히지"),
    ("tp @s ^ ^1 ~", "섞어 쓸 수 없습니다"),
    ("gamerule keepInventory true", "올 수 없습니다"),
    ("setblock ~ ~ ~ #minecraft:logs", r"태그\(#\)"),
    ("scoreboard players add @s", "더 필요합니다"),
    ("say", "더 와야|더 필요"),
    ("/say hi", "'/'"),
    ("give  @p diamond", "공백이 두 칸"),
])
def test_errors(ck, line, expect):
    import re
    r = ck.check(line)
    assert not r.ok
    assert re.search(expect, r.issues[0].message), r.issues[0].message


def test_function_refs(ck):
    r = ck.check("execute as @a run function campfire:reward")
    assert r.ok and r.refs == [("function", "campfire:reward")]
    r = ck.check("schedule function #campfire:later 1s")
    assert r.ok and r.refs == [("function_tag", "campfire:later")]


def test_other_namespace_ids_not_flagged(ck):
    # 모드·다른 팩의 ID 는 registries.json 에 없으니 오류로 보지 않는다
    assert ck.check("give @s mymod:ruby 1").ok


def test_syntax(ck):
    names = {n["name"] for n in ck.syntax(["execute"])}
    assert {"as", "at", "if", "run"} <= names
    give = ck.syntax(["give"])
    assert give[0]["parser"] == "minecraft:entity"
