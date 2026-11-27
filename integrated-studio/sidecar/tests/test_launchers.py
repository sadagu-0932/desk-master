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
    imp = world["imp"]
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


def test_linked_prism_runs_minecraft_from_its_minecraft_folder(world, monkeypatch, tmp_path):
    """연결: 원래 인스턴스 폴더 경로 저장 + 그 안의 게임 폴더(.minecraft)에 실행 파일.
    [실행] = 그 파일 → 앱이 Prism 의 [실행]을 누르는 것과 같게(prismlauncher --dir … --launch …), 다운로드 없음."""
    import os, stat, time as _t
    from importers import launchfile
    imp, store, prism = world["imp"], world["store"], world["prism"]
    out = tmp_path / "prism-args.txt"
    exe = prism / ("prismlauncher.exe" if os.name == "nt" else "prismlauncher")
    exe.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{out}"\n', "utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    world["installed"].clear()
    e = by_name(imp.detect(), "Fabric 팩")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    src = prism / "inst-moved" / "Fabric 팩"
    game = src / "minecraft"
    assert Path(inst["sourceDir"]) == src.resolve()
    f = Path(inst["launchFile"])
    assert f.parent == game.resolve() and launchfile.is_ours(f)       # 실행 파일은 .minecraft 안에
    assert inst["launchKind"] == "prism" and inst["installed"] is True
    assert world["installed"] == []                                   # 다운로드 없음
    win = launchfile.script_text(store.get(inst["id"]), str(exe), windows=True)
    assert '--launch "Fabric 팩"' in win and "prismlauncher.exe" in win
    if os.name != "nt":
        assert imp.launch_linked(inst["id"])["ok"]
        for _ in range(60):
            if out.exists():
                break
            _t.sleep(0.05)
        assert out.read_text("utf-8").split("\n")[:4] == ["--dir", str(prism), "--launch", "Fabric 팩"]
    f.unlink()
    monkeypatch.setattr(launchfile, "run", lambda p: None)
    imp.launch_linked(inst["id"])
    assert f.is_file()                                                # 지워도 다시 만든다
    assert imp.remove_launch_file(inst["id"]) and not f.exists()


def test_linked_with_version_already_in_official_needs_no_download(world):
    imp = world["imp"]
    vid = "fabric-loader-0.20.1-26.3"
    w(world["mc"] / "versions" / vid / f"{vid}.json", "{}")
    for name in ("All the Mods", "Cobblemon"):
        e = by_name(imp.detect(), name)
        inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
        assert inst["installed"] is True and inst["versionId"] == vid, name
        assert Path(inst["launchFile"]).parent == Path(inst["path"])


def test_curseforge_and_modrinth_link_make_launch_file_no_install(world):
    from importers import launchfile
    imp = world["imp"]
    world["installed"].clear()
    for name in ("All the Mods", "Cobblemon", "내 패브릭"):
        e = by_name(imp.detect(), name)
        inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
        assert inst["launchKind"] == "official"
        f = Path(inst["launchFile"])
        assert f.is_file() and f.parent == Path(inst["path"])         # 게임 폴더 안
    assert world["installed"] == []
    # 같은 이름의 남의 파일이 있으면 덮지 않는다
    cf = world["cf"]
    theirs = cf / launchfile.file_name()
    theirs.unlink()
    theirs.write_text("사용자 파일", "utf-8")
    e = by_name(imp.detect(), "All the Mods")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    assert theirs.read_text("utf-8") == "사용자 파일" and Path(inst["launchFile"]) != theirs


def test_migrate_old_linked_instance(world):
    """예전 버전(원래 런처로 실행·실행 파일은 인스턴스 폴더) → .minecraft 로 바로 실행·실행 파일은 .minecraft 안으로."""
    from importers import launchfile
    imp, store = world["imp"], world["store"]
    e = by_name(imp.detect(), "Fabric 팩")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    meta = store.get(inst["id"])
    old_file = Path(meta["sourceDir"]) / launchfile.file_name()
    old_file.write_text(f"rem {launchfile.MARKER}\n", "utf-8")
    Path(meta["launchFile"]).unlink()
    meta.update(launchKind="prism", launchFile=str(old_file), installed=True)
    meta.pop("launchVia")
    store.save(meta)
    assert imp.migrate_linked() >= 1
    m = store.get(inst["id"])
    assert m["launchKind"] == "prism" and m["launchVia"]["kind"] == "prism"   # 앱이 Prism 의 [실행]을 누름
    assert m["installed"] is True
    assert Path(m["launchFile"]).parent == Path(m["path"]) and Path(m["launchFile"]).is_file()
    assert not old_file.exists()                                      # 예전 위치의 우리 파일은 지움
    assert imp.migrate_linked() == 0


