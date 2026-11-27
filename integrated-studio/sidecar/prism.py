"""Prism Launcher 연동(사용자 결정 2026-11-27: 런처 부분은 Prism 으로).

- 인스턴스 = Prism 인스턴스. 만들기는 Prism 인스턴스 폴더(instance.cfg + mmc-pack.json)를 쓰고, 게임·로더 파일은
  Prism 이 처음 실행할 때 받는다. 실행은 `prismlauncher --dir <데이터> --launch <인스턴스>`(로그인·자바·다운로드는 Prism).
- Prism 찾기: 설치판(%LOCALAPPDATA%\\Programs\\PrismLauncher 등)·포터블(exe 옆 prismlauncher.cfg/portable.txt)·PATH,
  데이터 폴더는 포터블이면 exe 폴더, 아니면 %APPDATA%\\PrismLauncher. 인스턴스 폴더는 prismlauncher.cfg 의 InstanceDir.
- 설치: 사용자 확인 뒤 `winget install --id PrismLauncher.PrismLauncher`(winget 이 설치 파일 해시를 확인한다).
- 계정 파일(accounts.json)은 읽지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from importers import launchers
from importers.local import find_launcher_exe
from rpc import RpcError

WINGET_ID = "PrismLauncher.PrismLauncher"
MISSING_TAG = "[prism-missing]"   # 프런트가 이 글자를 보면 Prism 설치를 권한다
LOADER_UIDS = {"fabric": "net.fabricmc.fabric-loader", "quilt": "org.quiltmc.quilt-loader",
               "neoforge": "net.neoforged", "forge": "net.minecraftforge"}
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _env(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def data_root(exe: Path | None) -> Path | None:
    """Prism 데이터 폴더(인스턴스·설정·계정이 있는 곳)."""
    if exe is not None:
        d = exe.parent
        if (d / "portable.txt").is_file() or (d / "prismlauncher.cfg").is_file():
            return d                                      # 포터블
    appdata = _env("APPDATA")
    if appdata:
        return appdata / "PrismLauncher"
    if sys.platform != "win32":
        return Path.home() / ".local" / "share" / "PrismLauncher"
    return None


def instance_dir(root: Path) -> Path:
    """prismlauncher.cfg 의 InstanceDir(상대 경로면 데이터 폴더 기준). 없으면 <데이터>/instances."""
    cfg = root / "prismlauncher.cfg"
    inst = launchers._cfg(cfg).get("InstanceDir") if cfg.is_file() else None  # noqa: SLF001 - 같은 패키지의 cfg 읽기
    if inst:
        p = Path(inst)
        return p if p.is_absolute() else root / p
    return root / "instances"


def find() -> dict[str, Any]:
    """{found, exe, root, instanceDir}. exe 가 없어도 데이터 폴더는 알려 준다(설치 직후 등)."""
    exe = find_launcher_exe("prism", None)
    root = data_root(exe)
    return {"found": exe is not None, "exe": str(exe) if exe else None,
            "root": str(root) if root else None,
            "instanceDir": str(instance_dir(root)) if root else None}


def require() -> dict[str, Any]:
    info = find()
    if not info["found"] or not info["root"]:
        raise RpcError(f"{MISSING_TAG} Prism Launcher 가 없습니다. Prism 을 설치하면 인스턴스를 만들고 실행할 수 있습니다.")
    return info


def folder_name(name: str, parent: Path) -> str:
    """Prism 인스턴스 폴더 이름(= Prism 인스턴스 id): 쓸 수 없는 글자를 빼고, 겹치면 뒤에 숫자."""
    base = BAD_NAME.sub("", name).strip().rstrip(".") or "instance"
    base = base[:48]
    cand, n = base, 2
    while (parent / cand).exists():
        cand = f"{base} ({n})"
        n += 1
    return cand


def write_pack(folder: Path, version: str, loader: str, loader_version: str | None) -> None:
    """mmc-pack.json: 게임 버전 + 로더. 의존 구성 요소(intermediary·LWJGL)는 Prism 이 채운다."""
    comps: list[dict[str, Any]] = [{"uid": "net.minecraft", "version": version, "important": True}]
    if loader != "vanilla":
        uid = LOADER_UIDS[loader]
        comp: dict[str, Any] = {"uid": uid}
        if loader_version:
            comp["version"] = loader_version
        comps.append(comp)
    (folder / "mmc-pack.json").write_text(json.dumps({"formatVersion": 1, "components": comps}, indent=4), "utf-8")


def _write_cfg(path: Path, values: dict[str, str]) -> None:
    """instance.cfg 의 [General] 값을 바꾸거나 넣는다(나머지 줄은 그대로)."""
    lines = path.read_text("utf-8").splitlines() if path.is_file() else ["[General]"]
    if not any(l.strip() == "[General]" for l in lines):
        lines.insert(0, "[General]")
    keys = dict(values)
    out = []
    for l in lines:
        k = l.split("=", 1)[0].strip() if "=" in l else None
        if k in keys:
            out.append(f"{k}={keys.pop(k)}")
        else:
            out.append(l)
    at = next(i for i, l in enumerate(out) if l.strip() == "[General]") + 1
    for k, v in keys.items():
        out.insert(at, f"{k}={v}")
    path.write_text("\n".join(out) + "\n", "utf-8")


def create_instance(inst_dir: Path, name: str, version: str, loader: str, loader_version: str | None) -> Path:
    """Prism 인스턴스 폴더를 만들고 경로를 돌려준다. 게임 폴더는 <인스턴스>/minecraft."""
    if loader != "vanilla" and loader not in LOADER_UIDS:
        raise RpcError(f"Prism 이 모르는 로더입니다: {loader}")
    inst_dir.mkdir(parents=True, exist_ok=True)
    folder = inst_dir / folder_name(name, inst_dir)
    (folder / "minecraft").mkdir(parents=True)
    _write_cfg(folder / "instance.cfg", {"ConfigVersion": "1.2", "InstanceType": "OneSix", "name": name, "iconKey": "default"})
    write_pack(folder, version, loader, loader_version)
    return folder


def rename_instance(folder: Path, name: str) -> None:
    _write_cfg(folder / "instance.cfg", {"name": name})


def set_memory(folder: Path, memory_mb: int | None, java_args: str | None) -> None:
    """Prism 인스턴스 설정의 최대 메모리·자바 인자(Prism 으로 실행하므로 여기에 써야 적용된다)."""
    values = {"OverrideMemory": "true" if memory_mb else "false"}
    if memory_mb:
        values["MaxMemAlloc"] = str(int(memory_mb))
    values["OverrideJavaArgs"] = "true" if java_args else "false"
    values["JvmArgs"] = java_args or ""
    _write_cfg(folder / "instance.cfg", values)


def install(confirm: Callable[[str], bool], log: Callable[[str], None]) -> dict[str, Any]:
    """사용자 확인 뒤 winget 으로 Prism 설치. winget 이 없거나 실패하면 내려받기 페이지를 안내."""
    if sys.platform != "win32":
        raise RpcError("Prism 자동 설치는 Windows 에서만 됩니다. prismlauncher.org 에서 설치하세요.")
    if find()["found"]:
        return {"ok": True, "already": True, "message": "Prism Launcher 가 이미 설치돼 있습니다."}
    if not confirm("Prism Launcher 를 설치할까요?\n\n인스턴스 만들기·실행(로그인·자바·게임 파일 받기)을 Prism 이 맡습니다.\n"
                   "winget(Windows 패키지 관리자)으로 공식 설치 파일을 받아 설치합니다."):
        return {"ok": False, "cancelled": True, "message": "설치를 취소했습니다."}
    cmd = ["winget", "install", "--id", WINGET_ID, "--exact", "--silent", "--scope", "user",
           "--accept-package-agreements", "--accept-source-agreements"]
    log("Prism Launcher 설치 중(winget)…")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                           creationflags=0x08000000, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "message": f"winget 을 실행하지 못했습니다({e}). https://prismlauncher.org/download/ 에서 설치해 주세요.",
                "url": "https://prismlauncher.org/download/"}
    for line in (p.stdout or "").splitlines()[-15:]:
        if line.strip():
            log(line.strip())
    if find()["found"]:
        return {"ok": True, "message": "Prism Launcher 를 설치했습니다. 처음 한 번 Prism 에서 Microsoft 계정으로 로그인해 주세요."}
    return {"ok": False, "message": "Prism 설치를 확인하지 못했습니다. https://prismlauncher.org/download/ 에서 설치해 주세요.",
            "url": "https://prismlauncher.org/download/"}


def open_prism(exe: str, root: str | None) -> None:
    args = [exe] + (["--dir", root] if root else [])
    subprocess.Popen(args, close_fds=True, stdin=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) if sys.platform == "win32" else 0)
