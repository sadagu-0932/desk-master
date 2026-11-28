"""서버 도구 시험(2026-11-27): 모드 복사 규칙·일치 확인(MOD-1xx)·고치기, 서버 오류 코드, 자바 찾기."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import java_find  # noqa: E402
import server_errors  # noqa: E402
import server_runner as sr  # noqa: E402
from instances import InstanceStore  # noqa: E402
from test_server_runner import make_jar  # noqa: E402


def _fabric_jar(path: Path, mod_id: str, version: str = "1.0", env: str = "*") -> Path:
    return make_jar(path, "fabric", mod_id, env, extra={"version": version})


@pytest.fixture
def fab(tmp_path, monkeypatch):
    store = InstanceStore(tmp_path)
    iid = store.create("모드 서버", "26.3", "fabric")["id"]
    runner = sr.ServerRunner(tmp_path, store, lambda v: ["java"], emit=lambda m, p: None)
    monkeypatch.setattr(sr, "_trash", lambda p, base: shutil.move(str(p), str(tmp_path / ("trash_" + Path(p).name))))
    sid = runner.create(iid, "서버")["id"]
    return store, iid, runner, sid, store.game_dir(iid) / "mods", runner._sdir(iid, sid) / "mods"


def test_sync_keeps_user_jars_and_replaces_old_versions(fab):
    store, iid, runner, sid, cm, sm = fab
    _fabric_jar(cm / "create-1.0.jar", "create", "1.0")
    _fabric_jar(cm / "sodium.jar", "sodium", env="client")
    (cm / "some-library.jar").write_bytes(b"not a mod zip")          # 정보 없는 jar = 라이브러리일 수 있어 넣는다
    (cm / "config").mkdir(exist_ok=True)
    cfg = store.game_dir(iid) / "config" / "create-common.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("a=1", "utf-8")
    _fabric_jar(sm / "my-server-only.jar", "luckperms", env="server")    # 사용자가 서버에 직접 넣은 것
    _fabric_jar(sm / "create-0.9.jar", "create", "0.9")                  # 서버의 옛 버전
    d = runner._sdir(iid, sid)
    runner._sync_server_mods(iid, d)
    assert sorted(p.name for p in sm.iterdir()) == ["create-1.0.jar", "my-server-only.jar", "some-library.jar"]
    assert (d / "config" / "create-common.toml").read_text("utf-8") == "a=1"
    # 서버에서 고친 설정은 덮지 않음(인스턴스 쪽이 더 새 것일 때만)
    (d / "config" / "create-common.toml").write_text("a=2", "utf-8")
    runner._sync_server_mods(iid, d)
    assert (d / "config" / "create-common.toml").read_text("utf-8") == "a=2"
    # 인스턴스에서 뺀 것: 앱이 복사했던 것만 서버에서도 뺌
    (cm / "create-1.0.jar").unlink()
    runner._sync_server_mods(iid, d)
    assert sorted(p.name for p in sm.iterdir()) == ["my-server-only.jar", "some-library.jar"]


def test_mod_check_codes_and_fix(fab):
    store, iid, runner, sid, cm, sm = fab
    _fabric_jar(cm / "create-1.1.jar", "create", "1.1")           # 서버엔 1.0 → MOD-103
    _fabric_jar(cm / "farmers.jar", "farmersdelight")              # 서버에 없음 → MOD-101
    _fabric_jar(cm / "sodium.jar", "sodium", env="client")         # 클라이언트 전용: 서버에 없어도 됨
    _fabric_jar(sm / "create-1.0.jar", "create", "1.0")
    _fabric_jar(sm / "waystones.jar", "waystones")                 # 참가자도 필요한데 인스턴스엔 없음 → MOD-102
    _fabric_jar(sm / "iris.jar", "iris", env="client")             # 서버에 클라이언트 전용 → MOD-104
    _fabric_jar(sm / "luck.jar", "luckperms", env="server")        # 서버 전용: 문제 아님
    make_jar(sm / "neo.jar", "neoforge", "neomod")                 # 로더 다름 → MOD-106
    r = runner.mod_check(iid, sid)
    codes = sorted((i["code"], i["id"]) for i in r["issues"])
    assert codes == [("MOD-101", "farmersdelight"), ("MOD-102", "waystones"), ("MOD-103", "create"),
                     ("MOD-104", "iris"), ("MOD-106", "neomod")]
    res = runner.mod_fix(iid, sid, r["issues"])
    assert res["failed"] == [] and res["check"]["issues"] == []
    assert sorted(p.name for p in sm.iterdir() if p.suffix == ".jar") == ["create-1.1.jar", "farmers.jar", "luck.jar", "waystones.jar"]
    assert (cm / "waystones.jar").is_file()                       # 서버 → 인스턴스로 복사
    # 켜져 있으면 서버 쪽은 막음
    class Running:
        def poll(self):
            return None
    runner.procs[sid] = Running()
    with pytest.raises(Exception, match="중지"):
        runner.mod_fix(iid, sid, [{"fix": "removeServer", "serverFile": "luck.jar"}])
    runner.procs.clear()
    # 경로 밖은 거부
    res = runner.mod_fix(iid, sid, [{"fix": "toServer", "clientFile": "../../instance.json"}])
    assert res["failed"]


def test_mod_check_vanilla_and_paper_have_no_mods(tmp_path):
    store = InstanceStore(tmp_path)
    iid = store.create("바닐라", "26.3", "vanilla")["id"]
    runner = sr.ServerRunner(tmp_path, store, lambda v: ["java"], emit=lambda m, p: None)
    sid = runner.create(iid, "서버")["id"]
    assert runner.mod_check(iid, sid)["issues"] == []


def test_diagnoser_codes():
    dg = server_errors.Diagnoser()
    lines = [
        "[main/ERROR]: Incompatible mods found!",
        " - Mod 'Create' (create) 1.0 requires any version of fabric-api, which is missing!",
        " - Install fabric-api, any version.",
        "java.lang.UnsupportedClassVersionError: x has been compiled by a more recent version of the Java Runtime",
        "**** FAILED TO BIND TO PORT!",
        "[main/ERROR]: Incompatible mods found!",          # 같은 코드는 한 번
        "This crash report has been saved to: C:\\srv\\crash-reports\\crash-1.txt",
    ]
    got = [dg.feed(l) for l in lines]
    codes = [g["code"] for g in got if g]
    assert codes == ["MOD-201", "JAVA-101", "NET-101"]
    assert "fabric-api" in " ".join(dg.found[0]["details"])
    assert dg.found[0]["crashFile"].endswith("crash-1.txt")
    assert server_errors.Diagnoser().summary(1)[0]["code"] == "EXIT-1"
    assert server_errors.Diagnoser().summary(0) == []
    assert server_errors.match("오류: 기본 클래스 @user_jvm_args.txt을(를) 찾거나 로드할 수 없습니다.")["code"] == "JAVA-102"


def test_java_find_reads_release_and_picks_versions(tmp_path, monkeypatch):
    def jdk(name: str, version: str, javac: bool = True) -> Path:
        h = tmp_path / name
        (h / "bin").mkdir(parents=True)
        (h / "bin" / java_find.EXE).write_bytes(b"")
        if javac:
            (h / "bin" / java_find.JAVAC).write_bytes(b"")
        (h / "release").write_text(f'IMPLEMENTOR="x"\nJAVA_VERSION="{version}"\n', "utf-8")
        return h
    homes = [jdk("jdk-8", "1.8.0_402"), jdk("jdk-21", "21.0.5"), jdk("jre-25", "25.0.1", javac=False), jdk("jdk-26", "26.0.1")]
    monkeypatch.setattr(java_find, "_candidates", lambda: homes + [homes[0]])
    found = java_find.find_all()
    assert [j["major"] for j in found] == [26, 25, 21, 8]
    assert java_find.best(25)["home"].endswith("jre-25")                 # 정확히 같은 버전 먼저
    assert java_find.best(25, jdk=True)["home"].endswith("jdk-26")      # JDK 는 26 뿐
    assert java_find.best(27) is None
    env, j = java_find.build_env(25)
    assert j["home"].endswith("jdk-26") and env["JAVA_HOME"] == j["home"]
    assert java_find._major("1.8.0_402") == 8 and java_find._major("25.0.5") == 25


# ---------------------------------------------------------------- 주소 열기 모드·플러그인(2026-11-28: playit 대신)

@pytest.fixture
def addr(tmp_path, monkeypatch):
    import modrinth
    calls = []

    def fake_install(project, version, loader, target, **kw):
        if project == "boom":
            raise modrinth.NoMatch("없음")
        calls.append((project, version, loader, Path(target).name))
        Path(target).mkdir(parents=True, exist_ok=True)
        name = {"e4mc": "e4mc-fabric-6.2.3-modern.jar", "minekube-connect": "connect-spigot.jar"}[project]
        (Path(target) / name).write_bytes(b"jar")
        r = modrinth.InstallResult()
        r.installed.append({"filename": name})
        return r
    monkeypatch.setattr(modrinth, "install", fake_install)
    store = InstanceStore(tmp_path)
    events = []
    runner = sr.ServerRunner(tmp_path, store, lambda v: ["java"], emit=lambda m, p: events.append((m, p)))
    monkeypatch.setattr(runner, "_vanilla_jar", lambda v: _touch(tmp_path / "jars" / "server.jar"))
    monkeypatch.setattr(runner, "_fabric_launcher", lambda v, lv: _touch(tmp_path / "jars" / "fabric-launch.jar"))
    monkeypatch.setattr(runner, "_paper_jar", lambda v: _touch(tmp_path / "jars" / "paper.jar"))
    return store, runner, calls, events


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


@pytest.mark.address_mod
def test_address_mod_per_server_type(addr):
    store, runner, calls, _ = addr
    # Fabric 서버 → e4mc(fabric) 를 서버 mods/ 에
    fab = store.create("패브릭", "26.3", "fabric")["id"]
    s = runner.create(fab, "f")["id"]
    assert runner.prepare_launch(fab, s) == ["-jar", "fabric-server-launch.jar", "nogui"]
    assert calls[-1] == ("e4mc", "26.3", "fabric", "mods")
    assert (runner._sdir(fab, s) / "mods" / "e4mc-fabric-6.2.3-modern.jar").is_file()
    # Paper 서버 → Minekube Connect(paper) 를 plugins/ 에
    sp = runner.create(fab, "p", software="paper")["id"]
    assert runner.prepare_launch(fab, sp) == ["-jar", "paper.jar", "nogui"]
    assert calls[-1] == ("minekube-connect", "26.3", "paper", "plugins")
    # 바닐라 → Fabric 서버로 켜고 e4mc(참가자는 그냥 바닐라)
    van = store.create("바닐라", "26.3", "vanilla")["id"]
    sv = runner.create(van, "v")["id"]
    assert runner.prepare_launch(van, sv) == ["-jar", "fabric-server-launch.jar", "nogui"]
    assert calls[-1] == ("e4mc", "26.3", "fabric", "mods")
    # 끄면 아무것도 안 넣고 바닐라는 그냥 server.jar
    runner.update(van, sv, address_mod=False)
    n = len(calls)
    assert runner.prepare_launch(van, sv) == ["-jar", "server.jar", "nogui"]
    assert len(calls) == n
    assert sr.ServerRunner.address_provider({"loader": "paper"}) == "minekube"
    assert sr.ServerRunner.address_provider({"loader": "neoforge"}) == "e4mc"


@pytest.mark.address_mod
def test_address_mod_failure_falls_back(addr, monkeypatch):
    store, runner, calls, events = addr
    monkeypatch.setitem(sr.ADDRESS_MODS, "e4mc", "boom")       # Modrinth 에 그 버전 파일이 없음
    van = store.create("바닐라", "26.3", "vanilla")["id"]
    sv = runner.create(van, "v")["id"]
    assert runner.prepare_launch(van, sv) == ["-jar", "server.jar", "nogui"]      # 그냥 바닐라로 켬
    assert any("UPnP" in p.get("line", "") for m, p in events if m == "ds_log")


def test_address_lines_detected(tmp_path):
    """e4mc·Minekube Connect 의 실제 로그 문구(소스로 확인)에서 주소를 읽어 ds_address 로 알린다."""
    store = InstanceStore(tmp_path)
    iid = store.create("x", "26.3", "fabric")["id"]
    events = []
    runner = sr.ServerRunner(tmp_path, store, lambda v: ["java"], emit=lambda m, p: events.append((m, p)))
    sid = runner.create(iid, "s")["id"]

    class Proc:
        stdout = iter([
            "[12:00:00] [Server thread/INFO] [e4mc/]: Domain assigned: brave-cat.sg.e4mc.link\n",
            "[12:00:01] [Server thread/INFO]: [connect] Your public address: quick-fox.play.minekube.net\n",
            "[12:00:02] [Server thread/INFO]: Done (3.2s)! For help, type \"help\"\n",
        ])

        def wait(self):
            return 0
    runner._pump(iid, sid, Proc(), 25565)
    got = [(p["provider"], p["address"]) for m, p in events if m == "ds_address"]
    assert got == [("e4mc", "brave-cat.sg.e4mc.link"), ("minekube", "quick-fox.play.minekube.net")]


# ---------------------------------------------------------------- 뺀 모드 기억·기본 포트·로그로 찾기(2026-11-28)

def test_removed_mods_stay_removed_until_unexcluded(fab):
    """[모드 확인]에서 서버에서 뺀 모드가 다음 시작 때 인스턴스에서 다시 복사되던 것(같은 오류 되풀이)."""
    store, iid, runner, sid, cm, sm = fab
    _fabric_jar(cm / "bad-client.jar", "badclient")          # 정보상 양쪽인데 실제로는 서버에서 터지는 모드
    _fabric_jar(cm / "create.jar", "create")
    d = runner._sdir(iid, sid)
    runner._sync_server_mods(iid, d)
    assert (sm / "bad-client.jar").is_file()
    runner.mod_fix(iid, sid, [{"fix": "removeServer", "serverFile": "bad-client.jar"}])
    runner._sync_server_mods(iid, d)                          # 다시 시작
    assert not (sm / "bad-client.jar").exists() and (sm / "create.jar").is_file()
    r = runner.mod_check(iid, sid)
    assert [(i["code"], i["id"], i["pick"]) for i in r["issues"]] == [("MOD-107", "badclient", False)]   # 서버에 없음(101)으로 다시 권하지 않음
    runner.mod_fix(iid, sid, [i for i in r["issues"] if i["code"] == "MOD-107"])                         # 다시 넣기
    runner._sync_server_mods(iid, d)
    assert (sm / "bad-client.jar").is_file()


@pytest.mark.address_mod
def test_removed_e4mc_is_not_downloaded_again(addr):
    store, runner, calls, events = addr
    fab_id = store.create("패브릭", "26.3", "fabric")["id"]
    s = runner.create(fab_id, "f")["id"]
    runner.prepare_launch(fab_id, s)
    n = len(calls)
    mods = runner._sdir(fab_id, s) / "mods"
    (mods / "e4mc-fabric-6.2.3-modern.jar").unlink()
    _fabric_jar(mods / "e4mc-fabric-6.2.3-modern.jar", "e4mc")
    runner.mod_fix(fab_id, s, [{"fix": "removeServer", "serverFile": "e4mc-fabric-6.2.3-modern.jar"}])
    runner.prepare_launch(fab_id, s)
    assert len(calls) == n                                     # 다시 받지 않음
    assert any("e4mc 를 넣지 않습니다" in p.get("line", "") for m, p in events if m == "ds_log")
    issues = runner.mod_check(fab_id, s)["issues"]
    assert any(i["code"] == "MOD-107" and i["id"] == "e4mc" for i in issues)


def test_default_port_25565(tmp_path, monkeypatch):
    store = InstanceStore(tmp_path)
    iid = store.create("x", "26.3", "vanilla")["id"]
    runner = sr.ServerRunner(tmp_path, store, lambda v: ["java"], emit=lambda m, p: None)
    monkeypatch.setattr(sr, "port_free", lambda p: True)
    s = runner.create(iid, "a")
    assert sr.read_properties(runner._sdir(iid, s["id"]) / "server.properties")["server-port"] == "25565"
    monkeypatch.setattr(sr, "port_free", lambda p: p != 25565)                     # 25565 를 다른 프로그램이 씀
    s2 = runner.create(iid, "b")
    assert sr.read_properties(runner._sdir(iid, s2["id"]) / "server.properties")["server-port"] != "25565"


def test_mod_check_reads_server_log(fab):
    """서버 로그·크래시 리포트로 찾기: 없는 의존 모드(LOG-201), 클라이언트 코드(LOG-104), 오류에 나온 모드(LOG-301)."""
    import zipfile
    store, iid, runner, sid, cm, sm = fab
    d = runner._sdir(iid, sid)
    _fabric_jar(cm / "fabric-api.jar", "fabric-api")                       # 인스턴스엔 있음
    _fabric_jar(sm / "create.jar", "create")
    _fabric_jar(cm / "create.jar", "create")
    _fabric_jar(sm / "fancyhud.jar", "fancyhud")
    with zipfile.ZipFile(sm / "fancyhud.jar", "a") as z:                    # 클라이언트 코드를 부르는 클래스
        z.writestr("com/example/fancyhud/Hud.class", b"x")
    _fabric_jar(sm / "broken.jar", "brokenmod")
    _fabric_jar(cm / "fancyhud.jar", "fancyhud")
    _fabric_jar(cm / "broken.jar", "brokenmod")
    (d / "logs").mkdir(exist_ok=True)
    (d / "logs" / "latest.log").write_text("\n".join([
        "[main/ERROR]: Incompatible mods found!",
        " - Mod 'Create' (create) 6.0 requires any version of 'Fabric API' (fabric-api), which is missing!",
        " - Mod 'Create' (create) 6.0 requires version 2.0 or later of 'Flywheel' (flywheel), which is missing!",
        "java.lang.RuntimeException: Attempted to load class net/minecraft/client/gui/Gui for invalid dist DEDICATED_SERVER",
        "\tat com.example.fancyhud.Hud.<init>(Hud.java:10)",
    ]), "utf-8")
    (d / "crash-reports").mkdir(exist_ok=True)
    (d / "crash-reports" / "crash-1.txt").write_text("-- Head --\n\tMod File: C:\\srv\\mods\\broken.jar\n", "utf-8")
    issues = runner.mod_check(iid, sid)["issues"]
    got = {(i["code"], i.get("id"), i["fix"], i["pick"]) for i in issues if i.get("fromLog")}
    fapi = next(i for i in issues if i.get("id") == "fabric-api")
    assert (fapi["code"], fapi["fix"], fapi["pick"]) == ("MOD-101", "toServer", True)   # jar 비교로도 찾음 → 로그 근거만 붙음
    assert "Fabric API" in fapi["evidence"]
    assert ("LOG-201", "flywheel", None, False) in got                       # 어디에도 없음 → 받으라고 안내
    assert ("LOG-104", "fancyhud", "removeServer", True) in got              # 스택의 패키지로 jar 를 찾음
    assert ("LOG-301", "brokenmod", "removeServer", False) in got            # 원인일 수 있음(기본으로 안 고름)
    assert all(i.get("evidence") for i in issues if i.get("fromLog"))        # 근거 로그 줄
    res = runner.mod_fix(iid, sid, [i for i in issues if i["pick"]])
    assert not res["failed"] and (sm / "fabric-api.jar").is_file() and not (sm / "fancyhud.jar").exists()
