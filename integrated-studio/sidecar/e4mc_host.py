"""e4mc: 싱글플레이 LAN 공개를 인터넷 주소로(방식 B).

modrinth.py 로 버전·로더에 정확히 맞는 파일만 받는다(26.1+ Fabric 은 modern 파일). 끌 때는 .disabled 로 이름만 바꾼다(삭제 금지).
충돌 후보 모드를 경고하고, e4mc 탓으로 보이는 크래시면 다음 실행부터 자동으로 끈다.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

import modrinth
from instances import InstanceStore
from rpc import RpcError
from server_mods import E4MC_IDS, E4MC_PROJECT, mods_config, read_mod_info, scan_mods

E4MC_CRASH_RE = re.compile(r"(link\.e4mc|e4mc_minecraft|\be4mc\b|Quiclime|io\.netty\.incubator\.codec\.quic)", re.I)
NET_ERROR_RE = re.compile(r"(Exception|Error|crash)", re.I)


class E4mcHost:
    """인스턴스 mods/ 의 e4mc 관리. install_fabric(version) → Fabric 버전 id (바닐라 인스턴스의 호스트용 프로필)."""

    def __init__(self, store: InstanceStore, install_fabric: Callable[[str, str], str] | None = None,
                 register_host: Callable[[str, str], dict] | None = None):
        self.store = store
        self.install_fabric = install_fabric
        self.register_host = register_host

    def _mods(self, id: str) -> Path:
        return self.store.game_dir(id) / "mods"

    def _find(self, id: str) -> list[Path]:
        """e4mc 파일(켜진 것·꺼진 것). jar 안 모드 id 로 찾는다(네트워크 없이)."""
        mods = self._mods(id)
        out = []
        if mods.is_dir():
            for p in mods.iterdir():
                if p.is_file() and (p.suffix == ".jar" or p.name.endswith(".jar.disabled")):
                    info = read_mod_info(p)
                    if info and info["id"] in E4MC_IDS:
                        out.append(p)
        return out

    def conflicts(self, id: str) -> list[dict[str, Any]]:
        cfg = {c["id"]: c for c in mods_config().get("networkConflicts", [])}
        found = []
        for m in scan_mods(self._mods(id)):
            if m["id"] in cfg:
                found.append({**cfg[m["id"]], "file": m["file"]})
        return found

    def status(self, id: str) -> dict[str, Any]:
        meta = self.store.get(id)
        files = self._find(id)
        enabled = [p for p in files if p.suffix == ".jar"]
        loader = meta.get("loader", "vanilla")
        return {
            "loader": loader, "version": meta["version"],
            "installed": bool(files), "enabled": bool(enabled),
            "files": [p.name for p in files],
            "needsHostProfile": loader == "vanilla",
            "hostProfile": meta.get("e4mcHostProfile"),
            "autoDisabled": meta.get("e4mcAutoDisabled"),
            "conflicts": self.conflicts(id),
            "supportedLoader": loader in ("vanilla", "fabric", "quilt", "neoforge", "forge"),
        }

    def install(self, id: str, conflict_choice: str = "ask") -> dict[str, Any]:
        """e4mc 를 넣는다. conflict_choice: ask | disable_once | proceed.

        반환 {ok, ...} — ok=False 면 reason(한국어)과 fallback=True(UPnP 로 넘어가라).
        """
        meta = self.store.get(id)
        conflicts = self.conflicts(id)
        if conflicts and conflict_choice == "ask":
            return {"ok": False, "needsChoice": True, "conflicts": conflicts}
        loader = meta.get("loader", "vanilla")
        mod_loader = "fabric" if loader == "vanilla" else loader
        mods = self._mods(id)
        try:
            res = modrinth.install(E4MC_PROJECT, meta["version"], mod_loader, mods)
        except modrinth.NoMatch as e:
            return {"ok": False, "fallback": True,
                    "reason": f"e4mc 에 {meta['version']} · {modrinth.LOADER_NAMES.get(mod_loader, mod_loader)} 용 파일이 없어 설치하지 않았습니다. "
                              f"UPnP 로 넘어갑니다. ({e})"}
        except modrinth.Ambiguous as e:
            return {"ok": False, "ambiguous": e.choices, "reason": str(e)}
        except RpcError as e:
            return {"ok": False, "fallback": True, "reason": f"e4mc 를 받지 못했습니다: {e}. UPnP 로 넘어갑니다."}
        # 예전에 꺼 둔 e4mc 가 같은 이름으로 남아 있으면 그대로 두고, 이번에 넣은 것만 켠다
        for p in self._find(id):
            if p.name.endswith(".disabled") and p.name[: -len(".disabled")] in [i["filename"] for i in res.installed + res.kept]:
                target = p.with_name(p.name[: -len(".disabled")])
                if not target.exists():
                    p.rename(target)
        disabled_now = []
        if conflicts and conflict_choice == "disable_once":
            for c in conflicts:
                p = mods / c["file"]
                if p.is_file():
                    p.rename(p.with_name(p.name + ".disabled"))
                    disabled_now.append(c["file"])
        meta = self.store.get(id)
        if disabled_now:
            meta["e4mcDisabledOnce"] = sorted(set(meta.get("e4mcDisabledOnce") or []) | set(disabled_now))
        meta.pop("e4mcAutoDisabled", None)
        meta["e4mcSession"] = time.time()
        self.store.save(meta)
        out: dict[str, Any] = {"ok": True, "installed": [i["filename"] for i in res.installed],
                               "kept": [k["filename"] for k in res.kept], "optional": res.optional,
                               "disabledOnce": disabled_now}
        if loader == "vanilla":
            out["hostProfile"] = self._host_profile(id)
        return out

    def _host_profile(self, id: str) -> dict[str, Any]:
        """바닐라 인스턴스: 같은 버전 Fabric 으로 '호스트용' 공식 런처 항목을 만든다(원래 인스턴스는 그대로)."""
        meta = self.store.get(id)
        if not self.install_fabric:
            return {"ok": False, "reason": "Fabric 설치기를 쓸 수 없습니다."}
        version_id = self.install_fabric(id, meta["version"])
        meta = self.store.get(id)
        meta["e4mcHostProfile"] = version_id
        self.store.save(meta)
        reg = self.register_host(id, version_id) if self.register_host else {"ok": True}
        return {"ok": bool(reg.get("ok", True)), "versionId": version_id, "message": reg.get("message")}

    def disable(self, id: str, reason: str | None = None) -> dict[str, Any]:
        """끄기: 다음 실행부터 .disabled (삭제 금지). '이번만 끈' 충돌 모드는 되살린다."""
        changed = []
        for p in self._find(id):
            if p.suffix == ".jar":
                p.rename(p.with_name(p.name + ".disabled"))
                changed.append(p.name)
        self.restore_once(id)
        if reason:
            meta = self.store.get(id)
            meta["e4mcAutoDisabled"] = reason
            self.store.save(meta)
        return {"ok": True, "disabled": changed}

    def restore_once(self, id: str) -> list[str]:
        """'이번만 끄기' 로 꺼 둔 충돌 모드를 되살린다(게임이 꺼지거나 LAN 이 닫힌 뒤)."""
        meta = self.store.get(id)
        names = meta.pop("e4mcDisabledOnce", None) or []
        back = []
        for n in names:
            p = self._mods(id) / (n + ".disabled")
            if p.is_file() and not (self._mods(id) / n).exists():
                p.rename(self._mods(id) / n)
                back.append(n)
        self.store.save(meta)
        return back

    def check_crash(self, id: str) -> dict[str, Any]:
        """e4mc 를 켠 실행 뒤: crash-reports 와 latest.log 에서 e4mc 탓으로 보이는 오류를 찾는다.
        찾으면 다음 실행부터 e4mc 를 끄고(.disabled) 다음 방식으로 넘어가라고 알린다."""
        meta = self.store.get(id)
        since = float(meta.get("e4mcSession") or 0) - 5   # 파일 시각 단위·시계 차이(Windows) 여유
        game = self.store.game_dir(id)
        evidence = None
        crashes = sorted((game / "crash-reports").glob("crash-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if (game / "crash-reports").is_dir() else []
        for c in crashes[:3]:
            if c.stat().st_mtime < since:
                break
            text = c.read_text("utf-8", errors="replace")
            if E4MC_CRASH_RE.search(text):
                evidence = f"크래시 보고서 {c.name}"
                break
        log = game / "logs" / "latest.log"
        if not evidence and log.is_file() and log.stat().st_mtime >= since:
            for ln in log.read_text("utf-8", errors="replace").splitlines():
                if E4MC_CRASH_RE.search(ln) and NET_ERROR_RE.search(ln) and ("ERROR" in ln or "WARN" in ln or "Exception" in ln):
                    evidence = f"latest.log: {ln.strip()[:160]}"
                    break
        if not evidence:
            return {"e4mcProblem": False}
        reason = f"e4mc 때문에 문제가 난 것으로 보여 다음 실행부터 e4mc 를 껐습니다({evidence}). 다음 방식(UPnP·playit)으로 엽니다."
        self.disable(id, reason)
        return {"e4mcProblem": True, "reason": reason}
