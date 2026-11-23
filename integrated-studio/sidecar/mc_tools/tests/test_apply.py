"""apply_changes: 바뀐 파일 종류별 판단, 백업·동기화, 확인, 로그 오류."""
import json
import zipfile
from pathlib import Path

from mc_tools import apply as ap
from mc_tools.scaffold import add_mod_content, scaffold_resourcepack


def _apply(env, paths, bridge, **kw):
    return ap.apply_changes(env.inst, env.vd, paths, bridge=bridge, settle=0, **kw)


def test_function_only_is_instant(env, fake_bridge):
    env.copy_pack("good_pack")
    env.start_game()
    b = fake_bridge(env)
    r = _apply(env, ["datapacks/good_pack/data/campfire/function/tick.mcfunction"], b)
    assert r.status == ap.OK, r.to_dict()
    assert ("reload", {}) in b.calls
    assert (env.inst_dir / "saves/world1/datapacks/good_pack/data/campfire/function/tick.mcfunction").is_file()
    # 새 팩 켜기는 확인을 거친다
    assert any(c["action"] == "enable_datapack" for c in r.needs_confirmation)


def test_new_pack_enable_after_confirm(env, fake_bridge):
    env.copy_pack("good_pack")
    env.start_game()
    b = fake_bridge(env)
    _apply(env, ["datapacks/good_pack/pack.mcmeta"], b, confirm=True)
    assert ("run_command", {"command": 'datapack enable "file/good_pack"'}) in b.calls


def test_worldgen_needs_rejoin(env, fake_bridge):
    pack = env.copy_pack("good_pack")
    f = pack / "data/campfire/worldgen/biome/hot.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"temperature": 2.0}', "utf-8")
    env.start_game()
    b = fake_bridge(env)
    r = _apply(env, ["datapacks/good_pack/data/campfire/worldgen/biome/hot.json"], b)
    assert r.status == ap.REJOIN
    assert any("새로 생기는 청크" in n for n in r.notes)
    assert ("reload", {}) not in b.calls
    assert r.needs_confirmation and r.needs_confirmation[0]["action"] == "rejoin_world"
    r2 = _apply(env, ["datapacks/good_pack/data/campfire/worldgen/biome/hot.json"], b, confirm=True)
    assert ("rejoin_world", {"world": "world1"}) in b.calls and r2.status == ap.REJOIN


def test_enchantment_needs_rejoin(env, fake_bridge):
    pack = env.copy_pack("good_pack")
    f = pack / "data/campfire/enchantment/warm.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}", "utf-8")
    env.start_game()
    assert _apply(env, [str(f)], fake_bridge(env)).status == ap.REJOIN


def test_mod_needs_restart(env, fake_bridge):
    root = env.inst_dir / "mods-src" / "gems"
    (root / "src/main/java/com/example/gems").mkdir(parents=True)
    (root / "build.gradle").write_text("", "utf-8")
    (root / "src/main/resources").mkdir(parents=True, exist_ok=True)
    (root / "src/main/resources/fabric.mod.json").write_text(json.dumps(
        {"schemaVersion": 1, "id": "gems", "version": "1", "entrypoints": {"main": ["com.example.gems.GemsMod"]}}), "utf-8")
    (root / "src/main/java/com/example/gems/GemsMod.java").write_text("public void onInitialize() {\n}\n", "utf-8")
    add_mod_content(env.inst, root, [{"id": "ruby"}], [])
    jar = root / "build/libs/gems-1.0.0.jar"

    def fake_build(inst, project):
        jar.parent.mkdir(parents=True, exist_ok=True)
        jar.write_bytes(b"PK")
        return {"ok": True, "jar": str(jar), "errors": []}

    env.start_game()
    b = fake_bridge(env)
    r = ap.apply_changes(env.inst, env.vd, ["mods-src/gems/src/main/java/com/example/gems/ModItems.java"],
                         bridge=b, settle=0, builder=fake_build)
    assert r.status == ap.RESTART, r.to_dict()
    assert (env.inst_dir / "mods/gems-1.0.0.jar").is_file()
    assert any(c["action"] == "restart_game" for c in r.needs_confirmation)
    # 게임이 꺼져 있어도 모드는 '재시작 필요'(다음 실행 때 적용)
    env.stop_game()
    r = ap.apply_changes(env.inst, env.vd, ["mods-src/gems/build.gradle"], bridge=b, settle=0, builder=fake_build)
    assert r.status == ap.RESTART


def test_mod_build_errors(env, fake_bridge):
    root = env.inst_dir / "mods-src" / "gems"
    (root / "src/main/resources").mkdir(parents=True)
    (root / "build.gradle").write_text("", "utf-8")
    (root / "src/main/resources/fabric.mod.json").write_text('{"schemaVersion":1,"id":"gems","version":"1"}', "utf-8")
    r = ap.apply_changes(env.inst, env.vd, ["mods-src/gems/build.gradle"], bridge=fake_bridge(env), settle=0,
                         builder=lambda i, p: {"ok": False, "errors": ["src/X.java:3: error: cannot find symbol"]})
    assert r.status == ap.ERROR and "cannot find symbol" in r.errors[0] and r.blocking()


