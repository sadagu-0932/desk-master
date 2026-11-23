"""공식 마인크래프트 런처 연동 (Windows 전용, 개인용).

이 앱은 자체 MS 로그인을 하지 않는다. 온라인 플레이는 공식 런처에 맡기고,
우리는 인스턴스를 공식 런처의 "설치" 항목으로 등록하고 로그만 따라 읽는다.

사용 예시::

    import official_launcher as ol

    info = ol.is_installed()
    if not info["installed"]:
        result = ol.install(
            confirm_callback=lambda msg: ask_user_yes_no(msg),   # True 를 돌려줘야 실행
            log_callback=print,
        )
        print(result["message"])

    instance = {
        "id": "my-world", "name": "내 월드", "path": r"C:\\...\\instances\\my-world",
        "version": "1.21.4", "versionId": "fabric-loader-0.16.10-1.21.4",
        "jvmArgs": ["-Xmx4G"],
    }
    r = ol.register_instance(instance, confirm_callback=ask_user_yes_no,
                             app_minecraft_dir=r"C:\\...\\minecraft")
    print(r["message"])          # "통합 작업실 · 내 월드" 항목이 공식 런처에 생김

    ol.open_launcher()           # 사용자가 공식 런처에서 플레이를 누른다
    tail = ol.tail_log(instance["path"], lambda line: print(line))
    ...
    tail.stop()

    ol.unregister_instance("my-world", confirm_callback=ask_user_yes_no)

안전 규칙:
- launcher_accounts*.json, launcher_msa_credentials* 등 로그인·토큰 파일은 절대 열지 않는다(_guard_path).
- launcher_profiles.json 은 수정 전 항상 백업하고, 실패하면 백업으로 되돌린다.
- 설치·파일 수정은 confirm_callback 이 True 를 돌려줄 때만 한다.
- 우리가 만든 항목은 키가 "integrated-studio-<인스턴스 id>" 인 것뿐이며, 그것만 갱신·삭제한다.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import minecraft_launcher_lib.vanilla_launcher as vanilla_launcher

ConfirmCallback = Callable[[str], bool]
LogCallback = Callable[[str], None]

WINGET_ID = "Mojang.MinecraftLauncher"
STORE_PRODUCT_ID = "9PGW18NPBZV5"
STORE_URL = f"ms-windows-store://pdp/?productid={STORE_PRODUCT_ID}"
STORE_PACKAGE_NAME = "Microsoft.4297127D64EC6"            # Store/Xbox판 "Minecraft Launcher"
STORE_PACKAGE_FAMILY = "Microsoft.4297127D64EC6_8wekyb3d8bbwe"
LAUNCHER_EXE_NAMES = ("MinecraftLauncher.exe", "Minecraft.exe")

PROFILE_KEY_PREFIX = "integrated-studio-"
PROFILE_NAME_PREFIX = "통합 작업실 · "
PROFILES_FILE = "launcher_profiles.json"
BACKUP_KEEP = 10

UPDATE_NOTICE = ("winget 으로 설치되는 공식 런처는 MSI판이라 버전이 조금 오래됐을 수 있습니다. "
                 "처음 실행하면 런처가 스스로 최신 버전으로 업데이트하니 잠시 기다려 주세요.")

_ID_RE = re.compile(r"[0-9A-Za-z._\-]{1,64}")
# 이름에 이런 말이 들어간 파일은 어떤 경우에도 열지 않는다.
_FORBIDDEN_NAME_PARTS = ("launcher_accounts", "launcher_msa_credentials", "credentials", "accounts")


class OfficialLauncherError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 오류."""


# ---------------------------------------------------------------- 공통 도우미

def _is_windows() -> bool:
    """플랫폼 검사. 테스트에서 mock 한다."""
    return sys.platform == "win32"


def _not_windows_result(**extra: Any) -> dict[str, Any]:
    return {"ok": False, "message": "공식 런처 연동은 Windows에서만 사용할 수 있습니다.", **extra}


