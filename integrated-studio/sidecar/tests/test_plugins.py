"""Paper 플러그인 시험(2026-11-27): 템플릿 파일, Paper 서버 jar 고르기·검증, 빌드한 플러그인을 Paper 서버에 넣기.

실제 Fill API 응답 모양(fill.papermc.io/v3/projects/paper/versions/26.3/builds, 2026-11 확인)을 흉내 낸다.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import net  # noqa: E402
import packs as packs_mod  # noqa: E402
import server_runner as sr  # noqa: E402
from instances import InstanceStore  # noqa: E402
from rpc import RpcError  # noqa: E402

JAR = b"paper jar bytes"
SHA = hashlib.sha256(JAR).hexdigest()


def _build(i: int, channel: str, sha: str = SHA, host: str = "fill-data.papermc.io") -> dict:
    return {"id": i, "channel": channel, "downloads": {"server:default": {
        "name": f"paper-26.3-{i}.jar", "checksums": {"sha256": sha}, "size": len(JAR),
        "url": f"https://{host}/v1/objects/{sha}/paper-26.3-{i}.jar"}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = InstanceStore(tmp_path / "data")
    iid = store.create("플러그인 시험", "26.3", "vanilla")["id"]
    runner = sr.ServerRunner(tmp_path / "data", store, lambda v: ["java"])
    runner.emit = lambda m, p: None
    got = []

    def fake_download(url, dest, hashes=None, **kw):
        got.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(JAR)
        if hashes and not net.hashes_match(dest, hashes):
            dest.unlink()
            raise net.HashMismatch(dest.name)
        return dest
    monkeypatch.setattr(net, "download", fake_download)
    return store, iid, runner, got


def test_plugin_template_files_and_names(tmp_path):
    store = InstanceStore(tmp_path / "data")
    iid = store.create("시험", "26.3", "vanilla")["id"]
    pk = packs_mod.Packs(store, tmp_path / "mc")
    pk._latest_versions = lambda mc: {"gradle": "9.9.2", "loader": "x", "loom": "x", "fabric_api": "x", "checked": False}
    r = pk.plugin_new(iid, "HelloPaper", "com.example")
    root = Path(r["path"])
    assert Path(r["open"]).name == "HelloPaperPlugin.java" and r["paperApi"] == "26.3.build.+" and r["java"] == 25
    gradle = (root / "build.gradle.kts").read_text("utf-8")
    assert 'compileOnly("io.papermc.paper:paper-api:26.3.build.+")' in gradle and "JavaLanguageVersion.of(25)" in gradle
    assert "repo.papermc.io/repository/maven-public/" in gradle
    yml = (root / "src/main/resources/plugin.yml").read_text("utf-8")
    assert "main: com.example.hellopaper.HelloPaperPlugin" in yml and "api-version: '26.3'" in yml
    assert "gradle-9.9.2-bin.zip" in (root / "gradle/wrapper/gradle-wrapper.properties").read_text("utf-8")
    assert pk.list_plugin_projects(iid) == ["HelloPaper"]
    with pytest.raises(RpcError):
        pk.plugin_new(iid, "HelloPaper", "com.example")      # 이미 있음
    for bad in ("1abc", "a", "가나다", "../x"):
        with pytest.raises(RpcError):
            pk.plugin_new(iid, bad, "com.example")
    assert packs_mod.Packs.paper_api_version("1.21.4") == ("1.21.4-R0.1-SNAPSHOT", 21)


def test_paper_jar_prefers_stable_and_verifies(env, monkeypatch):
    store, iid, runner, got = env
    monkeypatch.setattr(sr, "_http_json", lambda url: [_build(264, "ALPHA"), _build(263, "STABLE")])
    jar = runner._paper_jar("26.3")
    assert jar.name == "paper-26.3-263.jar" and got[-1].endswith("paper-26.3-263.jar")
    runner._paper_jar("26.3")
    assert len(got) == 1                                          # 받아 둔 것은 다시 받지 않음(해시 확인)
    monkeypatch.setattr(sr, "_http_json", lambda url: [_build(270, "STABLE", sha="0" * 64)])
    with pytest.raises(RpcError, match="해시"):
        runner._paper_jar("26.3")
    monkeypatch.setattr(sr, "_http_json", lambda url: [_build(271, "STABLE", host="evil.example.com")])
    with pytest.raises(RpcError, match="이상"):
        runner._paper_jar("26.3")
    monkeypatch.setattr(sr, "_http_json", lambda url: [])
    with pytest.raises(RpcError, match="없습니다"):
        runner._paper_jar("27.0")


def test_paper_server_launch_and_plugin_install(env, monkeypatch, tmp_path):
    store, iid, runner, _ = env
    monkeypatch.setattr(sr, "_http_json", lambda url: [_build(263, "STABLE")])
    import server_runner
    monkeypatch.setattr(server_runner, "_trash", lambda p, b: Path(p).unlink())
    none = runner.install_plugin(iid, tmp_path / "x.jar")
    assert none["servers"] == [] and "Paper 서버가 없어" in none["message"]
    s = runner.create(iid, "플러그인 서버", online_mode=False, software="paper")
    assert s["loader"] == "paper"
    with pytest.raises(RpcError):
        runner.create(iid, "x", software="spigot")
    assert runner.prepare_launch(iid, s["id"]) == ["-jar", "paper.jar", "nogui"]
    d = runner._sdir(iid, s["id"])
    assert (d / "paper.jar").read_bytes() == JAR and (d / "plugins").is_dir()
    old = d / "plugins" / "HelloPaper-0.0.9.jar"
    old.write_bytes(b"old")
    jar = tmp_path / "HelloPaper-0.1.0.jar"
    jar.write_bytes(b"new")
    r = runner.install_plugin(iid, jar)
    assert r["servers"] == [s["id"]] and r["restarted"] == []
    assert [p.name for p in (d / "plugins").iterdir()] == ["HelloPaper-0.1.0.jar"]       # 예전 버전은 치움
    # 켜져 있던 서버는 다시 시작(가짜 프로세스로)
    calls = []

    class Running:
        def poll(self):
            return None
    runner.procs[s["id"]] = Running()
    monkeypatch.setattr(runner, "stop", lambda i, sid: calls.append(("stop", sid)))
    monkeypatch.setattr(runner, "start", lambda i, sid: calls.append(("start", sid)))
    r = runner.install_plugin(iid, jar)
    assert r["restarted"] == [s["id"]] and calls == [("stop", s["id"]), ("start", s["id"])]
    # EULA 는 자동으로 동의하지 않는다
    runner.procs.clear()
    monkeypatch.undo()
    monkeypatch.setattr(sr, "_http_json", lambda url: [_build(263, "STABLE")])
    assert runner.start(iid, s["id"])["needsEula"] is True
