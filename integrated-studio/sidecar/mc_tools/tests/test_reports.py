"""버전별 자료: pack_format 읽기, /reload 대상 분류, 바닐라 추출."""
import json
import zipfile

from mc_tools.reports import VersionData


def test_pack_formats_from_version_json(env):
    assert env.vd.pack_formats == {"data": (121, 0), "resource": (97, 1)}
    assert env.vd.pack_format_json("resource") == [97, 1]


def test_classify(env):
    c = env.vd.classify()
    for k in ("function", "recipe", "advancement", "loot_table", "predicate", "tags/block", "tags/item", "tags/function"):
        assert k in c["reload"], k
    for k in ("worldgen/biome", "worldgen/placed_feature", "enchantment", "dimension_type", "tags/worldgen/biome"):
        assert k in c["world"], k
    assert "datapacks" not in c["world"]


def test_unknown_kind_is_world_reload(env):
    assert env.vd.needs_world_reload("something_new")
    assert not env.vd.needs_world_reload("function")


def test_registry_ids_dynamic(env):
    assert "minecraft:sharpness" in env.vd.registry_ids("enchantment")
    assert "minecraft:diamond" in env.vd.registry_ids("item")
    assert env.vd.registry_ids("nope_registry") is None


def test_extract_vanilla_from_jar(tmp_path):
    data = tmp_path / "data"
    jar = data / "minecraft" / "versions" / "9.9" / "9.9.jar"
    jar.parent.mkdir(parents=True)
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("version.json", json.dumps({"id": "9.9", "pack_version": {"data_major": 200, "data_minor": 0,
                                                                            "resource_major": 150, "resource_minor": 2}}))
        z.writestr("data/minecraft/recipe/a.json", "{}")
        z.writestr("data/minecraft/structure/big.nbt", b"x")
        z.writestr("data/minecraft/../../evil.json", "{}")
        z.writestr("assets/minecraft/models/block/cube_all.json", "{}")
    vd = VersionData(data, "9.9")
    vd.extract_vanilla()
    assert (vd.vanilla_dir / "data/minecraft/recipe/a.json").is_file()
    assert not (vd.vanilla_dir / "data/minecraft/structure").exists()
    assert not (tmp_path / "evil.json").exists() and not (data / "evil.json").exists()
    assert "assets/minecraft/models/block/cube_all.json" in vd.assets_index
    assert vd.pack_formats["data"] == (200, 0)