def test_store_change_notifications(tmp_path):
    store = InstanceStore(tmp_path)
    seen = []
    store.on_change = lambda: seen.append(1)
    i = store.create("알림", "26.3", "vanilla")
    store.rename(i["id"], "바뀜")
    assert len(seen) >= 2


def test_connect_any_folder_from_new_instance_window(world, tmp_path):
    """새 인스턴스 창 → 폴더 고르기: 어느 런처 폴더든 연결, 받기 없음, 버전은 로그에서."""
    from importers import Importers
    store = world["store"]
    imp = Importers(store, tmp_path / "d")
    imp._local().roots = {"official": [world["mc"]]}
    # 1) CurseForge 인스턴스 폴더
    info = imp.inspect_import(str(world["cf"]))
    assert info["kind"] == "folder" and info["launcherName"] == "CurseForge" and info["version"] == "26.3"
    r = imp.import_file(str(world["cf"]))
    assert Path(r["instance"]["path"]) == world["cf"].resolve() and r["downloaded"] == 0
    # 2) Prism 인스턴스 안의 minecraft 폴더를 골라도 Prism 인스턴스로 연결(원래 런처로 실행)
    inner = world["prism"] / "inst-moved" / "Fabric 팩" / "minecraft"
    info = imp.inspect_import(str(inner))
    assert info["kind"] == "prism" and info["loader"] == "fabric"
    r = imp.import_file(str(inner))
    assert r["instance"]["launchVia"]["kind"] == "prism" and r["instance"]["launchKind"] == "prism"
    assert Path(r["instance"]["launchFile"]).parent == inner.resolve()   # 실행 파일은 그 .minecraft 안
    # 3) 그냥 게임 폴더: Fabric 로그로 버전 알아냄 + 공식 .minecraft 에 그 버전이 있으면 받지 않음
    g = tmp_path / "그냥" / ".minecraft"
    game_content(g)
    w(g / "logs" / "latest.log", "[12:00:00] [main/INFO]: Loading Minecraft 26.3 with Fabric Loader 0.20.1\n")
    vid = "fabric-loader-0.20.1-26.3"
    w(world["mc"] / "versions" / vid / f"{vid}.json", "{}")
    info = imp.inspect_import(str(g.parent))
    assert (info["version"], info["loader"], info["loaderVersion"]) == ("26.3", "fabric", "0.20.1")
    r = imp.import_file(str(g.parent))
    assert r["instance"]["installed"] is True and r["instance"]["versionId"] == vid
    # 4) 버전을 모르는 폴더는 버전을 받아서 연결
    h = tmp_path / "모름"
    w(h / "saves" / "w" / "level.dat", b"x")
    info = imp.inspect_import(str(h))
    assert info["needsVersion"] is True
    with pytest.raises(RpcError):
        imp.import_file(str(h))
    r = imp.import_file(str(h), version="26.3")
    assert r["instance"]["version"] == "26.3" and r["instance"]["linkedDir"]
    # 5) 아무것도 아닌 폴더
    (tmp_path / "빈").mkdir()
    with pytest.raises(RpcError):
        imp.inspect_import(str(tmp_path / "빈"))


def test_delete_when_folder_in_use_hides_then_purges(tmp_path, monkeypatch):
    import instances as inst_mod
    store = InstanceStore(tmp_path)
    i = store.create("쓰는 중", "26.3", "vanilla")
    d = store.dir_of(i["id"])

    def busy(p, b):
        raise PermissionError(32, "다른 프로세스가 파일을 사용 중이기 때문에 프로세스가 액세스 할 수 없습니다", str(p))
    monkeypatch.setattr(inst_mod, "trash", busy)
    store.delete(i["id"])                                            # 오류 없이
    assert all(x["id"] != i["id"] for i_ in [0] for x in store.list())   # 목록에서는 바로 빠짐
    assert (d / inst_mod.PENDING_DELETE).is_file()
    moved = []
    monkeypatch.setattr(inst_mod, "trash", lambda p, b: moved.append(p))
    assert store.purge_pending() == 1 and moved == [d]               # 다음 시작 때 휴지통으로


