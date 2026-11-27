"""이 PC 에 설치된 자바(JDK·JRE) 찾기와 Java 25 JDK 설치(사용자 요청 2026-11-27 "자바가 없어서 오류").

- 찾는 곳: JAVA_HOME → PATH → 표준 설치 폴더(Eclipse Adoptium·Microsoft·Oracle Java·Zulu·BellSoft·Amazon Corretto)
- 버전은 JDK 폴더의 `release` 파일(JAVA_VERSION="25.0.5")로 읽는다(자바를 실행하지 않아 빠르고 안전).
- JDK = bin/javac 가 있는 것(모드·플러그인 빌드에 필요). 서버 실행에는 JRE 도 된다.
- 설치: 사용자 확인 뒤 `winget install --id EclipseAdoptium.Temurin.25.JDK`(winget 목록 2026-11 확인: Scope machine,
  ADDLOCAL=ALL 로 PATH·JAVA_HOME 설정). 컴퓨터 전체 설치라 Windows 관리자 확인 창이 뜬다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from rpc import RpcError

WINGET_ID = "EclipseAdoptium.Temurin.25.JDK"
DOWNLOAD_PAGE = "https://adoptium.net/temurin/releases/?version=25"
BUILD_MAJOR = 25          # 26.x 모드·Paper 플러그인 빌드(툴체인 25)
VENDOR_DIRS = ("Eclipse Adoptium", "Microsoft", "Java", "Zulu", "BellSoft", "Amazon Corretto", "Semeru")
EXE = "java.exe" if sys.platform == "win32" else "java"
JAVAC = "javac.exe" if sys.platform == "win32" else "javac"


def _major(version: str) -> int:
    """'25.0.5' → 25, '1.8.0_402' → 8"""
    parts = re.findall(r"\d+", version or "")
    if not parts:
        return 0
    return int(parts[1]) if parts[0] == "1" and len(parts) > 1 else int(parts[0])


def read_home(home: Path) -> dict[str, Any] | None:
    """JDK·JRE 폴더 하나의 정보 {home, java, major, version, jdk}. 자바가 아니면 None."""
    java = home / "bin" / EXE
    if not java.is_file():
        return None
    version = ""
    try:
        m = re.search(r'^JAVA_VERSION="([^"]+)"', (home / "release").read_text("utf-8", "replace"), re.M)
        version = m.group(1) if m else ""
    except OSError:
        pass
    if not version:
        m = re.search(r"(?:jdk|jre|java)[-_]?(1\.\d+\.\d+|\d+(?:\.\d+)*)", home.name, re.I)
        version = m.group(1) if m else ""
    return {"home": str(home), "java": str(java), "major": _major(version), "version": version,
            "jdk": (home / "bin" / JAVAC).is_file()}


def _candidates() -> list[Path]:
    homes: list[Path] = []
    jh = os.environ.get("JAVA_HOME")
    if jh:
        homes.append(Path(jh))
    on_path = shutil.which("java")
    if on_path:
        try:
            homes.append(Path(on_path).resolve().parent.parent)
        except OSError:
            pass
    roots: list[Path] = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
            v = os.environ.get(env)
            if v:
                roots += [Path(v) / d for d in VENDOR_DIRS]
                if env == "LOCALAPPDATA":
                    roots.append(Path(v) / "Programs" / "Eclipse Adoptium")
    else:
        roots += [Path("/usr/lib/jvm"), Path("/Library/Java/JavaVirtualMachines"), Path.home() / ".jdks"]
    for r in roots:
        try:
            for d in r.iterdir():
                homes.append(d / "Contents" / "Home" if (d / "Contents" / "Home").is_dir() else d)
        except OSError:
            continue
    return homes


def find_all() -> list[dict[str, Any]]:
    """찾은 자바 목록(같은 폴더는 한 번). 새 버전·JDK 먼저."""
    seen: set[str] = set()
    out = []
    for h in _candidates():
        try:
            key = str(h.resolve()).lower()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        info = read_home(h)
        if info and info["major"]:
            out.append(info)
    out.sort(key=lambda j: (j["major"], j["jdk"]), reverse=True)
    return out


def best(min_major: int, jdk: bool = False, exact_first: bool = True) -> dict[str, Any] | None:
    """min_major 이상인 자바. exact_first 면 정확히 그 버전을 먼저(새 자바는 옛 모드를 못 돌리기도 해서)."""
    ok = [j for j in find_all() if j["major"] >= min_major and (j["jdk"] or not jdk)]
    if not ok:
        return None
    if exact_first:
        exact = [j for j in ok if j["major"] == min_major]
        if exact:
            return exact[0]
    return ok[-1]          # 조건을 만족하는 것 중 가장 낮은 버전(호환성)


def build_env(min_major: int = BUILD_MAJOR) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Gradle 빌드용 환경: 맞는 JDK 가 있으면 JAVA_HOME 과 PATH 앞자리를 그 JDK 로(사용자의 옛 JAVA_HOME 이 8·17 이어도 빌드되게)."""
    env = dict(os.environ)
    j = best(min_major, jdk=True, exact_first=False)
    if j:
        env["JAVA_HOME"] = j["home"]
        env["PATH"] = str(Path(j["home"]) / "bin") + os.pathsep + env.get("PATH", "")
    return env, j