def _guard_path(path: str | os.PathLike) -> Path:
    """로그인·토큰 파일이면 즉시 거부한다. 모든 파일 접근은 이 함수를 거친다."""
    p = Path(path)
    lower = p.name.lower()
    if any(part in lower for part in _FORBIDDEN_NAME_PARTS):
        raise OfficialLauncherError(f"로그인 정보 파일에는 접근하지 않습니다: {p.name}")
    return p


def _run(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    """짧은 명령 실행(출력 수집). 테스트에서 mock 한다."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=flags)


def _popen(args: list[str]) -> subprocess.Popen:
    """긴 명령 실행(한 줄씩 읽기용). 테스트에서 mock 한다."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=flags)


def _start_file(target: str) -> None:
    """Windows 셸로 파일/URI 열기. 테스트에서 mock 한다."""
    os.startfile(target)  # type: ignore[attr-defined]  # Windows 전용


def _env_dir(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


# ---------------------------------------------------------------- 설치 확인

def _store_package() -> dict[str, str] | None:
    """Store/Xbox판(Appx) 패키지 정보. PowerShell Get-AppxPackage 로 확인한다."""
    script = (
        f"$p = Get-AppxPackage -Name {STORE_PACKAGE_NAME} | Select-Object -First 1; "
        "if ($p) { $a = (Get-AppxPackageManifest $p).Package.Applications.Application | Select-Object -First 1; "
        "Write-Output ($p.PackageFamilyName + '|' + $p.InstallLocation + '|' + $a.Id + '|' + $p.Version) }"
    )
    try:
        r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (r.stdout or "").strip().splitlines()
    if r.returncode != 0 or not line or "|" not in line[0]:
        return None
    family, location, app_id, version = (line[0].split("|") + ["", "", "", ""])[:4]
    return {"family": family.strip(), "location": location.strip(),
            "app_id": app_id.strip() or "Minecraft", "version": version.strip()}


def _registry_launcher_paths() -> list[Path]:
    """레지스트리에서 MSI/winget판 설치 경로 후보를 모은다."""
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return []
    found: list[Path] = []

    def read(root: Any, sub: str, value: str) -> str | None:
        for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0)):
            try:
                with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view) as k:
                    return str(winreg.QueryValueEx(k, value)[0])
            except OSError:
                continue
        return None

    hklm, hkcu = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
    for root in (hklm, hkcu):
        loc = read(root, r"SOFTWARE\Mojang\InstalledProducts\Minecraft Launcher", "InstallLocation")
        if loc:
            found.append(Path(loc))
    # 제거 목록에서 DisplayName 이 "Minecraft Launcher" 인 항목
    for root in (hklm, hkcu):
        for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0,
                                    winreg.KEY_READ | view) as base:
                    for i in range(winreg.QueryInfoKey(base)[0]):
                        try:
                            name = winreg.EnumKey(base, i)
                            with winreg.OpenKey(base, name) as k:
                                disp = str(winreg.QueryValueEx(k, "DisplayName")[0])
                                if "minecraft launcher" not in disp.lower():
                                    continue
                                try:
                                    found.append(Path(str(winreg.QueryValueEx(k, "InstallLocation")[0])))
                                except OSError:
                                    pass
                        except OSError:
                            continue
            except OSError:
                continue
    return [p for p in found if str(p).strip()]


def _default_launcher_paths() -> list[Path]:
    """MSI/winget판 기본 설치 경로 후보."""
    paths = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = _env_dir(env)
        if base:
            paths.append(base / "Minecraft Launcher")
            if env == "LOCALAPPDATA":
                paths.append(base / "Programs" / "Minecraft Launcher")
    return paths


def _find_classic_exe() -> Path | None:
    for folder in _registry_launcher_paths() + _default_launcher_paths():
        for exe in LAUNCHER_EXE_NAMES:
            candidate = folder / exe
            if candidate.is_file():
                return candidate
    return None


