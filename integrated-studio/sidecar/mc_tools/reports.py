"""버전별 정답 자료.

- data/reports/<버전>/reports/  서버 jar 데이터 생성기(--reports) 결과: commands.json, registries.json, blocks.json …
- data/vanilla/<버전>/          클라이언트 jar 의 data/minecraft/** (레시피·루트테이블·태그·발전과제·월드 생성 …),
                                version.json, assets_index.txt(에셋 경로 목록만, 내용은 풀지 않음)
                                — 참고용. 인스턴스 밖으로 배포하지 않는다.
- data/reports/<버전>/reload_kinds.json  /reload 로 바뀌는 데이터 종류와 월드를 다시 불러와야 하는 종류

pack_format 은 하드코딩하지 않고 jar 의 version.json 에서 읽는다.
"""
from __future__ import annotations

import json
import re
import zipfile
from functools import cached_property
from pathlib import Path
from typing import Any

from .context import ToolError

# 서버의 ReloadableServerResources 가 /reload 때 다시 읽는 데이터 종류(데이터팩 폴더 이름).
# 이 목록은 "어떤 관리자가 /reload 에 참여하는가"라는 게임 구조이고, 실제로 그 버전에 있는 종류인지는
# 아래 classify() 가 그 버전의 바닐라 data 폴더와 registries.json 으로 확인한다.
RELOAD_MANAGERS = ("function", "recipe", "advancement", "loot_table", "predicate", "item_modifier")
# data/minecraft 아래지만 데이터 종류가 아닌 폴더(게임에 든 내장 데이터팩)
NOT_KINDS = {"datapacks"}
VERSION_RE = re.compile(r"[0-9A-Za-z._\-]{1,64}")


