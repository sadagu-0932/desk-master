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