def test_in_use_survives_powershell_returning_none(world, monkeypatch):
    """Windows: 명령줄에 cp949 로 못 읽는 글자가 있으면 PowerShell 결과가 None 으로 온다 → 실행이 막히면 안 된다."""
    import subprocess as sp
    from importers import local as local_mod
    imp = world["imp"]
    e = by_name(imp.detect(), "Fabric 팩")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    monkeypatch.delenv("INTEGRATED_STUDIO_FAKE_PROCS", raising=False)
    monkeypatch.setattr(local_mod.sys, "platform", "win32")

    class R:
        stdout = None
    seen = {}

    def fake_run(args, **kw):
        seen.update(kw)
        seen["cmd"] = args
        return R()
    monkeypatch.setattr(sp, "run", fake_run)
    assert local_mod._processes() == []
    import base64
    script = base64.b64decode(seen["cmd"][-1]).decode("utf-16-le")      # -EncodedCommand
    assert seen["encoding"] == "utf-8" and "OutputEncoding" in script and "-Filter" in script
    r = imp.in_use(inst["id"])
    assert r["linked"] is True


# ---------------------------------------------------------------- 2026-11-27 고침 4가지
def test_win_command_keeps_quotes_for_special_paths():
    """1) `cmd /c "경로"` 는 ( ) & 가 든 경로에서 따옴표가 떼어져 실패했다 → /s + 겹 따옴표."""
    from importers import launchfile
    p = Path(r"C:\Users\a (1)\instances\A & B\minecraft\통합 작업실 실행 (통합 작업실).cmd")
    assert launchfile.win_command(p) == f'cmd /d /s /c ""{p}""'
    meta = {"name": "100%~ 팩\r\n", "launchKind": "prism",
            "launchVia": {"kind": "prism", "root": r"C:\P (x)", "instance": "A & B"}}
    text = launchfile.script_text(meta, r"C:\P (x)\prismlauncher.exe", windows=True)
    rem = next(line for line in text.splitlines() if line.startswith("rem 통합"))
    assert "100%%~ 팩" in rem                     # %~ 가 배치 파일을 멈추지 않게
    assert '--dir "C:\\P (x)" --launch "A & B"' in text


def test_duplicate_of_prism_linked_installs_and_skips_launch_file(world):
    """2) Prism 연결 복제본: '설치됨'을 그대로 옮기면 설치를 건너뛰고 등록에서 막혔다."""
    imp, store = world["imp"], world["store"]
    e = by_name(imp.detect(), "Fabric 팩")
    linked = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    assert Path(linked["launchFile"]).is_file()
    dup = store.duplicate(linked["id"])
    assert dup["installed"] is False and not dup.get("versionId")
    assert "공식 런처" in dup["notice"]
    assert not list(Path(dup["path"]).glob("통합 작업실 실행*"))     # 원래 인스턴스를 켜는 파일은 복사 안 함
    assert (Path(dup["path"]) / "mods" / "mod0.jar").is_file()


def test_duplicate_of_linked_keeps_installed_when_official_has_version(world, monkeypatch):
    imp, store = world["imp"], world["store"]
    mc = world["mc"]
    w(mc / "versions" / "fabric-loader-0.20.1-26.3" / "fabric-loader-0.20.1-26.3.json", "{}")
    monkeypatch.setenv("APPDATA", str(mc.parent))
    e = by_name(imp.detect(), "Fabric 팩")
    linked = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    dup = store.duplicate(linked["id"])
    assert dup["installed"] is True and dup["versionId"] == "fabric-loader-0.20.1-26.3"
    assert "처음 실행할 때" not in dup["notice"]


