"""공식 런처 RPC 연결(official_rpc + main.py) 시험. pytest 없이 `python tests/test_official_rpc.py`.

1) main.py 를 실제 자식 프로세스로 띄워 stdin/stdout JSON-RPC 로 메서드 연결·로그 알림 형식을 확인
2) 같은 프로세스 안에서 Windows·.minecraft 를 흉내 내 확인 알림 → confirm_reply → 등록/취소/삭제 흐름 확인
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDECAR = HERE.parent
sys.path.insert(0, str(SIDECAR))

PASSED = 0


def check(cond: bool, msg: str) -> None:
    global PASSED
    if not cond:
        raise AssertionError(msg)
    PASSED += 1
    print(f"  ✓ {msg}")


# ------------------------------------------------------------------ 1) main.py 자식 프로세스
class Sidecar:
    def __init__(self, data: Path):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        self.proc = subprocess.Popen([sys.executable, "-u", str(SIDECAR / "main.py"), "--data", str(data)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", env=env)
        self.msgs: queue.Queue = queue.Queue()
        self.notes: list[dict] = []
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 1
        self.wait_note(lambda n: n["method"] == "ready")

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.msgs.put(json.loads(line))

    def _pump(self, timeout: float) -> dict:
        m = self.msgs.get(timeout=timeout)
        if "method" in m and "id" not in m:
            self.notes.append(m)
        return m

    def call(self, method: str, timeout: float = 30, **params):
        rid = self.next_id
        self.next_id += 1
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"id": rid, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        end = time.time() + timeout
        while True:
            m = self._pump(max(0.1, end - time.time()))
            if m.get("id") == rid:
                if "error" in m:
                    raise RuntimeError(m["error"]["message"])
                return m["result"]

    def wait_note(self, pred, timeout: float = 15) -> dict:
        for n in self.notes:
            if pred(n):
                return n
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = self._pump(0.2)
            except queue.Empty:
                continue
            if "method" in m and "id" not in m and pred(m):
                return m
        raise AssertionError("알림이 오지 않았습니다")

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def test_main_wiring(tmp: Path) -> None:
    print("1) main.py RPC 연결")
    sc = Sidecar(tmp / "data")
    try:
        info = sc.call("official_is_installed", timeout=60)
        check(isinstance(info.get("installed"), bool) and "message" in info, "official_is_installed 응답")
        r = sc.call("confirm_reply", token="없는토큰", ok=True)
        check(r["ok"] is False, "모르는 확인 토큰에는 ok=False")
        check(sc.call("official_tailing") == [], "처음에는 따라 읽는 인스턴스 없음")

        inst = sc.call("create_instance", name="공식 런처 시험", version="26.3", loader="vanilla")
        try:
            sc.call("official_register_instance", id=inst["id"])
            check(False, "설치 전 인스턴스 등록은 거부")
        except RuntimeError as e:
            check("먼저 이 인스턴스를 설치" in str(e), "설치 전 인스턴스 등록은 거부")

        logs = Path(inst["path"]) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "latest.log").write_text("[00:00:00] [main/INFO]: 이전 실행\n", "utf-8")
        r = sc.call("official_tail_log", id=inst["id"])
        check(r["ok"] and r["path"].endswith("latest.log"), "official_tail_log 시작")
        check(sc.call("official_tailing") == [inst["id"]], "따라 읽는 목록에 들어감")
        with open(logs / "latest.log", "a", encoding="utf-8") as f:
            f.write("[12:00:01] [Render thread/WARN]: 공식 런처 경고 줄\n")
        n = sc.wait_note(lambda m: m["method"] == "log" and "공식 런처 경고 줄" in m["params"]["line"])
        p = n["params"]
        check(p["id"] == inst["id"] and p["source"] == "official" and p["level"] == "warn",
              "로그가 게임 로그 알림 형식(id·line·level·source=official)으로 옴")
        check(not any("이전 실행" in m["params"].get("line", "") for m in sc.notes if m["method"] == "log"),
              "기존 내용은 건너뜀(from_start=False)")
        r = sc.call("official_tail_stop", id=inst["id"])
        check(r["stopped"] and sc.call("official_tailing") == [], "official_tail_stop")
        try:
            sc.call("official_tail_log", id="inst_00000000")
            check(False, "없는 인스턴스는 거부")
        except RuntimeError:
            check(True, "없는 인스턴스는 거부")
    finally:
        sc.close()


# ------------------------------------------------------------------ 2) 확인 흐름 (프로세스 안)
def test_confirm_flow(tmp: Path) -> None:
    print("2) 확인 알림 → confirm_reply 흐름")
    import official_launcher as ol
    import official_rpc
    from instances import InstanceStore

    ol._is_windows = lambda: True  # type: ignore[assignment]
    ol.launcher_running = lambda: False  # type: ignore[assignment]
    mc = tmp / "official" / ".minecraft"
    mc.mkdir(parents=True)
    (mc / "launcher_profiles.json").write_text(json.dumps(
        {"profiles": {"user-own": {"name": "내 프로필", "type": "custom", "lastVersionId": "26.3"}}, "version": 3}), "utf-8")
    token_file = mc / "launcher_accounts.json"
    token_file.write_text('{"secret": "do-not-touch"}', "utf-8")
    token_before = token_file.read_bytes()
    ol.find_minecraft_dir = lambda: {"path": mc, "kind": "roaming", "warning": None}  # type: ignore[assignment]

    app_mc = tmp / "app-mc"
    vid = "fabric-loader-0.20.1-26.3"
    (app_mc / "versions" / vid).mkdir(parents=True)
    (app_mc / "versions" / vid / f"{vid}.json").write_text('{"id": "%s"}' % vid, "utf-8")

    store = InstanceStore(tmp / "data2")
    inst = store.create("우리 Fabric", "26.3", "fabric", "0.20.1", cc_enabled=False)
    meta = store.get(inst["id"])
    meta.update(installed=True, versionId=vid)
    store.save(meta)

    answers: list[bool] = []
    notes: list[tuple[str, dict]] = []
    rpc_obj = official_rpc.OfficialLauncherRpc(store, app_mc, official_rpc.Confirmer(timeout=5))

    def fake_notify(method: str, params: dict) -> None:
        notes.append((method, params))
        if method == "confirm":
            ok = answers.pop(0) if answers else None
            if ok is not None:  # None 이면 답하지 않아 시간 초과를 흉내 낸다
                threading.Timer(0.05, lambda: rpc_obj.confirmer.reply(params["token"], ok)).start()

    official_rpc.notify = fake_notify  # type: ignore[assignment]
    h = rpc_obj.handlers()

    answers.append(False)
    r = h["official_register_instance"](id=inst["id"])
    data = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))
    check(not r["ok"] and len(data["profiles"]) == 1, "'아니오'면 아무것도 바꾸지 않음")
    confirm = next(p for m, p in notes if m == "confirm")
    check(confirm["id"] == inst["id"] and "우리 Fabric" in confirm["message"] and confirm["token"],
          "확인 알림에 token·인스턴스 id·질문이 들어감")

    answers.append(True)
    r = h["official_register_instance"](id=inst["id"])
    data = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))
    key = "integrated-studio-" + inst["id"]
    prof = data["profiles"].get(key, {})
    check(r["ok"] and prof.get("lastVersionId") == vid and prof.get("gameDir") == str(store.dir_of(inst["id"])),
          "'예'면 고정 키로 등록(버전·게임 폴더)")
    check("user-own" in data["profiles"], "사용자 기존 프로필은 그대로")
    check((mc / "versions" / vid / f"{vid}.json").is_file(), "Fabric 버전 JSON 복사")
    check(any(m == "log" and p["source"] == "official" and p["id"] == inst["id"] for m, p in notes),
          "등록 결과가 게임 로그로 감")

    answers.append(None)
    t0 = time.time()
    r = h["official_unregister_instance"](id=inst["id"])
    check(not r["ok"] and key in json.loads((mc / "launcher_profiles.json").read_text("utf-8"))["profiles"]
          and time.time() - t0 >= 4.5, "답이 없으면 시간 초과 = 취소")
    check(any(m == "confirm_cancel" for m, _ in notes), "시간 초과 시 confirm_cancel 알림으로 창을 닫게 함")

    answers.append(True)
    r = h["official_unregister_instance"](id=inst["id"])
    data = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))
    check(r["removed"] and key not in data["profiles"] and "user-own" in data["profiles"], "우리 항목만 삭제")
    check(token_file.read_bytes() == token_before, "로그인·토큰 파일은 건드리지 않음")

    try:
        h["official_unregister_instance"](id="../../etc")
        check(False, "잘못된 id 는 사용자용 오류로")
    except official_rpc.RpcError as e:
        check("잘못된 인스턴스 id" in str(e), "잘못된 id 는 사용자용 오류(RpcError)로")


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        test_main_wiring(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_confirm_flow(Path(d))
    print(f"\n통과 {PASSED}개")


if __name__ == "__main__":
    main()
