"""다른 런처 인스턴스 불러오기 시험(importers/launchers.py · importers/local.py).

각 런처의 실제 저장 형식을 흉내 낸 폴더를 만들어 감지 → 미리보기 → 복사/연결 → 원본 무변경 → 계정 파일 미접근을 확인한다.
사용: python -m pytest -q tests/test_launchers.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from importers import launchers  # noqa: E402
from importers.local import LocalImporter  # noqa: E402
from instances import InstanceStore  # noqa: E402
from rpc import RpcError  # noqa: E402


def w(p: Path, text: str | bytes = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, "utf-8")
    return p


def game_content(game: Path, mods: int = 2) -> None:
    for i in range(mods):
        w(game / "mods" / f"mod{i}.jar", f"jar{i}")
    w(game / "config" / "a.toml", "a=1")
    w(game / "saves" / "월드" / "level.dat", b"lvl")
    w(game / "options.txt", "lang:ko_kr\n")
    w(game / "servers.dat", b"\x0a\x00\x00\x00")
    w(game / "logs" / "latest.log", "old log")           # 옮기지 않는 것
    w(game / "accounts.json", '{"secret": 1}')           # 계정 파일: 복사 금지


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha1(p.read_bytes()).hexdigest() + str(p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def world(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData" / "Roaming"
    home = tmp_path / "Users" / "me"
    # ---- Prism (InstanceDir 를 바꾼 설정 포함)
    prism = appdata / "PrismLauncher"
    w(prism / "prismlauncher.cfg", "[General]\nInstanceDir=inst-moved\n")
    w(prism / "accounts.json", '{"accounts": "secret"}')
    p1 = prism / "inst-moved" / "Fabric 팩"
    w(p1 / "instance.cfg", "[General]\nname=Fabric 팩\nOverrideMemory=true\nMaxMemAlloc=6144\nJvmArgs=-XX:+UseG1GC\n"
                           f"lastLaunchTime={int(time.time() * 1000) - 1000}\nUnknownKey=whatever\n")
    w(p1 / "mmc-pack.json", json.dumps({"formatVersion": 1, "components": [
        {"uid": "net.minecraft", "version": "26.3"}, {"uid": "net.fabricmc.intermediary", "version": "26.3"},
        {"uid": "net.fabricmc.fabric-loader", "version": "0.20.1"}]}))
    game_content(p1 / "minecraft", 3)
    p2 = prism / "inst-moved" / "neo"
    w(p2 / "instance.cfg", "name=네오\n")                 # 섹션 없는 옛 형식
    w(p2 / "mmc-pack.json", json.dumps({"components": [{"uid": "net.minecraft", "version": "26.2"},
                                                       {"uid": "net.neoforged", "version": "26.2.10"}]}))
    game_content(p2 / ".minecraft", 1)
    w(prism / "inst-moved" / "broken" / "mmc-pack.json", "{not json")
    # ---- MultiMC (포터블)
    mmc = home / "Downloads" / "MultiMC"
    q = mmc / "instances" / "퀼트"
    w(q / "instance.cfg", "[General]\nname=퀼트\n")
    w(q / "mmc-pack.json", json.dumps({"components": [{"uid": "net.minecraft", "version": "26.3"},
                                                      {"uid": "org.quiltmc.quilt-loader", "version": "0.29.0"}]}))
    game_content(q / ".minecraft", 0)
    # ---- CurseForge
    cf = home / "curseforge" / "minecraft" / "Instances" / "All the Mods"
    w(cf / "minecraftinstance.json", json.dumps({
        "name": "All the Mods", "gameVersion": "26.3", "allocatedMemory": 8192, "javaArgsOverride": "-XX:+UseZGC",
        "lastPlayed": "2026-11-20T10:00:00Z", "baseModLoader": {"name": "fabric-0.20.1-26.3", "minecraftVersion": "26.3"},
        "installedAddons": [{"addonID": 1}], "someNewField": {"x": 1}}))
    game_content(cf, 4)
    # ---- Modrinth App (새 스키마)
    mr = appdata / "ModrinthApp"
    mr.mkdir(parents=True)
    con = sqlite3.connect(mr / "app.db")
    con.executescript("""
        CREATE TABLE settings (custom_dir TEXT);
        INSERT INTO settings VALUES (NULL);
        CREATE TABLE instances (id TEXT, path TEXT, applied_content_set_id TEXT, name TEXT, last_played INTEGER,
                                install_stage TEXT, created INTEGER, modified INTEGER);
        CREATE TABLE instance_content_sets (id TEXT, instance_id TEXT, name TEXT, game_version TEXT, loader TEXT, loader_version TEXT);
        CREATE TABLE instance_launch_overrides (instance_id TEXT, overrides TEXT);
        INSERT INTO instances VALUES ('i1', 'Cobblemon', 'c1', 'Cobblemon', 1763600000, 'installed', 0, 0);
        INSERT INTO instance_content_sets VALUES ('c1', 'i1', 'x', '26.3', 'fabric', '0.20.1');
        INSERT INTO instance_launch_overrides VALUES ('i1', '{"memory":{"maximum":4096},"extra_launch_args":["-Dfoo=1"]}');
    """)
    con.commit()
    con.close()
    game_content(mr / "profiles" / "Cobblemon", 5)
    # ---- 공식 런처
    mc = appdata / ".minecraft"
    w(mc / "launcher_profiles.json", json.dumps({"profiles": {
        "aaa": {"name": "내 패브릭", "type": "custom", "lastVersionId": "fabric-loader-0.20.1-26.3",
                "gameDir": str(tmp_path / "games" / "fab"), "javaArgs": "-Xmx4G -XX:+UseG1GC", "lastUsed": "2026-11-22T09:00:00.000Z"},
        "bbb": {"name": "", "type": "latest-release", "lastVersionId": "latest-release"},
        "integrated-studio-inst_00000000": {"name": "통합 작업실 · 우리 것", "type": "custom", "lastVersionId": "26.3"},
    }}))
    w(mc / "launcher_accounts.json", '{"accounts": "secret"}')
    w(mc / "launcher_msa_credentials.bin", b"secret")
    game_content(tmp_path / "games" / "fab", 2)
    roots = {"prism": [prism], "multimc": [mmc], "curseforge": [cf.parent], "modrinth": [mr], "official": [mc]}
    store = InstanceStore(tmp_path / "data")
    installed = []
    imp = LocalImporter(store, install=lambda iid: installed.append(iid), roots=roots)
    # 계정 파일을 열면 시험 실패
    real_open = open

    def guarded_open(file, *a, **kw):
        name = Path(str(file)).name
        assert not launchers.is_account_file(name), f"계정 파일을 열었습니다: {file}"
        return real_open(file, *a, **kw)

    monkeypatch.setattr("builtins.open", guarded_open)
    real_read_text = Path.read_text

    def guarded_read_text(self, *a, **kw):
        assert not launchers.is_account_file(self.name), f"계정 파일을 읽었습니다: {self}"
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    return {"imp": imp, "store": store, "installed": installed, "tmp": tmp_path, "prism": prism, "cf": cf, "mc": mc,
            "mr": mr}


def by_name(entries, name):
    return next(e for e in entries if e["name"] == name)


def test_detect_all_launchers(world):
    es = world["imp"].detect()
    names = {e["name"]: e for e in es}
    assert {"Fabric 팩", "네오", "퀼트", "All the Mods", "Cobblemon", "내 패브릭", "최신 릴리스"} <= set(names)
    assert "통합 작업실 · 우리 것" not in names                         # 우리 항목은 빼기
    f = names["Fabric 팩"]
    assert (f["launcher"], f["version"], f["loader"], f["loaderVersion"], f["mods"], f["memoryMb"]) == \
        ("prism", "26.3", "fabric", "0.20.1", 3, 6144)
    assert f["javaArgs"] == "-XX:+UseG1GC" and f["lastPlayed"]
    assert names["네오"]["loader"] == "neoforge" and names["네오"]["version"] == "26.2"
    assert names["퀼트"]["launcher"] == "multimc" and names["퀼트"]["loader"] == "quilt"
    a = names["All the Mods"]
    assert (a["loader"], a["loaderVersion"], a["memoryMb"], a["mods"]) == ("fabric", "0.20.1", 8192, 4)
    c = names["Cobblemon"]
    assert (c["launcher"], c["version"], c["loader"], c["memoryMb"], c["javaArgs"], c["mods"]) == \
        ("modrinth", "26.3", "fabric", 4096, "-Dfoo=1", 5)
    o = names["내 패브릭"]
    assert (o["version"], o["loader"], o["loaderVersion"], o["memoryMb"]) == ("26.3", "fabric", "0.20.1", 4096)
    assert names["최신 릴리스"]["supported"] is False
    assert not any(e["name"] == "broken" for e in es)                   # 깨진 파일은 건너뜀


def test_modrinth_old_profiles_schema(tmp_path):
    mr = tmp_path / "ModrinthApp"
    mr.mkdir()
    con = sqlite3.connect(mr / "app.db")
    con.executescript("""CREATE TABLE profiles (path TEXT, name TEXT, game_version TEXT, mod_loader TEXT,
                         mod_loader_version TEXT, last_played INTEGER, override_mc_memory_max INTEGER,
                         override_extra_launch_args TEXT, new_column TEXT);
                         INSERT INTO profiles VALUES ('old', '옛 프로필', '26.1', 'neoforge', '26.1.3', NULL, 3072, '["-Da=1"]', 'z');""")
    con.commit()
    con.close()
    w(mr / "profiles" / "old" / "mods" / "a.jar")
    e = launchers.detect_modrinth([mr])[0]
    assert (e["name"], e["version"], e["loader"], e["memoryMb"], e["javaArgs"], e["mods"]) == \
        ("옛 프로필", "26.1", "neoforge", 3072, "-Da=1", 1)


def test_preview_sizes_and_warnings(world):
    imp = world["imp"]
    es = imp.detect()
    key = by_name(es, "All the Mods")["key"]
    pv = imp.preview([key], "copy")
    items = {i["name"] for i in pv["items"][0]["items"]}
    assert {"mods", "config", "saves", "options.txt", "servers.dat"} <= items
    assert "accounts.json" not in items and "logs" not in items
    assert pv["bytes"] > 0
    pv2 = imp.preview([key], "link")
    assert "동시에" in pv2["warnings"][0]


def test_copy_import_many_keeps_source_untouched(world):
    imp, store = world["imp"], world["store"]
    es = imp.detect()
    before = {k: snapshot(Path(world[k]) if k != "cf" else world["cf"]) for k in ("prism", "cf", "mr")}
    keys = [by_name(es, n)["key"] for n in ("Fabric 팩", "All the Mods", "Cobblemon", "네오")]
    res = imp.import_many([{"key": k} for k in keys], "copy")
    assert not res["failed"], res["failed"]
    assert len(res["imported"]) == 4 and len(world["installed"]) == 4   # 설치(없을 때만)는 runner.install 에 맡김
    for inst in res["imported"]:
        d = Path(inst["path"])
        assert d == store.dir_of(inst["id"])                             # 복사본이 게임 폴더
        assert (d / "options.txt").is_file() and (d / "saves" / "월드" / "level.dat").is_file()
        assert not (d / "accounts.json").exists() and not (d / "logs" / "latest.log").exists()
    fab = by_name(res["imported"], "Fabric 팩")
    assert (fab["loader"], fab["loaderVersion"], fab["jvmArgs"]) == ("fabric", "0.20.1", "-Xmx6144M -XX:+UseG1GC")
    assert by_name(res["imported"], "네오")["loader"] == "neoforge"
    assert len(list((Path(fab["path"]) / "mods").glob("*.jar"))) == 3
    after = {k: snapshot(Path(world[k]) if k != "cf" else world["cf"]) for k in ("prism", "cf", "mr")}
    assert before == after                                              # 원본은 절대 수정하지 않음
    assert by_name(imp.detect(), "Fabric 팩")["importedAs"] == fab["id"]


def test_link_import_uses_source_as_game_dir(world):
    imp, store = world["imp"], world["store"]
    e = by_name(imp.detect(), "내 패브릭")
    res = imp.import_many([{"key": e["key"]}], "link")
    inst = res["imported"][0]
    assert Path(inst["path"]) == Path(e["gameDir"]).resolve()            # 원본 폴더를 게임 폴더로
    assert inst["linkedDir"] and inst["metaDir"] != inst["path"]
    assert inst["versionId"] == "fabric-loader-0.20.1-26.3"              # 공식 .minecraft 에 있던 로더 버전
    assert not (Path(inst["path"]) / "instance.json").exists()           # 원본 폴더에 우리 파일을 쓰지 않음
    assert inst["ccEnabled"] is False


def test_in_use_detection(world, monkeypatch):
    imp = world["imp"]
    e = by_name(imp.detect(), "내 패브릭")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    monkeypatch.setenv("INTEGRATED_STUDIO_FAKE_PROCS", "")
    old = time.time() - 3600
    os.utime(Path(inst["path"]) / "logs" / "latest.log", (old, old))
    assert imp.in_use(inst["id"])["busy"] is False
    monkeypatch.setenv("INTEGRATED_STUDIO_FAKE_PROCS", f"javaw.exe|javaw -cp x --gameDir {inst['path']} ;prismlauncher.exe|")
    r = imp.in_use(inst["id"])
    assert r["busy"] and "켜진 마인크래프트" in r["reasons"][0]
    assert "Prism Launcher" in r["warnings"][0]
    monkeypatch.setenv("INTEGRATED_STUDIO_FAKE_PROCS", "")
    w(Path(inst["path"]) / "logs" / "latest.log", "[12:00] [Render thread/INFO]: Loading\n")   # 방금 쓰인 로그
    assert imp.in_use(inst["id"])["busy"] is True


def test_unknown_version_requires_choice_and_failure_isolated(world):
    imp = world["imp"]
    es = imp.detect()
    latest = by_name(es, "최신 릴리스")
    fab = by_name(es, "Fabric 팩")
    res = imp.import_many([{"key": latest["key"]}, {"key": fab["key"]}], "copy")
    assert [f["name"] for f in res["failed"]] == ["최신 릴리스"] and "버전" in res["failed"][0]["error"]
    assert [i["name"] for i in res["imported"]] == ["Fabric 팩"]          # 하나가 실패해도 나머지는 계속
    res2 = imp.import_many([{"key": latest["key"], "version": "26.3", "name": "고른 버전"}], "copy")
    assert res2["imported"][0]["version"] == "26.3"


def test_inspect_folder_variants(world, tmp_path):
    imp = world["imp"]
    one = imp.inspect_folder(str(world["cf"]))
    assert len(one) == 1 and one[0]["launcher"] == "curseforge"
    many = imp.inspect_folder(str(world["prism"] / "inst-moved"))
    assert {e["name"] for e in many} == {"Fabric 팩", "네오"}
    plain = tmp_path / "그냥폴더" / ".minecraft"
    game_content(plain)
    e = imp.inspect_folder(str(plain.parent))[0]
    assert e["launcher"] == "folder" and e["supported"] is False and e["version"] is None
    assert imp.inspect_folder(str(tmp_path / "없음")) == []


def test_stale_key_rejected(world):
    with pytest.raises(RpcError):
        world["imp"].import_many([{"key": "prism:/nope"}])


def test_prism_export_zip(tmp_path):
    import zipfile
    from importers import Importers
    z = tmp_path / "pack.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("내보낸팩/instance.cfg", "[General]\nname=내보낸 팩\n")
        zf.writestr("내보낸팩/mmc-pack.json", json.dumps({"components": [{"uid": "net.minecraft", "version": "26.3"},
                                                                          {"uid": "net.neoforged", "version": "26.3.1"}]}))
        zf.writestr("내보낸팩/.minecraft/mods/a.jar", "a")
        zf.writestr("내보낸팩/.minecraft/options.txt", "lang:ko_kr")
        zf.writestr("내보낸팩/.minecraft/accounts.json", "secret")
    store = InstanceStore(tmp_path / "data")
    imp = Importers(store, tmp_path / "data")
    info = imp.inspect_import(str(z))
    assert (info["kind"], info["name"], info["loader"], info["files"], info["supported"]) == \
        ("prism-zip", "내보낸 팩", "neoforge", 1, True)
    res = imp.import_file(str(z))
    d = Path(res["instance"]["path"])
    assert (d / "mods" / "a.jar").is_file() and (d / "options.txt").is_file()
    assert not (d / "accounts.json").exists()
    assert res["instance"]["loader"] == "neoforge" and res["instance"]["loaderVersion"] == "26.3.1"


def test_install_failure_keeps_import(world):
    imp = world["imp"]

    def boom(iid):
        raise RuntimeError("네트워크 없음")
    imp.install = boom
    e = by_name(imp.detect(), "Fabric 팩")
    res = imp.import_many([{"key": e["key"]}], "copy")
    assert not res["failed"] and "다시 시도" in res["imported"][0]["warning"]
    assert (Path(res["imported"][0]["path"]) / "mods").is_dir()


def test_manage_duplicate_memory_delete_linked(world, monkeypatch):
    imp, store = world["imp"], world["store"]
    # 휴지통 대신 임시 폴더로 옮긴다(Windows 에서 .git 객체는 읽기 전용이라 바로 지우면 거부됨 — 실제 앱은 휴지통 사용)
    bin_dir = world["tmp"] / "휴지통"
    bin_dir.mkdir()

    def fake_trash(p, _base):
        __import__("shutil").move(str(p), str(bin_dir / Path(p).name))
    import paths
    monkeypatch.setattr(paths, "trash", fake_trash)
    import instances as inst_mod
    monkeypatch.setattr(inst_mod, "trash", fake_trash)
    e = by_name(imp.detect(), "내 패브릭")
    linked = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    src = Path(linked["path"])
    before = snapshot(src)
    dup = store.duplicate(linked["id"])
    d = Path(dup["path"])
    assert dup["name"] == "내 패브릭 복사본" and not dup.get("linkedDir") and d == store.dir_of(dup["id"])
    assert (d / "mods" / "mod0.jar").is_file() and (d / "saves" / "월드" / "level.dat").is_file()
    assert not (d / "logs").exists() and (d / "instance.json").is_file()
    m = store.set_memory(dup["id"], 6144)
    assert m["jvmArgs"].startswith("-Xmx6144M") and "-XX:+UseG1GC" in m["jvmArgs"]
    assert store.set_memory(dup["id"], 2048, "-Dfoo=1")["jvmArgs"] == "-Xmx2048M -Dfoo=1"
    with pytest.raises(RpcError):
        store.set_memory(dup["id"], 100)
    store.delete(linked["id"])                                     # 연결 인스턴스 삭제 = 목록에서만
    assert src.is_dir() and snapshot(src) == before                 # 원본 폴더는 그대로
    assert all(i["id"] != linked["id"] for i in store.list())
