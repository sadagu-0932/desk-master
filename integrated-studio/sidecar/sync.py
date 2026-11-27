"""설정 동기화 (사용자 결정 2026-11-22: "항상 모든 설정이 동기화", 2026-11-27: 실행은 Prism — 공식 런처 부분은 없앰).

맞추는 것(통합 작업실이 만든 인스턴스끼리. Prism 에 원래 있던·연결한 인스턴스는 건드리지 않는다)
- 게임 설정 options.txt: 같은 값을 쓴다. 리소스팩 목록(resourcePacks, incompatibleResourcePacks)은 인스턴스마다 달라야 하므로 맞추지 않는다.
- 서버 목록 servers.dat: 파일째로 맞춘다.

방식: 가장 최근에 바뀐(수정 시각) 파일을 기준으로 나머지에 쓰고, 쓴 파일의 수정 시각을 기준과 같게 맞춘다
(그래야 다음 확인 때 다시 "최신"이 되지 않는다). 심볼릭 링크는 쓰지 않는다(Windows 권한 문제).
- 실행 중인 인스턴스에는 쓰지 않는다(게임이 닫힐 때 덮어쓰므로). 닫힌 뒤 다시 맞춘다.
- 로그인·토큰 파일은 다루지 않는다.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable

from importers.launchers import is_account_file
from instances import InstanceStore
from rpc import notify

OPTIONS = "options.txt"
SERVERS = "servers.dat"
PER_INSTANCE_KEYS = {"resourcePacks", "incompatibleResourcePacks"}
INTERVAL = 30.0


def _parse(text: str) -> tuple[list[str], dict[str, str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines, {ln.split(":", 1)[0]: ln for ln in lines if ":" in ln}


def merge_options(src: str, dst: str | None) -> str:
    """src 값을 쓰되, 인스턴스별 키는 dst 것을 유지한다(dst 에 없으면 그 키는 넣지 않는다)."""
    src_lines, _ = _parse(src)
    _, dst_map = _parse(dst or "")
    out: list[str] = []
    for ln in src_lines:
        key = ln.split(":", 1)[0]
        if key in PER_INSTANCE_KEYS:
            if key in dst_map:
                out.append(dst_map[key])
            continue
        out.append(ln)
    have = {ln.split(":", 1)[0] for ln in out}
    out += [ln for k, ln in dst_map.items() if k in PER_INSTANCE_KEYS and k not in have]
    eol = "\r\n" if "\r\n" in src else "\n"  # Windows 에서 게임이 쓰는 CRLF 를 그대로
    return eol.join(out) + eol


def _same_text(a: str, b: str) -> bool:
    """줄바꿈(CRLF/LF)·빈 줄 차이는 같은 내용으로 본다."""
    return _parse(a)[0] == _parse(b)[0]


class SettingsSync:
    def __init__(self, store: InstanceStore, data_dir: Path, running: Callable[[], list[str]] | None = None,
                 log: Callable[[str], None] | None = None):
        """running: 지금 켜진 게임의 인스턴스 id 목록(그 인스턴스에는 쓰지 않는다)"""
        self.store = store
        self.data_dir = Path(data_dir)
        self.running = running or (lambda: [])
        self.log = log or (lambda line: notify("log", {"id": "", "line": line, "level": "info", "source": "studio"}))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 지난 동기화 직후의 파일 상태(경로·수정 시각·크기·쓰기 가능). 30초마다 돌 때 그대로면 파일을 읽지 않는다
        self._last: dict[str, tuple] = {}

    def _targets(self) -> list[dict[str, Any]]:
        """[{label, dir, writable}] — 통합 작업실이 만든 인스턴스만(Prism 인스턴스면 그 게임 폴더). 실행 중이면 읽기만."""
        running = set(self.running())
        out: list[dict[str, Any]] = []
        for inst in self.store.list():
            if inst.get("linkedDir") and not inst.get("managed"):
                continue   # 다른 곳(Prism 에 원래 있던 것 등)에서 연결한 인스턴스는 건드리지 않는다
            try:
                d = self.store.game_dir(inst["id"])
            except Exception:  # noqa: BLE001
                continue
            out.append({"label": inst.get("name", inst["id"]), "dir": d, "writable": inst["id"] not in running})
        return out

    @staticmethod
    def _guard(p: Path) -> Path:
        if is_account_file(p.name):
            raise PermissionError(f"로그인·토큰 파일은 다루지 않습니다: {p.name}")
        return p

    # ---------- 파일 맞추기 ----------
    def _sync_file(self, name: str, targets: list[dict[str, Any]]) -> list[str]:
        """가장 최근 파일을 기준으로 나머지를 맞춘다. 바뀐 곳 이름 목록을 돌려준다."""
        found = []
        for t in targets:
            p = self._guard(t["dir"] / name)
            try:
                st = p.stat()
            except OSError:
                continue
            found.append((st.st_mtime, t, p))
        if not found:
            return []
        found.sort(key=lambda x: x[0], reverse=True)
        mtime, src_t, src = found[0]
        try:
            src_bytes = src.read_bytes()
        except OSError:
            return []
        changed: list[str] = []
        for t in targets:
            if t is src_t or not t["writable"]:
                continue
            dst = self._guard(t["dir"] / name)
            old = dst.read_bytes() if dst.is_file() else None
            if name == OPTIONS:
                new = merge_options(src_bytes.decode("utf-8", "replace"),
                                    old.decode("utf-8", "replace") if old is not None else None).encode("utf-8")
            else:
                new = src_bytes
            if old == new:
                continue
            if name == OPTIONS and old is not None and _same_text(old.decode("utf-8", "replace"), new.decode("utf-8", "replace")):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".integrated-studio.tmp")
            tmp.write_bytes(new)
            os.replace(tmp, dst)
            os.utime(dst, (mtime, mtime))
            changed.append(t["label"])
        if changed:
            what = "게임 설정" if name == OPTIONS else "서버 목록"
            self.log(f"{what}을(를) '{src_t['label']}' 기준으로 맞췄습니다: {', '.join(changed)}")
        return changed

    @staticmethod
    def _file_state(name: str, targets: list[dict[str, Any]]) -> tuple:
        out = []
        for t in targets:
            p = t["dir"] / name
            try:
                st = p.stat()
                out.append((str(p), st.st_mtime_ns, st.st_size, t["writable"]))
            except OSError:
                out.append((str(p), None, None, t["writable"]))
        return tuple(out)

    def sync_now(self, force: bool = True) -> dict[str, Any]:
        """force=False(30초마다): 지난번과 파일 상태가 같으면 건너뛴다. 수동·게임 종료 뒤는 항상."""
        with self._lock:
            targets = self._targets()
            result: dict[str, Any] = {}
            for key, name in (("options", OPTIONS), ("servers", SERVERS)):
                if not force and self._last.get(name) == self._file_state(name, targets):
                    result[key] = []
                    continue
                result[key] = self._sync_file(name, targets)
                self._last[name] = self._file_state(name, targets)   # 맞춘 뒤의 상태를 기억
        return result

    # ---------- 항상 ----------
    def start(self, interval: float = INTERVAL) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.sync_now(force=False)
                except Exception as e:  # noqa: BLE001 - 동기화 실패로 사이드카가 죽지 않게
                    self.log(f"설정 동기화 중 오류: {e}")
                self._stop.wait(interval)

        self._thread = threading.Thread(target=loop, name="settings-sync", daemon=True)
        self._thread.start()

    def later(self, delay: float = 3.0) -> None:
        """게임이 닫힌 직후처럼 파일 저장이 끝나길 잠깐 기다렸다가 맞춘다."""
        threading.Timer(delay, lambda: self._safe_sync()).start()

    def _safe_sync(self) -> None:
        try:
            self.sync_now()
        except Exception as e:  # noqa: BLE001
            self.log(f"설정 동기화 중 오류: {e}")

    def shutdown(self) -> None:
        self._stop.set()
