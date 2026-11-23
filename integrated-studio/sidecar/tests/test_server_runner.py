"""M10 방식 A(전용 서버): 가짜 jar·가짜 자바로 만들기·EULA·시작·Done 감지·콘솔·중지·properties, servers.dat."""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server_runner as sr  # noqa: E402
from instances import InstanceStore  # noqa: E402
from rpc import RpcError  # noqa: E402

FAKE_JAVA = Path(__file__).resolve().parent / "fixtures_p2p" / "fake_java.py"


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
    d = store.dir_of(iid) / "p2p-servers" / s["id"]
    props = sr.read_properties(d / "server.properties")
    assert props["server-ip"] == "127.0.0.1"               # 터널로만 접속
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
    d = store.dir_of(iid) / "p2p-servers" / s["id"]
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
    assert wait(lambda: any(m == "p2p_server_state" and p.get("state") == "ready" for m, p in events)), events
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        pass                                            # 서버 포트가 실제로 열림
    with pytest.raises(RpcError):
        runner.start(iid, sid)                          # 두 번 시작 금지
    runner.command(iid, sid, "/say 안녕")
    runner.command(iid, sid, "fakejoin Steve")
    assert wait(lambda: any(m == "p2p_server_log" and "[Server] 안녕" in p["line"] for m, p in events))
    assert wait(lambda: runner.list(iid)[0]["players"] == ["Steve"])
    runner.command(iid, sid, "fakeleave Steve")
    assert wait(lambda: runner.list(iid)[0]["players"] == [])
    assert runner.list(iid)[0]["ready"] is True
    assert runner.stop(iid, sid)
    assert wait(lambda: any(m == "p2p_server_state" and p.get("state") == "stopped" for m, p in events))
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
    assert wait(lambda: sum(1 for m, p in events if m == "p2p_server_state" and p.get("state") == "ready") == 2)
    assert sorted(runner.running()) == sorted([a["id"], b["id"]])


def test_busy_port_is_replaced(env):
    runner, store, iid, _ = env
    s = runner.create(iid, "서버")
    runner.accept_eula(iid, s["id"])
    d = store.dir_of(iid) / "p2p-servers" / s["id"]
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
    jar = runner.prepare_jar(iid, s["id"])
    d = store.dir_of(iid) / "p2p-servers" / s["id"]
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


# ---------------- servers.dat ----------------
def test_servers_dat_roundtrip_keeps_existing(tmp_path):
    f = tmp_path / "servers.dat"
    existing = [{"name": (sr.STRING, "내 서버"), "ip": (sr.STRING, "mc.example.com"), "acceptTextures": (sr.BYTE, 1),
                 "icon": (sr.STRING, "abc")}]
    sr.write_servers_dat(f, existing)
    assert sr.read_servers_dat(f) == existing
    sr.servers_dat_upsert(f, "친구 서버", "127.0.0.1:50000")
    s = sr.read_servers_dat(f)
    assert s[0]["name"][1] == "[P2P] 친구 서버" and s[0]["ip"][1] == "127.0.0.1:50000"
    assert s[1] == existing[0]
    sr.servers_dat_upsert(f, "친구 서버", "127.0.0.1:50001")   # 같은 서버는 주소만 바꿈
    s = sr.read_servers_dat(f)
    assert len(s) == 2 and s[0]["ip"][1] == "127.0.0.1:50001"


def test_servers_dat_empty_and_broken(tmp_path):
    f = tmp_path / "servers.dat"
    assert sr.read_servers_dat(f) == []
    f.write_bytes(b"\x0a\x00")
    assert sr.read_servers_dat(f) == []
    sr.servers_dat_upsert(f, "x", "127.0.0.1:1")
    assert len(sr.read_servers_dat(f)) == 1


def test_servers_dat_rpc_validates(tmp_path):
    store = InstanceStore(tmp_path)
    iid = store.create("t", "26.3", "vanilla")["id"]
    sd = sr.ServersDat(store)
    with pytest.raises(RpcError):
        sd.add(iid, "x", "evil.example.com:25565")
    assert sd.add(iid, "x", "127.0.0.1:5000")["count"] == 1
