"""scaffold 결과가 validate 를 통과하는지."""
import json

import pytest

from mc_tools import scaffold
from mc_tools.context import ToolError
from mc_tools.validate import png_size, validate_datapack, validate_mod, validate_resourcepack


def test_datapack_scaffold_validates(env):
    r = scaffold.scaffold_datapack(env.inst, env.vd, "my_pack", "mine")
    rep = validate_datapack(env.vd, env.inst_dir / "datapacks" / "my_pack")
    assert rep.ok, rep.summary()
    meta = json.loads((env.inst_dir / "datapacks/my_pack/pack.mcmeta").read_text("utf-8"))
    assert meta["pack"]["min_format"] == 121 and meta["pack"]["max_format"] == 121   # version.json 에서 읽음
    assert "datapacks/my_pack/data/minecraft/tags/function/tick.json" in r["created"]


def test_datapack_scaffold_rejects_bad_names(env):
    with pytest.raises(ToolError):
        scaffold.scaffold_datapack(env.inst, env.vd, "My Pack", "mine")
    with pytest.raises(ToolError):
        scaffold.scaffold_datapack(env.inst, env.vd, "ok", "minecraft")
    with pytest.raises(ToolError):
        scaffold.scaffold_datapack(env.inst, env.vd, "../escape", "mine")


def test_resourcepack_scaffold_validates(env):
    scaffold.scaffold_resourcepack(env.inst, env.vd, "my_rp")
    rep = validate_resourcepack(env.vd, env.inst_dir / "resourcepacks" / "my_rp")
    assert rep.ok, rep.summary()
    meta = json.loads((env.inst_dir / "resourcepacks/my_rp/pack.mcmeta").read_text("utf-8"))
    assert meta["pack"]["min_format"] == [97, 1]


def _fake_mod_project(env, mod_id="gems"):
    root = env.inst_dir / "mods-src" / mod_id
    res = root / "src/main/resources"
    java = root / "src/main/java/com/example" / mod_id
    java.mkdir(parents=True)
    (res / "assets" / mod_id / "lang").mkdir(parents=True)
    (root / "build.gradle").write_text("plugins {}\n", "utf-8")
    (res / "fabric.mod.json").write_text(json.dumps({"schemaVersion": 1, "id": mod_id, "version": "${version}",
                                                     "entrypoints": {"main": [f"com.example.{mod_id}.GemsMod"]}}), "utf-8")
    (java / "GemsMod.java").write_text(
        "package com.example.gems;\n\npublic class GemsMod implements ModInitializer {\n"
        "\t@Override\n\tpublic void onInitialize() {\n\t\tLOGGER.info(\"x\");\n\t}\n}\n", "utf-8")
    return root


def test_mod_content_all_files_and_validates(env):
    root = _fake_mod_project(env)
    scaffold.add_mod_content(env.inst, root, [{"id": "ruby", "name_ko": "루비", "name_en": "Ruby"}],
                             [{"id": "ruby_block", "name_ko": "루비 블록"}])
    a = root / "src/main/resources/assets/gems"
    for f in ("textures/item/ruby.png", "models/item/ruby.json", "items/ruby.json",
              "textures/block/ruby_block.png", "models/block/ruby_block.json", "blockstates/ruby_block.json",
              "items/ruby_block.json", "lang/ko_kr.json", "lang/en_us.json"):
        assert (a / f).is_file(), f
    assert (root / "src/main/resources/data/gems/loot_table/blocks/ruby_block.json").is_file()
    assert png_size(a / "textures/item/ruby.png") == (16, 16)
    ko = json.loads((a / "lang/ko_kr.json").read_text("utf-8"))
    assert ko == {"item.gems.ruby": "루비", "block.gems.ruby_block": "루비 블록"}
    java = root / "src/main/java/com/example/gems"
    assert "RUBY = register(\"ruby\"" in (java / "ModItems.java").read_text("utf-8")
    assert "RUBY_BLOCK" in (java / "ModBlocks.java").read_text("utf-8")
    main = (java / "GemsMod.java").read_text("utf-8")
    assert "ModItems.init();" in main and "ModBlocks.init();" in main
    rep = validate_mod(env.vd, root)
    assert rep.ok, rep.summary()
    # 두 번째 추가는 기존 것을 지키고 새것만 더한다
    scaffold.add_mod_content(env.inst, root, [{"id": "sapphire"}], [])
    items = (java / "ModItems.java").read_text("utf-8")
    assert items.count("RUBY =") == 1 and "SAPPHIRE" in items
    assert main.count("ModItems.init();") == 1


def test_scaffold_fabric_mod_uses_sidecar_template(env, monkeypatch):
    from packs import Packs
    monkeypatch.setattr(Packs, "_latest_versions", staticmethod(lambda mc: {
        "loader": "0.20.1", "loom": "1.19.4", "fabric_api": f"0.166.2+{mc}", "gradle": "9.8.2", "checked": False}))
    r = scaffold.scaffold_fabric_mod(env.inst, env.vd, "Gems", "gems", "1.2.0", items=[{"id": "ruby"}])
    root = env.inst_dir / "mods-src" / "gems"
    assert (root / "build.gradle").is_file() and (root / "gradlew").is_file()
    assert "version=1.2.0" in (root / "gradle.properties").read_text("utf-8")
    assert any(p.endswith("ModItems.java") for p in r["created"])
    assert validate_mod(env.vd, root).ok


def test_mod_needs_fabric_instance(env):
    env.inst.loader = "vanilla"
    with pytest.raises(ToolError):
        scaffold.scaffold_fabric_mod(env.inst, env.vd, "x", "x_mod")
