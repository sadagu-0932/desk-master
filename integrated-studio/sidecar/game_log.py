"""게임 로그 따라 읽기·실행 상태, 그리고 사용자 확인 창.

- 게임은 Prism Launcher 가 켠다(우리 프로세스가 아님). 그래서 그 인스턴스의 logs/latest.log 를 따라 읽어
  게임 로그 알림({"id","line","level","source":"game"})으로 보내고, 로그 내용으로 켜짐·꺼짐을 안다
  (`Setting user:`·`Loading Minecraft` = 켜짐, `Stopping!`·`Game crashed!` = 꺼짐).
- 확인 창: 사이드카가 "confirm" 알림 {token, id, title, message} 을 보내고, 앱이 사용자에게 물은 뒤
  `confirm_reply(token, ok)` 로 답한다. 답이 올 때까지 그 작업 스레드만 기다린다(10분 지나면 취소).
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from instances import InstanceStore
from rpc import notify
from runner import _level

CONFIRM_TIMEOUT = 600.0  # 10분 안에 답이 없으면 취소로 본다
LOG_SOURCE = "game"
LogCallback = Callable[[str], None]


class Confirmer:
    """확인 질문을 앱에 알림으로 보내고 답을 기다린다."""

    def __init__(self, timeout: float = CONFIRM_TIMEOUT):
        self.timeout = timeout
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def ask(self, message: str, inst_id: str = "", title: str = "통합 작업실") -> bool:
        token = uuid.uuid4().hex
        slot: dict[str, Any] = {"event": threading.Event(), "ok": False}
        with self._lock:
            self._pending[token] = slot
        try:
            notify("confirm", {"token": token, "id": inst_id, "title": title, "message": message})
            answered = slot["event"].wait(self.timeout)
            if not answered:
                notify("confirm_cancel", {"token": token})
            return bool(answered and slot["ok"])
        finally:
            with self._lock:
                self._pending.pop(token, None)

    def callback(self, inst_id: str = "") -> Callable[[str], bool]:
        return lambda message: self.ask(message, inst_id)

    def reply(self, token: str, ok: bool) -> dict[str, Any]:
        with self._lock:
            slot = self._pending.get(token)
        if slot is None:
            return {"ok": False, "message": "이미 끝났거나 없는 확인 요청입니다."}
        slot["ok"] = bool(ok)
        slot["event"].set()
        return {"ok": True}



class LogTail:
    """tail_log 가 돌려주는 핸들. stop() 으로 멈춘다."""

    def __init__(self, path: Path, callback: LogCallback, from_start: bool, interval: float):
        self.path = path
        self.callback = callback
        self.interval = interval
        self._stop = threading.Event()
        self._pos = 0
        self._ident: tuple[int, int] | None = None
        self._buf = b""
        if not from_start:
            st = self._stat()
            if st is not None:
                self._pos, self._ident = st.st_size, (st.st_dev, st.st_ino)
        self.thread = threading.Thread(target=self._loop, name="game-log-tail", daemon=True)

    def _stat(self) -> os.stat_result | None:
        try:
            return os.stat(self.path)
        except OSError:
            return None

    def poll(self) -> None:
        """한 번 확인해 새 줄을 전달한다. 파일을 계속 열어두지 않아(게임의 로그 교체를 막지 않도록) 매번 열고 닫는다."""
        st = self._stat()
        if st is None:
            return
        ident = (st.st_dev, st.st_ino)
        if self._ident is not None and (ident != self._ident or st.st_size < self._pos):
            # 새 게임 실행으로 latest.log 가 교체·재생성됨 → 처음부터
            self._pos, self._buf = 0, b""
        self._ident = ident
        if st.st_size <= self._pos:
            return
        try:
            with open(self.path, "rb") as f:
                f.seek(self._pos)
                chunk = f.read()
        except OSError:
            return
        self._pos += len(chunk)
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            self.callback(raw.rstrip(b"\r").decode("utf-8", errors="replace"))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:  # noqa: BLE001 — 콜백 오류로 따라 읽기가 죽지 않게
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)


def tail_log(instance_dir: str | os.PathLike, callback: LogCallback, *, from_start: bool = False,
             interval: float = 0.5, start: bool = True) -> LogTail:
    """인스턴스의 logs/latest.log 를 따라 읽어 새 줄을 callback 으로 넘긴다.

    파일이 아직 없으면 생길 때까지 기다리고, 교체·재생성되면 처음부터 다시 읽는다.
    from_start=False 면 지금 있는 내용은 건너뛴다. 반환된 핸들의 stop() 으로 멈춘다.
    """
    path = Path(instance_dir) / "logs" / "latest.log"
    tail = LogTail(path, callback, from_start, interval)
    if start:
        tail.thread.start()
    return tail




class GameLogs:
    """인스턴스마다 latest.log 하나를 따라 읽고 실행 상태를 알린다."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self._tails: dict[str, LogTail] = {}
        self._lock = threading.Lock()
        self._running: dict[str, bool] = {}
        self.on_game_stopped: Callable[[str], None] | None = None   # 게임이 닫히면(설정 동기화 등)

    def tail_log(self, id: str, from_start: bool = False) -> dict[str, Any]:
        d = self.store.game_dir(id)   # 없는 인스턴스면 여기서 오류
        self.tail_stop(id)
        tail = tail_log(d, lambda line: self._on_line(id, line), from_start=bool(from_start))
        with self._lock:
            self._tails[id] = tail
        return {"ok": True, "path": str(tail.path), "message": "게임 로그를 따라 읽습니다."}

    def _on_line(self, id: str, line: str) -> None:
        notify("log", {"id": id, "line": line, "level": _level(line), "source": LOG_SOURCE})
        state = None
        if "Setting user:" in line or "Loading Minecraft" in line:
            state = True
        elif "Stopping!" in line or "Game crashed!" in line:
            state = False
        if state is not None and self._running.get(id) != state:
            self._running[id] = state
            notify("state", {"id": id, "source": "game", "running": state, "external": True})
            if not state and self.on_game_stopped:
                self.on_game_stopped(id)

    def running_games(self) -> list[str]:
        return sorted(k for k, v in self._running.items() if v)

    def tail_stop(self, id: str) -> dict[str, Any]:
        with self._lock:
            tail = self._tails.pop(id, None)
        if tail is not None:
            tail.stop()
        if self._running.pop(id, None):
            notify("state", {"id": id, "source": "game", "running": False, "external": True})
        return {"ok": True, "stopped": tail is not None}

    def tailing(self) -> list[str]:
        with self._lock:
            return sorted(self._tails)

    def shutdown(self) -> None:
        for id in self.tailing():
            self.tail_stop(id)
