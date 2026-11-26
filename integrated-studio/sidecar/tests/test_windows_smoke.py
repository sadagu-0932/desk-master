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
        print("in_use:", sc.call("import_in_use", id=iid))
        print("official:", sc.call("official_is_installed"))
        print("touch:", sc.call("official_touch", id=iid))
        try:
            print("launch:", sc.call("launch_linked", id=iid))
        except AssertionError as e:
            assert "Prism Launcher 실행 파일을 찾지 못했습니다" in str(e), e   # CI 에는 Prism 이 없음 → 안내 문구
        print("tail:", sc.call("official_tail_log", id=iid))
        print("running:", sc.call("running"))
        print("import_detect:", len(sc.call("import_detect")))
        time.sleep(1)
        sc.call("delete_instance", id=iid)
        assert all(i["id"] != iid for i in sc.call("list_instances"))
        assert inst.is_dir() and (game / "saves" / "w" / "level.dat").is_file()   # 원래 폴더는 그대로
    finally:
        sc.close()