def is_installed() -> dict[str, Any]:
    """공식 런처 설치 여부.

    반환: {"installed": bool, "kinds": ["store"|"classic"], "kind": 대표 종류 또는 None,
           "store": Appx 정보 또는 None, "exe": MSI/winget판 실행 파일 경로 또는 None, "message": 한국어 설명}
    """
    if not _is_windows():
        return {"installed": False, "kinds": [], "kind": None, "store": None, "exe": None,
                "message": "공식 런처 연동은 Windows에서만 사용할 수 있습니다."}
    store = _store_package()
    exe = _find_classic_exe()
    kinds = (["store"] if store else []) + (["classic"] if exe else [])
    labels = {"store": "Microsoft Store/Xbox판", "classic": "설치 프로그램(winget·MSI)판"}
    if kinds:
        message = "공식 런처가 설치되어 있습니다: " + ", ".join(labels[k] for k in kinds)
    else:
        message = "공식 마인크래프트 런처가 설치되어 있지 않습니다."
    return {"installed": bool(kinds), "kinds": kinds, "kind": kinds[0] if kinds else None,
            "store": store, "exe": str(exe) if exe else None, "message": message}


# ---------------------------------------------------------------- 설치

_PROGRESS_RE = re.compile(r"^[\s\-\\|/█▒░▓■□.%0-9KMGBkmgb/ ]*$")


def _clean_winget_line(line: str) -> str | None:
    """winget 의 진행 막대·스피너 줄은 버리고 의미 있는 줄만 남긴다."""
    line = line.split("\r")[-1].strip()
    if not line or _PROGRESS_RE.match(line):
        return None
    return line


def _open_store_page(log_callback: LogCallback) -> bool:
    try:
        _start_file(STORE_URL)
        log_callback("Microsoft Store 의 공식 런처 페이지를 열었습니다.")
        return True
    except OSError as e:
        log_callback(f"Microsoft Store 를 열지 못했습니다: {e}")
        return False


def install(confirm_callback: ConfirmCallback, log_callback: LogCallback) -> dict[str, Any]:
    """사용자가 확인하면 winget 으로 공식 런처를 설치한다. 안 되면 Store 페이지를 연다.

    반환: {"ok": bool, "method": "winget"|"store"|None, "message": 한국어 안내}
    """
    if not _is_windows():
        return _not_windows_result(method=None)
    question = ("공식 마인크래프트 런처를 설치할까요?\n"
                f"winget 으로 '{WINGET_ID}' 패키지를 설치합니다. "
                "winget 을 쓸 수 없으면 Microsoft Store 페이지를 엽니다.")
    if not confirm_callback(question):
        return {"ok": False, "method": None, "message": "설치를 취소했습니다."}

    winget = shutil.which("winget")
    if winget:
        args = [winget, "install", "--id", WINGET_ID, "--exact",
                "--accept-package-agreements", "--accept-source-agreements"]
        log_callback("winget 으로 공식 런처를 설치하는 중입니다…")
        try:
            proc = _popen(args)
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = _clean_winget_line(raw)
                if line:
                    log_callback(line)
            code = proc.wait()
        except (OSError, subprocess.SubprocessError) as e:
            log_callback(f"winget 실행에 실패했습니다: {e}")
            code = -1
        if code == 0:
            return {"ok": True, "method": "winget", "message": "공식 런처를 설치했습니다. " + UPDATE_NOTICE}
        log_callback(f"winget 설치가 실패했습니다(종료 코드 {code}). Microsoft Store 로 안내합니다.")
    else:
        log_callback("winget 을 찾을 수 없습니다. Microsoft Store 로 안내합니다.")

    if _open_store_page(log_callback):
        return {"ok": True, "method": "store",
                "message": "Microsoft Store 에서 '설치'를 눌러 주세요. 설치가 끝나면 다시 확인합니다."}
    return {"ok": False, "method": None,
            "message": "공식 런처를 설치하지 못했습니다. Microsoft Store 에서 'Minecraft Launcher'를 직접 설치해 주세요."}


# ---------------------------------------------------------------- .minecraft 경로

def minecraft_dir_candidates() -> list[dict[str, Any]]:
    """공식 런처의 .minecraft 후보. 일반판은 %APPDATA%, Store판은 가상화 시 패키지 LocalCache 아래."""
    out = []
    appdata, local = _env_dir("APPDATA"), _env_dir("LOCALAPPDATA")
    if appdata:
        out.append({"kind": "roaming", "path": appdata / ".minecraft"})
    if local:
        out.append({"kind": "store-virtualized",
                    "path": local / "Packages" / STORE_PACKAGE_FAMILY / "LocalCache" / "Roaming" / ".minecraft"})
    for c in out:
        c["exists"] = (c["path"] / PROFILES_FILE).is_file()
    return out


