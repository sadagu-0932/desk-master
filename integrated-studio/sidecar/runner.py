"""게임 설치·실행·중지, 로컬 서버, 데이터 생성기. minecraft-launcher-lib 래퍼."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import minecraft_launcher_lib as mll

from instances import InstanceStore, write_cc_config
from paths import safe_join
from rpc import RpcError, notify

USER_AGENT = "integrated-studio/0.1 (personal launcher)"
LOG_LEVEL = re.compile(r"/(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]")
EULA_URL = "https://aka.ms/MinecraftEULA"


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    tmp.replace(dest)


def _level(line: str) -> str:
    m = LOG_LEVEL.search(line)
    if not m:
        return "error" if ("Exception" in line or line.startswith("\tat ")) else "info"
    lv = m.group(1)
    return {"WARNING": "warn", "FATAL": "error", "TRACE": "debug"}.get(lv, lv.lower())


class Runner:
    def __init__(self, data_dir: Path, store: InstanceStore):
        self.mc_dir = (data_dir / "minecraft").resolve()
        self.reports_dir = (data_dir / "reports").resolve()
        self.mc_dir.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.procs: dict[str, subprocess.Popen] = {}       # (게임 클라이언트는 공식 런처가 실행한다 — 비어 있음)
        self.servers: dict[str, subprocess.Popen] = {}     # 로컬 서버
        self.install_lock = threading.Lock()

    # ---------- 버전 ----------
    def list_versions(self, snapshots: bool = False) -> list[dict[str, Any]]:
        """버전 목록(새 것부터). snapshots=True 면 스냅샷·베타·알파까지 모두."""
        out = []
        for v in mll.utils.get_version_list():
            if v["type"] == "release" or snapshots:
                rt = v.get("releaseTime")
                out.append({"id": v["id"], "type": v["type"],
                            "released": rt.date().isoformat() if hasattr(rt, "date") else str(rt or "")[:10]})
        return out

    def list_loader_versions(self, version: str, loader: str = "fabric") -> dict[str, Any]:
        """그 게임 버전에서 쓸 수 있는 로더 버전들(새 것부터)과 지원 여부."""
        if loader != "fabric":
            raise RpcError(f"지원하지 않는 로더입니다: {loader}")
        try:
            data = _http_json(f"https://meta.fabricmc.net/v2/versions/loader/{urllib.parse.quote(version)}")
            versions = [{"version": d["loader"]["version"], "stable": bool(d["loader"].get("stable"))} for d in data]
        except Exception:  # noqa: BLE001 - 메타 서버가 안 되면 라이브러리로
            fabric = mll.mod_loader.get_mod_loader("fabric")
            if not fabric.is_minecraft_version_supported(version):
                versions = []
            else:
                stable = set(fabric.get_loader_versions(version, True))
                versions = [{"version": v, "stable": v in stable} for v in fabric.get_loader_versions(version, False)]
        return {"supported": bool(versions), "versions": versions}

    # ---------- 설치 ----------
    def _callback(self, inst_id: str, stage: str) -> dict:
        state = {"max": 0}

        def set_status(text: str) -> None:
            notify("progress", {"id": inst_id, "stage": stage, "text": text})

        def set_progress(value: int) -> None:
            if state["max"]:
                notify("progress", {"id": inst_id, "stage": stage, "value": value, "max": state["max"]})

        def set_max(value: int) -> None:
            state["max"] = value

        return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}

    def _java_for(self, version_id: str) -> str | None:
        """버전 json이 요구하는 Mojang 자바 런타임 경로(설치돼 있으면)."""
        try:
            vjson = json.loads((self.mc_dir / "versions" / version_id / f"{version_id}.json").read_text("utf-8"))
            comp = vjson.get("javaVersion", {}).get("component")
            if comp:
                path = mll.runtime.get_executable_path(comp, str(self.mc_dir))
                if path:
                    return path
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def install(self, id: str) -> dict[str, Any]:
        meta = self.store.get(id)
        with self.install_lock:
            notify("progress", {"id": id, "stage": "install", "text": f"Java {meta['version']} 설치 중"})
            mll.install.install_minecraft_version(meta["version"], str(self.mc_dir), callback=self._callback(id, "install"))
            version_id = meta["version"]
            if meta["loader"] == "fabric":
                notify("progress", {"id": id, "stage": "install", "text": "Fabric 로더 설치 중"})
                fabric = mll.mod_loader.get_mod_loader("fabric")
                if not fabric.is_minecraft_version_supported(meta["version"]):
                    raise RpcError(f"Fabric이 아직 {meta['version']}을 지원하지 않습니다.")
                version_id = fabric.install(
                    meta["version"], str(self.mc_dir),
                    loader_version=meta.get("loaderVersion") or None,
                    callback=self._callback(id, "install"),
                    java=self._java_for(meta["version"]),
                )
                if meta.get("ccEnabled"):
                    self._install_commandcrafter(id, meta)
        meta = self.store.get(id)
        meta["versionId"] = version_id
        meta["installed"] = True
        self.store.save(meta)
        notify("progress", {"id": id, "stage": "install", "text": "설치 완료", "done": True})
        return self.store.get(id)

    # ---------- Modrinth (CommandCrafter 모드와 필수 의존성) ----------
    def _modrinth_install(self, project: str, game_version: str, mods_dir: Path, seen: set[str]) -> list[str]:
        if project in seen:
            return []
        seen.add(project)
        q = urllib.parse.urlencode({
            "loaders": json.dumps(["fabric"]),
            "game_versions": json.dumps([game_version]),
        })
        versions = _http_json(f"https://api.modrinth.com/v2/project/{project}/version?{q}")
        if not versions:
            raise RpcError(f"Modrinth에 {game_version}용 '{project}' 버전이 없습니다.")
        ver = next((v for v in versions if v.get("version_type") == "release"), versions[0])
        files = ver.get("files") or []
        file = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not file:
            raise RpcError(f"'{project}' 파일을 찾을 수 없습니다.")
        name = Path(file["filename"]).name
        dest = safe_join(mods_dir, name)
        if not dest.exists():
            _download(file["url"], dest)
        installed = [name]
        for dep in ver.get("dependencies") or []:
            if dep.get("dependency_type") == "required" and dep.get("project_id"):
                installed += self._modrinth_install(dep["project_id"], game_version, mods_dir, seen)
        return installed

    def _install_commandcrafter(self, inst_id: str, meta: dict[str, Any]) -> None:
        d = self.store.dir_of(inst_id)
        notify("progress", {"id": inst_id, "stage": "install", "text": "CommandCrafter 모드 받는 중(Modrinth)"})
        try:
            names = self._modrinth_install("commandcrafter", meta["version"], d / "mods", set())
            notify("log", {"id": inst_id, "level": "info", "source": "studio",
                           "line": f"CommandCrafter 설치: {', '.join(names)}"})
        except Exception as e:  # noqa: BLE001 - 모드가 없어도 게임은 실행돼야 한다
            notify("log", {"id": inst_id, "level": "warn", "source": "studio",
                           "line": f"CommandCrafter 모드를 받지 못했습니다: {e}"})
        write_cc_config(d, meta["ccPort"])

    # ---------- 실행·중지 ----------
    def _pump(self, inst_id: str, proc: subprocess.Popen, source: str, table: dict) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if line:
                notify("log", {"id": inst_id, "line": line, "level": _level(line), "source": source})
        code = proc.wait()
        table.pop(inst_id, None)
        notify("state", {"id": inst_id, "source": source, "running": False, "exitCode": code})

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    def running(self) -> dict[str, list[str]]:
        return {"game": list(self.procs), "server": list(self.servers)}

    # ---------- 로컬 서버 (F6) ----------
    def _server_jar(self, version: str, dest: Path) -> None:
        if dest.exists():
            return
        vjson = json.loads((self.mc_dir / "versions" / version / f"{version}.json").read_text("utf-8")) \
            if (self.mc_dir / "versions" / version).exists() else None
        if vjson is None:
            manifest = _http_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            url = next(v["url"] for v in manifest["versions"] if v["id"] == version)
            vjson = _http_json(url)
        server = vjson.get("downloads", {}).get("server")
        if not server:
            raise RpcError(f"{version}에는 서버 jar가 없습니다.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _download(server["url"], dest)

    def _runtime_java(self, version: str) -> str:
        java = self._java_for(version)
        if java:
            return java
        mll.install.install_minecraft_version(version, str(self.mc_dir))
        java = self._java_for(version)
        if not java:
            raise RpcError("자바 런타임을 찾을 수 없습니다.")
        return java

    def server_start(self, id: str, world: str | None = None) -> dict[str, Any]:
        """EULA는 사용자가 직접 읽고 eula.txt를 true로 바꿔야 한다(자동 동의하지 않는다)."""
        if id in self.servers:
            raise RpcError("서버가 이미 실행 중입니다.")
        meta = self.store.get(id)
        d = self.store.dir_of(id)
        sdir = safe_join(d, "server")
        sdir.mkdir(exist_ok=True)
        eula = sdir / "eula.txt"
        if not eula.exists():
            eula.write_text(
                "# 마인크래프트 EULA를 직접 읽고 동의하면 아래 값을 true로 바꾸세요.\n"
                f"# EULA: {EULA_URL}\n"
                "eula=false\n", "utf-8")
        if not re.search(r"^\s*eula\s*=\s*true\s*$", eula.read_text("utf-8"), re.M):
            return {"needsEula": True, "eulaPath": str(eula), "eulaUrl": EULA_URL}
        if world:
            safe_join(d, "saves", world)  # 경로 검사
            props = sdir / "server.properties"
            lines = props.read_text("utf-8").splitlines() if props.exists() else []
            lines = [l for l in lines if not l.startswith("level-name=")] + [f"level-name=../saves/{world}"]
            props.write_text("\n".join(lines) + "\n", "utf-8")
        jar = sdir / f"server-{meta['version']}.jar"
        self._server_jar(meta["version"], jar)
        java = self._runtime_java(meta["version"])
        proc = subprocess.Popen(
            [java, "-Xmx2G", "-jar", jar.name, "nogui"], cwd=sdir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.servers[id] = proc
        notify("state", {"id": id, "source": "server", "running": True, "pid": proc.pid})
        threading.Thread(target=self._pump, args=(id, proc, "server", self.servers), daemon=True).start()
        return {"pid": proc.pid}

    def server_command(self, id: str, command: str) -> bool:
        proc = self.servers.get(id)
        if not proc or not proc.stdin:
            raise RpcError("서버가 실행 중이 아닙니다.")
        proc.stdin.write(command.lstrip("/") + "\n")
        proc.stdin.flush()
        return True

    def server_stop(self, id: str) -> bool:
        proc = self.servers.get(id)
        if not proc:
            return False
        try:
            self.server_command(id, "stop")
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001
            self._terminate(proc)
        return True

    # ---------- 데이터 생성기 (게임이 꺼져 있을 때 자동완성용) ----------
    def generate_reports(self, version: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9A-Za-z._\-]{1,64}", version):
            raise RpcError("잘못된 버전입니다.")
        out = safe_join(self.reports_dir, version)
        commands = out / "reports" / "commands.json"
        if commands.exists():
            return {"path": str(out), "cached": True}
        out.mkdir(parents=True, exist_ok=True)
        notify("progress", {"id": "", "stage": "reports", "text": f"{version} 데이터 생성기 준비 중"})
        jar = out / "server.jar"
        self._server_jar(version, jar)
        java = self._runtime_java(version)
        notify("progress", {"id": "", "stage": "reports", "text": f"{version} 명령어 목록 만드는 중"})
        r = subprocess.run(
            [java, "-DbundlerMainClass=net.minecraft.data.Main", "-jar", "server.jar", "--reports", "--output", "."],
            cwd=out, capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0 or not commands.exists():
            raise RpcError(f"데이터 생성기 실패: {r.stdout[-400:]}{r.stderr[-400:]}")
        notify("progress", {"id": "", "stage": "reports", "text": "명령어 목록 준비 완료", "done": True})
        return {"path": str(out), "cached": False}

    def shutdown(self) -> None:
        for p in list(self.procs.values()) + list(self.servers.values()):
            try:
                self._terminate(p)
            except Exception:  # noqa: BLE001
                pass

