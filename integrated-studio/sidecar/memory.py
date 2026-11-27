"""메모리(램) 관련: PC 메모리 크기, 게임·서버 메모리 추천값, 통합 작업실이 쓰는 메모리 보기.

추천 기준(마인크래프트 자바판 일반적인 값):
- 바닐라 2GB, 모드 ~30개 3GB, ~100개 4GB, ~200개 6GB, 그 이상 8GB (NeoForge·Forge 는 같은 모드 수에서 1GB 더)
- 너무 많이 주면 오히려 느려진다(정리할 때 끊김이 길고, 윈도우·앱이 쓸 메모리가 모자람) → PC 메모리의 절반을 넘기지 않는다
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

GB = 1024


def system_memory_mb() -> int | None:
    """PC 전체 메모리(MB). 모르면 None."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
                return int(st.ullTotalPhys // (1024 * 1024))
            return None
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except (OSError, ValueError, AttributeError):
        return None


def _cap(want: int, total_mb: int | None) -> int:
    """PC 메모리의 절반을 넘기지 않게(512MB 단위로 내림). 최소 1GB."""
    if total_mb:
        want = min(want, max(GB, (total_mb // 2) // 512 * 512))
    return want


def count_mods(game_dir: Path) -> int:
    mods = game_dir / "mods"
    if not mods.is_dir():
        return 0
    return sum(1 for p in mods.iterdir() if p.is_file() and p.suffix == ".jar")


def recommend_game_mb(mods: int, loader: str, total_mb: int | None) -> dict[str, Any]:
    if mods == 0:
        want, why = 2 * GB, "모드 없음"
    elif mods <= 30:
        want, why = 3 * GB, f"모드 {mods}개"
    elif mods <= 100:
        want, why = 4 * GB, f"모드 {mods}개"
    elif mods <= 200:
        want, why = 6 * GB, f"모드 {mods}개(큰 모드팩)"
    else:
        want, why = 8 * GB, f"모드 {mods}개(아주 큰 모드팩)"
    if mods and loader in ("neoforge", "forge"):
        want += GB
        why += ", Forge 계열"
    rec = _cap(want, total_mb)
    if rec < want:
        why += f", PC 메모리({total_mb // GB}GB)의 절반까지만"
    return {"recommendedMb": rec, "mods": mods, "totalMb": total_mb, "reason": why}


def server_default_mb(total_mb: int | None) -> int:
    """전용·로컬 서버 기본 메모리: 2GB. PC 메모리가 8GB 보다 작으면 게임과 같이 켤 수 있게 PC 의 1/4(최소 1GB)."""
    if total_mb and total_mb < 8 * GB:
        return max(GB, (total_mb // 4) // 512 * 512)
    return 2 * GB


def server_xmx(meta: dict[str, Any]) -> str:
    """서버 java 의 -Xmx 인자. 서버 설정의 memoryMb, 없으면 기본값."""
    mb = int(meta.get("memoryMb") or server_default_mb(system_memory_mb()))
    return f"-Xmx{mb}M"


# ---------------------------------------------------------------- 사용량 보기

def classify(name: str, cmd: str) -> str:
    """프로세스 하나가 통합 작업실의 무엇인지(한국어 이름)."""
    c = cmd.lower()
    n = name.lower()
    if n in ("java.exe", "javaw.exe", "java"):
        return "로컬·전용 서버" if "nogui" in c else "마인크래프트 게임"
    if n.startswith("python"):
        return "사이드카(파이썬)"
    if "claude" in c and ("agent-sdk" in c or "cli.js" in c or n.startswith("claude")):
        return "Claude 패널"
    if "plugin-host" in c or "pluginhost" in c:
        return "VS Code 확장 실행기(CommandCrafter)"
    if "--type=renderer" in c:
        return "화면"
    if "--type=gpu-process" in c:
        return "그래픽(GPU)"
    if "--type=" in c:
        return "보조 프로세스"
    if n.startswith("integrated-studio") and ("main.js" in c or "backend" in c or "--app-project-path" in c):
        return "백엔드"
    if n.startswith("integrated-studio"):
        return "앱 본체"
    return "기타"


def summarize(rows: list[tuple[int, int, str, int, str]], root_pids: set[int]) -> dict[str, Any]:
    """rows = (pid, 부모 pid, 이름, 메모리 바이트, 명령줄). root_pids 의 자손 + 마인크래프트 게임만 센다."""
    children: dict[int, list[int]] = {}
    for pid, ppid, *_ in rows:
        children.setdefault(ppid, []).append(pid)
    mine: set[int] = set()
    stack = list(root_pids)
    while stack:
        p = stack.pop()
        if p in mine:
            continue
        mine.add(p)
        stack.extend(children.get(p, []))
    groups: dict[str, dict[str, Any]] = {}
    for pid, _ppid, name, mem, cmd in rows:
        label = classify(name, cmd)
        if pid not in mine and not (label == "마인크래프트 게임" and "minecraft" in cmd.lower()):
            continue
        g = groups.setdefault(label, {"label": label, "mb": 0, "count": 0})
        g["mb"] += mem // (1024 * 1024)
        g["count"] += 1
    items = sorted(groups.values(), key=lambda g: g["mb"], reverse=True)
    return {"supported": True, "items": items, "totalMb": sum(g["mb"] for g in items), "systemMb": system_memory_mb()}


def usage() -> dict[str, Any]:
    if sys.platform != "win32":
        return {"supported": False, "message": "메모리 사용량 보기는 Windows 에서만 됩니다."}
    import base64
    script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
              "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|$($_.WorkingSetSize)|$($_.CommandLine)\" }")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            creationflags=0x08000000, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return {"supported": False, "message": "프로세스 목록을 읽지 못했습니다."}
    rows = []
    for line in (out or "").splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2], int(parts[3] or 0), parts[4]))
    by_pid = {r[0]: r for r in rows}
    # 사이드카 → 백엔드 → 앱 본체: integrated-studio 이름인 가장 위 조상을 뿌리로
    root = os.getpid()
    cur = by_pid.get(root)
    while cur and cur[1] in by_pid and by_pid[cur[1]][2].lower().startswith("integrated-studio"):
        cur = by_pid[cur[1]]
    return summarize(rows, {cur[0] if cur else root})
