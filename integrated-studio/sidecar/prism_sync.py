"""Prism 과 인스턴스 목록 자동 연동(사용자 요청 2026-11-27 "프리즘의 경로를 추적해서 자동 연동").

몇 초마다 Prism 인스턴스 폴더를 확인해(폴더 이름·instance.cfg·mmc-pack.json 수정 시각이 바뀐 때만 읽음)
- Prism 에 새로 생긴 인스턴스 → 앱 목록에 연결(폴더는 그대로, 실행은 Prism)
- Prism 에서 지운 인스턴스 → 앱 목록에서 뺌
- Prism 에서 이름·게임 버전·로더를 바꾸면 → 앱 정보도 맞춤
"""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import prism
from importers import launchers
from importers.local import LocalImporter
from instances import InstanceStore

INTERVAL = 5.0


class PrismSync:
    def __init__(self, store: InstanceStore, local: LocalImporter, find: Callable[[], dict[str, Any]] = prism.find):
        self.store = store
        self.local = local
        self.find = find
        self._sig: tuple | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @staticmethod
    def _signature(inst_dir: Path) -> tuple:
        out = []
        try:
            names = sorted(os.listdir(inst_dir))
        except OSError:
            return ()
        try:
            out.append(("groups", (inst_dir / prism.GROUPS_FILE).stat().st_mtime_ns))   # Prism 에서 그룹을 바꾸면
        except OSError:
            out.append(("groups", None))
        for n in names:
            row: list[Any] = [n]
            for f in ("instance.cfg", "mmc-pack.json"):
                try:
                    row.append((inst_dir / n / f).stat().st_mtime_ns)
                except OSError:
                    row.append(None)
            out.append(tuple(row))
        return tuple(out)

    def sync(self, force: bool = False) -> dict[str, Any]:
        """{added, removed, updated}. Prism 이 없으면 아무것도 안 함."""
        with self._lock:
            info = self.find()
            if not info.get("root") or not info.get("instanceDir"):
                return {"added": 0, "removed": 0, "updated": 0, "prism": False}
            root, inst_dir = Path(info["root"]), Path(info["instanceDir"])
            sig = (str(inst_dir), self._signature(inst_dir))
            if not force and sig == self._sig:
                return {"added": 0, "removed": 0, "updated": 0, "prism": True}
            entries = launchers.detect_prism([root]) if root.is_dir() else []
            for e in entries:
                e["key"] = f"{e['launcher']}:{e['source']}"     # 불러오기 목록과 같은 키
            by_source = {str(Path(e["source"]).resolve()): e for e in entries}
            added = removed = updated = 0
            mine = {m.get("sourceDir"): m for m in self.store.list() if m.get("launchKind") == "prism"}
            # 새로 생긴 것 → 연결(실행 파일은 실행할 때 만든다)
            for src, e in by_source.items():
                if src in mine or not e.get("version") or not e.get("gameDir"):
                    continue
                self.local._remember([e])  # noqa: SLF001 - 같은 패키지 흐름(불러오기 목록에 등록)
                try:
                    self.local._import_one(e, "link", None, launch_file=False)  # noqa: SLF001
                    added += 1
                except Exception:  # noqa: BLE001 - 하나가 이상해도 나머지는 계속
                    continue
            # 이 Prism 인스턴스 폴더 안이었는데 지금은 없는 것 → 목록에서 뺀다(앱 쪽 정보만)
            for src, m in mine.items():
                if not src or src in by_source:
                    continue
                try:
                    inside = Path(src).resolve().parent == inst_dir.resolve()
                except OSError:
                    inside = False
                if inside and inst_dir.is_dir() and not Path(src).exists():
                    try:
                        self.store.forget(m["id"])
                        removed += 1
                    except Exception:  # noqa: BLE001
                        pass
            # Prism 에서 바꾼 이름·버전·로더·그룹 맞추기(새로 연결한 것 포함)
            groups = prism.read_groups(inst_dir)
            mine = {m.get("sourceDir"): m for m in self.store.list() if m.get("launchKind") == "prism"}
            for src, m in mine.items():
                e = by_source.get(src)
                if not e:
                    continue
                want = {"name": e["name"], "version": e.get("version") or m["version"], "loader": e["loader"],
                        "loaderVersion": e.get("loaderVersion")}
                if Path(src).parent == inst_dir.resolve() or Path(src).parent == inst_dir:
                    want["group"] = groups.get(Path(src).name)
                if any(m.get(k) != v for k, v in want.items()):
                    meta = self.store.get(m["id"])
                    meta.update(want)
                    self.store.save(meta)
                    updated += 1
            self._sig = sig
            return {"added": added, "removed": removed, "updated": updated, "prism": True}

    def start(self, interval: float = INTERVAL) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.sync()
                except Exception:  # noqa: BLE001 - 연동 실패로 사이드카가 죽지 않게
                    pass
                self._stop.wait(interval)
        threading.Thread(target=loop, name="prism-sync", daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------- 예전 인스턴스 → Prism 으로 옮기기

# 앱이 만든 예전 인스턴스 폴더에서 옮기지 않는 것: 앱 정보 파일, 새 인스턴스에 새로 만드는 것, 앱 쪽(서버 설정)으로 따로 옮기는 것
MIGRATE_SKIP = {"instance.json", "instance.deleted.json", "instance.import-failed.json", "CLAUDE.md", ".claude",
                ".gitignore", "servers", "session.lock"}
CARRY_KEYS = ("ccEnabled", "workMode", "group", "icon", "e4mcDisabledOnce", "e4mcAutoDisabled")


def _rmtree_force(path: Path) -> None:
    """방금 만든 폴더를 지운다. Windows 에서 git 객체 파일은 읽기 전용이라 그냥 지우면 '액세스 거부'(WinError 5) → 쓰기 가능으로 바꾸고 다시."""
    import shutil
    import stat

    def again(func: Callable[..., Any], p: str, _exc: Any) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)