def test_in_use_detects_prism_java_and_launch_guard(world, monkeypatch):
    """4) Prism 이 띄운 java 명령줄엔 '<인스턴스>/natives' 가 '/' 로 들어간다. 실행 직후 30초는 다시 실행 막기."""
    from importers import launchfile
    imp = world["imp"]
    e = by_name(imp.detect(), "Fabric 팩")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    src = inst["sourceDir"]
    old = time.time() - 3600
    os.utime(Path(inst["path"]) / "logs" / "latest.log", (old, old))
    natives = src.replace("\\", "/").upper() + "/natives"
    monkeypatch.setenv("INTEGRATED_STUDIO_FAKE_PROCS", f"javaw.exe|javaw -Djava.library.path={natives} -cp x Main")
    assert imp.in_use(inst["id"])["busy"] is True
    monkeypatch.setenv("INTEGRATED_STUDIO_FAKE_PROCS", f"javaw.exe|javaw -Djava.library.path={src}2/natives")
    assert imp.in_use(inst["id"])["busy"] is False                 # 'X' 가 'X2' 에 걸리지 않음
    monkeypatch.setenv("INTEGRATED_STUDIO_FAKE_PROCS", "")
    monkeypatch.setattr(launchfile, "run", lambda p: None)
    import importers.local as local_mod
    monkeypatch.setattr(local_mod, "find_launcher_exe", lambda k, r: Path("/x/prismlauncher"))
    imp.launch_linked(inst["id"])
    r = imp.in_use(inst["id"])
    assert r["busy"] and "켜지는 중" in r["reasons"][0]
    imp._launched[inst["id"]] -= local_mod.LAUNCH_GUARD_S + 1
    assert imp.in_use(inst["id"])["busy"] is False


def test_prism_root_found_when_instance_dir_moved_elsewhere(tmp_path, monkeypatch):
    """3) Prism 설정에서 인스턴스 폴더를 데이터 폴더 밖으로 옮긴 경우에도 데이터 폴더를 찾는다(설정 InstanceDir)."""
    appdata = tmp_path / "Roaming"
    prism = appdata / "PrismLauncher"
    elsewhere = tmp_path / "D" / "MC 인스턴스"
    w(prism / "prismlauncher.cfg", f"[General]\nInstanceDir={elsewhere}\n")
    inst = elsewhere / "팩 (1)"
    w(inst / "mmc-pack.json", json.dumps({"components": [{"uid": "net.minecraft", "version": "26.3"}]}))
    (inst / "minecraft").mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    assert launchers.guess_launcher_root(inst) == prism
    assert launchers.guess_launcher_root(tmp_path / "없는" / "곳") is None


def test_missing_prism_root_asks_user_then_launches(world, monkeypatch, tmp_path):
    from importers import launchfile
    import importers.local as local_mod
    imp, store = world["imp"], world["store"]
    e = by_name(imp.detect(), "Fabric 팩")
    inst = imp.import_many([{"key": e["key"]}], "link")["imported"][0]
    meta = store.get(inst["id"])
    meta["launchVia"]["root"] = None
    store.save(meta)
    monkeypatch.setattr(launchers, "guess_launcher_root", lambda f, extra=None: None)
    monkeypatch.setattr(launchfile, "run", lambda p: None)
    monkeypatch.setattr(local_mod, "find_launcher_exe", lambda k, r: Path("/x/prismlauncher"))
    with pytest.raises(RpcError) as ex:
        imp.launch_linked(inst["id"])
    assert local_mod.NEED_ROOT_TAG in str(ex.value)
    with pytest.raises(RpcError):
        imp.set_launcher_root(inst["id"], str(tmp_path))            # 데이터 폴더가 아님
    other = tmp_path / "다른 Prism"
    w(other / "prismlauncher.cfg", "[General]\n")
    with pytest.raises(RpcError):
        imp.set_launcher_root(inst["id"], str(other))               # 이 인스턴스가 없는 데이터 폴더
    out = imp.set_launcher_root(inst["id"], str(world["prism"]))
    assert out["launchVia"]["root"] == str(world["prism"].resolve())
    assert f'--dir "{world["prism"].resolve()}"' in Path(out["launchFile"]).read_text("utf-8").replace("'", '"')
    assert imp.launch_linked(inst["id"])["ok"]