def status() -> dict[str, Any]:
    all_ = find_all()
    j = next((x for x in all_ if x["major"] >= BUILD_MAJOR and x["jdk"]), None)
    return {"found": all_, "buildJdk": j, "ok": bool(j), "need": BUILD_MAJOR}


def missing_message(what: str) -> str:
    return (f"{what}에 Java {BUILD_MAJOR} JDK 가 필요한데 찾지 못했습니다. 명령 팔레트 'Java 25 JDK 설치'로 설치하거나 "
            f"{DOWNLOAD_PAGE} 에서 받아 주세요.")


def install(confirm: Callable[[str], bool], log: Callable[[str], None]) -> dict[str, Any]:
    """사용자 확인 뒤 winget 으로 Temurin 25 JDK 설치."""
    if status()["ok"]:
        return {"ok": True, "already": True, "message": f"Java {BUILD_MAJOR} JDK 가 이미 있습니다: {status()['buildJdk']['home']}"}
    if sys.platform != "win32":
        raise RpcError(f"자동 설치는 Windows 에서만 됩니다. {DOWNLOAD_PAGE} 에서 받아 주세요.")
    if not confirm(f"Java {BUILD_MAJOR} JDK(Eclipse Temurin)를 설치할까요?\n\n서버 실행과 모드·플러그인 빌드에 씁니다.\n"
                   "winget(Windows 패키지 관리자)으로 공식 설치 파일을 받아 컴퓨터 전체에 설치합니다 — 관리자 확인 창이 뜹니다."):
        return {"ok": False, "cancelled": True, "message": "설치를 취소했습니다."}
    log(f"Java {BUILD_MAJOR} JDK 설치 중(winget)…")
    cmd = ["winget", "install", "--id", WINGET_ID, "--exact", "--silent",
           "--accept-package-agreements", "--accept-source-agreements"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200,
                           creationflags=0x08000000, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "message": f"winget 을 실행하지 못했습니다({e}). {DOWNLOAD_PAGE} 에서 받아 주세요.", "url": DOWNLOAD_PAGE}
    for line in (p.stdout or "").splitlines()[-15:]:
        if line.strip():
            log(line.strip())
    st = status()
    if st["ok"]:
        return {"ok": True, "message": f"Java {BUILD_MAJOR} JDK 를 설치했습니다: {st['buildJdk']['home']}"}
    return {"ok": False, "message": f"설치를 확인하지 못했습니다(winget 코드 {p.returncode}). {DOWNLOAD_PAGE} 에서 받아 주세요.",
            "url": DOWNLOAD_PAGE}
