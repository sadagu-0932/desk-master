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

from instances import InstanceStore, write_cc_config
from paths import safe_join
import modrinth
import net
import server_runner
from rpc import RpcError, notify
from lazy import lazy_module

mll = lazy_module("minecraft_launcher_lib")   # 설치할 때만 필요 → 처음 쓸 때 불러옴

LOG_LEVEL = re.compile(r"/(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]")
EULA_URL = "https://aka.ms/MinecraftEULA"


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
        if loader == "neoforge":
            # minecraft-launcher-lib 8.0 은 26.x NeoForge 버전 형식(26.3.0.x)을 모른다 → 메이븐에서 직접
            try:
                versions = server_runner.neoforge_versions(version)
            except Exception as e:  # noqa: BLE001
                raise RpcError(f"NeoForge 버전 목록을 받지 못했습니다: {e}") from e
            return {"supported": bool(versions), "versions": versions}
        if loader in ("forge", "quilt"):
            ml = mll.mod_loader.get_mod_loader(loader)
            try:
                if not ml.is_minecraft_version_supported(version):
                    return {"supported": False, "versions": []}
                stable = set(ml.get_loader_versions(version, True))
                allv = ml.get_loader_versions(version, False)
            except Exception as e:  # noqa: BLE001 - 네트워크 오류 등
                raise RpcError(f"{loader} 버전 목록을 받지 못했습니다: {e.__class__.__name__}") from e
            return {"supported": True, "versions": [{"version": v, "stable": v in stable}
                                                    for v in sorted(allv, key=server_runner._vkey, reverse=True)]}
        if loader != "fabric":
            raise RpcError(f"지원하지 않는 로더입니다: {loader}")
        try:
            data = net.get_json(f"https://meta.fabricmc.net/v2/versions/loader/{urllib.parse.quote(version)}")
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
            loader = meta["loader"]
            prev = meta.get("versionId")
            if loader != "vanilla" and prev and (self.mc_dir / "versions" / prev / f"{prev}.json").is_file():
                version_id = prev   # 이미 설치된 로더 버전(불러온 인스턴스 등)은 다시 설치하지 않는다
            elif loader != "vanilla":
                name = {"fabric": "Fabric", "quilt": "Quilt", "neoforge": "NeoForge", "forge": "Forge"}.get(loader, loader)
                notify("progress", {"id": id, "stage": "install", "text": f"{name} 로더 설치 중"})
                ml = mll.mod_loader.get_mod_loader(loader)
                if loader == "neoforge":
                    version_id = self._install_neoforge(id, meta, ml)
                else:
                    if not ml.is_minecraft_version_supported(meta["version"]):
                        raise RpcError(f"{name}이(가) 아직 {meta['version']}을 지원하지 않습니다.")
                    version_id = ml.install(
                        meta["version"], str(self.mc_dir),
                        loader_version=meta.get("loaderVersion") or None,
                        callback=self._callback(id, "install"),
                        java=self._java_for(meta["version"]),
                    )
            if loader == "fabric" and meta.get("ccEnabled") and not meta.get("linkedDir"):
                self._install_commandcrafter(id, meta)
        meta = self.store.get(id)
        meta["versionId"] = version_id
        meta["installed"] = True
        self.store.save(meta)
        notify("progress", {"id": id, "stage": "install", "text": "설치 완료", "done": True})
        return self.store.get(id)

    def _install_neoforge(self, id: str, meta: dict[str, Any], ml: Any) -> str:
        """NeoForge: 버전은 메이븐에서 직접 고르고(26.x 형식), 설치는 라이브러리의 설치기 실행(--install-client)을 쓴다."""
        mc = meta["version"]
        lv = meta.get("loaderVersion")
        if lv and not lv.startswith(server_runner.neoforge_prefix(mc)):
            raise RpcError(f"NeoForge {lv} 는 {mc} 용이 아닙니다.")
        if not lv:
            vs = server_runner.neoforge_versions(mc)
            pick = [v["version"] for v in vs if v["stable"]] or [v["version"] for v in vs]
            if not pick:
                raise RpcError(f"NeoForge 가 아직 {mc}을 지원하지 않습니다.")
            lv = pick[0]
        mll.install.install_minecraft_version(mc, str(self.mc_dir), callback=self._callback(id, "install"))
        cb = self._callback(id, "install")
        ml._base.install(mc, str(self.mc_dir), cb, str(self._java_for(mc) or "java"), lv)
        return f"neoforge-{lv}"

    def install_fabric_for(self, id: str, version: str) -> str:
        """M10 e4mc: 바닐라 인스턴스의 '호스트용' 실행을 위해 같은 버전 Fabric 을 앱 .minecraft 에 설치(인스턴스는 그대로)."""
        with self.install_lock:
            notify("progress", {"id": id, "stage": "install", "text": f"호스트용 Fabric {version} 설치 중"})
            mll.install.install_minecraft_version(version, str(self.mc_dir), callback=self._callback(id, "install"))
            fabric = mll.mod_loader.get_mod_loader("fabric")
            if not fabric.is_minecraft_version_supported(version):
                raise RpcError(f"Fabric이 아직 {version}을 지원하지 않습니다.")
            vid = fabric.install(version, str(self.mc_dir), callback=self._callback(id, "install"),
                                 java=self._java_for(version))
        notify("progress", {"id": id, "stage": "install", "done": True})
        return vid

    # ---------- Modrinth (CommandCrafter 모드와 필수 의존성) — 받는 건 전부 modrinth.py ----------
    def _modrinth_install(self, project: str, game_version: str, mods_dir: Path, loader: str = "fabric") -> list[str]:
        res = modrinth.install(project, game_version, loader, mods_dir)
        return [e["filename"] for e in res.installed + res.kept]

    def _install_commandcrafter(self, inst_id: str, meta: dict[str, Any]) -> None:
        d = self.store.dir_of(inst_id)
        notify("progress", {"id": inst_id, "stage": "install", "text": "CommandCrafter 모드 받는 중(Modrinth)"})
        try:
            names = self._modrinth_install("commandcrafter", meta["version"], d / "mods", meta["loader"])
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
            manifest = net.get_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            url = next(v["url"] for v in manifest["versions"] if v["id"] == version)
            vjson = net.get_json(url)
        server = vjson.get("downloads", {}).get("server")
        if not server:
            raise RpcError(f"{version}에는 서버 jar가 없습니다.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        net.download(server["url"], dest, hashes={"sha1": server.get("sha1")})

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

