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
from instances import InstanceStore, write_cc_config
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
        self._game_running: dict[str, bool] = {}
        self._profiles_lock = threading.RLock()  # launcher_profiles.json 을 쓰는 작업은 한 번에 하나(실행·동기화 겹침 방지)
        self.on_game_stopped: Callable[[str], None] | None = None  # 게임이 닫히면(설정 동기화 등)

    # ---------- 메서드 ----------
    def is_installed(self) -> dict[str, Any]:
        return ol.is_installed()

    def install(self, id: str = "") -> dict[str, Any]:
        """id 를 주면 설치 로그가 그 인스턴스 로그에, 없으면 모든 인스턴스 로그에 나온다."""
        result = ol.install(self.confirmer.callback(id), lambda line: _log(id, line, "info"))
        _log(id, result["message"], "info" if result.get("ok") else "warn")
        return result

    def _instance_dict(self, id: str) -> dict[str, Any]:
        meta = self.store.get(id)
        if not meta.get("installed") or not meta.get("versionId"):
            raise RpcError("먼저 이 인스턴스를 설치해 주세요. 설치한 버전을 공식 런처에 등록합니다.")
        if meta.get("ccPort"):
            write_cc_config(self.store.dir_of(id), meta["ccPort"])  # CommandCrafter 포트(공식 런처로 켜도 같은 폴더)
        return {
            "id": meta["id"],
            "name": meta.get("name") or meta["id"],
            "path": str(self.store.dir_of(id)),
            "version": meta.get("version"),
            "versionId": meta["versionId"],
            "jvmArgs": meta.get("jvmArgs"),
        }

    def register_instance(self, id: str) -> dict[str, Any]:
        """처음 등록은 묻는다. 이미 우리 항목이 있으면(동기화 대상) 묻지 않고 맞춘다."""
        with self._profiles_lock:
            return self._register_instance_locked(id)

    def _register_instance_locked(self, id: str) -> dict[str, Any]:
        instance = self._instance_dict(id)
        current = ol.registered_profile(id)
        if current and self._same_profile(current, instance):
            return {"ok": True, "key": ol.profile_key(id), "updated": False, "unchanged": True, "backup": None,
                    "message": "공식 런처에 이미 등록돼 있습니다.", "warnings": []}
        confirm = (lambda _m: True) if current else self.confirmer.callback(id)
        result = ol.register_instance(instance, confirm, app_minecraft_dir=self.app_minecraft_dir)
        if result.get("ok"):
            _log(id, result["message"], "info")
        for w in result.get("warnings") or []:
            _log(id, w, "warn")
        return result

    def sync_profile(self, id: str) -> bool:
        """이미 등록된 인스턴스의 항목이 달라졌으면 확인 없이 고친다. 고쳤으면 True."""
        with self._profiles_lock:
            return self._sync_profile_locked(id)

    def _sync_profile_locked(self, id: str) -> bool:
        current = ol.registered_profile(id)
        if not current:
            return False
        try:
            instance = self._instance_dict(id)
        except RpcError:
            return False
        if self._same_profile(current, instance):
            return False
        result = ol.register_instance(instance, lambda _m: True, app_minecraft_dir=self.app_minecraft_dir)
        if result.get("ok"):
            _log(id, "공식 런처 항목을 맞췄습니다: " + result["message"], "info")
        return bool(result.get("ok"))

    def forget(self, id: str) -> bool:
        """인스턴스를 지울 때 우리 항목도 확인 없이 지운다. 지웠으면 True."""
        with self._profiles_lock:
            return self._forget_locked(id)

    def _forget_locked(self, id: str) -> bool:
        if not ol.registered_profile(id):
            return False
        self.tail_stop(id)
        r = ol.unregister_instance(id, lambda _m: True)
        if r.get("removed"):
            _log("", r["message"], "info")
        return bool(r.get("removed"))

    def remove_orphans(self, existing_ids: set[str]) -> int:
        """앱에 없는 인스턴스의 우리 항목(다른 곳에서 지운 경우)을 정리한다."""
        with self._profiles_lock:
            return self._remove_orphans_locked(existing_ids)

    def _remove_orphans_locked(self, existing_ids: set[str]) -> int:
        n = 0
        for iid in ol.registered_ids():
            if iid not in existing_ids:
                r = ol.unregister_instance(iid, lambda _m: True)
                if r.get("removed"):
                    _log("", "없어진 인스턴스의 공식 런처 항목을 지웠습니다: " + r["message"], "info")
                    n += 1
        return n

    @staticmethod
    def _same_profile(profile: dict[str, Any], instance: dict[str, Any]) -> bool:
        try:
            same_dir = Path(profile.get("gameDir", "")).resolve() == Path(instance["path"]).resolve()
        except OSError:
            return False
        return (same_dir and profile.get("lastVersionId") == instance["versionId"]
                and profile.get("name") == ol.PROFILE_NAME_PREFIX + str(instance["name"]).strip())

    def unregister_instance(self, id: str) -> dict[str, Any]:
        with self._profiles_lock:
            return self._unregister_instance_locked(id)

    def _unregister_instance_locked(self, id: str) -> dict[str, Any]:
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
        tail = ol.tail_log(d, lambda line: self._on_game_line(id, line), from_start=bool(from_start))
        with self._tails_lock:
            self._tails[id] = tail
        return {"ok": True, "path": str(tail.path),
                "message": "공식 런처로 실행한 게임의 로그를 따라 읽습니다."}

    def _on_game_line(self, id: str, line: str) -> None:
        """게임 로그를 전달하고, 공식 런처로 켠 게임의 실행 상태를 로그로 알아낸다(우리 프로세스가 아니므로)."""
        _log(id, line)
        state = None
        if "Setting user:" in line or "Loading Minecraft" in line:
            state = True
        elif "Stopping!" in line or "Game crashed!" in line:
            state = False
        if state is not None and self._game_running.get(id) != state:
            self._game_running[id] = state
            notify("state", {"id": id, "source": "game", "running": state, "official": True})
            if not state and self.on_game_stopped:
                self.on_game_stopped(id)

    def running_games(self) -> list[str]:
        return sorted(k for k, v in self._game_running.items() if v)

    def tail_stop(self, id: str) -> dict[str, Any]:
        with self._tails_lock:
            tail = self._tails.pop(id, None)
        if tail is not None:
            tail.stop()
        if self._game_running.pop(id, None):
            notify("state", {"id": id, "source": "game", "running": False, "official": True})
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
