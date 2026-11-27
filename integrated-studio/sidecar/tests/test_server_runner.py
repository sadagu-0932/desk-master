"""M10 서버 열기(사이드카): 방식 A 전용 서버(가짜 jar·가짜 자바), 모드 분석(참가자 필요 모드), e4mc 관리."""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import e4mc_host  # noqa: E402
import net  # noqa: E402
import server_mods  # noqa: E402
import server_runner as sr  # noqa: E402
from instances import InstanceStore  # noqa: E402
from rpc import RpcError  # noqa: E402

FAKE_JAVA = Path(__file__).resolve().parent / "fixtures_server" / "fake_java.py"


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = InstanceStore(tmp_path)
    inst = store.create("시험", "26.3", "vanilla")
    world = store.dir_of(inst["id"]) / "saves" / "내 월드"
    world.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"x")
    (world / "session.lock").write_bytes(b"lock")
    events: list[tuple[str, dict]] = []
    runner = sr.ServerRunner(tmp_path, store, lambda v: [sys.executable, str(FAKE_JAVA)],
                             emit=lambda m, p: events.append((m, p)))

    def fake_jar(version):
        dest = tmp_path / "server-jars" / version / "server.jar"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"vanilla-jar")
        return dest

    def fake_fabric(version, lv):
        dest = tmp_path / "server-jars" / "fabric.jar"
        dest.write_bytes(b"fabric-launcher")
        return dest

    monkeypatch.setattr(runner, "_vanilla_jar", fake_jar)
    monkeypatch.setattr(runner, "_fabric_launcher", fake_fabric)
    monkeypatch.setattr(sr, "trash", lambda p, b: __import__("shutil").rmtree(p), raising=False)
    import paths
    monkeypatch.setattr(paths, "trash", lambda p, b: __import__("shutil").rmtree(p) if Path(p).is_dir() else Path(p).unlink())
    yield runner, store, inst["id"], events
    runner.shutdown()


