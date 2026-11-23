"""official_launcher 테스트. Windows 가 아니어도 돌도록 플랫폼·winget·PowerShell 은 모두 mock."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import official_launcher as ol  # noqa: E402

TOKEN_FILES = ("launcher_accounts.json", "launcher_accounts_microsoft_store.json", "launcher_msa_credentials.bin")


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(ol, "_is_windows", lambda: True)
    monkeypatch.setattr(ol, "launcher_running", lambda: False)
    return monkeypatch


@pytest.fixture
def mc(tmp_path):
    """가짜 공식 런처 .minecraft. 기존 사용자 프로필과 토큰 파일을 넣어 둔다."""
    d = tmp_path / ".minecraft"
    d.mkdir()
    (d / "launcher_profiles.json").write_text(json.dumps({
        "profiles": {"abc": {"name": "내 프로필", "type": "custom", "lastVersionId": "1.21.4"},
                     "latest": {"name": "", "type": "latest-release", "lastVersionId": "latest-release"}},
        "settings": {"keepLauncherOpen": False}, "version": 3,
    }), "utf-8")
    for name in TOKEN_FILES:
        (d / name).write_text("SECRET", "utf-8")
    return d


def instance(tmp_path, **kw):
    p = tmp_path / "instances" / "inst_1"
    p.mkdir(parents=True, exist_ok=True)
    meta = {"id": "inst_1", "name": "내 월드", "path": str(p), "version": "1.21.4",
            "versionId": "fabric-loader-0.16.10-1.21.4", "jvmArgs": ["-Xmx4G", "-XX:+UseG1GC"]}
    meta.update(kw)
    return meta


def profiles(mc):
    return json.loads((mc / "launcher_profiles.json").read_text("utf-8"))["profiles"]


def yes(_msg):
    return True


# ---------------------------------------------------------------- 플랫폼

def test_non_windows_is_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(ol, "_is_windows", lambda: False)
    assert ol.is_installed()["installed"] is False
    assert ol.install(yes, print)["ok"] is False
    assert ol.open_launcher()["ok"] is False
    assert ol.register_instance(instance(tmp_path), yes)["ok"] is False
    assert ol.unregister_instance("inst_1", yes)["ok"] is False


# ---------------------------------------------------------------- is_installed

def test_is_installed_store(win):
    out = "Microsoft.4297127D64EC6_8wekyb3d8bbwe|C:\\Program Files\\WindowsApps\\x|Minecraft|1.2.3\n"
    win.setattr(ol, "_run", lambda args, timeout=30: subprocess.CompletedProcess(args, 0, out, ""))
    win.setattr(ol, "_find_classic_exe", lambda: None)
    r = ol.is_installed()
    assert r["installed"] and r["kind"] == "store" and r["kinds"] == ["store"]
    assert r["store"]["family"] == ol.STORE_PACKAGE_FAMILY and r["store"]["app_id"] == "Minecraft"


def test_is_installed_classic_default_path(win, tmp_path):
    win.setattr(ol, "_run", lambda args, timeout=30: subprocess.CompletedProcess(args, 0, "", ""))
    win.setattr(ol, "_registry_launcher_paths", lambda: [])
    pf = tmp_path / "pf86"
    (pf / "Minecraft Launcher").mkdir(parents=True)
    (pf / "Minecraft Launcher" / "MinecraftLauncher.exe").write_text("")
    win.setenv("ProgramFiles(x86)", str(pf))
    win.delenv("ProgramFiles", raising=False)
    win.delenv("LOCALAPPDATA", raising=False)
    r = ol.is_installed()
    assert r["kinds"] == ["classic"] and r["exe"].endswith("MinecraftLauncher.exe")


def test_is_installed_both_and_none(win):
    out = "fam|loc|App|1\n"
    win.setattr(ol, "_run", lambda args, timeout=30: subprocess.CompletedProcess(args, 0, out, ""))
    win.setattr(ol, "_find_classic_exe", lambda: Path("C:/x/MinecraftLauncher.exe"))
    assert ol.is_installed()["kinds"] == ["store", "classic"]

    win.setattr(ol, "_run", lambda args, timeout=30: subprocess.CompletedProcess(args, 1, "", "err"))
    win.setattr(ol, "_find_classic_exe", lambda: None)
    r = ol.is_installed()
    assert r["installed"] is False and "설치되어 있지 않습니다" in r["message"]


# ---------------------------------------------------------------- install

class FakeProc:
    def __init__(self, lines, code):
        self.stdout = io.StringIO("".join(lines))
        self._code = code

    def wait(self):
        return self._code


def test_install_requires_confirmation(win):
    called = []
    win.setattr(ol, "_popen", lambda args: called.append(args))
    win.setattr(ol, "_start_file", lambda t: called.append(t))
    r = ol.install(lambda m: False, print)
    assert r["ok"] is False and called == []


def test_install_winget_success(win):
    seen = {}

    def popen(args):
        seen["args"] = args
        return FakeProc(["Found Minecraft Launcher [Mojang.MinecraftLauncher]\n", "  ██████▒▒▒  1.0 MB / 2.0 MB\r\n",
                         "   - \n", "Successfully installed\n"], 0)

    win.setattr(ol.shutil, "which", lambda n: "C:/winget.exe")
    win.setattr(ol, "_popen", popen)
    win.setattr(ol, "_start_file", lambda t: pytest.fail("Store 를 열면 안 됨"))
    logs = []
    r = ol.install(yes, logs.append)
    assert r["ok"] and r["method"] == "winget"
    assert "스스로 최신 버전으로 업데이트" in r["message"]
    assert seen["args"][1:] == ["install", "--id", "Mojang.MinecraftLauncher", "--exact",
                                "--accept-package-agreements", "--accept-source-agreements"]
    assert "Successfully installed" in logs and not any("██" in l for l in logs)


def test_install_winget_fails_falls_back_to_store(win):
    opened = []
    win.setattr(ol.shutil, "which", lambda n: "C:/winget.exe")
    win.setattr(ol, "_popen", lambda args: FakeProc(["오류\n"], 1))
    win.setattr(ol, "_start_file", opened.append)
    r = ol.install(yes, lambda l: None)
    assert r["ok"] and r["method"] == "store" and opened == [ol.STORE_URL]


def test_install_no_winget_opens_store(win):
    opened = []
    win.setattr(ol.shutil, "which", lambda n: None)
    win.setattr(ol, "_start_file", opened.append)
    assert ol.install(yes, lambda l: None)["method"] == "store"
    assert opened == ["ms-windows-store://pdp/?productid=9PGW18NPBZV5"]


def test_install_everything_fails(win):
    def boom(t):
        raise OSError("no")

    win.setattr(ol.shutil, "which", lambda n: None)
    win.setattr(ol, "_start_file", boom)
    assert ol.install(yes, lambda l: None)["ok"] is False


# ---------------------------------------------------------------- .minecraft 경로

def _profiles_at(d: Path, mtime: float):
    d.mkdir(parents=True)
    f = d / "launcher_profiles.json"
    f.write_text('{"profiles": {}}', "utf-8")
    os.utime(f, (mtime, mtime))


def test_find_minecraft_dir_roaming_vs_store(win, tmp_path):
    appdata, local = tmp_path / "Roaming", tmp_path / "Local"
    win.setenv("APPDATA", str(appdata))
    win.setenv("LOCALAPPDATA", str(local))
    assert ol.find_minecraft_dir()["path"] is None

    store_mc = local / "Packages" / ol.STORE_PACKAGE_FAMILY / "LocalCache" / "Roaming" / ".minecraft"
    _profiles_at(store_mc, 1000)
    r = ol.find_minecraft_dir()
    assert r["path"] == store_mc and r["kind"] == "store-virtualized" and r["warning"] is None

    _profiles_at(appdata / ".minecraft", 2000)  # 더 최근
    r = ol.find_minecraft_dir()
    assert r["path"] == appdata / ".minecraft" and r["kind"] == "roaming" and "두 곳" in r["warning"]


def test_register_without_profiles_file_explains(win, tmp_path):
    win.setenv("APPDATA", str(tmp_path / "a"))
    win.setenv("LOCALAPPDATA", str(tmp_path / "b"))
    with pytest.raises(ol.OfficialLauncherError, match="한 번 실행"):
        ol.register_instance(instance(tmp_path), yes)


# ---------------------------------------------------------------- register / unregister

def test_register_adds_profile_with_backup(win, tmp_path, mc):
    original = (mc / "launcher_profiles.json").read_text("utf-8")
    inst = instance(tmp_path)
    r = ol.register_instance(inst, yes, minecraft_dir=mc)
    assert r["ok"] and r["key"] == "integrated-studio-inst_1" and r["updated"] is False

    p = profiles(mc)
    assert set(p) == {"abc", "latest", "integrated-studio-inst_1"}  # 기존 항목 보존
    ours = p["integrated-studio-inst_1"]
    assert ours["name"] == "통합 작업실 · 내 월드"
    assert ours["lastVersionId"] == "fabric-loader-0.16.10-1.21.4"
    assert ours["gameDir"] == str(Path(inst["path"]).resolve())
    assert ours["javaArgs"] == "-Xmx4G -XX:+UseG1GC"
    assert ours["type"] == "custom"
    assert json.loads((mc / "launcher_profiles.json").read_text("utf-8"))["settings"] == {"keepLauncherOpen": False}

    backup = Path(r["backup"])
    assert backup.parent == mc and backup.read_text("utf-8") == original


def test_register_twice_updates_not_duplicates(win, tmp_path, mc):
    ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc)
    data = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))
    data["profiles"]["integrated-studio-inst_1"]["icon"] = "Furnace"   # 사용자가 런처에서 바꾼 아이콘
    created = data["profiles"]["integrated-studio-inst_1"]["created"]
    (mc / "launcher_profiles.json").write_text(json.dumps(data), "utf-8")

    r = ol.register_instance(instance(tmp_path, name="새 이름", versionId=None, jvmArgs="-Xmx6G"), yes,
                             minecraft_dir=mc)
    assert r["updated"] is True
    p = profiles(mc)
    ours = [k for k in p if k.startswith("integrated-studio-")]
    assert ours == ["integrated-studio-inst_1"] and len(p) == 3
    o = p["integrated-studio-inst_1"]
    assert o["name"] == "통합 작업실 · 새 이름" and o["lastVersionId"] == "1.21.4"
    assert o["javaArgs"] == "-Xmx6G" and o["icon"] == "Furnace" and o["created"] == created


def test_register_declined_changes_nothing(win, tmp_path, mc):
    before = (mc / "launcher_profiles.json").read_bytes()
    for cb in (None, lambda m: False):
        r = ol.register_instance(instance(tmp_path), cb, minecraft_dir=mc)
        assert r["ok"] is False
    assert (mc / "launcher_profiles.json").read_bytes() == before
    assert not list(mc.glob("*.bak"))


def test_register_failure_restores_backup(win, tmp_path, mc):
    before = (mc / "launcher_profiles.json").read_bytes()

    def broken(mc_dir, profile):
        Path(mc_dir, "launcher_profiles.json").write_text("{깨짐", "utf-8")
        raise RuntimeError("disk")

    win.setattr(ol.vanilla_launcher, "add_vanilla_launcher_profile", broken)
    with pytest.raises(ol.OfficialLauncherError, match="되돌렸습니다"):
        ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc)
    assert (mc / "launcher_profiles.json").read_bytes() == before


def test_register_copies_fabric_version_json(win, tmp_path, mc):
    app_mc = tmp_path / "app_mc"
    vid = "fabric-loader-0.16.10-1.21.4"
    (app_mc / "versions" / vid).mkdir(parents=True)
    (app_mc / "versions" / vid / f"{vid}.json").write_text('{"id": "%s", "inheritsFrom": "1.21.4"}' % vid)
    r = ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc, app_minecraft_dir=app_mc)
    assert (mc / "versions" / vid / f"{vid}.json").is_file()
    assert "복사" in r["message"]


def test_register_warns_when_launcher_running(win, tmp_path, mc):
    win.setattr(ol, "launcher_running", lambda: True)
    r = ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc)
    assert r["ok"] and any("켜져 있습니다" in w for w in r["warnings"])


def test_register_rejects_bad_id_and_bad_file(win, tmp_path, mc):
    with pytest.raises(ol.OfficialLauncherError):
        ol.register_instance(instance(tmp_path, id="../evil"), yes, minecraft_dir=mc)
    (mc / "launcher_profiles.json").write_text('{"profiles": []}', "utf-8")
    with pytest.raises(ol.OfficialLauncherError, match="형식"):
        ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc)


def test_backups_are_pruned(win, tmp_path, mc):
    for _ in range(ol.BACKUP_KEEP + 3):
        ol.backup_profiles(mc)
    assert len(list(mc.glob("launcher_profiles.json.integrated-studio-*.bak"))) == ol.BACKUP_KEEP


def test_unregister_only_ours(win, tmp_path, mc):
    ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc)
    assert ol.unregister_instance("inst_1", lambda m: False, minecraft_dir=mc)["removed"] is False
    assert "integrated-studio-inst_1" in profiles(mc)

    r = ol.unregister_instance("inst_1", yes, minecraft_dir=mc)
    assert r["removed"] and Path(r["backup"]).is_file()
    assert set(profiles(mc)) == {"abc", "latest"}

    r = ol.unregister_instance("inst_1", yes, minecraft_dir=mc)
    assert r["ok"] and r["removed"] is False
    # 남의 항목 키를 줘도 우리 접두사가 붙어서 지울 수 없다
    ol.unregister_instance("abc", yes, minecraft_dir=mc)
    assert "abc" in profiles(mc)


def test_token_files_never_touched(win, tmp_path, mc, monkeypatch):
    real_open = open
    opened: list[str] = []

    def spy(file, *a, **kw):
        opened.append(os.path.basename(str(file)))
        return real_open(file, *a, **kw)

    monkeypatch.setattr("builtins.open", spy)
    stats = {n: (mc / n).stat().st_mtime_ns for n in TOKEN_FILES}
    ol.register_instance(instance(tmp_path), yes, minecraft_dir=mc)
    ol.unregister_instance("inst_1", yes, minecraft_dir=mc)
    assert not any(n in TOKEN_FILES for n in opened)
    for n in TOKEN_FILES:
        assert (mc / n).read_text("utf-8") == "SECRET" and (mc / n).stat().st_mtime_ns == stats[n]


def test_guard_rejects_credential_files(tmp_path):
    for n in TOKEN_FILES:
        with pytest.raises(ol.OfficialLauncherError):
            ol._guard_path(tmp_path / n)


# ---------------------------------------------------------------- open_launcher

def test_open_launcher_store(win):
    opened = []
    win.setattr(ol, "is_installed", lambda: {"exe": None, "store": {"family": "Fam_x", "app_id": "Minecraft"}})
    win.setattr(ol, "_start_file", opened.append)
    assert ol.open_launcher()["ok"] and opened == ["shell:AppsFolder\\Fam_x!Minecraft"]


def test_open_launcher_classic(win):
    started = []
    win.setattr(ol, "is_installed", lambda: {"exe": "C:/ML/MinecraftLauncher.exe", "store": None})
    win.setattr(ol.subprocess, "Popen", lambda args, **kw: started.append(args))
    assert ol.open_launcher()["ok"] and started == [["C:/ML/MinecraftLauncher.exe"]]


def test_open_launcher_not_installed(win):
    win.setattr(ol, "is_installed", lambda: {"exe": None, "store": None})
    assert ol.open_launcher()["ok"] is False


# ---------------------------------------------------------------- tail_log

def test_tail_log_poll_handles_partial_rotation_and_recreate(tmp_path):
    log = tmp_path / "logs" / "latest.log"
    lines: list[str] = []
    t = ol.tail_log(tmp_path, lines.append, start=False)
    t.poll()                                   # 아직 파일 없음
    assert lines == []

    log.parent.mkdir()
    log.write_bytes("[12:00:00] [main/INFO]: 시작\r\n반쪽".encode())
    t.poll()
    assert lines == ["[12:00:00] [main/INFO]: 시작"]   # 줄바꿈 없는 반쪽은 보류
    with open(log, "ab") as f:
        f.write(" 줄\n".encode())
    t.poll()
    assert lines[-1] == "반쪽 줄"

    # 새 게임 실행: 기존 파일을 옮기고 새로 만든다
    log.rename(tmp_path / "logs" / "2026-11-22-1.log")
    log.write_text("새 로그\n", "utf-8")
    t.poll()
    assert lines[-1] == "새 로그"

    # 같은 파일이 잘려서 다시 쓰임(크기 감소)
    log.write_text("x\n", "utf-8")
    t.poll()
    assert lines[-1] == "x"


def test_tail_log_skips_existing_by_default(tmp_path):
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "latest.log"
    log.write_text("옛날 줄\n", "utf-8")
    got: list[str] = []
    t = ol.tail_log(tmp_path, got.append, start=False)
    t.poll()
    assert got == []
    with open(log, "a", encoding="utf-8") as f:
        f.write("새 줄\n")
    t.poll()
    assert got == ["새 줄"]

    got2: list[str] = []
    t2 = ol.tail_log(tmp_path, got2.append, from_start=True, start=False)
    t2.poll()
    assert got2 == ["옛날 줄", "새 줄"]


def test_tail_log_thread(tmp_path):
    (tmp_path / "logs").mkdir()
    got: list[str] = []
    t = ol.tail_log(tmp_path, got.append, interval=0.02)
    try:
        (tmp_path / "logs" / "latest.log").write_text("a\nb\n", "utf-8")
        deadline = time.time() + 3
        while len(got) < 2 and time.time() < deadline:
            time.sleep(0.02)
    finally:
        t.stop()
    assert got == ["a", "b"] and not t.thread.is_alive()


def test_forge_generated_libraries_copied(tmp_path):
    """Forge·NeoForge 설치기가 만든 라이브러리(주소 없음)는 공식 .minecraft 로 복사, 주소 있는 건 런처에 맡긴다."""
    import json as _json
    app = tmp_path / "app"
    off = tmp_path / "official"
    vid = "neoforge-26.3.0.115"
    gen = "net/neoforged/neoforge/26.3.0.115/neoforge-26.3.0.115-client.jar"
    dl = "org/ow2/asm/asm/9.9/asm-9.9.jar"
    vj = {"id": vid, "inheritsFrom": "26.3", "libraries": [
        {"name": "gen", "downloads": {"artifact": {"path": gen, "url": ""}}},
        {"name": "asm", "downloads": {"artifact": {"path": dl, "url": "https://maven.neoforged.net/x.jar"}}},
        {"name": "evil", "downloads": {"artifact": {"path": "../../evil.jar", "url": ""}}},
    ]}
    (app / "versions" / vid).mkdir(parents=True)
    (app / "versions" / vid / f"{vid}.json").write_text(_json.dumps(vj), "utf-8")
    for rel in (gen, dl):
        (app / "libraries" / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / "libraries" / rel).write_bytes(b"jar")
    off.mkdir()
    log: list[str] = []
    ol._ensure_version_json(off, vid, app, log)
    assert (off / "versions" / vid / f"{vid}.json").is_file()
    assert (off / "libraries" / gen).is_file()
    assert not (off / "libraries" / dl).exists()
    assert not (tmp_path / "evil.jar").exists()
    assert any("라이브러리 1개" in m for m in log)