def find_minecraft_dir() -> dict[str, Any]:
    """launcher_profiles.json 이 있는 .minecraft 를 고른다.

    둘 다 있으면 최근에 런처가 쓴 쪽(launcher_profiles.json 수정 시각)을 쓰고 경고를 붙인다.
    반환: {"path": Path 또는 None, "kind": ..., "warning": str 또는 None}
    """
    found = [c for c in minecraft_dir_candidates() if c["exists"]]
    if not found:
        return {"path": None, "kind": None, "warning": None}
    found.sort(key=lambda c: (c["path"] / PROFILES_FILE).stat().st_mtime, reverse=True)
    warning = None
    if len(found) > 1:
        warning = ("launcher_profiles.json 이 두 곳에 있습니다. 최근에 사용된 곳에 등록했습니다: "
                   f"{found[0]['path']}")
    return {"path": found[0]["path"], "kind": found[0]["kind"], "warning": warning}


def _resolve_mc_dir(minecraft_dir: str | os.PathLike | None) -> tuple[Path, str | None]:
    if minecraft_dir is not None:
        return Path(minecraft_dir), None
    info = find_minecraft_dir()
    if info["path"] is None:
        raise OfficialLauncherError("공식 런처 설정 파일(launcher_profiles.json)을 찾지 못했습니다. "
                                    "공식 런처를 한 번 실행했다가 닫은 뒤 다시 시도해 주세요.")
    return info["path"], info["warning"]


# ---------------------------------------------------------------- launcher_profiles.json

def _profiles_path(mc_dir: Path) -> Path:
    return _guard_path(mc_dir / PROFILES_FILE)