def migrate_candidates(store: InstanceStore) -> list[dict[str, Any]]:
    """Prism 으로 옮겨야 실행할 수 있는 인스턴스: 앱 폴더 안의 것, 공식 런처·CurseForge·Modrinth 등에서 연결한 것."""
    out = []
    for m in store.list():
        if m.get("launchKind") in ("prism", "multimc"):
            continue
        out.append({"id": m["id"], "name": m["name"], "version": m["version"], "loader": m["loader"],
                    "linked": bool(m.get("linkedDir")), "path": m["path"]})
    return out


def migrate(store: InstanceStore, local: LocalImporter, ids: list[str],
            progress: Callable[[str, str], None] = lambda _id, _t: None) -> dict[str, Any]:
    """각각 새 Prism 인스턴스를 만들고 게임 내용을 복사한 뒤 예전 것은 목록에서 뺀다.
    - 앱 폴더 안의 인스턴스: 폴더 전체(월드·모드·설정·git 기록·데이터팩)를 옮기고 예전 폴더는 휴지통으로
    - 다른 런처에서 연결한 것: 게임 항목만 복사, 원래 폴더는 그대로(우리 실행 파일만 지움)
    """
    import shutil
    from importers.launchers import is_account_file
    from importers.local import COPY_ITEMS
    from paths import safe_join

    done, failed = [], []
    for old_id in ids:
        try:
            old = store.get(old_id)
            if old.get("launchKind") in ("prism", "multimc"):
                continue
            progress(old_id, f"'{old['name']}' Prism 으로 옮기는 중")
            new = store.create(old["name"], old["version"], old["loader"], old.get("loaderVersion"),
                               cc_enabled=bool(old.get("ccEnabled")))
            src = Path(old["path"])
            dst = store.game_dir(new["id"])

            def skip(_d: str, names: list[str]) -> set[str]:
                return {n for n in names if n == "session.lock" or is_account_file(n)}

            items = [p for p in src.iterdir()] if not old.get("linkedDir") else [src / n for n in COPY_ITEMS if (src / n).exists()]
            for item in items:
                if item.name in MIGRATE_SKIP or item.is_symlink() or is_account_file(item.name):
                    continue
                target = safe_join(dst, item.name)
                if item.name == ".git" and target.is_dir():
                    _rmtree_force(target)          # 방금 만든 빈 저장소 대신 예전 기록을 쓴다
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True, ignore=skip)
                else:
                    shutil.copy2(item, target)
            if not old.get("linkedDir") and (src / "servers").is_dir():
                shutil.copytree(src / "servers", store.dir_of(new["id"]) / "servers", dirs_exist_ok=True)  # 전용 서버 설정·월드
            meta = store.get(new["id"])
            for k in CARRY_KEYS:
                if old.get(k) is not None:
                    meta[k] = old[k]
            meta["migratedFrom"] = old_id
            store.save(meta)
            if old.get("jvmArgs"):
                mx = re.search(r"-Xmx(\d+)M", old["jvmArgs"])
                extra = " ".join(a for a in old["jvmArgs"].split() if not a.startswith("-Xm"))
                store.set_memory(new["id"], int(mx.group(1)) if mx else None, extra)
            local.remove_launch_file(old_id)
            store.forget(old_id)       # 앱 폴더 안의 것이면 예전 폴더째 휴지통(복원 가능), 연결이면 앱 정보만
            done.append({"from": old_id, "to": new["id"], "name": old["name"]})
        except Exception as e:  # noqa: BLE001 - 하나가 실패해도 나머지는 계속(실패한 것은 그대로 남음)
            failed.append({"id": old_id, "error": str(e)})
        finally:
            progress(old_id, "")
    return {"migrated": done, "failed": failed}
