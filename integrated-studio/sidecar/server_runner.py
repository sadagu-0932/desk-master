"""M10 방식 A: 전용 서버(바닐라 서버 jar 또는 Fabric 서버 런처). 인스턴스마다 여러 개를 동시에 돌릴 수 있다.

서버 폴더: <인스턴스>/p2p-servers/<서버id>/  (server.json · server.properties · eula.txt · world/ · logs/)
- 서버 jar 는 버전 json 의 downloads.server(바닐라), Fabric 이면 meta.fabricmc.net 의 서버 런처.
  받은 jar 는 data/server-jars/ 에 모아 두고 서버 폴더로 복사한다.
- EULA 는 앱의 동의 창에서 사용자가 직접 동의해야 true 가 된다(자동 동의 금지).
- server-ip=127.0.0.1: 밖에서는 P2P 터널로만 들어온다. 포트는 빈 포트를 자동으로.
- 로그에서 "Done (…)! For help, type" 을 보고 준비 완료를 알린다(앱이 그때 P2P 를 연다).

servers.dat(멀티플레이 서버 목록, 압축 없는 NBT) 읽기·쓰기도 여기 있다(참가할 때 서버 추가).
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _http_json(url: str) -> Any:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)


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
        return safe_join(self.store.dir_of(inst_id), "p2p-servers", sid)

    def _meta(self, inst_id: str, sid: str) -> dict[str, Any]:
        f = self._sdir(inst_id, sid) / "server.json"
        if not f.is_file():
            raise RpcError("서버를 찾을 수 없습니다.")
        return json.loads(f.read_text("utf-8"))

    def _save(self, inst_id: str, meta: dict[str, Any]) -> None:
        d = self._sdir(inst_id, meta["id"])
        (d / "server.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")

    def list(self, id: str) -> list[dict[str, Any]]:
        base = self.store.dir_of(id) / "p2p-servers"
        out = []
        if base.is_dir():
            for d in sorted(base.iterdir()):
                f = d / "server.json"
                if f.is_file():
                    m = json.loads(f.read_text("utf-8"))
                    out.append({**m, **self._state(m["id"], d)})
        return out

    def _state(self, sid: str, d: Path) -> dict[str, Any]:
        proc = self.procs.get(sid)
        running = bool(proc and proc.poll() is None)
        return {"running": running, "ready": running and self.ready.get(sid, False),
                "players": sorted(self.players.get(sid, set())), "needsEula": not self._eula_ok(d),
                "port": int(read_properties(d / "server.properties").get("server-port", "0") or 0)}

    @staticmethod
    def _eula_ok(d: Path) -> bool:
        f = d / "eula.txt"
        return f.is_file() and bool(re.search(r"^\s*eula\s*=\s*true\s*$", f.read_text("utf-8"), re.M))

    def create(self, id: str, name: str, online_mode: bool = True, world: str | None = None,
               max_players: int = 10) -> dict[str, Any]:
        meta_i = self.store.get(id)
        name = (name or "").strip() or f"{meta_i['name']} 서버"
        if world:  # 만들기 전에 월드부터 확인(실패해도 빈 서버 폴더가 남지 않게)
            w = safe_join(self.store.dir_of(id), "saves", world)
            if not (w / "level.dat").is_file():
                raise RpcError(f"월드를 찾을 수 없습니다: {world}")
        sid = "srv_" + uuid.uuid4().hex[:8]
        d = self._sdir(id, sid)
        d.mkdir(parents=True)
        meta = {"id": sid, "name": name[:60], "instanceId": id, "version": meta_i["version"],
                "loader": meta_i.get("loader", "vanilla"), "loaderVersion": meta_i.get("loaderVersion"),
                "onlineMode": bool(online_mode), "world": None, "created": time.time()}
        self._save(id, meta)
        write_properties(d / "server.properties", {
            "server-ip": "127.0.0.1", "server-port": free_port(), "online-mode": bool(online_mode),
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
        base = self.store.dir_of(id)
        src = safe_join(base, "saves", world)
        if not (src / "level.dat").is_file():
            raise RpcError(f"월드를 찾을 수 없습니다: {world}")
        d = self._sdir(id, sid)
        dst = d / "world"
        if dst.exists():
            from paths import trash
            trash(dst, base)
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
        from paths import trash
        trash(self._sdir(id, sid), self.store.dir_of(id))
        return {"ok": True}

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
        self.emit("p2p_server_log", {"id": self._current, "line": f"[통합 작업실] {version} 서버 jar 받는 중"})
        _download(server["url"], dest)
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
            self.emit("p2p_server_log", {"id": self._current, "line": f"[통합 작업실] Fabric 서버 런처 받는 중({lv})"})
            _download(f"{FABRIC_META}/versions/loader/{version}/{lv}/{iv}/server/jar", dest)
        return dest

    def prepare_jar(self, id: str, sid: str) -> str:
        self._current = sid
        meta = self._meta(id, sid)
        d = self._sdir(id, sid)
        vanilla = self._vanilla_jar(meta["version"])
        if not (d / "server.jar").is_file() or (d / "server.jar").stat().st_size != vanilla.stat().st_size:
            shutil.copy2(vanilla, d / "server.jar")
        if meta["loader"] == "fabric":
            launcher = self._fabric_launcher(meta["version"], meta.get("loaderVersion"))
            shutil.copy2(launcher, d / "fabric-server-launch.jar")
            (d / "fabric-server-launcher.properties").write_text("serverJar=server.jar\n", "utf-8")
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
            write_properties(d / "server.properties", {"server-ip": "127.0.0.1", "server-port": port})
            jar = self.prepare_jar(id, sid)
            cmd = [*self.java_cmd(meta["version"]), "-Xmx2G", "-jar", jar, "nogui"]
            proc = subprocess.Popen(cmd, cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.procs[sid] = proc
            self.ready[sid] = False
            self.players[sid] = set()
        self.emit("p2p_server_state", {"id": sid, "instanceId": id, "state": "starting", "port": port})
        threading.Thread(target=self._pump, args=(id, sid, proc, port), daemon=True).start()
        return {"pid": proc.pid, "port": port, "state": "starting"}

    def _pump(self, id: str, sid: str, proc: subprocess.Popen, port: int) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            self.emit("p2p_server_log", {"id": sid, "instanceId": id, "line": line})
            if not self.ready.get(sid) and DONE_RE.search(line):
                self.ready[sid] = True
                self.emit("p2p_server_state", {"id": sid, "instanceId": id, "state": "ready", "port": port})
            m = JOIN_RE.search(line)
            if m:
                self.players.setdefault(sid, set()).add(m.group(1))
                self.emit("p2p_server_players", {"id": sid, "players": sorted(self.players[sid])})
            m = LEFT_RE.search(line)
            if m:
                self.players.setdefault(sid, set()).discard(m.group(1))
                self.emit("p2p_server_players", {"id": sid, "players": sorted(self.players[sid])})
        code = proc.wait()
        self.procs.pop(sid, None)
        self.ready.pop(sid, None)
        self.players.pop(sid, None)
        self.emit("p2p_server_state", {"id": sid, "instanceId": id, "state": "stopped", "exitCode": code})

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


# ================================================================ servers.dat (압축 없는 NBT)
END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND, INT_ARRAY, LONG_ARRAY = range(13)


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.i = 0

    def take(self, n: int) -> bytes:
        b = self.d[self.i:self.i + n]
        if len(b) != n:
            raise ValueError("NBT 가 잘렸습니다")
        self.i += n
        return b

    def string(self) -> str:
        (n,) = struct.unpack(">H", self.take(2))
        return self.take(n).decode("utf-8", "replace")

    def payload(self, t: int) -> Any:
        fmt = {BYTE: ">b", SHORT: ">h", INT: ">i", LONG: ">q", FLOAT: ">f", DOUBLE: ">d"}
        if t in fmt:
            size = struct.calcsize(fmt[t])
            return (t, struct.unpack(fmt[t], self.take(size))[0])
        if t == STRING:
            return (t, self.string())
        if t in (BYTE_ARRAY, INT_ARRAY, LONG_ARRAY):
            (n,) = struct.unpack(">i", self.take(4))
            width = {BYTE_ARRAY: 1, INT_ARRAY: 4, LONG_ARRAY: 8}[t]
            return (t, self.take(n * width))
        if t == LIST:
            et = self.take(1)[0]
            (n,) = struct.unpack(">i", self.take(4))
            return (t, (et, [self.payload(et) for _ in range(n)]))
        if t == COMPOUND:
            items: dict[str, Any] = {}
            while True:
                ct = self.take(1)[0]
                if ct == END:
                    return (t, items)
                name = self.string()
                items[name] = self.payload(ct)
        raise ValueError(f"모르는 NBT 태그 {t}")


def _w_string(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def _w_payload(tag: tuple[int, Any]) -> bytes:
    t, v = tag
    fmt = {BYTE: ">b", SHORT: ">h", INT: ">i", LONG: ">q", FLOAT: ">f", DOUBLE: ">d"}
    if t in fmt:
        return struct.pack(fmt[t], v)
    if t == STRING:
        return _w_string(v)
    if t in (BYTE_ARRAY, INT_ARRAY, LONG_ARRAY):
        width = {BYTE_ARRAY: 1, INT_ARRAY: 4, LONG_ARRAY: 8}[t]
        return struct.pack(">i", len(v) // width) + v
    if t == LIST:
        et, items = v
        return bytes([et]) + struct.pack(">i", len(items)) + b"".join(_w_payload(x) for x in items)
    if t == COMPOUND:
        return b"".join(bytes([ct]) + _w_string(k) + _w_payload((ct, cv)) for k, (ct, cv) in v.items()) + bytes([END])
    raise ValueError(t)


def read_servers_dat(path: Path) -> list[dict[str, Any]]:
    """[{name, ip, ...원래 태그}] — 파일이 없거나 깨졌으면 빈 목록."""
    if not path.is_file():
        return []
    try:
        r = _Reader(path.read_bytes())
        if r.take(1)[0] != COMPOUND:
            return []
        r.string()
        _, root = r.payload(COMPOUND)
        lst = root.get("servers")
        if not lst or lst[0] != LIST:
            return []
        out = []
        for _, comp in lst[1][1]:
            out.append({k: v for k, v in comp.items()})
        return out
    except (ValueError, IndexError, struct.error):
        return []


def write_servers_dat(path: Path, servers: list[dict[str, Any]]) -> None:
    root = {"servers": (LIST, (COMPOUND if servers else END, [(COMPOUND, s) for s in servers]))}
    data = bytes([COMPOUND]) + _w_string("") + _w_payload((COMPOUND, root))
    tmp = path.with_suffix(".dat.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def servers_dat_upsert(path: Path, name: str, ip: str) -> dict[str, Any]:
    """통합 작업실이 넣은 항목(이름 "[P2P] …")은 이름으로 찾아 주소만 바꾸고, 없으면 맨 위에 넣는다.
    (게임은 서버 목록을 저장할 때 모르는 태그를 지우므로 표시는 이름으로 한다.)"""
    servers = read_servers_dat(path)
    label = f"[P2P] {name}"[:60]
    for s in servers:
        if s.get("name", (None, None))[1] == label:
            s["ip"] = (STRING, ip)
            break
    else:
        servers.insert(0, {"name": (STRING, label), "ip": (STRING, ip)})
    path.parent.mkdir(parents=True, exist_ok=True)
    write_servers_dat(path, servers)
    return {"name": label, "ip": ip, "count": len(servers)}


class ServersDat:
    """사이드카 RPC: 참가할 때 인스턴스 servers.dat 에 서버 추가."""

    def __init__(self, store: InstanceStore):
        self.store = store

    def add(self, id: str, name: str, ip: str) -> dict[str, Any]:
        if not re.fullmatch(r"127\.0\.0\.1:\d{1,5}", ip or ""):
            raise RpcError("주소는 127.0.0.1:<포트> 형식이어야 합니다.")
        return servers_dat_upsert(self.store.dir_of(id) / "servers.dat", name, ip)