def wait(pred, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_create_writes_properties_and_copies_world(env):
    runner, store, iid, _ = env
    s = runner.create(iid, "친구 서버", online_mode=False, world="내 월드")
    d = store.dir_of(iid) / "servers" / s["id"]
    props = sr.read_properties(d / "server.properties")
    assert props["server-ip"] == ""                        # UPnP(공유기 → LAN 주소)·playit(127.0.0.1) 모두 받게
    assert props["online-mode"] == "false"
    assert props["motd"] == "친구 서버" and props["level-name"] == "world"
    assert 0 < int(props["server-port"]) < 65536
    assert (d / "world" / "level.dat").is_file() and not (d / "world" / "session.lock").exists()
    assert s["needsEula"] and s["eulaUrl"].startswith("https://")
    assert runner.list(iid)[0]["name"] == "친구 서버"


def test_eula_is_never_automatic(env):
    runner, store, iid, _ = env
    s = runner.create(iid, "서버")
    r = runner.start(iid, s["id"])
    assert r == {"needsEula": True, "eulaUrl": sr.EULA_URL}
    d = store.dir_of(iid) / "servers" / s["id"]
    assert not (d / "eula.txt").exists() or "eula=true" not in (d / "eula.txt").read_text("utf-8")
    runner.accept_eula(iid, s["id"])
    assert "eula=true" in (d / "eula.txt").read_text("utf-8")


def test_start_done_console_players_stop(env):
    runner, store, iid, events = env
    s = runner.create(iid, "서버")
    runner.accept_eula(iid, s["id"])
    r = runner.start(iid, s["id"])
    sid, port = s["id"], r["port"]
    assert r["state"] == "starting"
    assert wait(lambda: any(m == "ds_state" and p.get("state") == "ready" for m, p in events)), events
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        pass                                            # 서버 포트가 실제로 열림
    with pytest.raises(RpcError):
        runner.start(iid, sid)                          # 두 번 시작 금지
    runner.command(iid, sid, "/say 안녕")
    runner.command(iid, sid, "fakejoin Steve")
    assert wait(lambda: any(m == "ds_log" and "[Server] 안녕" in p["line"] for m, p in events))
    assert wait(lambda: runner.list(iid)[0]["players"] == ["Steve"])
    runner.command(iid, sid, "fakeleave Steve")
    assert wait(lambda: runner.list(iid)[0]["players"] == [])
    assert runner.list(iid)[0]["ready"] is True
    assert runner.stop(iid, sid)
    assert wait(lambda: any(m == "ds_state" and p.get("state") == "stopped" for m, p in events))
    assert not runner.list(iid)[0]["running"]
    with pytest.raises(RpcError):
        runner.command(iid, sid, "say x")


def test_two_servers_at_once_get_different_ports(env):
    runner, store, iid, events = env
    a = runner.create(iid, "A")
    b = runner.create(iid, "B")
    for s in (a, b):
        runner.accept_eula(iid, s["id"])
    pa = runner.start(iid, a["id"])["port"]
    pb = runner.start(iid, b["id"])["port"]
    assert pa != pb
    assert wait(lambda: sum(1 for m, p in events if m == "ds_state" and p.get("state") == "ready") == 2)
    assert sorted(runner.running()) == sorted([a["id"], b["id"]])


def test_busy_port_is_replaced(env):
    runner, store, iid, _ = env
    s = runner.create(iid, "서버")
    runner.accept_eula(iid, s["id"])
    d = store.dir_of(iid) / "servers" / s["id"]
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    sr.write_properties(d / "server.properties", {"server-port": busy.getsockname()[1]})
    try:
        r = runner.start(iid, s["id"])
        assert r["port"] != busy.getsockname()[1]
        assert sr.read_properties(d / "server.properties")["server-port"] == str(r["port"])
    finally:
        busy.close()


def test_fabric_uses_server_launcher(env, monkeypatch):
    runner, store, iid, _ = env
    meta = store.get(iid)
    meta.update(loader="fabric", loaderVersion="0.20.1")
    store.save(meta)
    s = runner.create(iid, "패브릭")
    args = runner.prepare_launch(iid, s["id"])
    jar = args[args.index("-jar") + 1]
    d = store.dir_of(iid) / "servers" / s["id"]
    assert jar == "fabric-server-launch.jar"
    assert (d / "server.jar").read_bytes() == b"vanilla-jar"
    assert (d / "fabric-server-launcher.properties").read_text("utf-8") == "serverJar=server.jar\n"


def test_bad_ids_rejected(env):
    runner, store, iid, _ = env
    with pytest.raises(RpcError):
        runner.start(iid, "../../etc")
    with pytest.raises(RpcError):
        runner.create(iid, "x", world="../../밖")
    with pytest.raises(RpcError):
        runner.create(iid, "x", world="없는 월드")
    assert runner.list(iid) == []          # 실패한 만들기는 흔적을 남기지 않는다


def test_done_regex():
    assert sr.DONE_RE.search('[12:00:02] [Server thread/INFO]: Done (12,345s)! For help, type "help"')
    assert not sr.DONE_RE.search("[12:00:02] [Server thread/INFO]: Done preparing level")


def test_other_loaders_refused_for_dedicated(env):
    runner, store, iid, _ = env
    meta = store.get(iid)
    meta["loader"] = "quilt"
    store.save(meta)
    with pytest.raises(RpcError) as e:
        runner.create(iid, "x")
    assert "싱글 LAN" in str(e.value)


# ---------------- 모드 분석 ----------------
def make_jar(path: Path, kind: str, mod_id: str, env: str = "*", extra: dict | None = None) -> Path:
    import zipfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        if kind == "fabric":
            z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mod_id, "name": mod_id.title(),
                                                      "version": "1.0", "environment": env, **(extra or {})}))
        elif kind == "quilt":
            z.writestr("quilt.mod.json", json.dumps({"quilt_loader": {"id": mod_id, "version": "1"},
                                                     "minecraft": {"environment": env}}))
        elif kind == "neoforge":
            disp = (extra or {}).get("displayTest", "MATCH_VERSION")
            z.writestr("META-INF/neoforge.mods.toml",
                       f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{mod_id}"\nversion="1"\n'
                       f'displayName="{mod_id}"\ndisplayTest="{disp}"\n')
    return path


