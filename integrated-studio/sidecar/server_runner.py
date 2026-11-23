"""M10 서버 열기 — 사이드카 쪽.

1) 방식 A 전용 서버(ServerRunner): 바닐라 서버 jar 또는 Fabric 서버 런처. 인스턴스마다 여러 개를 동시에.
   서버 폴더: data/instances/<인스턴스>/servers/<서버id>/ (server.json · server.properties · eula.txt · world/ · mods/ · logs/)
   - 서버 jar 는 버전 json 의 downloads.server(바닐라), Fabric 은 meta.fabricmc.net 서버 런처. data/server-jars/ 에 모아 둔다.
   - EULA 는 앱의 동의 창에서 사용자가 직접 동의해야 true 가 된다(자동 동의 금지).
   - server.properties 기본값: 빈 포트 자동, online-mode 선택. server-ip 는 비운다(UPnP 로 들어오는 공유기 연결을 받으려면
     LAN 주소에서도 들어와야 한다. playit 은 127.0.0.1 로 들어온다).
   - 로그 "Done (…)! For help, type" 을 보고 준비 완료를 알린다(앱이 그때 주소를 연다).
   - Fabric 서버면 인스턴스 mods/ 에서 서버에서도 도는 모드(environment != client)를 서버 mods/ 로 복사한다.
2) 모드 분석: 참가자도 같은 모드가 필요한지(fabric.mod.json·quilt.mod.json·mods.toml).
3) e4mc(방식 B 싱글 LAN 공개를 인터넷 주소로): modrinth.py 로 버전·로더에 정확히 맞는 파일만, 26.1+ Fabric 은 modern.
   끌 때는 .disabled 로 이름만 바꾼다(삭제 금지). 충돌 후보 모드 경고, e4mc 탓으로 보이는 크래시면 다음부터 자동으로 끈다.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import socket
import sys
import subprocess
import threading
import time
import tomllib
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

import modrinth
from instances import InstanceStore
from paths import safe_join
from rpc import RpcError, notify

EULA_URL = "https://aka.ms/MinecraftEULA"
DONE_RE = re.compile(r'Done \([0-9.,]+s\)! For help, type')
JOIN_RE = re.compile(r"\]: (\S+) joined the game")
LEFT_RE = re.compile(r"\]: (\S+) left the game")
SID_RE = re.compile(r"srv_[0-9a-f]{8}")
FABRIC_META = "https://meta.fabricmc.net/v2"
UA = {"User-Agent": "integrated-studio/0.1 (personal launcher)"}
MODS_CONFIG = Path(__file__).resolve().parent / "server_host_mods.json"
DEDICATED_LOADERS = ("vanilla", "fabric", "neoforge", "forge")
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
LOADER_NAMES = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric", "vanilla": "바닐라"}
E4MC_PROJECT = "e4mc"
E4MC_IDS = {"e4mc", "e4mc_minecraft"}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def port_free(port: int) -> bool:
    """그 포트를 아무도 안 쓰는지. Windows 는 127.0.0.1 에 다른 프로그램이 듣고 있어도 0.0.0.0 묶기가 성공하므로
    실제로 접속해 보는 것까지 확인한다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
        c.settimeout(0.5)
        if c.connect_ex(("127.0.0.1", port)) == 0:
            return False
    for host in ("0.0.0.0", "127.0.0.1"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                return False
    return True


def _http_json(url: str) -> Any:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def _download(url: str, dest: Path, sha1: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    if sha1 and modrinth.file_hashes(tmp, ("sha1",))["sha1"] != sha1.lower():
        tmp.unlink(missing_ok=True)
        raise RpcError(f"받은 서버 jar 의 해시가 맞지 않아 버렸습니다: {dest.name}")
    tmp.replace(dest)


def neoforge_prefix(mc: str) -> str:
    """NeoForge 버전은 마인크래프트 버전 세 자리 + 빌드(26.3 → 26.3.0.x, 26.1.2 → 26.1.2.x).
    1.x 시절은 앞의 '1.' 을 뺀 형식(1.21.1 → 21.1.x). (maven.neoforged.net 메타데이터로 확인, 2026-11)"""
    parts = mc.split(".")
    old = parts[0] == "1"
    if old:
        parts = parts[1:]
    while len(parts) < (2 if old else 3):
        parts.append("0")
    return ".".join(parts) + "."


def _vkey(v: str) -> list[int]:
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", v)]


def neoforge_versions(mc: str) -> list[dict[str, Any]]:
    """그 게임 버전용 NeoForge 버전들(새 것부터) [{version, stable}]."""
    with urllib.request.urlopen(urllib.request.Request(f"{NEOFORGE_MAVEN}/maven-metadata.xml", headers=UA), timeout=30) as r:
        xml = r.read().decode("utf-8", "replace")
    prefix = neoforge_prefix(mc)
    vs = sorted((v for v in re.findall(r"<version>([^<]+)</version>", xml) if v.startswith(prefix)), key=_vkey, reverse=True)
    return [{"version": v, "stable": "beta" not in v and "alpha" not in v} for v in vs]


def write_properties(path: Path, values: dict[str, Any]) -> None:
    """server.properties 를 고친다(있는 다른 값은 유지)."""
    lines = path.read_text("utf-8").splitlines() if path.is_file() else ["#Minecraft server properties (통합 작업실)"]
    keys = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()}
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.lstrip().startswith("#") else None
        if k in keys:
            out.append(f"{k}={keys[k]}")
            seen.add(k)
        else:
            out.append(ln)
    out += [f"{k}={v}" for k, v in keys.items() if k not in seen]
    path.write_text("\n".join(out) + "\n", "utf-8")


def read_properties(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return {ln.split("=", 1)[0].strip(): ln.split("=", 1)[1].strip()
            for ln in path.read_text("utf-8").splitlines() if "=" in ln and not ln.lstrip().startswith("#")}


def _trash(p: Path, base: Path) -> None:
    from paths import trash
    trash(p, base)


# ================================================================ 모드 분석

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


# ================================================================ 방식 A 전용 서버

class ServerRunner:
    def __init__(self, data_dir: Path, store: InstanceStore, java_cmd: Callable[[str], list[str]],
                 emit: Callable[[str, dict], None] = notify):
        """java_cmd(version) → 자바 실행 명령 앞부분(예: ["C:/.../java.exe"]). emit = 사이드카 알림."""
        self.data_dir = Path(data_dir)
        self.store = store
        self.java_cmd = java_cmd
        self.emit = emit
        self.jars_dir = self.data_dir / "server-jars"
        self.procs: dict[str, subprocess.Popen] = {}
        self.players: dict[str, set[str]] = {}
        self.ready: dict[str, bool] = {}
        self.lock = threading.Lock()
        self._current = ""

    # ---------- 폴더·설정 ----------
    def _sdir(self, inst_id: str, sid: str) -> Path:
        if not SID_RE.fullmatch(sid or ""):
            raise RpcError(f"잘못된 서버 id 입니다: {sid}")
        return safe_join(self.store.dir_of(inst_id), "servers", sid)

    def _meta(self, inst_id: str, sid: str) -> dict[str, Any]:
        f = self._sdir(inst_id, sid) / "server.json"
        if not f.is_file():
            raise RpcError("서버를 찾을 수 없습니다.")
        return json.loads(f.read_text("utf-8"))

    def _save(self, inst_id: str, meta: dict[str, Any]) -> None:
        d = self._sdir(inst_id, meta["id"])
        (d / "server.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")

    def list(self, id: str) -> list[dict[str, Any]]:
        base = self.store.dir_of(id) / "servers"
        out = []
        if base.is_dir():
            for d in sorted(base.iterdir()):
                f = d / "server.json"
                if f.is_file():
                    m = json.loads(f.read_text("utf-8"))
                    out.append({**m, **self._state(m["id"], d)})
        return out

    def list_all(self) -> list[dict[str, Any]]:
        out = []
        for inst in self.store.list():
            try:
                out += self.list(inst["id"])
            except RpcError:
                continue
        return out

    def _state(self, sid: str, d: Path) -> dict[str, Any]:
        proc = self.procs.get(sid)
        running = bool(proc and proc.poll() is None)
        return {"running": running, "ready": running and self.ready.get(sid, False),
                "players": sorted(self.players.get(sid, set())), "needsEula": not self._eula_ok(d),
                "port": int(read_properties(d / "server.properties").get("server-port", "0") or 0),
                "maxPlayers": int(read_properties(d / "server.properties").get("max-players", "10") or 10)}

    @staticmethod
    def _eula_ok(d: Path) -> bool:
        f = d / "eula.txt"
        return f.is_file() and bool(re.search(r"^\s*eula\s*=\s*true\s*$", f.read_text("utf-8"), re.M))

    def create(self, id: str, name: str, online_mode: bool = True, world: str | None = None,
               max_players: int = 10) -> dict[str, Any]:
        meta_i = self.store.get(id)
        loader = meta_i.get("loader", "vanilla")
        if loader not in DEDICATED_LOADERS:
            raise RpcError(f"전용 서버는 바닐라·Fabric·NeoForge·Forge 인스턴스만 됩니다({loader}). 싱글 LAN 공개를 쓰세요.")
        name = (name or "").strip() or f"{meta_i['name']} 서버"
        if world:  # 만들기 전에 월드부터 확인(실패해도 빈 서버 폴더가 남지 않게)
            w = safe_join(self.store.game_dir(id), "saves", world)
            if not (w / "level.dat").is_file():
                raise RpcError(f"월드를 찾을 수 없습니다: {world}")
        sid = "srv_" + uuid.uuid4().hex[:8]
        d = self._sdir(id, sid)
        d.mkdir(parents=True)
        meta = {"id": sid, "name": name[:60], "instanceId": id, "version": meta_i["version"],
                "loader": loader, "loaderVersion": meta_i.get("loaderVersion"),
                "onlineMode": bool(online_mode), "world": None, "created": time.time()}
        self._save(id, meta)
        write_properties(d / "server.properties", {
            "server-ip": "", "server-port": free_port(), "online-mode": bool(online_mode),
            "motd": name[:59], "max-players": int(max_players), "level-name": "world",
            "enable-query": False, "enable-rcon": False, "white-list": False,
        })
        if world:
            self.set_world(id, sid, world)
        return {**self._meta(id, sid), **self._state(sid, d), "eulaUrl": EULA_URL}

    def set_world(self, id: str, sid: str, world: str) -> dict[str, Any]:
        """인스턴스의 월드를 서버 월드로 복사한다(원본은 그대로)."""
        if sid in self.procs and self.procs[sid].poll() is None:
            raise RpcError("서버를 멈춘 뒤 월드를 바꾸세요.")
        src = safe_join(self.store.game_dir(id), "saves", world)
        if not (src / "level.dat").is_file():
            raise RpcError(f"월드를 찾을 수 없습니다: {world}")
        d = self._sdir(id, sid)
        dst = d / "world"
        if dst.exists():
            _trash(dst, self.store.dir_of(id))
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("session.lock"))
        meta = self._meta(id, sid)
        meta["world"] = world
        self._save(id, meta)
        return {"world": world, "path": str(dst)}

    def update(self, id: str, sid: str, name: str | None = None, online_mode: bool | None = None) -> dict[str, Any]:
        meta = self._meta(id, sid)
        d = self._sdir(id, sid)
        props: dict[str, Any] = {}
        if name:
            meta["name"] = name.strip()[:60]
            props["motd"] = meta["name"][:59]
        if online_mode is not None:
            meta["onlineMode"] = bool(online_mode)
            props["online-mode"] = bool(online_mode)
        self._save(id, meta)
        if props:
            write_properties(d / "server.properties", props)
        return {**meta, **self._state(sid, d)}

    def accept_eula(self, id: str, sid: str) -> dict[str, Any]:
        """앱의 EULA 동의 창에서 사용자가 '동의'를 눌렀을 때만 부른다."""
        d = self._sdir(id, sid)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        (d / "eula.txt").write_text(
            f"# 사용자가 통합 작업실의 동의 창에서 마인크래프트 EULA({EULA_URL})를 읽고 동의함 ({stamp})\n"
            "eula=true\n", "utf-8")
        return {"ok": True}

    def delete(self, id: str, sid: str) -> dict[str, Any]:
        if sid in self.procs and self.procs[sid].poll() is None:
            raise RpcError("실행 중인 서버는 지울 수 없습니다. 먼저 멈추세요.")
        _trash(self._sdir(id, sid), self.store.dir_of(id))
        return {"ok": True}

    def mods(self, id: str, sid: str | None = None) -> dict[str, Any]:
        """참가자도 필요한 모드 목록(전용 서버는 서버 mods/, 아니면 인스턴스 mods/)."""
        mods_dir = (self._sdir(id, sid) / "mods") if sid else (self.store.game_dir(id) / "mods")
        return {"clientRequired": client_required_mods(mods_dir)}

    # ---------- jar ----------
    def _vanilla_jar(self, version: str) -> Path:
        dest = self.jars_dir / version / "server.jar"
        if dest.is_file():
            return dest
        vfile = self.data_dir / "minecraft" / "versions" / version / f"{version}.json"
        if vfile.is_file():
            vjson = json.loads(vfile.read_text("utf-8"))
        else:
            manifest = _http_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            url = next((v["url"] for v in manifest["versions"] if v["id"] == version), None)
            if not url:
                raise RpcError(f"{version} 버전을 찾을 수 없습니다.")
            vjson = _http_json(url)
        server = vjson.get("downloads", {}).get("server")
        if not server:
            raise RpcError(f"{version} 에는 서버 jar 가 없습니다.")
        self.emit("ds_log", {"id": self._current, "line": f"[통합 작업실] {version} 서버 jar 받는 중"})
        _download(server["url"], dest, server.get("sha1"))
        return dest

    def _fabric_launcher(self, version: str, loader_version: str | None) -> Path:
        loaders = _http_json(f"{FABRIC_META}/versions/loader/{version}")
        if not loaders:
            raise RpcError(f"{version} 용 Fabric 로더가 없습니다.")
        lv = loader_version or loaders[0]["loader"]["version"]
        installers = _http_json(f"{FABRIC_META}/versions/installer")
        iv = next((i["version"] for i in installers if i.get("stable")), installers[0]["version"])
        dest = self.jars_dir / f"fabric-server-{version}-{lv}-{iv}.jar"
        if not dest.is_file():
            self.emit("ds_log", {"id": self._current, "line": f"[통합 작업실] Fabric 서버 런처 받는 중({lv})"})
            _download(f"{FABRIC_META}/versions/loader/{version}/{lv}/{iv}/server/jar", dest)
        return dest

    # ---------- Forge 계열(NeoForge·Forge) 서버 ----------
    @staticmethod
    def _neoforge_prefix(mc: str) -> str:
        return neoforge_prefix(mc)

    def _forge_version(self, loader: str, mc: str, wanted: str | None) -> str:
        """실제 설치할 로더 버전(Forge 는 '<mc>-<버전>' 형식으로 돌려준다). 맞는 버전이 없으면 RpcError."""
        if loader == "neoforge":
            prefix = self._neoforge_prefix(mc)
            if wanted:
                if not wanted.startswith(prefix):
                    raise RpcError(f"NeoForge {wanted} 는 {mc} 용이 아닙니다.")
                return wanted
            vs = neoforge_versions(mc)
            pick = [v["version"] for v in vs if v["stable"]] or [v["version"] for v in vs]
            if not pick:
                raise RpcError(f"{mc} 용 NeoForge 가 아직 없습니다.")
            return pick[0]
        if wanted:
            return wanted if wanted.startswith(mc + "-") else f"{mc}-{wanted}"
        promos = _http_json(FORGE_PROMOS).get("promos", {})
        ver = promos.get(f"{mc}-recommended") or promos.get(f"{mc}-latest")
        if not ver:
            raise RpcError(f"{mc} 용 Forge 가 아직 없습니다.")
        return f"{mc}-{ver}"

    def _forge_installer(self, loader: str, full: str) -> Path:
        """설치기 jar 를 받아 메이븐의 .sha256 으로 검증한다(공식 메이븐만)."""
        base = NEOFORGE_MAVEN if loader == "neoforge" else FORGE_MAVEN
        name = f"{'neoforge' if loader == 'neoforge' else 'forge'}-{full}-installer.jar"
        dest = self.jars_dir / loader / name
        url = f"{base}/{full}/{name}"
        with urllib.request.urlopen(urllib.request.Request(url + ".sha256", headers=UA), timeout=30) as r:
            sha256 = r.read().decode("ascii", "replace").strip().split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise RpcError("설치기 검증값(sha256)을 받지 못했습니다.")
        if dest.is_file() and modrinth.file_hashes(dest, ("sha256",))["sha256"] == sha256:
            return dest
        self.emit("ds_log", {"id": self._current, "line": f"[통합 작업실] {LOADER_NAMES[loader]} {full} 서버 설치기 받는 중"})
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        if modrinth.file_hashes(tmp, ("sha256",))["sha256"] != sha256:
            tmp.unlink(missing_ok=True)
            raise RpcError(f"받은 {LOADER_NAMES[loader]} 설치기의 해시가 맞지 않아 버렸습니다.")
        tmp.replace(dest)
        return dest

    @staticmethod
    def forge_args_file(d: Path, loader: str, full: str) -> str:
        """설치 뒤 실행 인자 파일(libraries/.../<버전>/win_args.txt|unix_args.txt) 상대 경로."""
        group = "net/neoforged/neoforge" if loader == "neoforge" else "net/minecraftforge/forge"
        name = "win_args.txt" if sys.platform == "win32" else "unix_args.txt"
        return f"libraries/{group}/{full}/{name}"

    def _run_forge_installer(self, id: str, sid: str, d: Path, version: str, loader: str, installer: Path, full: str) -> None:
        """설치기로 서버 폴더를 만든다(한 번만). NeoForge 는 --install-server, Forge 는 --installServer."""
        marker = d / f".studio-{loader}-{full}"
        if marker.is_file() and (d / self.forge_args_file(d, loader, full)).is_file():
            return
        flag = "--install-server" if loader == "neoforge" else "--installServer"
        self.emit("ds_log", {"id": sid, "line": f"[통합 작업실] {LOADER_NAMES[loader]} 서버 설치 중(처음 한 번, 몇 분 걸릴 수 있음)"})
        proc = subprocess.run([*self.java_cmd(version), "-jar", str(installer), flag, str(d)], cwd=d,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for ln in (proc.stdout or "").splitlines()[-15:]:
            self.emit("ds_log", {"id": sid, "line": ln})
        if proc.returncode != 0 or not (d / self.forge_args_file(d, loader, full)).is_file():
            raise RpcError(f"{LOADER_NAMES[loader]} 서버 설치에 실패했습니다(코드 {proc.returncode}). 콘솔을 확인하세요.")
        marker.write_text(full, "utf-8")

    def _sync_server_mods(self, id: str, d: Path) -> list[str]:
        """인스턴스 mods/ 중 서버에서도 도는 모드를 서버 mods/ 로. 인스턴스에서 빠진 모드는 서버에서도 뺀다(휴지통)."""
        src = self.store.game_dir(id) / "mods"
        dst = d / "mods"
        dst.mkdir(exist_ok=True)
        wanted: dict[str, Path] = {}
        for m in scan_mods(src):
            if m["environment"] != "client" and m["id"] not in E4MC_IDS:
                wanted[m["file"]] = src / m["file"]
        for p in dst.iterdir():
            if p.is_file() and p.suffix == ".jar" and p.name not in wanted:
                _trash(p, self.store.dir_of(id))
        for name, p in wanted.items():
            t = dst / name
            if not t.is_file() or t.stat().st_size != p.stat().st_size:
                shutil.copy2(p, t)
        return sorted(wanted)

    def prepare_jar(self, id: str, sid: str) -> str:
        """실행할 jar(바닐라·Fabric). Forge 계열은 prepare_launch 를 쓴다."""
        args = self.prepare_launch(id, sid)
        return args[args.index("-jar") + 1] if "-jar" in args else args[-2]

    def prepare_launch(self, id: str, sid: str) -> list[str]:
        """java 뒤에 붙일 인자(메모리 제외). 바닐라·Fabric = -jar <jar> nogui, Forge 계열 = @인자파일 nogui."""
        self._current = sid
        meta = self._meta(id, sid)
        d = self._sdir(id, sid)
        loader = meta["loader"]
        if loader in ("neoforge", "forge"):
            full = self._forge_version(loader, meta["version"], meta.get("loaderVersion"))
            installer = self._forge_installer(loader, full)
            self._run_forge_installer(id, sid, d, meta["version"], loader, installer, full)
            copied = self._sync_server_mods(id, d)
            if copied:
                self.emit("ds_log", {"id": sid, "line": f"[통합 작업실] 서버 모드 {len(copied)}개: {', '.join(copied[:8])}"})
            return ["@user_jvm_args.txt", "@" + self.forge_args_file(d, loader, full), "nogui"]
        return ["-jar", self._prepare_plain(id, sid, meta, d), "nogui"]

    def _prepare_plain(self, id: str, sid: str, meta: dict[str, Any], d: Path) -> str:
        vanilla = self._vanilla_jar(meta["version"])
        if not (d / "server.jar").is_file() or (d / "server.jar").stat().st_size != vanilla.stat().st_size:
            shutil.copy2(vanilla, d / "server.jar")
        if meta["loader"] == "fabric":
            launcher = self._fabric_launcher(meta["version"], meta.get("loaderVersion"))
            shutil.copy2(launcher, d / "fabric-server-launch.jar")
            (d / "fabric-server-launcher.properties").write_text("serverJar=server.jar\n", "utf-8")
            copied = self._sync_server_mods(id, d)
            if copied:
                self.emit("ds_log", {"id": sid, "line": f"[통합 작업실] 서버 모드 {len(copied)}개: {', '.join(copied[:8])}"})
            return "fabric-server-launch.jar"
        return "server.jar"

    # ---------- 실행 ----------
    def start(self, id: str, sid: str) -> dict[str, Any]:
        with self.lock:
            if sid in self.procs and self.procs[sid].poll() is None:
                raise RpcError("이미 실행 중입니다.")
            d = self._sdir(id, sid)
            if not self._eula_ok(d):
                return {"needsEula": True, "eulaUrl": EULA_URL}
            meta = self._meta(id, sid)
            props = read_properties(d / "server.properties")
            port = int(props.get("server-port", "0") or 0)
            if not port or not port_free(port):
                port = free_port()
            write_properties(d / "server.properties", {"server-ip": "", "server-port": port})
            launch = self.prepare_launch(id, sid)
            cmd = [*self.java_cmd(meta["version"]), "-Xmx2G", *launch]
            proc = subprocess.Popen(cmd, cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.procs[sid] = proc
            self.ready[sid] = False
            self.players[sid] = set()
        self.emit("ds_state", {"id": sid, "instanceId": id, "state": "starting", "port": port})
        threading.Thread(target=self._pump, args=(id, sid, proc, port), daemon=True).start()
        return {"pid": proc.pid, "port": port, "state": "starting"}

    def _pump(self, id: str, sid: str, proc: subprocess.Popen, port: int) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            self.emit("ds_log", {"id": sid, "instanceId": id, "line": line})
            if not self.ready.get(sid) and DONE_RE.search(line):
                self.ready[sid] = True
                self.emit("ds_state", {"id": sid, "instanceId": id, "state": "ready", "port": port})
            m = JOIN_RE.search(line)
            if m:
                self.players.setdefault(sid, set()).add(m.group(1))
                self.emit("ds_players", {"id": sid, "players": sorted(self.players[sid])})
            m = LEFT_RE.search(line)
            if m:
                self.players.setdefault(sid, set()).discard(m.group(1))
                self.emit("ds_players", {"id": sid, "players": sorted(self.players[sid])})
        code = proc.wait()
        self.procs.pop(sid, None)
        self.ready.pop(sid, None)
        self.players.pop(sid, None)
        self.emit("ds_state", {"id": sid, "instanceId": id, "state": "stopped", "exitCode": code})

    def command(self, id: str, sid: str, command: str) -> bool:
        proc = self.procs.get(sid)
        if not proc or proc.poll() is not None or not proc.stdin:
            raise RpcError("서버가 실행 중이 아닙니다.")
        proc.stdin.write(command.lstrip("/") + "\n")
        proc.stdin.flush()
        return True

    def stop(self, id: str, sid: str, timeout: float = 30) -> bool:
        proc = self.procs.get(sid)
        if not proc or proc.poll() is not None:
            return False
        try:
            self.command(id, sid, "stop")
            proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        return True

    def running(self) -> list[str]:
        return [sid for sid, p in self.procs.items() if p.poll() is None]

    def shutdown(self) -> None:
        for sid, p in list(self.procs.items()):
            try:
                if p.stdin:
                    p.stdin.write("stop\n")
                    p.stdin.flush()
                p.wait(timeout=20)
            except Exception:  # noqa: BLE001
                p.kill()


# ================================================================ e4mc (싱글 LAN 공개 → 인터넷 주소)

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