class VersionData:
    """한 게임 버전의 자료. 파일이 없으면 ensure() 로 만든다."""

    def __init__(self, data_dir: Path, version: str):
        if not VERSION_RE.fullmatch(version or ""):
            raise ToolError(f"잘못된 버전입니다: {version!r}")
        self.data_dir = Path(data_dir)
        self.version = version
        self.reports_dir = self.data_dir / "reports" / version
        self.vanilla_dir = self.data_dir / "vanilla" / version

    # ---------- 만들기 ----------
    @property
    def client_jar(self) -> Path:
        return self.data_dir / "minecraft" / "versions" / self.version / f"{self.version}.jar"

    def has_reports(self) -> bool:
        return (self.reports_dir / "reports" / "commands.json").is_file()

    def has_vanilla(self) -> bool:
        return (self.vanilla_dir / "version.json").is_file()

    def ensure(self, generate: bool = True) -> dict[str, Any]:
        """없는 자료를 만든다. generate=False 면 확인만."""
        done: list[str] = []
        if not self.has_vanilla():
            if not generate:
                raise ToolError(self._missing_msg())
            self.extract_vanilla()
            done.append("바닐라 data·version.json 추출")
        if not self.has_reports():
            if not generate:
                raise ToolError(self._missing_msg())
            self.generate_reports()
            done.append("데이터 생성기(--reports) 실행")
        if not (self.reports_dir / "reload_kinds.json").is_file():
            self.write_reload_kinds()
            done.append("/reload 대상 목록 작성")
        return {"version": self.version, "made": done}

    def _missing_msg(self) -> str:
        return (f"{self.version} 버전 자료가 아직 없습니다. 인스턴스를 설치한 뒤 mc-tools 의 prepare_version_data 를 "
                "한 번 실행하세요(서버 데이터 생성기를 돌려 명령어·ID 목록을 만듭니다).")

    def extract_vanilla(self) -> None:
        jar = self.client_jar
        if not jar.is_file():
            raise ToolError(f"{self.version} 게임 파일(클라이언트 jar)이 없습니다. 인스턴스를 먼저 설치하세요.")
        out = self.vanilla_dir
        out.mkdir(parents=True, exist_ok=True)
        assets: list[str] = []
        with zipfile.ZipFile(jar) as z:
            for info in z.infolist():
                name = info.filename
                if info.is_dir():
                    continue
                if name.startswith("data/minecraft/") and not name.startswith("data/minecraft/structure/"):
                    dest = (out / name).resolve()
                    if out.resolve() not in dest.parents:
                        continue  # zip slip 방지
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(info))
                elif name.startswith("assets/"):
                    assets.append(name)
            (out / "version.json").write_bytes(z.read("version.json"))
        (out / "assets_index.txt").write_text("\n".join(sorted(assets)) + "\n", "utf-8")

    def generate_reports(self) -> None:
        """사이드카 Runner 의 데이터 생성기를 그대로 쓴다(서버 jar·자바 런타임 준비 포함). 진행 알림은 끈다."""
        import runner as runner_mod  # 사이드카 모듈
        from instances import InstanceStore

        runner_mod.notify = lambda *a, **k: None  # MCP 표준 출력에 사이드카 알림이 섞이지 않게
        r = runner_mod.Runner(self.data_dir, InstanceStore(self.data_dir))
        try:
            r.generate_reports(self.version)
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"데이터 생성기를 실행하지 못했습니다: {e}") from e

    # ---------- 읽기 ----------
    def _report(self, name: str) -> Any:
        p = self.reports_dir / "reports" / name
        if not p.is_file():
            raise ToolError(self._missing_msg())
        return json.loads(p.read_text("utf-8"))

    @cached_property
    def commands(self) -> dict[str, Any]:
        return self._report("commands.json")

    @cached_property
    def registries(self) -> dict[str, set[str]]:
        raw = self._report("registries.json")
        return {k: set(v.get("entries", {})) for k, v in raw.items()}

    @cached_property
    def blocks(self) -> dict[str, Any]:
        try:
            return self._report("blocks.json")
        except ToolError:
            return {}

    @cached_property
    def version_json(self) -> dict[str, Any]:
        p = self.vanilla_dir / "version.json"
        if not p.is_file():
            if self.client_jar.is_file():
                with zipfile.ZipFile(self.client_jar) as z:
                    return json.loads(z.read("version.json"))
            raise ToolError(self._missing_msg())
        return json.loads(p.read_text("utf-8"))

    @cached_property
    def pack_formats(self) -> dict[str, tuple[int, int]]:
        pv = self.version_json.get("pack_version")
        if isinstance(pv, int):
            return {"data": (pv, 0), "resource": (pv, 0)}
        return {"data": (int(pv["data_major"]), int(pv.get("data_minor", 0))),
                "resource": (int(pv["resource_major"]), int(pv.get("resource_minor", 0)))}

    def pack_format_json(self, kind: str) -> Any:
        major, minor = self.pack_formats[kind]
        return major if minor == 0 else [major, minor]

    @cached_property
    def vanilla_data(self) -> Path:
        return self.vanilla_dir / "data" / "minecraft"

    @cached_property
    def vanilla_kinds(self) -> set[str]:
        """바닐라 data/minecraft 아래의 데이터 종류 폴더(중첩 worldgen/* 포함, tags 는 tags/<레지스트리>)."""
        kinds: set[str] = set()
        base = self.vanilla_data
        if not base.is_dir():
            return kinds
        for f in base.rglob("*.json"):
            rel = f.relative_to(base).parts
            if rel[0] in NOT_KINDS:
                continue
            kinds.add(self._kind_of(rel))
        return kinds

    def _kind_of(self, rel_parts: tuple[str, ...]) -> str:
        """data/<ns>/ 다음 경로 조각에서 데이터 종류를 뽑는다. worldgen/biome, tags/worldgen/biome 처럼 레지스트리 이름이 2단계일 수 있다."""
        if not rel_parts:
            return ""
        if rel_parts[0] == "tags":
            reg = self._registry_prefix(rel_parts[1:])
            return "tags/" + reg if reg else "tags"
        return self._registry_prefix(rel_parts) or rel_parts[0]

    def _registry_prefix(self, parts: tuple[str, ...]) -> str:
        if not parts:
            return ""
        if len(parts) >= 3 and f"{parts[0]}/{parts[1]}" in self._two_level:
            return f"{parts[0]}/{parts[1]}"
        return parts[0]

    @cached_property
    def _two_level(self) -> set[str]:
        """worldgen/biome 같은 2단계 레지스트리 이름(registries.json·바닐라 폴더에서)."""
        names = {k.split(":", 1)[1] for k in self._safe_registry_names() if "/" in k}
        base = self.vanilla_data
        if base.is_dir():
            for top in ("worldgen",):
                if (base / top).is_dir():
                    names |= {f"{top}/{d.name}" for d in (base / top).iterdir() if d.is_dir()}
        return names

    def _safe_registry_names(self) -> list[str]:
        try:
            return list(self.registries)
        except ToolError:
            return []

    def kind_of_path(self, rel_from_namespace: tuple[str, ...]) -> str:
        return self._kind_of(rel_from_namespace)

    # ---------- /reload 판단 ----------
    def classify(self) -> dict[str, list[str]]:
        """그 버전의 데이터 종류를 /reload 대상과 월드 재접속 대상으로 나눈다.
        - /reload: RELOAD_MANAGERS + 정적 레지스트리(registries.json 에 있는 것)의 태그
        - 월드 로드 때만: 나머지 바닐라 데이터 종류(동적 레지스트리: 월드 생성·차원·인챈트·피해 유형 …)와 그 태그"""
        static = {k.split(":", 1)[1] for k in self._safe_registry_names()}
        reload: set[str] = set(RELOAD_MANAGERS) | {"tags/function"}
        world: set[str] = set()
        for kind in self.vanilla_kinds | {f"tags/{s}" for s in static}:
            if kind in RELOAD_MANAGERS:
                continue
            if kind.startswith("tags/"):
                reg = kind[5:]
                if reg in RELOAD_MANAGERS or reg in static:
                    reload.add(kind)
                else:
                    world.add(kind)
            elif kind not in static:
                world.add(kind)
        world.discard("structure")  # 구조물(.nbt)은 새로 만드는 구조물부터 쓰인다 — 별도 안내
        return {"reload": sorted(reload), "world": sorted(world)}

    def write_reload_kinds(self) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        data = {"version": self.version, **self.classify(),
                "note": "reload = /reload 로 바로 바뀜, world = 월드를 다시 열어야 바뀜(월드 생성은 새로 생기는 청크부터)"}
        (self.reports_dir / "reload_kinds.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    @cached_property
    def reload_kinds(self) -> dict[str, set[str]]:
        p = self.reports_dir / "reload_kinds.json"
        data = json.loads(p.read_text("utf-8")) if p.is_file() else self.classify()
        return {"reload": set(data["reload"]), "world": set(data["world"])}

    def needs_world_reload(self, kind: str) -> bool:
        """알 수 없는 종류는 안전하게 '재접속 필요'로 본다."""
        if kind in ("", "pack.mcmeta"):
            return False
        return kind not in self.reload_kinds["reload"]

    # ---------- ID ----------
    def registry_ids(self, registry: str) -> set[str] | None:
        """레지스트리의 ID 목록. 정적 레지스트리는 registries.json, 동적 레지스트리는 바닐라 data 폴더의 파일 이름.
        모르는 레지스트리면 None."""
        key = registry if ":" in registry else f"minecraft:{registry}"
        if key in self.registries:
            return self.registries[key]
        folder = self.vanilla_data / key.split(":", 1)[1]
        if folder.is_dir():
            return {"minecraft:" + f.relative_to(folder).with_suffix("").as_posix() for f in folder.rglob("*.json")}
        return None

    def tag_ids(self, registry: str) -> set[str]:
        folder = self.vanilla_data / "tags" / registry.split(":", 1)[-1]
        if not folder.is_dir():
            return set()
        return {"minecraft:" + f.relative_to(folder).with_suffix("").as_posix() for f in folder.rglob("*.json")}

    @cached_property
    def assets_index(self) -> set[str]:
        p = self.vanilla_dir / "assets_index.txt"
        if p.is_file():
            return {ln for ln in p.read_text("utf-8").splitlines() if ln}
        return set()

    def has_vanilla_asset(self, path: str) -> bool:
        """assets/minecraft/... 경로가 바닐라에 있는지(목록이 없으면 모름 → True)."""
        if not self.assets_index:
            return True
        return path in self.assets_index


def load(data_dir: Path, version: str, generate: bool = False) -> VersionData:
    vd = VersionData(data_dir, version)
    vd.ensure(generate=generate)
    return vd
