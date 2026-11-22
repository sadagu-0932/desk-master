"""official_launcher 를 JSON-RPC 메서드로 감싼다 (M8-1).

- 확인 콜백: 사이드카가 "confirm" 알림 {token, id, title, message} 을 보내고, 앱이 사용자에게 물은 뒤
  `confirm_reply(token, ok)` 로 답한다. 답이 올 때까지 해당 작업 스레드만 기다린다(시간 초과 = 취소).
- 로그: 기존 게임 로그 알림 형식 {"id", "line", "level", "source"} 그대로, source 는 "official".
  설치(winget) 로그처럼 특정 인스턴스가 아닌 줄은 id 를 비워 두어 모든 인스턴스 로그에 보인다.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Callable

import official_launcher as ol
from instances import InstanceStore
from rpc import RpcError, notify
from runner import _level

CONFIRM_TIMEOUT = 600.0  # 10분 안에 답이 없으면 취소로 본다
LOG_SOURCE = "official"


class Confirmer:
    """확인 질문을 앱에 알림으로 보내고 답을 기다린다."""

    def __init__(self, timeout: float = CONFIRM_TIMEOUT):
        self.timeout = timeout
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def ask(self, message: str, inst_id: str = "", title: str = "공식 런처") -> bool:
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


def _log(inst_id: str, line: str, level: str | None = None) -> None:
    notify("log", {"id": inst_id, "line": line, "level": level or _level(line), "source": LOG_SOURCE})


def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """OfficialLauncherError 를 사용자에게 그대로 보여줄 RpcError 로 바꾼다."""

    def inner(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ol.OfficialLauncherError as e:
            raise RpcError(str(e)) from e

    inner.__name__ = getattr(fn, "__name__", "official")
    return inner


class OfficialLauncherRpc:
    def __init__(self, store: InstanceStore, app_minecraft_dir: Path, confirmer: Confirmer | None = None):
        self.store = store
        self.app_minecraft_dir = Path(app_minecraft_dir)
        self.confirmer = confirmer or Confirmer()
        self._tails: dict[str, ol.LogTail] = {}
        self._tails_lock = threading.Lock()

    # ---------- 메서드 ----------
    def is_installed(self) -> dict[str, Any]:
        return ol.is_installed()

    def install(self, id: str = "") -> dict[str, Any]:
        """id 를 주면 설치 로그가 그 인스턴스 로그에, 없으면 모든 인스턴스 로그에 나온다."""
        result = ol.install(self.confirmer.callback(id), lambda line: _log(id, line, "info"))
        _log(id, result["message"], "info" if result.get("ok") else "warn")
        return result

    def register_instance(self, id: str) -> dict[str, Any]:
        meta = self.store.get(id)
        if not meta.get("installed") or not meta.get("versionId"):
            raise RpcError("먼저 이 인스턴스를 설치해 주세요. 설치한 버전을 공식 런처에 등록합니다.")
        instance = {
            "id": meta["id"],
            "name": meta.get("name") or meta["id"],
            "path": str(self.store.dir_of(id)),
            "version": meta.get("version"),
            "versionId": meta["versionId"],
            "jvmArgs": meta.get("jvmArgs"),
        }
        result = ol.register_instance(instance, self.confirmer.callback(id),
                                      app_minecraft_dir=self.app_minecraft_dir)
        if result.get("ok"):
            _log(id, result["message"], "info")
        for w in result.get("warnings") or []:
            _log(id, w, "warn")
        return result

    def unregister_instance(self, id: str) -> dict[str, Any]:
        result = ol.unregister_instance(id, self.confirmer.callback(id))
        if result.get("removed"):
            _log(id, result["message"], "info")
        return result

    def open_launcher(self) -> dict[str, Any]:
        return ol.open_launcher()

    def tail_log(self, id: str, from_start: bool = False) -> dict[str, Any]:
        """인스턴스 logs/latest.log 를 따라 읽어 게임 로그로 보낸다. 같은 인스턴스는 하나만(다시 부르면 새로 시작)."""
        d = self.store.dir_of(id)
        self.store.get(id)  # 없는 인스턴스면 여기서 오류
        self.tail_stop(id)
        tail = ol.tail_log(d, lambda line: _log(id, line), from_start=bool(from_start))
        with self._tails_lock:
            self._tails[id] = tail
        return {"ok": True, "path": str(tail.path),
                "message": "공식 런처로 실행한 게임의 로그를 따라 읽습니다."}

    def tail_stop(self, id: str) -> dict[str, Any]:
        with self._tails_lock:
            tail = self._tails.pop(id, None)
        if tail is not None:
            tail.stop()
        return {"ok": True, "stopped": tail is not None}

    def tailing(self) -> list[str]:
        with self._tails_lock:
            return sorted(self._tails)

    def shutdown(self) -> None:
        for id in self.tailing():
            self.tail_stop(id)

    # ---------- main.py 등록용 ----------
    def handlers(self) -> dict[str, Callable[..., Any]]:
        return {
            "official_is_installed": _wrap(self.is_installed),
            "official_install": _wrap(self.install),
            "official_register_instance": _wrap(self.register_instance),
            "official_unregister_instance": _wrap(self.unregister_instance),
            "official_open_launcher": _wrap(self.open_launcher),
            "official_tail_log": _wrap(self.tail_log),
            "official_tail_stop": _wrap(self.tail_stop),
            "official_tailing": self.tailing,
            "confirm_reply": lambda token, ok: self.confirmer.reply(token, ok),
        }

    # 확인을 기다리거나 PowerShell·winget 을 부르는 메서드는 입력 루프를 막지 않게 별도 스레드로.
    # confirm_reply 는 입력 루프에서 바로 처리해야 기다리는 스레드를 깨울 수 있다(여기에 넣지 않음).
    BACKGROUND = {"official_is_installed", "official_install", "official_register_instance",
                  "official_unregister_instance", "official_open_launcher"}