def _read_profiles(mc_dir: Path) -> dict[str, Any]:
    data = json.loads(_profiles_path(mc_dir).read_text("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise OfficialLauncherError("launcher_profiles.json 형식이 올바르지 않아 수정하지 않았습니다.")
    return data


def _write_profiles(mc_dir: Path, data: dict[str, Any]) -> None:
    path = _profiles_path(mc_dir)
    tmp = _guard_path(path.with_name(path.name + ".integrated-studio.tmp"))
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def backup_profiles(mc_dir: str | os.PathLike) -> Path:
    """launcher_profiles.json 을 같은 폴더에 시각 붙은 이름으로 복사한다. 오래된 백업은 정리."""
    mc = Path(mc_dir)
    src = _profiles_path(mc)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = _guard_path(mc / f"{PROFILES_FILE}.integrated-studio-{stamp}.bak")
    shutil.copy2(src, dest)
    olds = sorted(mc.glob(f"{PROFILES_FILE}.integrated-studio-*.bak"))
    for old in olds[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def _restore(mc_dir: Path, backup: Path) -> None:
    shutil.copy2(_guard_path(backup), _profiles_path(mc_dir))


def launcher_running() -> bool:
    """공식 런처가 켜져 있는지. 켜져 있으면 런처가 종료 때 파일을 덮어쓸 수 있다."""
    if not _is_windows():
        return False
    for exe in LAUNCHER_EXE_NAMES:
        try:
            r = _run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"], timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if exe.lower() in (r.stdout or "").lower():
            return True
    return False


def profile_key(instance_id: str) -> str:
    if not isinstance(instance_id, str) or not _ID_RE.fullmatch(instance_id):
        raise OfficialLauncherError(f"잘못된 인스턴스 id 입니다: {instance_id!r}")
    return PROFILE_KEY_PREFIX + instance_id


def _jvm_args(instance: dict[str, Any]) -> list[str] | None:
    raw = instance.get("jvmArgs", instance.get("javaArgs"))
    if raw is None:
        return None
    args = raw.split() if isinstance(raw, str) else [str(a) for a in raw]
    return [a for a in args if a] or None


def _ensure_version_json(mc_dir: Path, version_id: str, app_minecraft_dir: Path | None,
                         log: list[str]) -> None:
    """공식 런처는 자기 .minecraft/versions 에서만 버전을 찾는다.
    바닐라가 아니면(Fabric 등) 앱이 설치한 버전 JSON 을 복사해 둔다. 라이브러리는 런처가 받는다."""
    dest = mc_dir / "versions" / version_id / f"{version_id}.json"
    if app_minecraft_dir is None:
        return
    src = app_minecraft_dir / "versions" / version_id / f"{version_id}.json"
    if not dest.is_file():
        if not src.is_file():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        log.append(f"버전 정보 {version_id} 를 공식 런처 폴더에 복사했습니다.")
    _copy_generated_libraries(dest, mc_dir, app_minecraft_dir, log)


def _copy_generated_libraries(version_json: Path, mc_dir: Path, app_minecraft_dir: Path, log: list[str]) -> None:
    """Forge·NeoForge 설치기가 만든 라이브러리(내려받을 주소가 비어 있는 것: 패치된 클라이언트 jar 등)는
    공식 런처가 받을 수 없으므로 앱 .minecraft 에서 복사한다. 주소가 있는 라이브러리는 런처가 받는다."""
    try:
        data = json.loads(version_json.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    copied = 0
    for lib in data.get("libraries") or []:
        art = ((lib.get("downloads") or {}).get("artifact")) or {}
        rel = art.get("path")
        if not rel or art.get("url"):
            continue
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            continue
        src = app_minecraft_dir / "libraries" / rel_path
        dst = mc_dir / "libraries" / rel_path
        if src.is_file() and not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    if copied:
        log.append(f"설치기가 만든 라이브러리 {copied}개를 공식 런처 폴더에 복사했습니다(Forge·NeoForge).")


def register_instance(instance: dict[str, Any], confirm_callback: ConfirmCallback | None = None, *,
                      minecraft_dir: str | os.PathLike | None = None,
                      app_minecraft_dir: str | os.PathLike | None = None) -> dict[str, Any]:
    """인스턴스를 공식 런처의 "설치" 항목으로 등록(이미 있으면 갱신)한다.

    instance: {"id", "name", "path", "version", "versionId"(Fabric 등 실제 실행 버전), "jvmArgs"}
    confirm_callback: 파일 수정 전에 물어본다. 없거나 False 면 아무것도 바꾸지 않는다.
    minecraft_dir: 공식 런처 .minecraft (없으면 자동으로 찾음, 테스트용으로도 씀)
    app_minecraft_dir: 이 앱이 버전을 설치한 폴더(Fabric 버전 JSON 복사용)
    반환: {"ok", "key", "updated", "backup", "message", "warnings"}
    """
    if minecraft_dir is None and not _is_windows():
        return _not_windows_result()
    key = profile_key(instance.get("id", ""))
    version_id = instance.get("versionId") or instance.get("version")
    if not version_id:
        raise OfficialLauncherError("인스턴스 버전이 비어 있어 등록할 수 없습니다.")
    game_dir = instance.get("path")
    if not game_dir:
        raise OfficialLauncherError("인스턴스 폴더 경로가 비어 있어 등록할 수 없습니다.")
    display = str(instance.get("name") or instance["id"]).strip()
    name = PROFILE_NAME_PREFIX + display

    mc_dir, warning = _resolve_mc_dir(minecraft_dir)
    warnings = [w for w in [warning] if w]
    if launcher_running():
        warnings.append("공식 런처가 켜져 있습니다. 런처를 닫았다가 다시 열어야 항목이 보이며, "
                        "켜진 채로 두면 런처가 변경을 덮어쓸 수 있습니다.")

    before = _read_profiles(mc_dir)
    updated = key in before["profiles"]
    question = (f"공식 런처에 '{name}' 항목을 {'갱신' if updated else '추가'}할까요?\n"
                f"수정할 파일: {mc_dir / PROFILES_FILE} (수정 전에 백업합니다)")
    if confirm_callback is None or not confirm_callback(question):
        return {"ok": False, "key": key, "updated": False, "backup": None,
                "message": "등록을 취소했습니다.", "warnings": warnings}

    backup = backup_profiles(mc_dir)
    log: list[str] = []
    try:
        old_keys = set(before["profiles"])
        profile: dict[str, Any] = {
            "name": name, "versionType": "custom", "version": str(version_id),
            "gameDirectory": str(Path(game_dir).resolve()),
        }
        jvm = _jvm_args(instance)
        if jvm:
            profile["javaArguments"] = jvm
        vanilla_launcher.add_vanilla_launcher_profile(str(mc_dir), profile)  # type: ignore[arg-type]

        # 라이브러리는 무작위 키로 새 항목을 만든다 → 우리 고정 키로 옮겨 중복을 막는다.
        data = _read_profiles(mc_dir)
        new_keys = [k for k in data["profiles"] if k not in old_keys]
        if len(new_keys) != 1:
            raise OfficialLauncherError("새로 추가된 항목을 찾지 못했습니다.")
        new_profile = data["profiles"].pop(new_keys[0])
        old_profile = before["profiles"].get(key) or {}
        if old_profile.get("created"):
            new_profile["created"] = old_profile["created"]
        for keep in ("icon", "resolution", "javaDir"):  # 사용자가 공식 런처에서 바꾼 값은 유지
            if keep in old_profile and keep not in new_profile:
                new_profile[keep] = old_profile[keep]
        data["profiles"][key] = new_profile
        _write_profiles(mc_dir, data)
        _ensure_version_json(mc_dir, str(version_id),
                             Path(app_minecraft_dir) if app_minecraft_dir else None, log)
    except Exception as e:
        _restore(mc_dir, backup)
        raise OfficialLauncherError(f"등록에 실패해 원래대로 되돌렸습니다: {e}") from e

    msg = f"공식 런처에 '{name}' 항목을 {'갱신' if updated else '추가'}했습니다. 공식 런처의 '플레이'에서 고르세요."
    return {"ok": True, "key": key, "updated": updated, "backup": str(backup),
            "message": " ".join([msg] + log), "warnings": warnings}


def registered_profile(instance_id: str, *, minecraft_dir: str | os.PathLike | None = None) -> dict[str, Any] | None:
    """우리가 등록한 항목(키 integrated-studio-<id>)을 읽기만 한다. 없거나 설정 파일이 없으면 None."""
    if minecraft_dir is None and not _is_windows():
        return None
    key = profile_key(instance_id)
    try:
        mc_dir, _ = _resolve_mc_dir(minecraft_dir)
        return _read_profiles(mc_dir)["profiles"].get(key)
    except (OfficialLauncherError, OSError, ValueError):
        return None


def registered_ids(*, minecraft_dir: str | os.PathLike | None = None) -> list[str]:
    """우리가 등록한 항목들의 인스턴스 id (읽기만)."""
    if minecraft_dir is None and not _is_windows():
        return []
    try:
        mc_dir, _ = _resolve_mc_dir(minecraft_dir)
        keys = _read_profiles(mc_dir)["profiles"]
    except (OfficialLauncherError, OSError, ValueError):
        return []
    return [k[len(PROFILE_KEY_PREFIX):] for k in keys if k.startswith(PROFILE_KEY_PREFIX)]


def unregister_instance(instance_id: str, confirm_callback: ConfirmCallback | None = None, *,
                        minecraft_dir: str | os.PathLike | None = None) -> dict[str, Any]:
    """우리가 만든 항목(키 integrated-studio-<id>)만 공식 런처에서 지운다."""
    if minecraft_dir is None and not _is_windows():
        return _not_windows_result()
    key = profile_key(instance_id)
    mc_dir, _ = _resolve_mc_dir(minecraft_dir)
    data = _read_profiles(mc_dir)
    if key not in data["profiles"]:
        return {"ok": True, "removed": False, "backup": None, "message": "등록된 항목이 없습니다."}
    name = data["profiles"][key].get("name", key)
    if confirm_callback is None or not confirm_callback(
            f"공식 런처에서 '{name}' 항목을 지울까요? (게임 폴더는 지우지 않습니다. 수정 전에 백업합니다)"):
        return {"ok": False, "removed": False, "backup": None, "message": "삭제를 취소했습니다."}
    backup = backup_profiles(mc_dir)
    try:
        del data["profiles"][key]
        _write_profiles(mc_dir, data)
    except Exception as e:
        _restore(mc_dir, backup)
        raise OfficialLauncherError(f"삭제에 실패해 원래대로 되돌렸습니다: {e}") from e
    return {"ok": True, "removed": True, "backup": str(backup), "message": f"'{name}' 항목을 지웠습니다."}


# ---------------------------------------------------------------- 실행

def open_launcher() -> dict[str, Any]:
    """공식 런처를 연다. 플레이 버튼은 사용자가 누른다."""
    if not _is_windows():
        return _not_windows_result()
    info = is_installed()
    try:
        if info["exe"]:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen([info["exe"]], creationflags=flags, close_fds=True)
            return {"ok": True, "message": "공식 런처를 열었습니다. 원하는 항목을 고르고 '플레이'를 눌러 주세요."}
        if info["store"]:
            store = info["store"]
            _start_file(f"shell:AppsFolder\\{store['family']}!{store['app_id']}")
            return {"ok": True, "message": "공식 런처를 열었습니다. 원하는 항목을 고르고 '플레이'를 눌러 주세요."}
    except OSError as e:
        return {"ok": False, "message": f"공식 런처를 열지 못했습니다: {e}"}
    return {"ok": False, "message": "공식 런처가 설치되어 있지 않습니다. 먼저 설치해 주세요."}


# ---------------------------------------------------------------- 로그 따라 읽기

class LogTail:
    """tail_log 가 돌려주는 핸들. stop() 으로 멈춘다."""

    def __init__(self, path: Path, callback: LogCallback, from_start: bool, interval: float):
        self.path = path
        self.callback = callback
        self.interval = interval
        self._stop = threading.Event()
        self._pos = 0
        self._ident: tuple[int, int] | None = None
        self._buf = b""
        if not from_start:
            st = self._stat()
            if st is not None:
                self._pos, self._ident = st.st_size, (st.st_dev, st.st_ino)
        self.thread = threading.Thread(target=self._loop, name="official-launcher-tail", daemon=True)

    def _stat(self) -> os.stat_result | None:
        try:
            return os.stat(self.path)
        except OSError:
            return None

    def poll(self) -> None:
        """한 번 확인해 새 줄을 전달한다. 파일을 계속 열어두지 않아(게임의 로그 교체를 막지 않도록) 매번 열고 닫는다."""
        st = self._stat()
        if st is None:
            return
        ident = (st.st_dev, st.st_ino)
        if self._ident is not None and (ident != self._ident or st.st_size < self._pos):
            # 새 게임 실행으로 latest.log 가 교체·재생성됨 → 처음부터
            self._pos, self._buf = 0, b""
        self._ident = ident
        if st.st_size <= self._pos:
            return
        try:
            with open(self.path, "rb") as f:
                f.seek(self._pos)
                chunk = f.read()
        except OSError:
            return
        self._pos += len(chunk)
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            self.callback(raw.rstrip(b"\r").decode("utf-8", errors="replace"))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:  # noqa: BLE001 — 콜백 오류로 따라 읽기가 죽지 않게
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)


def tail_log(instance_dir: str | os.PathLike, callback: LogCallback, *, from_start: bool = False,
             interval: float = 0.5, start: bool = True) -> LogTail:
    """인스턴스의 logs/latest.log 를 따라 읽어 새 줄을 callback 으로 넘긴다.

    파일이 아직 없으면 생길 때까지 기다리고, 교체·재생성되면 처음부터 다시 읽는다.
    from_start=False 면 지금 있는 내용은 건너뛴다. 반환된 핸들의 stop() 으로 멈춘다.
    """
    path = _guard_path(Path(instance_dir) / "logs" / "latest.log")
    tail = LogTail(path, callback, from_start, interval)
    if start:
        tail.thread.start()
    return tail


__all__ = [
    "OfficialLauncherError", "is_installed", "install", "register_instance", "unregister_instance",
    "open_launcher", "tail_log", "LogTail", "find_minecraft_dir", "minecraft_dir_candidates",
    "backup_profiles", "launcher_running", "profile_key", "registered_profile", "registered_ids",
]
