"""Prism 연동 시험(2026-11-27): 인스턴스 폴더 형식, 찾기, 자동 연동(생김·지움·바뀜), 예전 인스턴스 옮기기."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import prism  # noqa: E402
import prism_sync  # noqa: E402
from importers.local import LocalImporter  # noqa: E402
from instances import InstanceStore  # noqa: E402
from rpc import RpcError  # noqa: E402


def _store(tmp_path, root: Path) -> InstanceStore:
    store = InstanceStore(tmp_path / "data")
    store.make_prism_instance = lambda n, v, l, lv: {
        "folder": str(prism.create_instance(prism.instance_dir(root), n, v, l, lv)), "root": str(root)}
    store.remove_prism_instance = lambda f: shutil.move(str(f), str(tmp_path / ("trash_" + f.name))) if f.is_dir() else None
    return store


def test_create_instance_writes_prism_format(tmp_path):
    root = tmp_path / "PrismLauncher"
    f = prism.create_instance(root / "instances", 'A/B:C*"팩"', "26.3", "fabric", "0.20.1")
    assert f.name == "ABC팩" and (f / "minecraft").is_dir()
    cfg = (f / "instance.cfg").read_text("utf-8")
    assert cfg.startswith("[General]") and 'name=A/B:C*"팩"' in cfg and "InstanceType=OneSix" in cfg
    pack = json.loads((f / "mmc-pack.json").read_text("utf-8"))
    assert pack["components"] == [{"uid": "net.minecraft", "version": "26.3", "important": True},
                                  {"uid": "net.fabricmc.fabric-loader", "version": "0.20.1"}]
    f2 = prism.create_instance(root / "instances", "ABC팩", "26.3", "vanilla", None)
    assert f2.name == "ABC팩 (2)" and len(json.loads((f2 / "mmc-pack.json").read_text("utf-8"))["components"]) == 1
    with pytest.raises(RpcError):
        prism.create_instance(root / "instances", "x", "26.3", "모름", None)


def test_set_memory_and_rename_keep_other_lines(tmp_path):
    f = prism.create_instance(tmp_path / "i", "팩", "26.3", "neoforge", "26.3.0.5")
    (f / "instance.cfg").write_text("[General]\nname=팩\nnotes=내 메모\n[UI]\nx=1\n", "utf-8")
    prism.set_memory(f, 4096, "-XX:+UseZGC")
    prism.rename_instance(f, "새 팩")
    cfg = (f / "instance.cfg").read_text("utf-8")
    assert "MaxMemAlloc=4096" in cfg and "OverrideMemory=true" in cfg and "JvmArgs=-XX:+UseZGC" in cfg
    assert "name=새 팩" in cfg and "notes=내 메모" in cfg and "[UI]\nx=1" in cfg


def test_find_reads_instance_dir_and_portable(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    root = appdata / "PrismLauncher"
    root.mkdir(parents=True)
    (root / "prismlauncher.cfg").write_text("[General]\nInstanceDir=D:/MC\n", "utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(prism, "find_launcher_exe", lambda k, r: None)
    info = prism.find()
    assert not info["found"] and Path(info["root"]) == root and info["instanceDir"].replace("\\", "/").endswith("D:/MC")
    with pytest.raises(RpcError, match=r"\[prism-missing\]"):
        prism.require()
    portable = tmp_path / "PrismPortable"
    portable.mkdir()
    (portable / "portable.txt").write_text("", "utf-8")
    exe = portable / "prismlauncher.exe"
    exe.write_text("", "utf-8")
    monkeypatch.setattr(prism, "find_launcher_exe", lambda k, r: exe)
    info = prism.find()
    assert info["found"] and Path(info["root"]) == portable and Path(info["instanceDir"]) == portable / "instances"


def test_store_create_makes_prism_instance_and_delete_removes_it(tmp_path, monkeypatch):
    root = tmp_path / "PrismLauncher"
    store = _store(tmp_path, root)
    i = store.create("새 인스턴스", "26.3", "fabric", "0.20.1")
    game = Path(i["path"])
    assert game == root / "instances" / "새 인스턴스" / "minecraft"
    assert i["launchKind"] == "prism" and i["managed"] and i["launchVia"]["instance"] == "새 인스턴스"
    assert (game / "CLAUDE.md").is_file() and (game / "datapacks").is_dir() and (game / ".git").is_dir()
    assert not (Path(i["metaDir"]) / "datapacks").exists()       # 게임 내용은 Prism 쪽에만
    import instances as inst_mod
    monkeypatch.setattr(inst_mod, "trash", lambda p, b: shutil.move(str(p), str(tmp_path / ("bin_" + Path(p).name))))
    store.delete(i["id"])
    assert not (root / "instances" / "새 인스턴스").exists() and store.list() == []


def test_auto_sync_links_updates_and_forgets(tmp_path, monkeypatch):
    root = tmp_path / "PrismLauncher"
    store = _store(tmp_path, root)
    import instances as inst_mod
    monkeypatch.setattr(inst_mod, "trash", lambda p, b: shutil.move(str(p), str(tmp_path / ("bin_" + Path(p).name))))
    local = LocalImporter(store, roots={"prism": [root]})
    find = lambda: {"found": True, "exe": "x", "root": str(root), "instanceDir": str(root / "instances")}  # noqa: E731
    ps = prism_sync.PrismSync(store, local, find=find)
    # Prism 에서 만든 인스턴스(앱 밖)
    f = prism.create_instance(root / "instances", "Prism 에서 만듦", "26.2", "vanilla", None)
    r = ps.sync()
    assert r["added"] == 1
    m = next(x for x in store.list() if x["name"] == "Prism 에서 만듦")
    assert m["launchKind"] == "prism" and not m.get("managed") and not m.get("launchFile")   # 남의 폴더에 파일 안 씀
    assert not list((f / "minecraft").glob("통합 작업실 실행*")) and not (f / "minecraft" / "CLAUDE.md").exists()
    assert ps.sync() == {"added": 0, "removed": 0, "updated": 0, "prism": True}           # 바뀐 게 없으면 읽지 않음
    # 앱이 만든 것은 두 번 들어가지 않음
    store.create("앱에서 만듦", "26.3", "fabric", "0.20.1")
    assert ps.sync()["added"] == 0 and len(store.list()) == 2
    # Prism 에서 이름·버전을 바꾸면 맞춤
    prism.rename_instance(f, "이름 바꿈")
    prism.write_pack(f, "26.3", "fabric", "0.20.1")
    assert ps.sync()["updated"] == 1
    m = store.get(m["id"])
    assert (m["name"], m["version"], m["loader"]) == ("이름 바꿈", "26.3", "fabric")
    # Prism 에서 지우면 목록에서 빠짐(앱 정보만)
    shutil.rmtree(f)
    assert ps.sync()["removed"] == 1 and all(x["id"] != m["id"] for x in store.list())


def test_rmtree_force_removes_readonly_files(tmp_path):
    import os
    import stat
    d = tmp_path / ".git" / "objects" / "00"
    d.mkdir(parents=True)
    f = d / "abc"
    f.write_bytes(b"x")
    os.chmod(f, stat.S_IREAD)                 # Windows 의 git 객체처럼 읽기 전용
    os.chmod(d, stat.S_IREAD | stat.S_IEXEC)
    prism_sync._rmtree_force(tmp_path / ".git")
    assert not (tmp_path / ".git").exists()


def test_migrate_old_instances_into_prism(tmp_path, monkeypatch):
    root = tmp_path / "PrismLauncher"
    store = InstanceStore(tmp_path / "data")       # 예전: Prism 연동 없이 앱 폴더에 만든 인스턴스
    old = store.create("예전 팩", "26.3", "fabric", "0.20.1")
    og = Path(old["path"])
    (og / "mods" / "a.jar").write_bytes(b"jar")
    (og / "saves" / "월드").mkdir()
    (og / "saves" / "월드" / "level.dat").write_bytes(b"lvl")
    (og / "servers" / "srv_00000001").mkdir(parents=True)
    (og / "servers" / "srv_00000001" / "server.json").write_text("{}", "utf-8")
    store.set_memory(old["id"], 4096, "-XX:+UseG1GC")
    meta = store.get(old["id"])
    meta["workMode"] = "mod"
    store.save(meta)
    assert [c["id"] for c in prism_sync.migrate_candidates(store)] == [old["id"]]
    s2 = _store(tmp_path, root)
    import instances as inst_mod
    moved = []
    monkeypatch.setattr(inst_mod, "trash", lambda p, b: moved.append(Path(p).name) or shutil.move(str(p), str(tmp_path / ("bin_" + Path(p).name))))
    res = prism_sync.migrate(s2, LocalImporter(s2), [old["id"]])
    assert not res["failed"] and len(res["migrated"]) == 1
    new = s2.get(res["migrated"][0]["to"])
    ng = Path(new["path"])
    assert root / "instances" in ng.parents and new["launchKind"] == "prism" and new["workMode"] == "mod"
    assert (ng / "mods" / "a.jar").read_bytes() == b"jar" and (ng / "saves" / "월드" / "level.dat").is_file()
    assert (Path(new["metaDir"]) / "servers" / "srv_00000001" / "server.json").is_file()   # 전용 서버 설정도
    assert not (ng / "instance.json").exists() and (ng / ".git").is_dir()
    assert "MaxMemAlloc=4096" in (Path(new["sourceDir"]) / "instance.cfg").read_text("utf-8")
    assert old["id"] in moved and prism_sync.migrate_candidates(s2) == []                  # 예전 것은 휴지통으로


def test_groups_follow_prism_both_ways(tmp_path, monkeypatch):
    """그룹(폴더): 앱에서 바꾸면 Prism instgroups.json 에, Prism 에서 바꾸면 앱에(자동 연동)."""
    root = tmp_path / "PrismLauncher"
    store = _store(tmp_path, root)
    local = LocalImporter(store, roots={"prism": [root]})
    find = lambda: {"found": True, "exe": "x", "root": str(root), "instanceDir": str(root / "instances")}  # noqa: E731
    ps = prism_sync.PrismSync(store, local, find=find)
    a = store.create("가", "26.3", "fabric", "0.20.1", group="생존")
    b = store.create("나", "26.3", "vanilla")
    groups_file = root / "instances" / "instgroups.json"
    assert json.loads(groups_file.read_text("utf-8"))["groups"]["생존"]["instances"] == ["가"]
    store.set_group(b["id"], "생존")
    store.set_group(a["id"], "건축")
    g = json.loads(groups_file.read_text("utf-8"))["groups"]
    assert g["생존"]["instances"] == ["나"] and g["건축"]["instances"] == ["가"]
    # Prism 에서 그룹을 바꾸면(파일을 직접) 앱에도
    ps.sync(force=True)
    prism.set_group(root / "instances", "나", "미니게임")
    assert ps.sync()["updated"] == 1 and store.get(b["id"])["group"] == "미니게임"
    # 그룹 이름 바꾸기·풀기
    assert store.rename_group("미니게임", "놀이") == 1 and store.get(b["id"])["group"] == "놀이"
    assert store.rename_group("놀이", None) == 1 and store.get(b["id"])["group"] is None
    g = json.loads(groups_file.read_text("utf-8"))["groups"]
    assert "놀이" not in g and "미니게임" not in g and g["건축"]["instances"] == ["가"]   # 빈 그룹은 지움
    with pytest.raises(RpcError):
        store.set_group(a["id"], "줄\n바꿈")
    assert prism.read_groups(tmp_path / "없음") == {}
