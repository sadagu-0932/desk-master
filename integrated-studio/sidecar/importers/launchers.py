"""다른 런처의 인스턴스 감지(읽기 전용).

지원: Prism Launcher / MultiMC, CurseForge, Modrinth App, 공식 런처, 폴더 직접 선택.
형식 확인(2026-11):
- Prism/MultiMC: instance.cfg([General] name·JvmArgs·MaxMemAlloc·OverrideMemory·lastLaunchTime(ms)),
  mmc-pack.json components(uid·version). 게임 폴더는 .minecraft 또는 minecraft.
  Prism 데이터 폴더의 prismlauncher.cfg InstanceDir 로 인스턴스 위치를 바꿀 수 있다.
- CurseForge: <Instances>/<이름>/minecraftinstance.json — name, gameVersion, baseModLoader{name "fabric-0.16.9-1.21.4",
  minecraftVersion, forgeVersion}, allocatedMemory, javaArgsOverride, lastPlayed.
- Modrinth App(%APPDATA%\\ModrinthApp): app.db(SQLite). 2026-06 이후 instances(path·name·last_played·applied_content_set_id)
  + instance_content_sets(game_version·loader·loader_version) + instance_launch_overrides(overrides JSON: memory.maximum,
  extra_launch_args). 그 전 버전은 profiles 표(path·name·game_version·mod_loader·mod_loader_version·last_played).
  프로필 폴더 = <settings.custom_dir 또는 앱 폴더>/profiles/<path>. (modrinth/code packages/app-lib 소스로 확인)
- 공식 런처: launcher_profiles.json profiles{lastVersionId, gameDir, name, javaArgs, lastUsed}.

모르는 필드는 무시하고, 파일 하나가 깨져도 그 항목만 건너뛴다.
계정·로그인·토큰 파일(accounts.json, launcher_accounts*.json, launcher_msa_credentials* 등)은 열지 않는다.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

LAUNCHER_NAMES = {"prism": "Prism Launcher", "multimc": "MultiMC", "curseforge": "CurseForge",
                  "modrinth": "Modrinth App", "official": "공식 런처", "folder": "폴더"}
# 열지도, 복사하지도 않는 파일(이름 패턴)
ACCOUNT_FILE = re.compile(r"^(accounts\.json|launcher_accounts.*\.json|launcher_msa_credentials.*|"
                          r".*\.(token|msa)|msa_.*|authlib.*\.json|cf_auth.*|modrinth_auth.*)$", re.I)
OWN_PROFILE_PREFIX = "integrated-studio-"


def is_account_file(p: Path | str) -> bool:
    return bool(ACCOUNT_FILE.match(Path(p).name))


def _read_text(p: Path) -> str:
    if is_account_file(p):
        raise PermissionError(f"계정 파일은 읽지 않습니다: {p.name}")
    return p.read_text("utf-8", errors="replace")


def _read_json(p: Path) -> Any:
    return json.loads(_read_text(p))


# ---------------------------------------------------------------- 기본 위치

def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def default_roots() -> dict[str, list[Path]]:
    """런처별 찾을 위치. Windows 기준(다른 OS 는 환경 변수가 있을 때만)."""
    appdata = _env_path("APPDATA")
    home = _env_path("USERPROFILE") or (Path.home() if sys.platform == "win32" else None)
    local = _env_path("LOCALAPPDATA")
    roots: dict[str, list[Path]] = {"prism": [], "multimc": [], "curseforge": [], "modrinth": [], "official": []}
    if appdata:
        roots["prism"].append(appdata / "PrismLauncher")
        roots["modrinth"].append(appdata / "ModrinthApp")
        roots["official"].append(appdata / ".minecraft")
    if local:
        roots["official"].append(local / "Packages" / "Microsoft.4297127D64EC6_8wekyb3d8bbwe" / "LocalCache" / "Roaming" / ".minecraft")
    if home:
        roots["curseforge"].append(home / "curseforge" / "minecraft" / "Instances")
        for d in ("MultiMC", "Downloads/MultiMC", "Desktop/MultiMC", "Documents/MultiMC"):
            roots["multimc"].append(home / d)
    roots["multimc"].append(Path("C:/MultiMC"))
    extra = os.environ.get("INTEGRATED_STUDIO_MULTIMC_DIR")
    if extra:
        roots["multimc"].insert(0, Path(extra))
    return roots


# ---------------------------------------------------------------- 공통 정보

def _count_mods(game: Path | None) -> int:
    if not game or not (game / "mods").is_dir():
        return 0
    return sum(1 for p in (game / "mods").iterdir() if p.is_file() and p.suffix == ".jar")


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _parse_iso(s: Any) -> str | None:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.year < 2000:
            return None
        return dt.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return None


def _entry(launcher: str, name: str, root: Path, game: Path | None, version: str | None, loader: str,
           loader_version: str | None = None, last_played: str | None = None, memory_mb: int | None = None,
           java_args: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "launcher": launcher, "launcherName": LAUNCHER_NAMES[launcher], "name": name,
        "source": str(root), "gameDir": str(game) if game else None, "version": version,
        "loader": loader, "loaderVersion": loader_version, "mods": _count_mods(game),
        "lastPlayed": last_played, "memoryMb": memory_mb, "javaArgs": (java_args or "").strip() or None,
        "supported": bool(version and game), **extra,
    }


# ---------------------------------------------------------------- Prism / MultiMC

PRISM_COMPONENTS = [
    ("net.fabricmc.fabric-loader", "fabric"), ("org.quiltmc.quilt-loader", "quilt"),
    ("net.neoforged", "neoforge"), ("net.minecraftforge", "forge"),
]


def _cfg(p: Path) -> dict[str, str]:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # 대소문자 유지
    try:
        text = _read_text(p)
        if not text.lstrip().startswith("["):
            text = "[General]\n" + text
        cp.read_string(text)
    except (configparser.Error, OSError):
        return {}
    out: dict[str, str] = {}
    for sec in cp.sections():
        out.update({k: v for k, v in cp.items(sec)})
    return out


def read_prism_instance(folder: Path, launcher: str = "prism") -> dict[str, Any] | None:
    pack = folder / "mmc-pack.json"
    if not pack.is_file():
        return None
    try:
        comps = {c.get("uid"): c.get("version") for c in _read_json(pack).get("components", []) if isinstance(c, dict)}
    except (json.JSONDecodeError, OSError, AttributeError):
        return None
    loader, lver = "vanilla", None
    for uid, name in PRISM_COMPONENTS:
        if uid in comps:
            loader, lver = name, comps[uid]
            break
    cfg = _cfg(folder / "instance.cfg") if (folder / "instance.cfg").is_file() else {}
    game = next((folder / d for d in (".minecraft", "minecraft") if (folder / d).is_dir()), None)
    mem = None
    if cfg.get("OverrideMemory", "false").lower() == "true":
        try:
            mem = int(cfg.get("MaxMemAlloc", "0")) or None
        except ValueError:
            mem = None
    java = cfg.get("JvmArgs") if cfg.get("OverrideJavaArgs", "true").lower() == "true" else None
    last = None
    try:
        last = _iso(int(cfg.get("lastLaunchTime", "0")) / 1000)
    except ValueError:
        pass
    # 그 런처로 바로 실행할 때 쓸 정보: 데이터 폴더(prismlauncher.cfg·multimc.cfg 가 있는 곳)와 인스턴스 id(폴더 이름)
    root = guess_launcher_root(folder)
    return _entry(launcher, cfg.get("name") or folder.name, folder, game, comps.get("net.minecraft"), loader, lver,
                  last, mem, java, launcherInstanceId=folder.name, launcherRoot=str(root) if root else None)


def guess_launcher_root(instance_folder: Path) -> Path | None:
    """인스턴스 폴더에서 Prism·MultiMC 데이터 폴더를 찾는다(보통 <데이터>/instances/<인스턴스>)."""
    for cand in (instance_folder.parent.parent, instance_folder.parent):
        if any((cand / n).is_file() for n in ("prismlauncher.cfg", "multimc.cfg", "accounts.json")) or \
                any((cand / n).is_file() for n in ("prismlauncher.exe", "MultiMC.exe", "multimc.exe")):
            return cand
    return None


def _prism_instance_dirs(root: Path) -> list[Path]:
    """Prism·MultiMC 데이터 폴더 → 인스턴스 폴더(설정 InstanceDir 반영)."""
    dirs = []
    for cfg_name in ("prismlauncher.cfg", "multimc.cfg"):
        cfg = root / cfg_name
        if cfg.is_file():
            inst = _cfg(cfg).get("InstanceDir")
            if inst:
                p = Path(inst)
                dirs.append(p if p.is_absolute() else root / p)
    dirs.append(root / "instances")
    seen, out = set(), []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen and d.is_dir():
            seen.add(key)
            out.append(d)
    return out


def detect_prism(roots: Iterable[Path], launcher: str = "prism") -> list[dict[str, Any]]:
    out = []
    for root in roots:
        for idir in _prism_instance_dirs(root) if root.is_dir() else []:
            for folder in sorted(idir.iterdir()):
                if folder.is_dir() and not folder.name.startswith(("_", ".")):
                    e = read_prism_instance(folder, launcher)
                    if e:
                        e["launcherRoot"] = str(root)
                        out.append(e)
    return out


# ---------------------------------------------------------------- CurseForge

def read_cf_instance(folder: Path) -> dict[str, Any] | None:
    f = folder / "minecraftinstance.json"
    if not f.is_file():
        return None
    try:
        d = _read_json(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(d, dict):
        return None
    base = d.get("baseModLoader") or {}
    version = d.get("gameVersion") or base.get("minecraftVersion")
    loader, lver = "vanilla", None
    lname = str(base.get("name") or "")
    m = re.match(r"(fabric|quilt|neoforge|forge)-(.+)", lname, re.I)
    if m:
        loader = m.group(1).lower()
        lver = m.group(2)
        if version and lver.endswith("-" + version):          # "fabric-0.16.9-1.21.4" → 0.16.9
            lver = lver[: -len(version) - 1]
    elif base.get("forgeVersion"):
        loader, lver = {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}.get(base.get("type"), "forge"), base["forgeVersion"]
    mem = d.get("allocatedMemory") if isinstance(d.get("allocatedMemory"), int) and d.get("allocatedMemory") > 0 else None
    return _entry("curseforge", d.get("name") or folder.name, folder, folder, version, loader, lver,
                  _parse_iso(d.get("lastPlayed")), mem, d.get("javaArgsOverride"))


def detect_curseforge(roots: Iterable[Path]) -> list[dict[str, Any]]:
    out = []
    for root in roots:
        if root.is_dir():
            for folder in sorted(root.iterdir()):
                if folder.is_dir():
                    e = read_cf_instance(folder)
                    if e:
                        out.append(e)
    return out


# ---------------------------------------------------------------- Modrinth App

def _sqlite_snapshot(db: Path) -> tuple[sqlite3.Connection, Path]:
    """앱이 켜져 있어도 읽을 수 있게 db(와 -wal)를 임시 폴더에 복사해서 연다(원본은 건드리지 않음)."""
    tmp = Path(tempfile.mkdtemp(prefix="is-mr-"))
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(db) + suffix)
        if src.is_file():
            shutil.copy2(src, tmp / ("app.db" + suffix))
    con = sqlite3.connect(f"file:{tmp / 'app.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    return con, tmp


def _close(con: sqlite3.Connection, tmp: Path) -> None:
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _mr_ts(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return _iso(v / 1000 if v > 1e11 else v)
    return _parse_iso(str(v))


def detect_modrinth(roots: Iterable[Path]) -> list[dict[str, Any]]:
    out = []
    for root in roots:
        db = root / "app.db"
        if not db.is_file():
            continue
        try:
            con, tmp = _sqlite_snapshot(db)
        except (sqlite3.Error, OSError):
            continue
        try:
            tables = _tables(con)
            base = root
            if "settings" in tables:
                try:
                    row = con.execute("SELECT custom_dir FROM settings LIMIT 1").fetchone()
                    if row and row[0]:
                        base = Path(row[0])
                except sqlite3.Error:
                    pass
            profiles = base / "profiles"
            rows: list[dict[str, Any]] = []
            if "instances" in tables and "instance_content_sets" in tables:
                q = """SELECT i.id, i.path, i.name, i.last_played, c.game_version, c.loader, c.loader_version
                       FROM instances i LEFT JOIN instance_content_sets c ON c.id = i.applied_content_set_id"""
                overrides = {}
                if "instance_launch_overrides" in tables:
                    for r in con.execute("SELECT instance_id, overrides FROM instance_launch_overrides"):
                        try:
                            overrides[r[0]] = json.loads(r[1]) if isinstance(r[1], str) else {}
                        except (json.JSONDecodeError, TypeError):
                            pass
                for r in con.execute(q):
                    o = overrides.get(r["id"], {})
                    rows.append({"path": r["path"], "name": r["name"], "last": r["last_played"],
                                 "version": r["game_version"], "loader": r["loader"], "lver": r["loader_version"],
                                 "mem": (o.get("memory") or {}).get("maximum"), "args": " ".join(o.get("extra_launch_args") or [])})
            elif "profiles" in tables:
                cols = {c[1] for c in con.execute("PRAGMA table_info(profiles)")}
                for r in con.execute("SELECT * FROM profiles"):
                    r = dict(r)
                    args = r.get("override_extra_launch_args") if "override_extra_launch_args" in cols else None
                    try:
                        args = " ".join(json.loads(args)) if args else None
                    except (json.JSONDecodeError, TypeError):
                        args = None
                    rows.append({"path": r.get("path"), "name": r.get("name"), "last": r.get("last_played"),
                                 "version": r.get("game_version"), "loader": r.get("mod_loader"), "lver": r.get("mod_loader_version"),
                                 "mem": r.get("override_mc_memory_max"), "args": args})
            for r in rows:
                if not r["path"]:
                    continue
                folder = profiles / r["path"]
                loader = (r["loader"] or "vanilla").lower()
                loader = {"neo_forge": "neoforge"}.get(loader, loader)
                out.append(_entry("modrinth", r["name"] or r["path"], folder, folder if folder.is_dir() else None,
                                  r["version"], loader, r["lver"], _mr_ts(r["last"]),
                                  int(r["mem"]) if r.get("mem") else None, r.get("args")))
        except sqlite3.Error:
            pass
        finally:
            _close(con, tmp)
    return out


# ---------------------------------------------------------------- 공식 런처

def _official_loader(mc_dir: Path, version_id: str) -> tuple[str | None, str, str | None]:
    """lastVersionId → (게임 버전, 로더, 로더 버전). versions/<id>/<id>.json 의 inheritsFrom 을 본다."""
    vid = version_id
    m = re.match(r"fabric-loader-([^-]+)-(.+)$", vid)
    if m:
        return m.group(2), "fabric", m.group(1)
    m = re.match(r"quilt-loader-([^-]+)-(.+)$", vid)
    if m:
        return m.group(2), "quilt", m.group(1)
    m = re.match(r"neoforge-(.+)$", vid)
    vj = mc_dir / "versions" / vid / f"{vid}.json"
    parent = None
    if vj.is_file():
        try:
            parent = _read_json(vj).get("inheritsFrom")
        except (json.JSONDecodeError, OSError, AttributeError):
            parent = None
    if m:
        return parent, "neoforge", m.group(1)
    m = re.match(r"(.+?)-forge-(.+)$", vid)
    if m:
        return m.group(1), "forge", m.group(2)
    return (parent or vid), "vanilla", None


def detect_official(roots: Iterable[Path]) -> list[dict[str, Any]]:
    out = []
    for mc in roots:
        f = mc / "launcher_profiles.json"
        if not f.is_file():
            continue
        try:
            profiles = (_read_json(f) or {}).get("profiles") or {}
        except (json.JSONDecodeError, OSError, AttributeError):
            continue
        for key, p in profiles.items():
            if not isinstance(p, dict) or key.startswith(OWN_PROFILE_PREFIX):
                continue
            vid = str(p.get("lastVersionId") or "")
            if p.get("type") in ("latest-release", "latest-snapshot") or vid in ("latest-release", "latest-snapshot"):
                version, loader, lver = None, "vanilla", None
                name = p.get("name") or ("최신 릴리스" if "release" in (p.get("type") or vid) else "최신 스냅숏")
                note = "최신 버전 항목이라 버전을 직접 골라야 합니다."
            else:
                version, loader, lver = _official_loader(mc, vid)
                name = p.get("name") or vid
                note = None
            game = Path(p["gameDir"]) if p.get("gameDir") else mc
            mem = None
            m = re.search(r"-Xmx(\d+)([GgMm])", p.get("javaArgs") or "")
            if m:
                mem = int(m.group(1)) * (1024 if m.group(2).lower() == "g" else 1)
            installed = bool(vid) and (mc / "versions" / vid / f"{vid}.json").is_file()
            e = _entry("official", name, game, game if game.is_dir() else None, version, loader, lver,
                       _parse_iso(p.get("lastUsed")), mem, p.get("javaArgs"), profileKey=key, versionId=vid,
                       officialInstalled=installed)
            if note:
                e["note"] = note
                e["supported"] = False
            out.append(e)
    return out


# ---------------------------------------------------------------- 전체·폴더

def detect_all(roots: dict[str, list[Path]] | None = None) -> list[dict[str, Any]]:
    roots = roots or default_roots()
    found: list[dict[str, Any]] = []
    for fn, key in ((lambda r: detect_prism(r, "prism"), "prism"), (lambda r: detect_prism(r, "multimc"), "multimc"),
                    (detect_curseforge, "curseforge"), (detect_modrinth, "modrinth"), (detect_official, "official")):
        try:
            found += fn([Path(p) for p in roots.get(key, [])])
        except OSError:
            continue
    # 같은 게임 폴더가 두 번 잡히면(예: Prism 과 MultiMC 같은 폴더) 하나만
    seen, out = set(), []
    for e in found:
        k = (e["launcher"] in ("prism", "multimc"), e.get("gameDir") or e["source"], e.get("profileKey"))
        if k in seen:
            continue
        seen.add(k)
        e["key"] = f"{e['launcher']}:{e.get('profileKey') or e['source']}"
        out.append(e)
    out.sort(key=lambda e: e.get("lastPlayed") or "", reverse=True)
    return out


_LOG_PATTERNS = [
    (re.compile(r"Loading Minecraft (\S+) with Fabric Loader (\S+)"), "fabric"),
    (re.compile(r"Loading Minecraft (\S+) with Quilt Loader (\S+)"), "quilt"),
]


def version_from_logs(game: Path) -> tuple[str | None, str, str | None]:
    """게임 폴더의 로그로 (게임 버전, 로더, 로더 버전)을 알아낸다. 모르면 (None, "vanilla", None)."""
    texts = []
    for f in (game / "logs" / "latest.log", game / "logs" / "debug.log"):
        try:
            if f.is_file():
                texts.append(f.read_bytes()[:400_000].decode("utf-8", "replace"))
        except OSError:
            continue
    text = "\n".join(texts)
    for rx, loader in _LOG_PATTERNS:
        m = rx.search(text)
        if m:
            return m.group(1), loader, m.group(2)
    mc = re.search(r"--fml\.mcVersion,? (\S+?)[,\s\]]", text)
    nf = re.search(r"--fml\.neoForgeVersion,? (\S+?)[,\s\]]", text)
    fg = re.search(r"--fml\.forgeVersion,? (\S+?)[,\s\]]", text)
    if mc and nf:
        return mc.group(1), "neoforge", nf.group(1)
    if mc and fg:
        return mc.group(1), "forge", fg.group(1)
    m = re.search(r"Minecraft Version:? (\d+\.\d+(?:\.\d+)?)", text) or re.search(r"Starting minecraft (?:client|server) version (\S+)", text)
    if m:
        return m.group(1), "vanilla", None
    return None, "vanilla", None


def inspect_folder(path: Path) -> list[dict[str, Any]]:
    """직접 고른 폴더: 인스턴스 하나, 또는 인스턴스들이 든 폴더. 어느 런처 것이든(또는 그냥 게임 폴더) 알아본다."""
    path = Path(path)
    if not path.is_dir():
        return []
    # Prism·MultiMC 인스턴스 안의 게임 폴더(.minecraft / minecraft)를 고른 경우 → 인스턴스로
    if path.name in (".minecraft", "minecraft") and (path.parent / "mmc-pack.json").is_file():
        path = path.parent
    # Modrinth App 프로필 폴더 하나(<앱>/profiles/<이름>)
    if path.parent.name == "profiles" and (path.parent.parent / "app.db").is_file():
        hits = [e for e in detect_modrinth([path.parent.parent]) if Path(e["source"]).resolve() == path.resolve()]
        if hits:
            return [{**hits[0], "key": f"modrinth:{hits[0]['source']}"}]
    for reader in (read_prism_instance, read_cf_instance):
        e = reader(path)
        if e:
            e["key"] = f"{e['launcher']}:{e['source']}"
            return [e]
    if (path / "launcher_profiles.json").is_file():
        return [{**e, "key": f"official:{e.get('profileKey')}"} for e in detect_official([path])]
    if (path / "app.db").is_file():
        return [{**e, "key": f"modrinth:{e['source']}"} for e in detect_modrinth([path])]
    # 인스턴스들이 든 폴더?
    many = detect_prism([path.parent], "prism") if path.name == "instances" else []
    if not many:
        for sub in sorted(p for p in path.iterdir() if p.is_dir()):
            for reader in (read_prism_instance, read_cf_instance):
                e = reader(sub)
                if e:
                    many.append(e)
                    break
    if many:
        for e in many:
            e["key"] = f"{e['launcher']}:{e['source']}"
        return many
    # 그냥 게임 폴더(.minecraft 같은): 로그에서 버전을 찾고, 없으면 사용자가 고른다
    game = path / ".minecraft" if (path / ".minecraft").is_dir() else path
    if any((game / d).exists() for d in ("mods", "saves", "options.txt", "resourcepacks", "logs")):
        version, loader, lver = version_from_logs(game)
        e = _entry("folder", path.name, path, game, version, loader, lver)
        if not version:
            e["supported"] = False
            e["note"] = "게임 버전을 로그에서 찾지 못해 직접 골라야 합니다."
        e["key"] = f"folder:{path}"
        return [e]
    return []


def entry_size(e: dict[str, Any], items: Iterable[str]) -> dict[str, int]:
    """옮길 항목별 용량(바이트). 계정 파일은 세지 않는다."""
    game = Path(e["gameDir"]) if e.get("gameDir") else None
    sizes: dict[str, int] = {}
    if not game:
        return sizes
    for name in items:
        p = game / name
        if p.is_file() and not is_account_file(p):
            sizes[name] = p.stat().st_size
        elif p.is_dir():
            total = 0
            for f in p.rglob("*"):
                try:
                    if f.is_file() and not is_account_file(f):
                        total += f.stat().st_size
                except OSError:
                    continue
            sizes[name] = total
    return sizes


def now() -> float:
    return time.time()