def test_client_required_mods(tmp_path):
    mods = tmp_path / "mods"
    make_jar(mods / "e4mc.jar", "fabric", "e4mc")                       # 호스트 전용
    make_jar(mods / "sodium.jar", "fabric", "sodium", "client")         # 클라이언트 전용 → 참가자 필요 없음
    make_jar(mods / "fabric-api.jar", "fabric", "fabric-api")           # 라이브러리
    assert server_mods.client_required_mods(mods) == []                          # 콘텐츠 모드가 없으면 라이브러리도 안 보임
    make_jar(mods / "lithium.jar", "fabric", "lithium", "server")       # 서버 전용
    make_jar(mods / "create.jar", "fabric", "create")                   # 콘텐츠
    make_jar(mods / "q.jar", "quilt", "qmod", "*")
    make_jar(mods / "nf.jar", "neoforge", "jei", extra={"displayTest": "IGNORE_ALL_VERSION"})
    make_jar(mods / "nf2.jar", "neoforge", "mekanism")
    ids = {m["id"]: m for m in server_mods.client_required_mods(mods)}
    assert set(ids) == {"create", "qmod", "mekanism", "fabric-api"}
    assert ids["fabric-api"]["library"] is True and ids["create"]["library"] is False


def test_fabric_server_gets_server_side_mods(env):
    runner, store, iid, _ = env
    meta = store.get(iid)
    meta.update(loader="fabric")
    store.save(meta)
    mods = store.game_dir(iid) / "mods"
    make_jar(mods / "create.jar", "fabric", "create")
    make_jar(mods / "sodium.jar", "fabric", "sodium", "client")
    make_jar(mods / "e4mc.jar", "fabric", "e4mc")
    s = runner.create(iid, "패브릭")
    runner.prepare_launch(iid, s["id"])
    sm = store.dir_of(iid) / "servers" / s["id"] / "mods"
    assert sorted(p.name for p in sm.iterdir()) == ["create.jar"]
    (mods / "create.jar").unlink()
    runner.prepare_launch(iid, s["id"])
    assert list(sm.iterdir()) == []                                     # 빠진 모드는 서버에서도 뺌(휴지통)
    assert runner.mods(iid)["clientRequired"] == []


# ---------------- e4mc ----------------
@pytest.fixture
def e4(tmp_path, monkeypatch):
    import modrinth
    store = InstanceStore(tmp_path)
    iid = store.create("호스트", "26.3", "fabric")["id"]
    calls = []

    def fake_install(project, version, loader, mods_dir, **kw):
        calls.append((project, version, loader))
        if version == "26.9":
            raise modrinth.NoMatch("없음")
        make_jar(mods_dir / "e4mc-fabric-6.2.3-modern.jar", "fabric", "e4mc")
        r = modrinth.InstallResult()
        r.installed.append({"filename": "e4mc-fabric-6.2.3-modern.jar"})
        return r

    monkeypatch.setattr(modrinth, "install", fake_install)
    host = e4mc_host.E4mcHost(store, install_fabric=lambda i, v: f"fabric-loader-0.20.1-{v}",
                       register_host=lambda i, vid: {"ok": True, "message": "등록"})
    return host, store, iid, calls


