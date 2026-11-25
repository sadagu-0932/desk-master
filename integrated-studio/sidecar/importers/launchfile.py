"""연결한 외부 인스턴스의 "실행 파일".

연결할 때 원래 인스턴스 폴더 안에 `통합 작업실 실행.cmd` 를 만든다. 이 파일은 그 인스턴스를 가진 런처를 연다.
통합 작업실에서 [실행]을 누르면 이 파일을 실행한다(파일이 없어졌으면 다시 만든다). 탐색기에서 더블클릭해도 같다.

- prism·multimc : <exe> --dir <데이터 폴더> --launch <인스턴스 폴더 이름> → 그 인스턴스가 바로 켜진다
- curseforge    : CurseForge 앱을 연다(바깥에서 특정 인스턴스를 켜는 방법이 없어 앱에서 [플레이])
- modrinth      : Modrinth App 을 연다(같은 이유)
- official      : 공식 런처를 연다(통합 작업실이 먼저 공식 런처 항목을 등록해 둔다)

실행 파일은 실제 경로 후보(지금 찾은 경로 + 기본 설치 위치 + PATH)를 차례로 확인한다. 못 찾으면 이유를 보여 주고 멈춘다.
파일 첫 줄 표식(MARKER)이 있는 파일만 우리 것으로 보고 다시 쓰거나 지운다(사용자 파일은 건드리지 않음).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MARKER = "integrated-studio-launch-file v1"
BASENAME = "통합 작업실 실행"
KINDS = ("prism", "multimc", "curseforge", "modrinth", "official")
KIND_NAMES = {"prism": "Prism Launcher", "multimc": "MultiMC", "curseforge": "CurseForge", "modrinth": "Modrinth App",
              "official": "공식 마인크래프트 런처"}
STORE_APP = r"shell:AppsFolder\Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft"


def file_name() -> str:
    return BASENAME + (".cmd" if sys.platform == "win32" else ".sh")


def kind_for(launcher: str | None) -> str:
    return launcher if launcher in KINDS else "official"


def _bat(s: str) -> str:
    """배치 파일 안의 글자: % 는 %% 로(경로에 % 가 있어도 환경 변수로 읽히지 않게)."""
    return s.replace("%", "%%")


def _candidates(kind: str, root: str | None, found: str | None) -> tuple[list[str], list[str], str | None]:
    """(실제 경로 후보, 환경 변수를 쓰는 후보, PATH 에서 찾을 이름)"""
    lit: list[str] = [found] if found else []
    env: list[str] = []
    where = None
    if kind == "prism":
        if root:
            lit += [str(Path(root) / "prismlauncher.exe")]
        env += [r"%LOCALAPPDATA%\Programs\PrismLauncher\prismlauncher.exe", r"%ProgramFiles%\PrismLauncher\prismlauncher.exe"]
        where = "prismlauncher"
    elif kind == "multimc":
        if root:
            lit += [str(Path(root) / "MultiMC.exe")]
        where = "MultiMC"
    elif kind == "curseforge":
        env += [r"%LOCALAPPDATA%\Programs\CurseForge Windows\CurseForge.exe", r"%ProgramFiles%\CurseForge Windows\CurseForge.exe"]
    elif kind == "modrinth":
        env += [r"%LOCALAPPDATA%\Modrinth App\Modrinth App.exe", r"%ProgramFiles%\Modrinth App\Modrinth App.exe",
                r"%LOCALAPPDATA%\Programs\Modrinth App\Modrinth App.exe"]
    else:
        env += [r"%ProgramFiles(x86)%\Minecraft Launcher\MinecraftLauncher.exe", r"%ProgramFiles%\Minecraft Launcher\MinecraftLauncher.exe",
                r"%LOCALAPPDATA%\Programs\Minecraft Launcher\MinecraftLauncher.exe"]
    seen, uniq = set(), []
    for c in lit:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq, env, where


def script_text(meta: dict[str, Any], found_exe: str | None = None, windows: bool | None = None) -> str:
    """실행 파일 내용. windows=None 이면 지금 OS 기준."""
    windows = sys.platform == "win32" if windows is None else windows
    kind = meta.get("launchKind") or "official"
    via = meta.get("launchVia") or {}
    root = via.get("root")
    inst = via.get("instance")
    name = KIND_NAMES.get(kind, kind)
    lit, env, where = _candidates(kind, root, found_exe)
    args_w = f' --dir "{_bat(root)}" --launch "{_bat(inst)}"' if kind in ("prism", "multimc") and root else \
        (f' --launch "{_bat(inst)}"' if kind in ("prism", "multimc") and inst else "")
    if windows:
        out = ["@echo off", "chcp 65001 >nul",
               f"rem {MARKER}",
               f"rem 통합 작업실이 만든 파일: '{meta.get('name', '')}' 을(를) {name}(으)로 엽니다. 지워도 통합 작업실에서 실행하면 다시 만듭니다."]
        for c in lit:
            out.append(f'if exist "{_bat(c)}" start "" "{_bat(c)}"{args_w} & exit /b 0')
        for c in env:   # 환경 변수는 실행할 때 풀린다
            out.append(f'if exist "{c}" start "" "{c}"{args_w} & exit /b 0')
        if where:
            out.append(f'for /f "delims=" %%P in (\'where {where} 2^>nul\') do start "" "%%P"{args_w} & exit /b 0')
        if kind == "curseforge":
            out.append('start "" "curseforge://" & exit /b 0')
        elif kind == "modrinth":
            out.append('start "" "modrinth://" & exit /b 0')
        elif kind == "official":
            out.append(f'start "" "{STORE_APP}" & exit /b 0')
        out += [f"echo [통합 작업실] {name} 을(를) 찾지 못했습니다. 설치돼 있는지 확인해 주세요.", "pause", "exit /b 1"]
        return "\r\n".join(out) + "\r\n"
    # Windows 가 아닐 때(개발·시험용): 같은 순서의 sh
    args_s = (f' --dir "{root}" --launch "{inst}"' if root else f' --launch "{inst}"') if kind in ("prism", "multimc") and inst else ""
    out = ["#!/bin/sh", f"# {MARKER}", f"# 통합 작업실이 만든 파일: {name}(으)로 엽니다."]
    for c in lit:
        out.append(f'[ -x "{c}" ] && exec "{c}"{args_s}')
    if where:
        out.append(f'command -v {where} >/dev/null 2>&1 && exec {where}{args_s}')
    out += [f'echo "[통합 작업실] {name} 을(를) 찾지 못했습니다." >&2', "exit 1"]
    return "\n".join(out) + "\n"


def is_ours(path: Path) -> bool:
    try:
        return MARKER in path.read_bytes()[:400].decode("utf-8", "replace")
    except OSError:
        return False


def write(meta: dict[str, Any], folder: Path, found_exe: str | None = None) -> Path:
    """폴더 안에 실행 파일을 만든다(같은 이름의 남의 파일이 있으면 이름 뒤에 (통합 작업실)을 붙인다)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name()
    if path.exists() and not is_ours(path):
        path = folder / file_name().replace(BASENAME, BASENAME + " (통합 작업실)")
    text = script_text(meta, found_exe)
    data = text.encode("utf-8")
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)
    if sys.platform != "win32":
        path.chmod(0o755)
    return path


def run(path: Path) -> None:
    """실행 파일을 실행한다(창 없이). 런처는 파일 안의 start 로 따로 뜬다."""
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", str(path)], cwd=str(path.parent),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    else:
        subprocess.Popen(["sh", str(path)], cwd=str(path.parent), close_fds=True, start_new_session=True)


def remove(path: Path) -> bool:
    if path.is_file() and is_ours(path):
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def env_expand(path: str) -> str:
    return os.path.expandvars(path)
