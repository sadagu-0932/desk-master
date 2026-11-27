"""서버 열기용 모드 분석: 참가자도 같은 모드가 필요한지 jar 안 정보로 판단한다.

- Fabric: fabric.mod.json environment / Quilt: quilt.mod.json / NeoForge·Forge: mods.toml(displayTest IGNORE_*·clientSideOnly)
- 호스트에만 필요한 모드·라이브러리·네트워크 충돌 후보 목록은 server_host_mods.json
전용 서버(server_runner)와 e4mc(e4mc_host)가 함께 쓴다.
"""
from __future__ import annotations

import json
import tomllib
import zipfile
from pathlib import Path
from typing import Any

MODS_CONFIG = Path(__file__).resolve().parent / "server_host_mods.json"
E4MC_PROJECT = "e4mc"                      # Modrinth 프로젝트 이름
E4MC_IDS = {"e4mc", "e4mc_minecraft"}      # jar 안 모드 id(옛 이름 포함)


def mods_config() -> dict[str, Any]:
    try:
        return json.loads(MODS_CONFIG.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"networkConflicts": [], "hostOnly": [], "libraries": []}


def read_mod_info(jar: Path) -> dict[str, Any] | None:
    """jar 안 모드 정보: {id, name, version, loader, environment, clientRequired}.

    - Fabric: fabric.mod.json environment "*"|"client"|"server" (없으면 "*")
    - Quilt: quilt.mod.json minecraft.environment "*"|"client"|"dedicated_server"
    - NeoForge/Forge: META-INF/neoforge.mods.toml·mods.toml. displayTest 가 IGNORE_* 면 클라이언트에 필요 없음.
    """
    try:
        with zipfile.ZipFile(jar) as zf:
            names = set(zf.namelist())
            if "fabric.mod.json" in names:
                d = json.loads(zf.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
                env = d.get("environment") or "*"
                return {"id": str(d.get("id", "")).lower(), "name": d.get("name") or d.get("id"), "version": d.get("version"),
                        "loader": "fabric", "environment": env, "clientRequired": env == "*"}
            if "quilt.mod.json" in names:
                d = json.loads(zf.read("quilt.mod.json").decode("utf-8", "replace"), strict=False)
                ql = d.get("quilt_loader") or {}
                env = ((d.get("minecraft") or {}).get("environment")) or "*"
                return {"id": str(ql.get("id", "")).lower(), "name": (ql.get("metadata") or {}).get("name") or ql.get("id"),
                        "version": ql.get("version"), "loader": "quilt", "environment": env, "clientRequired": env == "*"}
            for toml_name, loader in (("META-INF/neoforge.mods.toml", "neoforge"), ("META-INF/mods.toml", "forge")):
                if toml_name in names:
                    d = tomllib.loads(zf.read(toml_name).decode("utf-8", "replace"))
                    mods = d.get("mods") or [{}]
                    m = mods[0]
                    disp = str(m.get("displayTest") or d.get("displayTest") or "MATCH_VERSION").upper()
                    client_only = bool(d.get("clientSideOnly"))
                    return {"id": str(m.get("modId", "")).lower(), "name": m.get("displayName") or m.get("modId"),
                            "version": m.get("version"), "loader": loader,
                            "environment": "client" if client_only else "*",
                            "clientRequired": not client_only and not disp.startswith("IGNORE")}
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    return None


def scan_mods(mods_dir: Path) -> list[dict[str, Any]]:
    out = []
    if mods_dir.is_dir():
        for p in sorted(mods_dir.iterdir()):
            if p.is_file() and p.suffix == ".jar":
                info = read_mod_info(p)
                if info:
                    out.append({**info, "file": p.name})
    return out


def client_required_mods(mods_dir: Path) -> list[dict[str, Any]]:
    """참가자도 같은 모드가 필요한 목록. 라이브러리는 다른 콘텐츠 모드가 있을 때만 넣는다."""
    cfg = mods_config()
    host_only = set(cfg.get("hostOnly", []))
    libs = set(cfg.get("libraries", []))
    mods = [m for m in scan_mods(mods_dir) if m["clientRequired"] and m["id"] not in host_only]
    content = [m for m in mods if m["id"] not in libs]
    if not content:
        return []
    return [{"id": m["id"], "name": m["name"], "version": m["version"], "file": m["file"],
             "library": m["id"] in libs} for m in mods]