def test_build_mod_extracts_compile_errors(env):
    root = env.inst_dir / "mods-src" / "gems"
    root.mkdir(parents=True)
    (root / "build.gradle").write_text("", "utf-8")
    out = (f"{root}/src/main/java/com/example/A.java:12: error: cannot find symbol\n"
           "        Foo bar = new Foo();\n        ^\n  symbol: class Foo\nFAILURE: Build failed\n")

    class R:
        returncode = 1
        stdout = out
        stderr = ""

    r = ap.build_mod(env.inst, root, run=lambda *a, **k: R())
    assert not r["ok"]
    assert r["errors"] == ["src/main/java/com/example/A.java:12: cannot find symbol  ← Foo bar = new Foo();"]


def test_validation_error_blocks_apply(env, fake_bridge):
    env.copy_pack("bad_pack")
    env.start_game()
    b = fake_bridge(env)
    r = _apply(env, ["datapacks/bad_pack/data/bad/function/main.mcfunction"], b)
    assert r.status == ap.ERROR and r.errors and not b.calls
    assert not (env.inst_dir / "saves/world1/datapacks/bad_pack").exists()


def test_log_errors_after_reload(env, fake_bridge):
    env.copy_pack("good_pack")
    env.start_game()
    b = fake_bridge(env, log_line="[12:00:05] [Server thread/ERROR]: Failed to load function campfire:tick")
    r = _apply(env, ["datapacks/good_pack/data/campfire/function/tick.mcfunction"], b)
    assert r.status == ap.ERROR
    assert any("Failed to load function" in e for e in r.log_errors) and r.blocking()


def test_game_off(env, fake_bridge):
    env.copy_pack("good_pack")
    b = fake_bridge(env)
    r = _apply(env, ["datapacks/good_pack/data/campfire/function/tick.mcfunction"], b)
    assert r.status == ap.OK and not b.calls
    assert any("게임이 꺼져" in n for n in r.notes)


def test_backup_before_sync(env, fake_bridge):
    env.copy_pack("good_pack")
    old = env.inst_dir / "saves/world1/datapacks/other"
    old.mkdir(parents=True)
    (old / "pack.mcmeta").write_text("{}", "utf-8")
    _apply(env, ["datapacks/good_pack/pack.mcmeta"], fake_bridge(env))
    backups = list((env.inst_dir / ".studio/backups").glob("world1-datapacks-*.zip"))
    assert len(backups) == 1
    assert "other/pack.mcmeta" in zipfile.ZipFile(backups[0]).namelist()


def test_sync_removes_deleted_files(env, fake_bridge):
    pack = env.copy_pack("good_pack")
    _apply(env, ["datapacks/good_pack/pack.mcmeta"], fake_bridge(env))
    (pack / "data/campfire/recipe/gem.json").unlink()
    _apply(env, ["datapacks/good_pack/data/campfire/recipe/gem.json"], fake_bridge(env))
    assert not (env.inst_dir / "saves/world1/datapacks/good_pack/data/campfire/recipe/gem.json").exists()


def test_resourcepack(env, fake_bridge):
    scaffold_resourcepack(env.inst, env.vd, "my_rp")
    env.start_game()
    b = fake_bridge(env)
    r = _apply(env, ["resourcepacks/my_rp/pack.mcmeta"], b)
    assert r.status == ap.RESTART   # 켜진 게임에서 처음 켠 팩
    assert 'file/my_rp' in (env.inst_dir / "options.txt").read_text("utf-8")
    r = _apply(env, ["resourcepacks/my_rp/pack.mcmeta"], b)
    assert r.status == ap.OK and ("reload_resources", {}) in b.calls


def test_bridge_missing_is_not_blocking(env):
    env.copy_pack("good_pack")
    env.start_game()
    r = ap.apply_changes(env.inst, env.vd, ["datapacks/good_pack/pack.mcmeta"],
                         bridge=ap.FileBridge(env.inst, timeout=0.3), settle=0)
    assert r.bridge_missing and not r.blocking()
    assert any("/reload" in n for n in r.notes)
    assert not list((env.inst_dir / ".studio/bridge/requests").glob("*.json"))


def test_file_bridge_roundtrip(env, tmp_path):
    import threading
    import time
    br = ap.FileBridge(env.inst, timeout=5)

    def responder():
        req_dir = env.inst_dir / ".studio/bridge/requests"
        for _ in range(50):
            reqs = list(req_dir.glob("*.json")) if req_dir.is_dir() else []
            if reqs:
                req = json.loads(reqs[0].read_text("utf-8"))
                reqs[0].unlink()
                (env.inst_dir / ".studio/bridge/responses" / f"{req['id']}.json").write_text(
                    json.dumps({"id": req["id"], "ok": True, "message": f"{req['action']} 함"}), "utf-8")
                return
            time.sleep(0.05)

    t = threading.Thread(target=responder)
    t.start()
    r = br.request("reload")
    t.join()
    assert r["ok"] and r["message"] == "reload 함"


def test_paths_outside_instance_rejected(env, fake_bridge):
    import pytest
    from mc_tools.context import ToolError
    with pytest.raises(ToolError):
        _apply(env, ["../../etc/passwd"], fake_bridge(env))


def test_last_apply_saved(env, fake_bridge):
    env.copy_pack("good_pack")
    _apply(env, ["datapacks/good_pack/pack.mcmeta"], fake_bridge(env))
    last = ap.load_last(env.inst)
    assert last["status"] == ap.OK and Path(env.inst_dir / ".studio/last-apply.json").is_file()