def test_e4mc_install_disable_keeps_file(e4):
    host, store, iid, calls = e4
    r = host.install(iid)
    assert r["ok"] and calls == [("e4mc", "26.3", "fabric")]
    st = host.status(iid)
    assert st["enabled"] and not st["needsHostProfile"]
    host.disable(iid)
    mods = store.game_dir(iid) / "mods"
    assert (mods / "e4mc-fabric-6.2.3-modern.jar.disabled").is_file()  # 삭제가 아니라 이름 변경
    assert not host.status(iid)["enabled"] and host.status(iid)["installed"]


def test_e4mc_no_file_falls_back(e4):
    host, store, iid, _ = e4
    meta = store.get(iid)
    meta["version"] = "26.9"
    store.save(meta)
    r = host.install(iid)
    assert not r["ok"] and r["fallback"] and "UPnP" in r["reason"]
    assert not host.status(iid)["installed"]


def test_e4mc_conflicts_choice(e4):
    host, store, iid, _ = e4
    mods = store.game_dir(iid) / "mods"
    make_jar(mods / "viafabricplus.jar", "fabric", "viafabricplus")
    r = host.install(iid)
    assert r.get("needsChoice") and r["conflicts"][0]["name"] == "ViaFabricPlus"
    r = host.install(iid, "disable_once")
    assert r["ok"] and r["disabledOnce"] == ["viafabricplus.jar"]
    assert (mods / "viafabricplus.jar.disabled").is_file()
    assert host.restore_once(iid) == ["viafabricplus.jar"]              # 이번만 끈 모드는 되살린다
    assert (mods / "viafabricplus.jar").is_file()


def test_e4mc_vanilla_gets_host_profile(e4):
    host, store, iid, calls = e4
    meta = store.get(iid)
    meta["loader"] = "vanilla"
    store.save(meta)
    r = host.install(iid)
    assert calls[-1] == ("e4mc", "26.3", "fabric")                     # 바닐라는 같은 버전 Fabric 용
    assert r["hostProfile"]["versionId"] == "fabric-loader-0.20.1-26.3"
    assert store.get(iid)["loader"] == "vanilla"                        # 원래 인스턴스는 그대로


def test_e4mc_crash_auto_disables(e4):
    host, store, iid, _ = e4
    host.install(iid)
    game = store.game_dir(iid)
    (game / "crash-reports").mkdir()
    (game / "crash-reports" / "crash-2026-11-23_12.00.00-client.txt").write_text(
        "---- Minecraft Crash Report ----\njava.lang.NullPointerException\n\tat link.e4mc.QuiclimeSession.start", "utf-8")
    r = host.check_crash(iid)
    assert r["e4mcProblem"] and "e4mc" in r["reason"]
    assert not host.status(iid)["enabled"] and host.status(iid)["autoDisabled"]


def test_e4mc_unrelated_crash_ignored(e4):
    host, store, iid, _ = e4
    host.install(iid)
    game = store.game_dir(iid)
    (game / "logs").mkdir(exist_ok=True)
    (game / "logs" / "latest.log").write_text("[12:00:00] [Render thread/ERROR]: Failed to load texture\n", "utf-8")
    assert host.check_crash(iid) == {"e4mcProblem": False}
    assert host.status(iid)["enabled"]


# ---------------- Forge 계열 ----------------
def test_neoforge_prefix_and_version_pick(env, monkeypatch):
    runner, *_ = env
    assert runner._neoforge_prefix("26.3") == "26.3.0."
    assert runner._neoforge_prefix("26.1.2") == "26.1.2."
    assert runner._neoforge_prefix("1.21.1") == "21.1."
    xml = "".join(f"<version>{v}</version>" for v in
                  ["26.1.2.129", "26.3.0.99", "26.3.0.115", "26.3.0.116-beta", "26.3.1.2"])

    class R:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout=0: R(xml.encode()))
    assert runner._forge_version("neoforge", "26.3", None) == "26.3.0.115"     # 정확히 26.3 용, 베타 제외
    with pytest.raises(RpcError):
        runner._forge_version("neoforge", "26.3", "26.1.2.129")                 # 다른 버전용은 거부
    monkeypatch.setattr(sr, "_http_json", lambda url: {"promos": {"26.3-recommended": "66.1.9", "26.3-latest": "66.1.10"}})
    assert runner._forge_version("forge", "26.3", None) == "26.3-66.1.9"
    assert runner._forge_version("forge", "26.3", "66.1.5") == "26.3-66.1.5"
    monkeypatch.setattr(sr, "_http_json", lambda url: {"promos": {}})
    with pytest.raises(RpcError):
        runner._forge_version("forge", "26.9", None)


