"""Windows 에서만: 앱이 부르는 순서 그대로 사이드카를 띄워 연결·실행·삭제를 해 본다(PowerShell·tasklist·휴지통 등 Windows 경로).

실패하면 사이드카 오류 기록(전체 traceback)을 그대로 보여 준다. CI(windows-latest)에서 돈다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SIDECAR = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")


class Sidecar:
    def __init__(self, data: Path, env: dict):
        self.p = subprocess.Popen([sys.executable, "-u", str(SIDECAR / "main.py"), "--data", str(data)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", env=env, cwd=str(SIDECAR))
        self.n = 0
        self.data = data

    def call(self, method: str, timeout: float = 120, **params):
        self.n += 1
        self.p.stdin.write(json.dumps({"id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            line = self.p.stdout.readline()
            if not line:
                break
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    log = self.data / "logs" / "sidecar-errors.log"
                    detail = log.read_text("utf-8") if log.exists() else ""
                    raise AssertionError(f"{method}: {msg['error']['message']}\n{detail}")
                return msg["result"]
        raise AssertionError(f"{method}: 응답 없음({timeout}s) — 멈춤")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:  # noqa: BLE001
            self.p.kill()


def test_windows_link_run_delete(tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    prism = appdata / "PrismLauncher"
    inst = prism / "instances" / "Create Mostly Create"
    game = inst / "minecraft"
    (game / "mods").mkdir(parents=True)
    (game / "saves" / "w").mkdir(parents=True)
    (game / "saves" / "w" / "level.dat").write_bytes(b"x")
    (inst / "instance.cfg").write_text("[General]\nname=Create: Mostly Create\n", "utf-8")
    (inst / "mmc-pack.json").write_text(json.dumps({"components": [
        {"uid": "net.minecraft", "version": "1.20.1"}, {"uid": "net.minecraftforge", "version": "47.2.0"}]}), "utf-8")
    (prism / "prismlauncher.cfg").write_text("[General]\n", "utf-8")
    env = {**os.environ, "APPDATA": str(appdata), "LOCALAPPDATA": str(tmp_path / "AppData" / "Local"),
           "USERPROFILE": str(tmp_path / "home"), "PYTHONIOENCODING": "utf-8"}
    sc = Sidecar(tmp_path / "data", env)
    try:
        assert sc.call("ping")
        info = sc.call("inspect_import", path=str(inst))
        assert info["loader"] == "forge"
        res = sc.call("import_file", path=str(inst), name=None, group=None, icon=None, version=None)
        iid = res["instance"]["id"]
        assert Path(res["instance"]["launchFile"]).parent == game.resolve()
        assert res["instance"]["launchKind"] == "prism"
        assert any(i["id"] == iid for i in sc.call("list_instances"))
        # cp949 로 못 읽는 글자가 명령줄에 든 프로세스가 있어도(사용자 PC 재현) 사용 중 확인이 막히면 안 된다
        odd = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "🙂 크리에이트 ⛏ ⁂"])
        try:
            print("in_use:", sc.call("import_in_use", id=iid))
        finally:
            odd.kill()
        print("prism:", sc.call("prism_status"))
        try:
            print("launch:", sc.call("launch_linked", id=iid))
        except AssertionError as e:
            assert "Prism Launcher 실행 파일을 찾지 못했습니다" in str(e), e   # CI 에는 Prism 이 없음 → 안내 문구
        print("tail:", sc.call("game_tail_log", id=iid))
        print("running:", sc.call("running"))
        print("import_detect:", len(sc.call("import_detect")))
        time.sleep(1)
        sc.call("delete_instance", id=iid)
        assert all(i["id"] != iid for i in sc.call("list_instances"))
        # Prism 인스턴스 지우기 = Prism 쪽 폴더도 휴지통(목록이 Prism 과 자동 연동이라, 2026-11-27)
        assert not inst.exists()
    finally:
        sc.close()


def test_windows_launch_file_runs_with_special_characters(tmp_path):
    """1) 경로·파일 이름에 ( ) & 한글이 있어도 실행 파일이 실제로 실행된다(launchfile.run).
    예전 `cmd /c "경로"` 는 따옴표가 떼어져 '...\\통합' 에서 끊겼다. 실행되면 표시 파일을 남기는 파일로 확인."""
    sys.path.insert(0, str(SIDECAR))
    from importers import launchfile
    for sub in ("보통 폴더", "괄호 (1) & 한글"):
        game = tmp_path / sub / "instances" / "팩 A & B (1)" / "minecraft"
        game.mkdir(parents=True)
        for name in (launchfile.file_name(), launchfile.file_name().replace(launchfile.BASENAME, launchfile.BASENAME + " (통합 작업실)")):
            path = game / name
            marker = game / "ran.txt"
            marker.unlink(missing_ok=True)
            path.write_bytes(f'@echo off\r\nrem {launchfile.MARKER}\r\necho ok> "%~dp0ran.txt"\r\n'.encode("utf-8"))
            launchfile.run(path)
            for _ in range(150):
                if marker.exists():
                    break
                time.sleep(0.1)
            assert marker.exists(), f"실행되지 않음: {path}"


def test_windows_process_query_filtered_and_encoded(monkeypatch):
    """사용 중 확인의 프로세스 조회: 필요한 이름만 WMI 에서 거르고(-Filter), 스크립트는 -EncodedCommand 로 넘긴다.
    필터에 python.exe 를 넣어 한글·이모지 명령줄의 자식 프로세스가 실제로 잡히는지 확인한다."""
    sys.path.insert(0, str(SIDECAR))
    from importers import local
    monkeypatch.delenv("INTEGRATED_STUDIO_FAKE_PROCS", raising=False)
    monkeypatch.setattr(local, "_WANTED_FILTER", local._WANTED_FILTER + " OR Name='python.exe'")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "🙂 크리에이트 ⛏"])
    try:
        time.sleep(1)
        t = time.time()
        rows = local._processes()
        took = time.time() - t
        print(f"process query: {len(rows)} rows in {took:.2f}s")
        assert any("크리에이트" in cmd for _n, cmd in rows), rows[:5]
        assert all(n in ("python.exe", "java.exe", "javaw.exe") or n in local.LAUNCHER_PROCS for n, _c in rows)
    finally:
        child.kill()


def test_windows_firewall_check_and_java_find():
    """방화벽 확인 PowerShell 이 실제 Windows 에서 돌고(듣는 서버가 있으면 그 java.exe 를 찾음), 자바 찾기가 동작하는지."""
    import socket
    sys.path.insert(0, str(SIDECAR))
    import java_find
    import firewall
    srv = socket.socket()
    srv.bind(("0.0.0.0", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        st = firewall.check(port)
        print("firewall:", st)
        assert st["supported"] and "message" in st
        assert st.get("unknown") or st["path"].lower().endswith("python.exe")    # 이 시험 프로세스가 듣고 있음
    finally:
        srv.close()
    found = java_find.find_all()
    print("java:", [(j["major"], j["jdk"], j["home"]) for j in found])
    assert all(j["major"] > 0 for j in found)
