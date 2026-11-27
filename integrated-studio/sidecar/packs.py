"""데이터팩·리소스팩·Fabric 모드 도구. 모든 경로는 인스턴스 폴더 안으로 제한한다."""
from __future__ import annotations

import json
import os
import re
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from instances import InstanceStore
import net
from paths import safe_join, trash
from rpc import RpcError, notify

NAME_RE = re.compile(r"[a-z0-9_][a-z0-9_.\-]{0,63}")
NS_RE = re.compile(r"[a-z0-9_.\-]{1,64}")
TEMPLATES = Path(__file__).resolve().parent / "templates"


def _check_name(name: str, what: str = "이름") -> str:
    name = (name or "").strip()
    if not NAME_RE.fullmatch(name):
        raise RpcError(f"{what}은(는) 소문자·숫자·_ . - 만 쓸 수 있습니다: {name!r}")
    return name


def _fmt(major: int, minor: int) -> Any:
    return major if minor == 0 else [major, minor]


class Packs:
    def __init__(self, store: InstanceStore, mc_dir: Path):
        self.store = store
        self.mc_dir = mc_dir
        self.builds: dict[str, subprocess.Popen] = {}

    # ---------- 공통 ----------
    def pack_formats(self, version: str) -> dict[str, Any]:
        """설치된 클라이언트 jar의 version.json 에서 팩 포맷을 읽는다(추측하지 않음)."""
        jar = self.mc_dir / "versions" / version / f"{version}.jar"
        if not jar.is_file():
            raise RpcError(f"{version} 게임 파일이 아직 없습니다. 인스턴스를 먼저 설치하세요.")
        with zipfile.ZipFile(jar) as z:
            info = json.loads(z.read("version.json"))
        pv = info.get("pack_version")
        if isinstance(pv, int):  # 아주 옛 형식
            return {"data": pv, "resource": pv}
        return {
            "data": _fmt(pv["data_major"], pv.get("data_minor", 0)),
            "resource": _fmt(pv["resource_major"], pv.get("resource_minor", 0)),
        }

    def _pack_mcmeta(self, version: str, kind: str, description: str) -> str:
        f = self.pack_formats(version)[kind]
        return json.dumps({"pack": {"description": description, "min_format": f, "max_format": f}},
                          ensure_ascii=False, indent=2) + "\n"

    def list_worlds(self, id: str) -> list[str]:
        saves = self.store.game_dir(id) / "saves"
        if not saves.is_dir():
            return []
        worlds = [d for d in saves.iterdir() if (d / "level.dat").is_file()]
        worlds.sort(key=lambda d: (d / "level.dat").stat().st_mtime, reverse=True)
        return [d.name for d in worlds]

    # ---------- 데이터팩 (M5) ----------
    def list_datapacks(self, id: str) -> list[str]:
        d = self.store.game_dir(id) / "datapacks"
        return sorted(p.name for p in d.iterdir() if (p / "pack.mcmeta").is_file()) if d.is_dir() else []

    def datapack_new(self, id: str, name: str, namespace: str, description: str = "") -> dict[str, Any]:
        meta = self.store.get(id)
        base = self.store.game_dir(id)
        name = _check_name(name, "데이터팩 이름")
        namespace = (namespace or "").strip()
        if not NS_RE.fullmatch(namespace) or namespace == "minecraft":
            raise RpcError("네임스페이스는 소문자·숫자·_ . - 만, 'minecraft'는 쓸 수 없습니다.")
        root = safe_join(base, "datapacks", name)
        if root.exists():
            raise RpcError(f"이미 있는 데이터팩입니다: {name}")
        fn = root / "data" / namespace / "function"
        tags = root / "data" / "minecraft" / "tags" / "function"
        fn.mkdir(parents=True)
        tags.mkdir(parents=True)
        (root / "pack.mcmeta").write_text(self._pack_mcmeta(meta["version"], "data", description or name), "utf-8")
        (fn / "load.mcfunction").write_text(
            f"# /reload 또는 월드를 열 때 한 번 실행\ntellraw @a {{text:\"[{name}] 불러옴\",color:\"green\"}}\n", "utf-8")
        (fn / "tick.mcfunction").write_text("# 매 틱(1초에 20번) 실행 — @e 는 type·tag·distance 로 좁힐 것\n", "utf-8")
        (tags / "load.json").write_text(json.dumps({"values": [f"{namespace}:load"]}, indent=2) + "\n", "utf-8")
        (tags / "tick.json").write_text(json.dumps({"values": [f"{namespace}:tick"]}, indent=2) + "\n", "utf-8")
        return {"path": str(root), "open": str(fn / "load.mcfunction")}

    def datapack_sync(self, id: str, pack: str, world: str) -> dict[str, Any]:
        """작업용 원본 datapacks/<팩> → saves/<월드>/datapacks/<팩> (원본이 기준, 대상은 통째로 교체)."""
        base = self.store.game_dir(id)
        src = safe_join(base, "datapacks", _check_name(pack, "데이터팩"))
        if not (src / "pack.mcmeta").is_file():
            raise RpcError(f"데이터팩이 아닙니다(pack.mcmeta 없음): {pack}")
        world_dir = safe_join(base, "saves", world)
        if not (world_dir / "level.dat").is_file():
            raise RpcError(f"월드를 찾을 수 없습니다: {world}")
        dst = safe_join(world_dir, "datapacks", pack)
        if dst.exists():
            trash(dst, base)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", ".DS_Store"))
        count = sum(1 for _ in dst.rglob("*") if _.is_file())
        return {"path": str(dst), "files": count}

    def datapack_zip(self, id: str, pack: str) -> dict[str, Any]:
        """.zip 내보내기: 루트에 pack.mcmeta 가 오도록."""
        base = self.store.game_dir(id)
        src = safe_join(base, "datapacks", _check_name(pack, "데이터팩"))
        if not (src / "pack.mcmeta").is_file():
            raise RpcError(f"데이터팩이 아닙니다(pack.mcmeta 없음): {pack}")
        out_dir = safe_join(base, "exports")
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"{pack}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(src.rglob("*")):
                if f.is_file() and ".git" not in f.relative_to(src).parts:
                    z.write(f, f.relative_to(src).as_posix())
        return {"path": str(out)}

    def read_commands(self, reports_dir: str) -> dict[str, Any]:
        """데이터 생성기 commands.json 을 자동완성용 간단한 트리로 줄인다."""
        path = Path(reports_dir) / "reports" / "commands.json"
        if not path.is_file():
            raise RpcError("명령어 목록이 아직 없습니다. '게임 없이 쓸 자동완성 준비'를 실행하세요.")
        tree = json.loads(path.read_text("utf-8"))

        def slim(node: dict, depth: int) -> dict:
            out: dict[str, Any] = {}
            if node.get("type") == "argument":
                out["arg"] = node.get("parser", "")
            if depth < 6:
                kids = node.get("children") or {}
                if kids:
                    out["c"] = {k: slim(v, depth + 1) for k, v in kids.items()}
            if "redirect" in node:
                out["r"] = node["redirect"]
            return out

        registries: dict[str, list[str]] = {}
        reg_path = Path(reports_dir) / "reports" / "registries.json"
        if reg_path.is_file():
            regs = json.loads(reg_path.read_text("utf-8"))
            for key in ("minecraft:item", "minecraft:block", "minecraft:entity_type", "minecraft:mob_effect",
                        "minecraft:particle_type", "minecraft:sound_event", "minecraft:enchantment"):
                if key in regs:
                    registries[key] = sorted(regs[key].get("entries", {}).keys())
        return {"tree": slim(tree, 0), "registries": registries}

    # ---------- 리소스팩 (M6) ----------
    def list_resourcepacks(self, id: str) -> list[str]:
        d = self.store.game_dir(id) / "resourcepacks"
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir()
                      if (p.is_dir() and (p / "pack.mcmeta").is_file()) or p.suffix == ".zip")

    def resourcepack_new(self, id: str, name: str, description: str = "") -> dict[str, Any]:
        meta = self.store.get(id)
        root = safe_join(self.store.game_dir(id), "resourcepacks", _check_name(name, "리소스팩 이름"))
        if root.exists():
            raise RpcError(f"이미 있는 리소스팩입니다: {name}")
        (root / "assets" / "minecraft" / "textures").mkdir(parents=True)
        (root / "pack.mcmeta").write_text(self._pack_mcmeta(meta["version"], "resource", description or name), "utf-8")
        return {"path": str(root)}

    def resourcepack_import(self, id: str, zip_path: str) -> dict[str, Any]:
        """Texel 등에서 내보낸 .zip 을 resourcepacks/<이름>/ 으로 풀어 넣는다."""
        src = Path(zip_path)
        if src.suffix.lower() != ".zip" or not src.is_file():
            raise RpcError("리소스팩 .zip 파일을 고르세요.")
        name = re.sub(r"[^a-z0-9_.\-]", "_", src.stem.lower()) or "pack"
        base = self.store.game_dir(id)
        dest = safe_join(base, "resourcepacks", name)
        if dest.exists():
            trash(dest, base)
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            prefix = ""
            if "pack.mcmeta" not in names:
                tops = {n.split("/")[0] for n in names if "/" in n}
                if len(tops) == 1 and f"{next(iter(tops))}/pack.mcmeta" in names:
                    prefix = next(iter(tops)) + "/"
                else:
                    raise RpcError("zip 안에 pack.mcmeta 가 없습니다.")
            for info in z.infolist():
                if not info.filename.startswith(prefix) or info.is_dir():
                    continue
                rel = info.filename[len(prefix):]
                target = safe_join(dest, rel)  # zip slip 방지
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as fsrc, open(target, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
        return {"name": name, "path": str(dest)}

    def resourcepack_apply(self, id: str, pack: str) -> dict[str, Any]:
        """options.txt 의 resourcePacks 에 file/<팩> 을 맨 위(마지막)로 넣는다. 다음 실행 또는 리소스 다시 불러오기에서 적용."""
        base = self.store.game_dir(id)
        safe_join(base, "resourcepacks", pack)
        opts = safe_join(base, "options.txt")
        lines = opts.read_text("utf-8").splitlines() if opts.exists() else []
        entry = f"file/{pack}"
        packs: list[str] = ["vanilla"]
        idx = next((i for i, l in enumerate(lines) if l.startswith("resourcePacks:")), None)
        if idx is not None:
            try:
                packs = json.loads(lines[idx].split(":", 1)[1])
            except json.JSONDecodeError:
                packs = ["vanilla"]
        packs = [p for p in packs if p != entry] + [entry]
        line = "resourcePacks:" + json.dumps(packs)
        if idx is None:
            lines.append(line)
        else:
            lines[idx] = line
        opts.write_text("\n".join(lines) + "\n", "utf-8")
        return {"resourcePacks": packs}

    # ---------- Fabric 모드 (M7) ----------
    @staticmethod
    def _latest_versions(mc: str) -> dict[str, str]:
        """설치 시점의 최신 안정판을 확인한다. 네트워크가 안 되면 2026-11 확인값을 쓴다."""
        found = {"loader": "0.20.1", "loom": "1.19.4", "fabric_api": f"0.166.2+{mc}", "gradle": "9.8.2", "checked": False}

        def get(url: str) -> bytes:
            return net.get_bytes(url, timeout=20)

        def vkey(v: str) -> tuple:
            return tuple(int(x) for x in re.findall(r"\d+", v))

        try:
            loaders = json.loads(get("https://meta.fabricmc.net/v2/versions/loader"))
            found["loader"] = next(l["version"] for l in loaders if l.get("stable"))
            xml = get("https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/maven-metadata.xml").decode()
            apis = [v for v in re.findall(r"<version>([^<]+)</version>", xml) if v.endswith(f"+{mc}")]
            if apis:
                found["fabric_api"] = max(apis, key=vkey)
            xml = get("https://maven.fabricmc.net/net/fabricmc/fabric-loom/"
                      "net.fabricmc.fabric-loom.gradle.plugin/maven-metadata.xml").decode()
            looms = [v for v in re.findall(r"<version>([^<]+)</version>", xml) if re.fullmatch(r"\d+\.\d+\.\d+", v)]
            if looms:
                found["loom"] = max(looms, key=vkey)
            g = json.loads(get("https://services.gradle.org/versions/current"))
            found["gradle"] = g["version"]
            found["checked"] = True
        except Exception:  # noqa: BLE001
            pass
        return found

    def mod_new(self, id: str, modid: str, name: str, group: str = "com.example") -> dict[str, Any]:
        meta = self.store.get(id)
        if meta["loader"] != "fabric":
            raise RpcError("모드 템플릿은 Fabric 인스턴스에서 만들 수 있습니다(테스트 인스턴스로 씀).")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", modid or ""):
            raise RpcError("모드 ID는 소문자로 시작하고 소문자·숫자·_ 만 2~64자.")
        if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", group or ""):
            raise RpcError("그룹은 com.example 같은 패키지 이름이어야 합니다.")
        base = self.store.game_dir(id)
        root = safe_join(base, "mods-src", modid)
        if root.exists():
            raise RpcError(f"이미 있는 모드 폴더입니다: {modid}")
        v = self._latest_versions(meta["version"])
        cls = "".join(p.capitalize() for p in modid.split("_")) + "Mod"
        pkg = f"{group}.{modid}"
        java_dir = root / "src" / "main" / "java" / Path(*pkg.split("."))
        res = root / "src" / "main" / "resources"
        java_dir.mkdir(parents=True)
        (res / "assets" / modid / "lang").mkdir(parents=True)

        shutil.copytree(TEMPLATES / "gradle-wrapper", root, dirs_exist_ok=True)
        (root / "gradle" / "wrapper" / "gradle-wrapper.properties").write_text(
            "distributionBase=GRADLE_USER_HOME\ndistributionPath=wrapper/dists\n"
            f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{v['gradle']}-bin.zip\n"
            "networkTimeout=10000\nvalidateDistributionUrl=true\n"
            "zipStoreBase=GRADLE_USER_HOME\nzipStorePath=wrapper/dists\n", "utf-8")
        (root / "settings.gradle").write_text(
            "pluginManagement {\n\trepositories {\n\t\tmaven {\n\t\t\tname = 'Fabric'\n"
            "\t\t\turl = 'https://maven.fabricmc.net/'\n\t\t}\n\t\tmavenCentral()\n\t\tgradlePluginPortal()\n\t}\n}\n\n"
            f"rootProject.name = '{modid}'\n", "utf-8")
        (root / "gradle.properties").write_text(
            "org.gradle.jvmargs=-Xmx2G\norg.gradle.parallel=true\n\n"
            f"# 통합 작업실이 만든 템플릿 ({'버전 확인됨' if v['checked'] else '오프라인 — 기본값'})\n"
            f"minecraft_version={meta['version']}\nloader_version={v['loader']}\n"
            f"loom_version={v['loom']}\nfabric_api_version={v['fabric_api']}\n\n"
            f"version=0.1.0\ngroup={group}\n", "utf-8")
        (root / "build.gradle").write_text(
            "plugins {\n\tid 'net.fabricmc.fabric-loom' version \"${loom_version}\"\n}\n\n"
            "dependencies {\n"
            "\tminecraft \"com.mojang:minecraft:${project.minecraft_version}\"\n"
            "\timplementation \"net.fabricmc:fabric-loader:${project.loader_version}\"\n"
            "\timplementation \"net.fabricmc.fabric-api:fabric-api:${project.fabric_api_version}\"\n}\n\n"
            "processResources {\n\tdef version = project.version\n\tinputs.property \"version\", version\n"
            "\tfilesMatching(\"fabric.mod.json\") {\n\t\texpand \"version\": version\n\t}\n}\n\n"
            "tasks.withType(JavaCompile).configureEach {\n\tit.options.release = 25\n\tit.options.encoding = \"UTF-8\"\n}\n\n"
            "java {\n\tsourceCompatibility = JavaVersion.VERSION_25\n\ttargetCompatibility = JavaVersion.VERSION_25\n}\n",
            "utf-8")
        (res / "fabric.mod.json").write_text(json.dumps({
            "schemaVersion": 1,
            "id": modid,
            "version": "${version}",
            "name": name or modid,
            "description": f"{name or modid} — 통합 작업실에서 만든 모드",
            "license": "All-Rights-Reserved",
            "environment": "*",
            "entrypoints": {"main": [f"{pkg}.{cls}"]},
            "depends": {"fabricloader": f">={v['loader']}", "minecraft": f"~{meta['version']}", "java": ">=25",
                        "fabric-api": "*"},
        }, ensure_ascii=False, indent=2) + "\n", "utf-8")
        (java_dir / f"{cls}.java").write_text(
            f"package {pkg};\n\n"
            "import net.fabricmc.api.ModInitializer;\n"
            "import net.minecraft.resources.Identifier;\n"
            "import org.slf4j.Logger;\nimport org.slf4j.LoggerFactory;\n\n"
            f"public class {cls} implements ModInitializer {{\n"
            f"\tpublic static final String MOD_ID = \"{modid}\";\n"
            "\tpublic static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);\n\n"
            "\tpublic static Identifier id(String path) {\n"
            "\t\treturn Identifier.fromNamespaceAndPath(MOD_ID, path);\n\t}\n\n"
            "\t@Override\n\tpublic void onInitialize() {\n"
            f"\t\tLOGGER.info(\"{name or modid} 불러옴\");\n\t}}\n}}\n", "utf-8")
        (res / "assets" / modid / "lang" / "ko_kr.json").write_text("{}\n", "utf-8")
        (root / ".gitignore").write_text(".gradle/\nbuild/\nrun/\n*.iml\n.idea/\n", "utf-8")
        for script in ("gradlew",):
            (root / script).chmod(0o755)
        return {"path": str(root), "open": str(java_dir / f"{cls}.java"), "versions": v}

    def list_mod_projects(self, id: str) -> list[str]:
        d = self.store.game_dir(id) / "mods-src"
        return sorted(p.name for p in d.iterdir() if (p / "build.gradle").is_file()) if d.is_dir() else []

    def mod_build(self, id: str, modid: str) -> dict[str, Any]:
        """./gradlew build → build/libs 의 jar(-sources 제외)를 인스턴스 mods/ 에 복사."""
        base = self.store.game_dir(id)
        root = safe_join(base, "mods-src", _check_name(modid, "모드 ID"))
        if not (root / "build.gradle").is_file():
            raise RpcError(f"모드 프로젝트가 없습니다: {modid}")
        if id in self.builds:
            raise RpcError("이미 빌드 중입니다.")
        win = sys.platform == "win32"
        cmd = [str(root / ("gradlew.bat" if win else "gradlew")), "build", "--console=plain"]
        env = dict(os.environ)  # 빌드는 사용자가 설치한 JDK 25(JAVA_HOME)를 쓴다. 게임용 런타임에는 javac가 없다
        notify("log", {"id": id, "level": "info", "source": "build", "line": f"빌드 시작: {modid} (./gradlew build)"})
        proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.builds[id] = proc
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    level = "error" if ("error:" in line or "FAILED" in line) else "warn" if "warning:" in line else "info"
                    notify("log", {"id": id, "level": level, "source": "build", "line": line})
            code = proc.wait()
        finally:
            self.builds.pop(id, None)
        if code != 0:
            raise RpcError(f"빌드 실패(코드 {code}). 게임 로그 탭의 빌드 출력을 확인하세요. JDK 25가 설치돼 있고 JAVA_HOME이 그 JDK를 가리켜야 합니다.")
        libs = root / "build" / "libs"
        jars = [j for j in libs.glob("*.jar") if not j.name.endswith(("-sources.jar", "-dev.jar"))]
        if not jars:
            raise RpcError("build/libs 에서 jar를 찾지 못했습니다.")
        jar = max(jars, key=lambda j: j.stat().st_mtime)
        mods = base / "mods"
        for old in mods.glob(f"{modid}-*.jar"):
            trash(old, base)
        dest = safe_join(mods, jar.name)
        shutil.copy2(jar, dest)
        notify("log", {"id": id, "level": "info", "source": "build", "line": f"빌드 완료 → mods/{jar.name}"})
        return {"jar": str(dest)}

    def open_external(self, id: str, rel: str) -> bool:
        """폴더를 외부 IDE로 연다: IntelliJ(idea) 명령이 있으면 그것, 없으면 OS 기본 프로그램."""
        target = safe_join(self.store.game_dir(id), rel)
        if not target.exists():
            raise RpcError(f"폴더가 없습니다: {rel}")
        for ide in ("idea", "idea64.exe", "idea.cmd"):
            exe = shutil.which(ide)
            if exe:
                subprocess.Popen([exe, str(target)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return True
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return True
