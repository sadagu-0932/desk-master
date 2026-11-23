"""다른 런처 인스턴스 불러오기 — "복사"(기본) 또는 "연결".

복사: data/instances/inst_<id>/ 로 정해진 항목만 복사한다. 원본은 절대 수정하지 않는다(읽기만).
연결: 원본 폴더를 그대로 게임 폴더로 쓴다(공식 런처 항목의 gameDirectory = 원본). 두 런처를 동시에 쓰면
      월드·설정이 깨질 수 있어 경고하고, 실행 전에 다른 런처·게임이 그 폴더를 쓰는지 확인한다.
계정·로그인·토큰 파일은 읽지도 복사하지도 않는다(launchers.is_account_file).
불러온 뒤 버전·로더는 minecraft-launcher-lib 로 설치(없을 때만), 메모리·자바 인자도 옮긴다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from instances import InstanceStore
from paths import safe_join
from rpc import RpcError, notify

from . import launchers

COPY_ITEMS = ["mods", "config", "saves", "resourcepacks", "shaderpacks", "datapacks", "kubejs", "defaultconfigs",
              "schematics", "options.txt", "optionsof.txt", "optionsshaders.txt", "servers.dat"]
LAUNCHER_PROCS = {"prismlauncher.exe": "Prism Launcher", "multimc.exe": "MultiMC", "curseforge.exe": "CurseForge",
                  "modrinth app.exe": "Modrinth App", "theseus.exe": "Modrinth App",
                  "minecraftlauncher.exe": "공식 런처", "minecraft.exe": "공식 런처"}


def _jvm_args(memory_mb: int | None, java_args: str | None) -> str | None:
    parts = [a for a in (java_args or "").split() if not re.match(r"-Xm[xs]\d", a)]
    if memory_mb:
        parts.insert(0, f"-Xmx{int(memory_mb)}M")
    return " ".join(parts) or None


def _copytree(src: Path, dst: Path, on_file: Callable[[int], None]) -> int:
    n = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            s = Path(root) / f
            if launchers.is_account_file(s) or s.is_symlink():
                continue
            shutil.copy2(s, dst / rel / f)
            n += 1
            on_file(s.stat().st_size)
    return n


class LocalImporter:
    def __init__(self, store: InstanceStore, install: Callable[[str], Any] | None = None,
                 roots: dict[str, list[Path]] | None = None):
        self.store = store
        self.install = install
        self.roots = roots
        self._cache: dict[str, dict[str, Any]] = {}

    # ---------- 감지 ----------
    def detect(self) -> list[dict[str, Any]]:
        entries = launchers.detect_all(self.roots)
        return self._remember(entries)

    def inspect_folder(self, path: str) -> list[dict[str, Any]]:
        return self._remember(launchers.inspect_folder(Path(path)))

    def _remember(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        imported = {m.get("importedFrom"): m["id"] for m in self.store.list() if m.get("importedFrom")}
        for e in entries:
            e["importedAs"] = imported.get(e["key"])
            self._cache[e["key"]] = e
        return entries

    def _entry(self, key: str) -> dict[str, Any]:
        e = self._cache.get(key)
        if not e:
            raise RpcError("목록이 바뀌었습니다. 다시 찾아 주세요.")
        return e

    # ---------- 미리보기 ----------
    def preview(self, keys: list[str], mode: str = "copy") -> dict[str, Any]:
        items = []
        total = 0
        for key in keys:
            e = self._entry(key)
            sizes = launchers.entry_size(e, COPY_ITEMS) if mode == "copy" else {}
            size = sum(sizes.values())
            total += size
            items.append({"key": key, "name": e["name"], "launcherName": e["launcherName"], "version": e["version"],
                          "loader": e["loader"], "items": [{"name": k, "bytes": v} for k, v in sizes.items()],
                          "bytes": size, "gameDir": e.get("gameDir"), "supported": e.get("supported"),
                          "note": e.get("note")})
        warnings = ["계정·로그인 파일은 옮기지 않습니다. 로그인은 공식 런처에서 합니다."]
        if mode == "link":
            warnings.insert(0, "연결은 원본 폴더를 그대로 씁니다. 같은 인스턴스를 두 런처에서 동시에 켜면 월드·설정이 망가질 수 있습니다. "
                               "실행 전에 다른 런처가 쓰고 있는지 확인합니다.")
        return {"mode": mode, "items": items, "bytes": total, "warnings": warnings}

    # ---------- 불러오기 ----------
    def import_many(self, entries: list[dict[str, Any]], mode: str = "copy") -> dict[str, Any]:
        """entries: [{key, name?, version?}] (version 은 알 수 없을 때 사용자가 고른 값)."""
        if mode not in ("copy", "link"):
            raise RpcError("불러오기 방식은 copy 또는 link 입니다.")
        done, failed = [], []
        for req in entries:
            e = dict(self._entry(req["key"]))
            if req.get("version"):
                e["version"] = req["version"]
                e["supported"] = bool(e.get("gameDir"))
            try:
                done.append(self._import_one(e, mode, req.get("name")))
            except Exception as ex:  # noqa: BLE001 - 하나가 실패해도 나머지는 계속
                failed.append({"key": e["key"], "name": e["name"], "error": str(ex)})
        return {"imported": done, "failed": failed}

    def _import_one(self, e: dict[str, Any], mode: str, name: str | None) -> dict[str, Any]:
        if not e.get("version"):
            raise RpcError(f"{e['name']}: 게임 버전을 알 수 없습니다. 버전을 골라 주세요.")
        game = Path(e["gameDir"]) if e.get("gameDir") else None
        if not game or not game.is_dir():
            raise RpcError(f"{e['name']}: 게임 폴더를 찾을 수 없습니다.")
        inst = self.store.create(name or e["name"], e["version"], e["loader"], e.get("loaderVersion"), cc_enabled=False)
        iid = inst["id"]
        try:
            meta = self.store.get(iid)
            meta["importedFrom"] = e["key"]
            meta["importedLauncher"] = e["launcher"]
            meta["jvmArgs"] = _jvm_args(e.get("memoryMb"), e.get("javaArgs"))
            if e["launcher"] == "official" and e.get("versionId") and e["loader"] != "vanilla":
                meta["versionId"] = e["versionId"]      # 공식 .minecraft 에 이미 설치된 로더 버전
            if mode == "link":
                meta["linkedDir"] = str(game.resolve())
                self.store.save(meta)
            else:
                self.store.save(meta)
                self._copy(iid, game, e)
            warning = None
            if self.install:
                notify("progress", {"id": iid, "stage": "import", "text": "게임·로더 설치 중(없을 때만)"})
                try:
                    self.install(iid)
                except Exception as ex:  # noqa: BLE001 - 받기 실패(네트워크 등)여도 불러온 파일은 남기고 실행할 때 다시 설치
                    warning = f"버전·로더 설치는 실패해서 실행할 때 다시 시도합니다: {ex}"
            notify("progress", {"id": iid, "stage": "import", "text": "불러오기 완료", "done": True})
            out = self.store.get(iid)
            if warning:
                out["warning"] = warning
            return out
        except Exception:
            notify("progress", {"id": iid, "stage": "import", "done": True})
            self._discard(iid)
            raise

    def _copy(self, iid: str, game: Path, e: dict[str, Any]) -> None:
        base = self.store.dir_of(iid)
        total = sum(launchers.entry_size(e, COPY_ITEMS).values()) or 1
        copied = 0
        last = 0.0

        def tick(n: int) -> None:
            nonlocal copied, last
            copied += n
            if time.time() - last > 0.3:
                last = time.time()
                notify("progress", {"id": iid, "stage": "import", "text": f"{e['name']} 복사 중",
                                    "value": min(copied, total), "max": total})

        for item in COPY_ITEMS:
            src = game / item
            if launchers.is_account_file(src) or src.is_symlink():
                continue
            if src.is_dir():
                _copytree(src, safe_join(base, item), tick)
            elif src.is_file():
                shutil.copy2(src, safe_join(base, item))
                tick(src.stat().st_size)

    def _discard(self, iid: str) -> None:
        d = self.store.dir_of(iid)
        try:
            (d / "instance.json").replace(d / "instance.import-failed.json")
        except OSError:
            pass
        try:
            from paths import trash
            trash(d, self.store.root)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 연결한 인스턴스: 다른 런처가 쓰는 중인지 ----------
    def in_use(self, iid: str) -> dict[str, Any]:
        meta = self.store.get(iid)
        if not meta.get("linkedDir"):
            return {"linked": False, "busy": False, "reasons": []}
        game = Path(meta["linkedDir"])
        reasons: list[str] = []
        warnings: list[str] = []
        for lock in game.glob("saves/*/session.lock"):
            if _locked(lock):
                reasons.append(f"월드 '{lock.parent.name}' 가 열려 있습니다(session.lock).")
        procs = _processes()
        game_s = str(game).lower().rstrip("\\/")
        for name, cmd in procs:
            if name in ("java.exe", "javaw.exe", "java") and game_s and game_s in cmd.lower():
                reasons.append("이 폴더로 켜진 마인크래프트가 있습니다.")
                break
        owners = sorted({LAUNCHER_PROCS[n] for n, _ in procs if n in LAUNCHER_PROCS and LAUNCHER_PROCS[n] != "공식 런처"})
        if owners:
            warnings.append(f"{', '.join(owners)} 이(가) 켜져 있습니다. 같은 인스턴스를 동시에 켜지 마세요.")
        log = game / "logs" / "latest.log"
        try:
            if log.is_file() and time.time() - log.stat().st_mtime < 20:
                tail = log.read_bytes()[-4000:].decode("utf-8", "replace")
                if "Stopping!" not in tail and "Game crashed" not in tail:
                    reasons.append("방금까지 이 폴더의 게임 로그가 쓰이고 있습니다.")
        except OSError:
            pass
        return {"linked": True, "busy": bool(reasons), "reasons": reasons, "warnings": warnings, "dir": str(game)}


def _locked(p: Path) -> bool:
    """마인크래프트가 월드를 열면 session.lock 을 잠근다. 열어 보기만 하고 아무것도 쓰지 않는다."""
    if sys.platform == "win32":
        try:
            fd = os.open(str(p), os.O_RDWR)
        except PermissionError:
            return True
        except OSError:
            return False
        try:
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return False
        except OSError:
            return True
        finally:
            os.close(fd)
    try:
        import fcntl
        with open(p, "rb") as f:
            try:
                fcntl.lockf(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.lockf(f, fcntl.LOCK_UN)
                return False
            except OSError:
                return True
    except OSError:
        return False


def _processes() -> list[tuple[str, str]]:
    """(소문자 이름, 명령줄). 시험용: INTEGRATED_STUDIO_FAKE_PROCS='name|cmd;name|cmd'."""
    fake = os.environ.get("INTEGRATED_STUDIO_FAKE_PROCS")
    if fake is not None:
        return [tuple(x.split("|", 1)) if "|" in x else (x, "") for x in fake.split(";") if x]  # type: ignore[misc]
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | ForEach-Object { $_.Name + '|' + $_.CommandLine }"],
            capture_output=True, text=True, timeout=15, creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        name, _, cmd = line.partition("|")
        if name:
            rows.append((name.strip().lower(), cmd))
    return rows
