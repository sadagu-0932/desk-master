"""M10 서버 열기 — 사이드카 쪽.

1) 방식 A 전용 서버(ServerRunner): 바닐라 서버 jar 또는 Fabric 서버 런처. 인스턴스마다 여러 개를 동시에.
   서버 폴더: data/instances/<인스턴스>/servers/<서버id>/ (server.json · server.properties · eula.txt · world/ · mods/ · logs/)
   - 서버 jar 는 버전 json 의 downloads.server(바닐라), Fabric 은 meta.fabricmc.net 서버 런처. data/server-jars/ 에 모아 둔다.
   - EULA 는 앱의 동의 창에서 사용자가 직접 동의해야 true 가 된다(자동 동의 금지).
   - server.properties 기본값: 빈 포트 자동, online-mode 선택. server-ip 는 비운다(UPnP 로 들어오는 공유기 연결을 받으려면
     LAN 주소에서도 들어와야 한다. playit 은 127.0.0.1 로 들어온다).
   - 로그 "Done (…)! For help, type" 을 보고 준비 완료를 알린다(앱이 그때 주소를 연다).
   - Fabric 서버면 인스턴스 mods/ 에서 서버에서도 도는 모드(environment != client)를 서버 mods/ 로 복사한다.
모드 분석(참가자도 같은 모드가 필요한지)은 server_mods.py, e4mc(싱글 LAN 공개 → 인터넷 주소)는 e4mc_host.py.
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
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable

import memory
import net
from instances import InstanceStore
from paths import safe_join
from rpc import RpcError, notify
import server_errors
from server_mods import E4MC_IDS, client_required_mods, mods_config, read_mod_info, scan_mods

EULA_URL = "https://aka.ms/MinecraftEULA"
DONE_RE = re.compile(r'Done \([0-9.,]+s\)! For help, type')
JOIN_RE = re.compile(r"\]: (\S+) joined the game")
LEFT_RE = re.compile(r"\]: (\S+) left the game")
SID_RE = re.compile(r"srv_[0-9a-f]{8}")
FABRIC_META = "https://meta.fabricmc.net/v2"
DEDICATED_LOADERS = ("vanilla", "fabric", "neoforge", "forge")
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
LOADER_NAMES = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric", "vanilla": "바닐라", "paper": "Paper"}
# Paper(플러그인 서버, 사용자 요청 2026-11-27). Fill v3 API — fill.papermc.io/v3/projects/paper/versions/<mc>/builds 로 확인(2026-11):
# 빌드마다 channel(STABLE 등), downloads["server:default"] = {name, checksums.sha256, url(fill-data.papermc.io)}
PAPER_API = "https://fill.papermc.io/v3/projects/paper"
PAPER_DOWNLOAD_HOSTS = ("fill-data.papermc.io", "fill.papermc.io")


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


_http_json = net.get_json   # 시험이 이 이름을 바꿔 끼운다


def _download(url: str, dest: Path, sha1: str | None = None) -> None:
    try:
        net.download(url, dest, hashes={"sha1": sha1} if sha1 else None)
    except net.HashMismatch as e:
        raise RpcError(f"받은 서버 jar 의 해시가 맞지 않아 버렸습니다: {dest.name}") from e


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
    xml = net.get_bytes(f"{NEOFORGE_MAVEN}/maven-metadata.xml").decode("utf-8", "replace")
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
        self.diag: dict[str, server_errors.Diagnoser] = {}

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
               max_players: int = 10, software: str | None = None) -> dict[str, Any]:
        """software="paper" 면 Paper 서버(플러그인 테스트·친구와 플레이). 인스턴스 로더와 상관없이 같은 게임 버전."""
        meta_i = self.store.get(id)
        loader = meta_i.get("loader", "vanilla")
        if software == "paper":
            loader = "paper"
        elif software:
            raise RpcError(f"모르는 서버 종류입니다: {software}")
        elif loader not in DEDICATED_LOADERS:
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

    def update(self, id: str, sid: str, name: str | None = None, online_mode: bool | None = None,
               memory_mb: int | None = None) -> dict[str, Any]:
        meta = self._meta(id, sid)
        d = self._sdir(id, sid)
        props: dict[str, Any] = {}
        if name:
            meta["name"] = name.strip()[:60]
            props["motd"] = meta["name"][:59]
        if online_mode is not None:
            meta["onlineMode"] = bool(online_mode)
            props["online-mode"] = bool(online_mode)
        if memory_mb == 0:
            meta.pop("memoryMb", None)          # 기본값으로
        elif memory_mb is not None:
            if not (512 <= int(memory_mb) <= 65536):
                raise RpcError("서버 메모리는 512MB ~ 64GB 사이로 정하세요.")
            meta["memoryMb"] = int(memory_mb)   # 다음 시작부터
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
    def _paper_jar(self, version: str) -> Path:
        """그 게임 버전의 가장 새 STABLE Paper 빌드(없으면 가장 새 빌드)를 받아 sha256 으로 검증한다(받아 둔 건 다시 씀)."""
        try:
            builds = _http_json(f"{PAPER_API}/versions/{version}/builds")
        except Exception as e:  # noqa: BLE001
            raise RpcError(f"Paper 에 {version} 서버가 없거나 연결하지 못했습니다: {e}") from e
        if not isinstance(builds, list) or not builds:
            raise RpcError(f"Paper 에 {version} 빌드가 아직 없습니다.")
        build = next((b for b in builds if b.get("channel") == "STABLE"), builds[0])
        dl = (build.get("downloads") or {}).get("server:default") or {}
        name, url, sha = dl.get("name"), dl.get("url") or "", (dl.get("checksums") or {}).get("sha256")
        host = urllib.parse.urlparse(url).hostname or ""
        if not name or not sha or not url.startswith("https://") or host not in PAPER_DOWNLOAD_HOSTS:
            raise RpcError("Paper 다운로드 정보가 이상해서 받지 않았습니다.")
        dest = self.jars_dir / "paper" / Path(name).name
        if dest.is_file() and net.hashes_match(dest, {"sha256": sha}):
            return dest
        self.emit("ds_log", {"id": self._current, "line": f"[통합 작업실] Paper {name} 받는 중(빌드 {build.get('id')}, {build.get('channel')})"})
        try:
            return net.download(url, dest, hashes={"sha256": sha})
        except net.HashMismatch as e:
            raise RpcError(f"받은 Paper 서버의 해시가 맞지 않아 버렸습니다: {name}") from e

    def paper_servers(self, id: str) -> list[str]:
        """이 인스턴스의 Paper 서버 id 들."""
        return [m["id"] for m in self.list(id) if m.get("loader") == "paper"]

    def install_plugin(self, id: str, jar: Path) -> dict[str, Any]:
        """빌드한 플러그인 jar 를 이 인스턴스의 모든 Paper 서버 plugins/ 에 넣고(같은 이름의 예전 jar 는 휴지통),
        켜져 있는 서버는 다시 시작한다(Paper 는 /reload 를 권하지 않는다)."""
        sids = self.paper_servers(id)
        if not sids:
            return {"servers": [], "restarted": [],
                    "message": "Paper 서버가 없어 넣지 않았습니다. 서버 패널 [서버 열기] → 전용 서버 → Paper 로 만들면 빌드할 때마다 자동으로 넣습니다."}
        stem = jar.name.rsplit("-", 1)[0] if "-" in jar.name else jar.stem
        restarted = []
        for sid in sids:
            plugins = self._sdir(id, sid) / "plugins"
            plugins.mkdir(exist_ok=True)
            for old in plugins.glob(f"{stem}-*.jar"):
                if old.name != jar.name:
                    _trash(old, self.store.dir_of(id))
            shutil.copy2(jar, safe_join(plugins, jar.name))
            if sid in self.procs and self.procs[sid].poll() is None:
                self.emit("ds_log", {"id": sid, "line": f"[통합 작업실] 플러그인 {jar.name} 을(를) 넣고 서버를 다시 시작합니다"})
                self.stop(id, sid)
                self.start(id, sid)
                restarted.append(sid)
        return {"servers": sids, "restarted": restarted,
                "message": f"Paper 서버 {len(sids)}개의 plugins/ 에 {jar.name} 을(를) 넣었습니다"
                           + (f"(켜져 있던 {len(restarted)}개는 다시 시작)." if restarted else ". 서버를 켜면 적용됩니다.")}

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
        sha256 = (net.get_bytes(url + ".sha256").decode("ascii", "replace").strip().split() or [""])[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise RpcError("설치기 검증값(sha256)을 받지 못했습니다.")
        if dest.is_file() and net.hashes_match(dest, {"sha256": sha256}):
            return dest
        self.emit("ds_log", {"id": self._current, "line": f"[통합 작업실] {LOADER_NAMES[loader]} {full} 서버 설치기 받는 중"})
        try:
            return net.download(url, dest, hashes={"sha256": sha256})
        except net.HashMismatch as e:
            raise RpcError(f"받은 {LOADER_NAMES[loader]} 설치기의 해시가 맞지 않아 버렸습니다.") from e

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

    # ---------- 모드: 인스턴스 → 서버 복사, 일치 확인(사용자 요청 2026-11-27 "복사가 이상함 · 일치하는지 확인") ----------
    MANIFEST = ".studio-mods.json"          # (서버 폴더) 앱이 서버 mods/ 에 복사한 파일 목록(사용자가 직접 넣은 건 건드리지 않으려고)
    CONFIG_DIRS = ("config", "defaultconfigs", "kubejs")

    @staticmethod
    def _server_side(info: dict[str, Any] | None) -> bool:
        """서버에서도 돌릴 모드인가. 정보를 못 읽는 jar(라이브러리 등)는 넣는다 — 빼면 의존 모드가 없어 서버가 안 켜진다."""
        if info is None:
            return True
        if info["id"] in E4MC_IDS:
            return False
        return info.get("environment") not in ("client",)

    def _read_manifest(self, d: Path) -> dict[str, Any]:
        try:
            return json.loads((d / self.MANIFEST).read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"copied": {}}

    def _sync_server_mods(self, id: str, d: Path) -> list[str]:
        """인스턴스 mods/ 중 서버에서도 도는 모드를 서버 mods/ 로(크기·수정 시각이 다르면 다시).
        지우는 것은 '예전에 앱이 복사했는데 인스턴스에서 빠진 것'만(휴지통). 사용자가 서버에 직접 넣은 jar 는 그대로.
        같은 모드 id 의 다른 파일(옛 버전)이 서버에 있으면 그것도 휴지통으로(중복 MOD-105 방지).
        config·defaultconfigs·kubejs 는 서버에 없거나 인스턴스 쪽이 더 새 파일만 복사한다(서버에서 고친 설정은 덮지 않음)."""
        src = self.store.game_dir(id) / "mods"
        dst = d / "mods"
        dst.mkdir(exist_ok=True)
        base = self.store.dir_of(id)
        manifest = self._read_manifest(d)
        wanted: dict[str, Path] = {}
        wanted_ids: dict[str, str] = {}
        if src.is_dir():
            for p in sorted(src.iterdir()):
                if p.is_file() and p.suffix == ".jar":
                    info = read_mod_info(p)
                    if self._server_side(info):
                        wanted[p.name] = p
                        if info and info.get("id"):
                            wanted_ids[info["id"]] = p.name
        for name in list(manifest.get("copied", {})):
            if name not in wanted and (dst / name).is_file():
                _trash(dst / name, base)
        for p in list(dst.iterdir()):
            if p.is_file() and p.suffix == ".jar" and p.name not in wanted:
                info = read_mod_info(p)
                if info and wanted_ids.get(info.get("id", "")) not in (None, p.name):
                    _trash(p, base)            # 같은 모드의 옛 버전
        for name, p in wanted.items():
            t = dst / name
            st = p.stat()
            if not t.is_file() or t.stat().st_size != st.st_size or int(t.stat().st_mtime) != int(st.st_mtime):
                shutil.copy2(p, t)
        (d / self.MANIFEST).write_text(json.dumps({"copied": {n: wanted[n].stat().st_size for n in wanted}},
                                                    ensure_ascii=False, indent=1), "utf-8")
        self._sync_configs(id, d)
        return sorted(wanted)

    def _sync_configs(self, id: str, d: Path) -> int:
        game = self.store.game_dir(id)
        n = 0
        for folder in self.CONFIG_DIRS:
            root = game / folder
            if not root.is_dir():
                continue
            for f in root.rglob("*"):
                if not f.is_file() or f.is_symlink():
                    continue
                rel = f.relative_to(game)
                t = safe_join(d, *rel.parts)
                if not t.is_file() or f.stat().st_mtime > t.stat().st_mtime + 1:
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, t)
                    n += 1
        return n

    def mod_check(self, id: str, sid: str) -> dict[str, Any]:
        """인스턴스(참가자 쪽)와 서버 mods/ 비교. issues = [{code, kind, title, fix, id, name, file, clientFile, serverFile, ...}]
        MOD-101 서버에 없음 · MOD-102 인스턴스에 없음(참가자도 필요) · MOD-103 버전 다름 · MOD-104 클라이언트 전용이 서버에 · MOD-105 서버에 중복 · MOD-106 로더가 다른 모드"""
        meta = self._meta(id, sid)
        d = self._sdir(id, sid)
        loader = meta.get("loader")
        if loader in ("vanilla", "paper"):
            return {"loader": loader, "issues": [], "client": [], "server": [],
                    "message": "바닐라·Paper 서버는 모드를 쓰지 않습니다(Paper 는 plugins/)."}
        host_only = set(mods_config().get("hostOnly", []))

        def load(folder: Path) -> list[dict[str, Any]]:
            out = []
            if folder.is_dir():
                for p in sorted(folder.iterdir()):
                    if p.is_file() and p.suffix == ".jar":
                        info = read_mod_info(p) or {"id": "", "name": p.stem, "version": None, "loader": None,
                                                    "environment": "*", "clientRequired": False, "unknown": True}
                        out.append({**info, "file": p.name})
            return out
        client = load(self.store.game_dir(id) / "mods")
        server = load(d / "mods")
        cby = {m["id"]: m for m in client if m["id"]}
        sby: dict[str, list[dict[str, Any]]] = {}
        for m in server:
            if m["id"]:
                sby.setdefault(m["id"], []).append(m)
        compatible = {"fabric": ("fabric", "quilt"), "quilt": ("fabric", "quilt"), "neoforge": ("neoforge",), "forge": ("forge",)}
        issues: list[dict[str, Any]] = []

        def add(code: str, title: str, fix: str | None, m: dict[str, Any], **kw: Any) -> None:
            issues.append({"code": code, "title": title, "fix": fix, "id": m.get("id"), "name": m.get("name") or m.get("file"),
                           **kw})
        for mid, ms in sby.items():
            if len(ms) > 1:
                for extra in sorted(ms, key=lambda x: x["file"])[:-1]:
                    add("MOD-105", "서버에 같은 모드가 두 개", "removeServer", extra, serverFile=extra["file"],
                        version=extra.get("version"))
        for m in server:
            if m.get("environment") == "client":
                add("MOD-104", "클라이언트 전용 모드가 서버에 있음(서버가 안 켜질 수 있음)", "removeServer", m, serverFile=m["file"])
            elif m.get("loader") and loader in compatible and m["loader"] not in compatible[loader]:
                add("MOD-106", f"{LOADER_NAMES.get(m['loader'], m['loader'])} 모드가 {LOADER_NAMES.get(loader, loader)} 서버에 있음",
                    "removeServer", m, serverFile=m["file"])
        for mid, c in cby.items():
            if not self._server_side(c) or mid in E4MC_IDS:
                continue
            ss = sby.get(mid)
            if not ss:
                add("MOD-101", "서버에 없음", "toServer", c, clientFile=c["file"], clientVersion=c.get("version"))
            elif all(s.get("version") != c.get("version") for s in ss):
                s0 = ss[-1]
                add("MOD-103", "버전이 다름", "toServer", c, clientFile=c["file"], serverFile=s0["file"],
                    clientVersion=c.get("version"), serverVersion=s0.get("version"))
        for mid, ss in sby.items():
            s0 = ss[-1]
            wrong_loader = bool(s0.get("loader") and loader in compatible and s0["loader"] not in compatible[loader])
            if mid in cby or not s0.get("clientRequired") or mid in host_only or s0.get("environment") == "client" or wrong_loader:
                continue
            add("MOD-102", "인스턴스(참가자 쪽)에 없음 — 들어가려면 필요", "toClient", s0, serverFile=s0["file"],
                serverVersion=s0.get("version"))
        unknown_c = [m["file"] for m in client if m.get("unknown")]
        return {"loader": loader, "issues": issues, "client": client, "server": server, "unknownClient": unknown_c,
                "ok": not issues}

    def mod_fix(self, id: str, sid: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """mod_check 의 항목 고치기. fix: toServer(인스턴스 → 서버, 같은 모드 옛 파일은 휴지통) · toClient(서버 → 인스턴스) · removeServer(서버에서 휴지통).
        실행 중인 서버 mods/ 는 바꾸지 않는다(다시 시작해야 적용 — 켜져 있으면 막음)."""
        if sid in self.procs and self.procs[sid].poll() is None and any(i.get("fix") in ("toServer", "removeServer") for i in items):
            raise RpcError("서버가 켜져 있습니다. 서버 모드를 바꾸려면 먼저 중지하세요.")
        d = self._sdir(id, sid)
        game_mods = self.store.game_dir(id) / "mods"
        srv_mods = d / "mods"
        base_srv = self.store.dir_of(id)
        done, failed = [], []
        manifest = self._read_manifest(d)
        for it in items:
            fix = it.get("fix")
            try:
                if fix == "toServer":
                    srcf = safe_join(game_mods, str(it["clientFile"]))
                    self._replace_mod(srcf, srv_mods, base_srv)
                    manifest.setdefault("copied", {})[srcf.name] = srcf.stat().st_size
                elif fix == "toClient":
                    srcf = safe_join(srv_mods, str(it["serverFile"]))
                    game_mods.mkdir(parents=True, exist_ok=True)
                    self._replace_mod(srcf, game_mods, game_mods.parent)
                elif fix == "removeServer":
                    f = safe_join(srv_mods, str(it["serverFile"]))
                    if f.is_file():
                        _trash(f, base_srv)
                    manifest.get("copied", {}).pop(f.name, None)
                else:
                    raise RpcError(f"모르는 작업: {fix}")
                done.append(it)
            except Exception as e:  # noqa: BLE001 - 하나가 실패해도 나머지는
                failed.append({**it, "error": str(e)})
        (d / self.MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
        return {"done": len(done), "failed": failed, "check": self.mod_check(id, sid)}

    @staticmethod
    def _replace_mod(src: Path, dst_dir: Path, base: Path) -> None:
        """src 를 dst_dir 에 복사. 같은 모드 id 의 다른 파일은 휴지통으로."""
        if not src.is_file():
            raise RpcError(f"파일이 없습니다: {src.name}")
        info = read_mod_info(src)
        dst_dir.mkdir(parents=True, exist_ok=True)
        if info and info.get("id"):
            for p in dst_dir.iterdir():
                if p.is_file() and p.suffix == ".jar" and p.name != src.name:
                    o = read_mod_info(p)
                    if o and o.get("id") == info["id"]:
                        _trash(p, base)
        shutil.copy2(src, dst_dir / src.name)

    def open_folder(self, id: str, sid: str) -> dict[str, Any]:
        """서버 폴더를 파일 탐색기로(사용자 요청 2026-11-27)."""
        d = self._sdir(id, sid)
        if not d.is_dir():
            raise RpcError(f"서버 폴더가 없습니다: {d}")
        if sys.platform == "win32":
            import os
            os.startfile(str(d))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(d)])
        return {"ok": True, "path": str(d)}

    def errors(self, id: str, sid: str) -> list[dict[str, Any]]:
        dg = self.diag.get(sid)
        return dg.found if dg else []

    def _write_run_script(self, d: Path, java: list[str], xmx: str, launch: list[str]) -> None:
        """앱 밖에서 켜도 되는 run.bat. Forge 설치기가 만든 run.bat 은 PATH 의 자바(옛 8 이면 '@user_jvm_args.txt 를 찾을 수 없음')를
        써서 실패했다 — 앱이 고른 자바의 전체 경로로 바꿔 쓴다. 앱의 주소 열기·상태 표시는 앱의 [시작]으로 켤 때만."""
        if sys.platform != "win32":
            return
        args = " ".join(f'"{a}"' if " " in a else a for a in [*java, xmx, *launch])
        (d / "run.bat").write_text(
            "@echo off\r\nchcp 65001 >nul\r\n"
            "rem 통합 작업실이 만든 실행 파일. 앱 밖에서 켜면 주소 열기·상태 표시는 되지 않습니다(앱의 [시작]을 권장).\r\n"
            f'cd /d "%~dp0"\r\n{args} %*\r\npause\r\n', "utf-8")

    def prepare_launch(self, id: str, sid: str) -> list[str]:
        """java 뒤에 붙일 인자(메모리 제외). 바닐라·Fabric = -jar <jar> nogui, Forge 계열 = @인자파일 nogui."""
        self._current = sid
        meta = self._meta(id, sid)
        d = self._sdir(id, sid)
        loader = meta["loader"]
        if loader == "paper":
            jar = self._paper_jar(meta["version"])
            target = d / "paper.jar"
            if not target.is_file() or target.stat().st_size != jar.stat().st_size:
                shutil.copy2(jar, target)
            (d / "plugins").mkdir(exist_ok=True)
            return ["-jar", "paper.jar", "nogui"]
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
            java = self.java_cmd(meta["version"])
            cmd = [*java, memory.server_xmx(meta), *launch]
            try:
                self._write_run_script(d, java, memory.server_xmx(meta), launch)
            except OSError:
                pass
            self.diag[sid] = server_errors.Diagnoser()
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
            hit = self.diag.setdefault(sid, server_errors.Diagnoser()).feed(line)
            if hit:
                self.emit("ds_error", {"id": sid, "instanceId": id, "error": hit})
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
        dg = self.diag.get(sid)
        self.emit("ds_state", {"id": sid, "instanceId": id, "state": "stopped", "exitCode": code,
                               "errors": dg.summary(code) if dg else []})

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
        for p in list(self.procs.values()):
            try:
                if p.stdin:
                    p.stdin.write("stop\n")
                    p.stdin.flush()
                p.wait(timeout=20)
            except Exception:  # noqa: BLE001
                p.kill()