def test_forge_installer_sha256_checked(env, monkeypatch, tmp_path):
    runner, *_ = env
    import hashlib
    good = b"installer-bytes"
    answers = {}

    class R:
        def __init__(self, b): self.b = b; self.i = 0
        def read(self, n=-1):
            if n < 0:
                out, self.b = self.b, b""
                return out
            out, self.b = self.b[:n], self.b[n:]
            return out
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout=0: R(answers[req.full_url]))
    url = f"{sr.NEOFORGE_MAVEN}/26.3.0.115/neoforge-26.3.0.115-installer.jar"
    answers[url] = good
    answers[url + ".sha256"] = (hashlib.sha256(good).hexdigest() + "\n").encode()
    p = runner._forge_installer("neoforge", "26.3.0.115")
    assert p.read_bytes() == good
    answers[url] = b"tampered"
    p.unlink()
    with pytest.raises(RpcError) as e:
        runner._forge_installer("neoforge", "26.3.0.115")
    assert "해시" in str(e.value) and not p.exists()


@pytest.mark.parametrize("loader,full", [("neoforge", "26.3.0.115"), ("forge", "26.3-66.1.9")])
def test_forge_family_server_runs_with_args_file(env, monkeypatch, loader, full):
    runner, store, iid, events = env
    meta = store.get(iid)
    meta.update(loader=loader, loaderVersion=None)
    store.save(meta)
    mods = store.game_dir(iid) / "mods"
    make_jar(mods / "mek.jar", "neoforge", "mekanism")
    make_jar(mods / "jei.jar", "neoforge", "jei", extra={"displayTest": "IGNORE_ALL_VERSION"})
    installs = []
    monkeypatch.setattr(runner, "_forge_version", lambda l, mc, w: full)
    monkeypatch.setattr(runner, "_forge_installer", lambda l, f: Path("installer.jar"))

    def fake_install(id, sid, d, version, l, installer, f):
        installs.append((l, f))
        args = d / runner.forge_args_file(d, l, f)
        args.parent.mkdir(parents=True, exist_ok=True)
        args.write_text("-Dfake=1 -jar shim.jar", "utf-8")
        (d / "user_jvm_args.txt").write_text("# 메모리\n", "utf-8")
    monkeypatch.setattr(runner, "_run_forge_installer", fake_install)
    s = runner.create(iid, "포지 서버")
    launch = runner.prepare_launch(iid, s["id"])
    group = "net/neoforged/neoforge" if loader == "neoforge" else "net/minecraftforge/forge"
    assert launch[0] == "@user_jvm_args.txt" and launch[1].startswith(f"@libraries/{group}/{full}/") and launch[2] == "nogui"
    sm = store.dir_of(iid) / "servers" / s["id"] / "mods"
    assert sorted(p.name for p in sm.iterdir()) == ["jei.jar", "mek.jar"]      # 서버엔 둘 다(클라이언트 필요 여부와 별개)
    assert [m["id"] for m in runner.mods(iid)["clientRequired"]] == ["mekanism"]
    runner.accept_eula(iid, s["id"])
    r = runner.start(iid, s["id"])
    assert wait(lambda: any(m == "ds_state" and p.get("state") == "ready" for m, p in events))
    assert any(m == "ds_log" and f"@libraries/{group}" in p["line"] for m, p in events)
    assert runner.stop(iid, s["id"]) and r["port"]
    assert installs and installs[0] == (loader, full)
