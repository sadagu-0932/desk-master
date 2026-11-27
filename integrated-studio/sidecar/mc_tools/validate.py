"""데이터팩·리소스팩·모드 리소스 검사. 결과는 "파일:줄: 설명" 목록.

근거는 그 인스턴스 버전의 자료(reports.VersionData)다. 기억으로 쓴 규칙은 없다:
- 폴더 이름: 그 버전 바닐라 data 의 폴더 이름과 비교(구버전 복수형 → 오류)
- pack.mcmeta: jar 의 version.json 형식 번호, 필요한 키는 jar 안 내장 데이터팩의 pack.mcmeta 와 같게
- 명령어: commands.json 트리, ID: registries.json·바닐라 data
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .commands import CommandChecker
from .reports import RELOAD_MANAGERS, VersionData

RL_PATH_RE = re.compile(r"[a-z0-9_.\-/]+")
NS_RE = re.compile(r"[a-z0-9_.\-]+")
MACRO_VAR_RE = re.compile(r"\$\(([A-Za-z0-9_]+)\)")


@dataclass
class Problem:
    file: str
    line: int
    message: str
    severity: str = "error"

    def text(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        mark = "" if self.severity == "error" else "(경고) "
        return f"{where}: {mark}{self.message}"


@dataclass
class Report:
    kind: str
    root: Path
    problems: list[Problem] = field(default_factory=list)
    checked_files: int = 0
    namespaces: set[str] = field(default_factory=set)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, file: Path | str, line: int, message: str, severity: str = "error") -> None:
        rel = file if isinstance(file, str) else _rel(file, self.root)
        self.problems.append(Problem(rel, line, message, severity))

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "kind": self.kind, "path": str(self.root), "files": self.checked_files,
                "errors": [p.text() for p in self.errors],
                "warnings": [p.text() for p in self.problems if p.severity != "error"]}

    def summary(self) -> str:
        if self.ok:
            w = len(self.problems)
            return f"검사 통과: {self.root.name} ({self.checked_files}개 파일{f', 경고 {w}개' if w else ''})"
        lines = [f"검사 실패: {self.root.name} — 오류 {len(self.errors)}개"]
        lines += [p.text() for p in self.problems]
        return "\n".join(lines)


def _rel(p: Path, root: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return str(p)


def _json_error(e: json.JSONDecodeError) -> str:
    return f"JSON 문법 오류: {e.msg} (줄 {e.lineno}, 칸 {e.colno})"


def _load_json(path: Path, rep: Report) -> Any:
    try:
        text = path.read_text("utf-8")
    except UnicodeDecodeError:
        rep.add(path, 0, "UTF-8 로 저장해야 합니다")
        return None
    if text.startswith("﻿"):
        rep.add(path, 1, "파일 맨 앞에 BOM 이 있습니다 — BOM 없는 UTF-8 로 저장하세요")
        text = text[1:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        rep.add(path, e.lineno, _json_error(e))
        return None


def _format_tuple(v: Any) -> tuple[int, int] | None:
    if isinstance(v, int):
        return (v, 0)
    if isinstance(v, list) and v and all(isinstance(x, int) for x in v):
        return (v[0], v[1] if len(v) > 1 else 0)
    return None


# ================================================================ pack.mcmeta
def _expected_pack_keys(vd: VersionData) -> set[str]:
    """그 버전 jar 안 내장 데이터팩의 pack.mcmeta 에 있는 형식 키(min_format/max_format 또는 pack_format)."""
    keys: set[str] = set()
    base = vd.vanilla_data / "datapacks"
    if base.is_dir():
        for f in base.glob("*/pack.mcmeta"):
            try:
                pack = json.loads(f.read_text("utf-8")).get("pack", {})
                keys |= {k for k in pack if k in ("pack_format", "min_format", "max_format")}
            except (OSError, ValueError):
                pass
    return keys or {"min_format", "max_format"}


def check_pack_mcmeta(root: Path, vd: VersionData, kind: str, rep: Report) -> None:
    f = root / "pack.mcmeta"
    if not f.is_file():
        rep.add("pack.mcmeta", 0, "pack.mcmeta 가 없습니다(팩 폴더 바로 아래에 있어야 합니다)")
        return
    data = _load_json(f, rep)
    if data is None:
        return
    pack = data.get("pack") if isinstance(data, dict) else None
    if not isinstance(pack, dict):
        rep.add(f, 1, '"pack" 항목이 없습니다')
        return
    if "description" not in pack:
        rep.add(f, 1, '"pack.description" 이 없습니다')
    cur = vd.pack_formats[kind]
    cur_txt = f"{cur[0]}" if cur[1] == 0 else f"[{cur[0]}, {cur[1]}]"
    want = _expected_pack_keys(vd)
    lo = _format_tuple(pack.get("min_format"))
    hi = _format_tuple(pack.get("max_format"))
    if hi and isinstance(pack.get("max_format"), int):
        hi = (hi[0], 10 ** 9)  # 정수만 쓰면 그 큰 번호의 모든 작은 번호까지
    pf = _format_tuple(pack.get("pack_format"))
    missing = [k for k in sorted(want) if k not in pack]
    if missing:
        rep.add(f, 1, f"이 버전({vd.version})의 pack.mcmeta 에는 {', '.join(missing)} 가 필요합니다(현재 형식 {cur_txt})")
    if lo and hi:
        if not (lo <= cur <= hi):
            rep.add(f, 1, f"형식 범위 {pack.get('min_format')}~{pack.get('max_format')} 가 이 버전({vd.version}, 형식 {cur_txt})을 포함하지 않습니다")
    elif pf and not (lo or hi) and pf[0] != cur[0]:
        rep.add(f, 1, f"pack_format {pf[0]} 은(는) 이 버전({vd.version}, 형식 {cur_txt})과 다릅니다")


# ================================================================ 데이터팩
class DatapackValidator:
    def __init__(self, vd: VersionData):
        self.vd = vd
        self._checker: CommandChecker | None = None

    def known_kinds(self) -> set[str]:
        rk = self.vd.reload_kinds
        return rk["reload"] | rk["world"] | {"structure", "tags/function"} | set(RELOAD_MANAGERS)

    def checker(self) -> CommandChecker:
        if self._checker is None:
            vd = self.vd

            def tag_lookup(registry: str, nid: str) -> bool:
                return nid in vd.tag_ids(registry) or nid in self._pack_tags.get(registry.split(":", 1)[1], set())

            self._checker = CommandChecker(vd.commands, vd.registry_ids, vd.blocks, tag_lookup)
        return self._checker

    def validate(self, root: Path) -> Report:
        root = Path(root).resolve()
        rep = Report("datapack", root)
        check_pack_mcmeta(root, self.vd, "data", rep)
        data = root / "data"
        if not data.is_dir():
            rep.add("data", 0, "data 폴더가 없습니다(data/<네임스페이스>/function/... 구조)")
            return rep
        known = self.known_kinds()
        functions: dict[str, Path] = {}
        self._pack_tags: dict[str, set[str]] = {}
        files: list[tuple[Path, str, str, tuple[str, ...]]] = []   # (파일, ns, kind, kind 뒤 경로)
        for ns_dir in sorted(p for p in data.iterdir() if p.is_dir()):
            ns = ns_dir.name
            if not NS_RE.fullmatch(ns):
                rep.add(ns_dir, 0, f"네임스페이스 '{ns}' 에는 소문자·숫자·_ . - 만 쓸 수 있습니다")
                continue
            rep.namespaces.add(ns)
            for f in sorted(p for p in ns_dir.rglob("*") if p.is_file()):
                rel = f.relative_to(ns_dir).parts
                kind = self.vd.kind_of_path(rel)
                n_kind = len(kind.split("/"))
                rest = rel[n_kind:]
                files.append((f, ns, kind, rest))
                rep.checked_files += 1
        # 폴더 이름 검사 + 참조 목록 만들기
        reported_dirs: set[str] = set()
        for f, ns, kind, rest in files:
            dir_key = f"{ns}/{kind}"
            if kind not in known:
                if dir_key not in reported_dirs:
                    reported_dirs.add(dir_key)
                    rep.add(f"data/{ns}/{kind}", 0, self._unknown_kind_msg(kind, known),
                            "error" if self._old_name(kind, known) else "warning")
                continue
            path_str = "/".join(rest)
            if not RL_PATH_RE.fullmatch(path_str.rsplit(".", 1)[0] if "." in path_str else path_str):
                rep.add(f, 0, "파일·폴더 이름에는 소문자·숫자·_ . - / 만 쓸 수 있습니다(대문자·공백·한글 불가)")
            if kind == "function":
                if f.suffix != ".mcfunction":
                    rep.add(f, 0, "function 폴더에는 .mcfunction 파일만 둡니다", "warning")
                else:
                    functions[f"{ns}:{path_str[:-len('.mcfunction')]}"] = f
            elif kind.startswith("tags/") and f.suffix == ".json":
                self._pack_tags.setdefault(kind[5:], set()).add(f"{ns}:{path_str[:-5]}")
        # 파일 내용
        function_tags = self._pack_tags.get("function", set())
        refs: list[tuple[Path, int, str, str]] = []
        for f, _ns, kind, _rest in files:
            if kind not in known:
                continue
            if f.suffix == ".json":
                obj = _load_json(f, rep)
                if obj is not None:
                    self._check_json(f, kind, obj, rep, refs)
            elif f.suffix == ".mcfunction" and kind == "function":
                self._check_function(f, rep, refs)
        # 참조 검사
        for f, line, rkind, rid in refs:
            ns = rid.split(":", 1)[0]
            if rkind == "function":
                if rid in functions:
                    continue
                msg = f"없는 함수를 부릅니다: {rid}"
            else:
                if rid in function_tags or (ns == "minecraft" and rid in ("minecraft:load", "minecraft:tick")):
                    continue
                msg = f"없는 함수 태그를 부릅니다: #{rid}"
            if ns in rep.namespaces or ns == "minecraft":
                rep.add(f, line, msg + f" (data/{ns}/{'function' if rkind == 'function' else 'tags/function'}/ 에 만들어야 합니다)")
            else:
                rep.add(f, line, msg + " — 다른 데이터팩에 있어야 합니다", "warning")
        self._spyglass(root, rep)
        return rep

    @staticmethod
    def _old_name(kind: str, known: set[str]) -> str | None:
        head, _, last = kind.rpartition("/")
        if last.endswith("s"):
            single = (head + "/" if head else "") + last[:-1]
            if single in known:
                return single
        return None

    def _unknown_kind_msg(self, kind: str, known: set[str]) -> str:
        single = self._old_name(kind, known)
        if single:
            return f"구버전 폴더 이름입니다: '{kind}' → 이 버전({self.vd.version})에서는 '{single}' (게임이 읽지 않습니다)"
        return f"이 버전({self.vd.version})이 읽지 않는 폴더입니다: '{kind}'"

    # ---------- .mcfunction ----------
    def _check_function(self, f: Path, rep: Report, refs: list) -> None:
        try:
            lines = f.read_text("utf-8").split("\n")
        except UnicodeDecodeError:
            rep.add(f, 0, "UTF-8 로 저장해야 합니다")
            return
        if lines and lines[0].startswith("﻿"):
            rep.add(f, 1, "파일 맨 앞에 BOM 이 있습니다 — BOM 없는 UTF-8 로 저장하세요")
            lines[0] = lines[0][1:]
        checker = self.checker()
        i = 0
        while i < len(lines):
            start = i
            raw = lines[i].rstrip("\r")
            while raw.endswith("\\") and i + 1 < len(lines):  # 줄 이어 쓰기
                i += 1
                raw = raw[:-1] + lines[i].rstrip("\r").lstrip()
            i += 1
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            if text.startswith("$"):
                self._check_macro(f, start + 1, text, rep)
                continue
            res = checker.check(text)
            for issue in res.issues:
                col = f"{issue.col + 1}칸: " if issue.col else ""
                rep.add(f, start + 1, f"{col}{issue.message}  ← {text[:80]}", issue.severity)
            for rkind, rid in res.refs:
                refs.append((f, start + 1, rkind, rid))

    def _check_macro(self, f: Path, line: int, text: str, rep: Report) -> None:
        body = text[1:]
        if not MACRO_VAR_RE.search(body):
            rep.add(f, line, "매크로 줄($)에 $(이름) 변수가 없습니다 — 변수가 없으면 $ 를 빼세요")
        first = body.split(" ", 1)[0]
        if "$(" not in first and first not in self.vd.commands.get("children", {}):
            rep.add(f, line, f"알 수 없는 명령어입니다: '{first}'")
        # 변수 자리를 값으로 바꾸면 검사할 수 있는 줄만 추가로 검사한다(숫자·ID 자리 등은 알 수 없으니 건너뜀)

    # ---------- JSON ----------
    def _check_json(self, f: Path, kind: str, obj: Any, rep: Report, refs: list) -> None:
        vd = self.vd
        if kind.startswith("tags/"):
            reg = kind[5:]
            if not isinstance(obj, dict) or not isinstance(obj.get("values"), list):
                rep.add(f, 1, '태그에는 "values" 목록이 있어야 합니다')
                return
            ids = vd.registry_ids(reg) if reg != "function" else None
            for v in obj["values"]:
                vid = v.get("id") if isinstance(v, dict) else v
                if not isinstance(vid, str):
                    rep.add(f, 1, f"태그 값은 문자열 ID 또는 {{\"id\":…}} 이어야 합니다: {v!r}")
                    continue
                is_tag = vid.startswith("#")
                nid = vid.lstrip("#")
                nid = nid if ":" in nid else f"minecraft:{nid}"
                if reg == "function":
                    refs.append((f, 1, "function_tag" if is_tag else "function", nid))
                elif nid.startswith("minecraft:"):
                    if is_tag:
                        if nid not in vd.tag_ids(reg) and nid not in self._pack_tags.get(reg, set()):
                            rep.add(f, 1, f"없는 태그입니다({reg}): #{nid}")
                    elif ids is not None and nid not in ids:
                        rep.add(f, 1, f"없는 ID 입니다({reg}): {nid}")
            return
        if not isinstance(obj, dict):
            rep.add(f, 1, "JSON 최상위는 객체({ … })여야 합니다")
            return
        if kind == "advancement":
            if "criteria" not in obj:
                rep.add(f, 1, '발전과제에는 "criteria" 가 있어야 합니다')
            fn = (obj.get("rewards") or {}).get("function")
            if isinstance(fn, str):
                refs.append((f, 1, "function", fn if ":" in fn else f"minecraft:{fn}"))
        elif kind == "recipe":
            self._check_type(f, obj.get("type"), "minecraft:recipe_serializer", "레시피 type", rep)
            res = obj.get("result")
            if isinstance(res, dict) and isinstance(res.get("id"), str):
                self._check_item(f, res["id"], rep)
        elif kind == "loot_table":
            for pool in obj.get("pools", []) or []:
                for entry in (pool or {}).get("entries", []) or []:
                    if not isinstance(entry, dict):
                        continue
                    self._check_type(f, entry.get("type"), "minecraft:loot_pool_entry_type", "루트 항목 type", rep)
                    if str(entry.get("type", "")).endswith(":item") and isinstance(entry.get("name"), str):
                        self._check_item(f, entry["name"], rep)

    def _check_type(self, f: Path, value: Any, registry: str, label: str, rep: Report) -> None:
        if not isinstance(value, str):
            rep.add(f, 1, f"{label} 이(가) 없습니다")
            return
        nid = value if ":" in value else f"minecraft:{value}"
        ids = self.vd.registry_ids(registry)
        if nid.startswith("minecraft:") and ids is not None and nid not in ids:
            rep.add(f, 1, f"없는 {label}: {nid}")

    def _check_item(self, f: Path, value: str, rep: Report) -> None:
        nid = value if ":" in value else f"minecraft:{value}"
        ids = self.vd.registry_ids("minecraft:item")
        if nid.startswith("minecraft:") and ids is not None and nid not in ids:
            rep.add(f, 1, f"없는 아이템 ID: {nid}")

    # ---------- Spyglass (있으면) ----------
    @staticmethod
    def _spyglass(root: Path, rep: Report) -> None:
        exe = shutil.which("spyglassmc") or shutil.which("spyglass")
        if not exe:
            return
        try:
            out = subprocess.run([exe, "check", str(root)], capture_output=True, text=True, timeout=120,
                                 encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return
        for line in (out.stdout + out.stderr).splitlines():
            m = re.match(r"(.+?):(\d+):\d+\s*[-:]\s*(?:error|Error)\s*[:-]?\s*(.+)", line)
            if m:
                rep.add(_rel(Path(m.group(1)), root), int(m.group(2)), f"[Spyglass] {m.group(3)}")


# ================================================================ 리소스팩·모드 에셋
def png_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


class AssetValidator:
    """assets/<ns>/… 구조 검사. 리소스팩과 Fabric 모드(src/main/resources)가 같이 쓴다."""

    def __init__(self, vd: VersionData):
        self.vd = vd

    def validate_resourcepack(self, root: Path) -> Report:
        root = Path(root).resolve()
        rep = Report("resourcepack", root)
        check_pack_mcmeta(root, self.vd, "resource", rep)
        self._assets(root, rep)
        return rep

    def validate_mod_resources(self, project: Path) -> Report:
        project = Path(project).resolve()
        res = project / "src" / "main" / "resources"
        rep = Report("mod", project)
        fmj = res / "fabric.mod.json"
        if not fmj.is_file():
            rep.add("src/main/resources/fabric.mod.json", 0, "fabric.mod.json 이 없습니다")
        else:
            data = _load_json(fmj, rep)
            if isinstance(data, dict):
                for k in ("schemaVersion", "id", "version"):
                    if k not in data:
                        rep.add(fmj, 1, f'fabric.mod.json 에 "{k}" 가 없습니다')
        self._assets(res, rep, rel_root=project)
        data_dir = res / "data"
        if data_dir.is_dir():
            for f in data_dir.rglob("*.json"):
                rep.checked_files += 1
                _load_json(f, rep)
        return rep

    def _exists(self, root: Path, ns: str, sub: str, name: str, ext: str) -> bool:
        if (root / "assets" / ns / sub / f"{name}{ext}").is_file():
            return True
        if ns == "minecraft":
            return self.vd.has_vanilla_asset(f"assets/minecraft/{sub}/{name}{ext}")
        return False

    def _assets(self, root: Path, rep: Report, rel_root: Path | None = None) -> None:
        if rel_root is not None:
            rep.root = rel_root
        assets = root / "assets"
        if not assets.is_dir():
            if rep.kind == "resourcepack":
                rep.add("assets", 0, "assets 폴더가 없습니다(assets/<네임스페이스>/textures/... 구조)")
            return
        for ns_dir in sorted(p for p in assets.iterdir() if p.is_dir()):
            ns = ns_dir.name
            if not NS_RE.fullmatch(ns):
                rep.add(ns_dir, 0, f"네임스페이스 '{ns}' 에는 소문자·숫자·_ . - 만 쓸 수 있습니다")
                continue
            for f in sorted(p for p in ns_dir.rglob("*") if p.is_file()):
                rep.checked_files += 1
                rel = f.relative_to(ns_dir).as_posix()
                if not RL_PATH_RE.fullmatch(rel):
                    rep.add(f, 0, "파일·폴더 이름에는 소문자·숫자·_ . - / 만 쓸 수 있습니다(대문자·공백·한글 불가)")
                    continue
                if f.suffix == ".png":
                    self._png(f, rel, rep)
                elif f.suffix in (".json", ".mcmeta"):
                    obj = _load_json(f, rep)
                    if obj is None:
                        continue
                    top = rel.split("/", 1)[0]
                    if top == "models":
                        self._model(root, f, obj, rep)
                    elif top == "blockstates":
                        self._blockstate(root, f, obj, rep)
                    elif top == "items":
                        self._item_def(root, f, obj, rep)

    def _png(self, f: Path, rel: str, rep: Report) -> None:
        size = png_size(f)
        if size is None:
            rep.add(f, 0, "PNG 파일이 아닙니다(확장자만 .png)")
            return
        w, h = size
        if rel.startswith(("textures/block/", "textures/item/")):
            animated = f.with_name(f.name + ".mcmeta").is_file()
            if w != h and not (animated and h % w == 0):
                rep.add(f, 0, f"블록·아이템 텍스처는 정사각형이어야 합니다({w}×{h}). 애니메이션이면 세로로 이어 붙이고 .png.mcmeta 를 두세요")
            elif w & (w - 1):
                rep.add(f, 0, f"텍스처 크기는 16·32·64 처럼 2의 거듭제곱이 좋습니다({w}×{h})", "warning")

    def _ref(self, root: Path, f: Path, ref: str, sub: str, ext: str, label: str, rep: Report) -> None:
        if ref.startswith(("#", "builtin/", "minecraft:builtin/")):
            return
        ns, _, name = ref.partition(":") if ":" in ref else ("minecraft", "", ref)
        if not self._exists(root, ns, sub, name, ext):
            rep.add(f, 1, f"없는 {label}를 가리킵니다: {ns}:{name} (assets/{ns}/{sub}/{name}{ext})")

    def _model(self, root: Path, f: Path, obj: Any, rep: Report) -> None:
        if not isinstance(obj, dict):
            return
        if isinstance(obj.get("parent"), str):
            self._ref(root, f, obj["parent"], "models", ".json", "부모 모델", rep)
        for tex in (obj.get("textures") or {}).values():
            if isinstance(tex, str):
                self._ref(root, f, tex, "textures", ".png", "텍스처", rep)
            elif isinstance(tex, dict) and isinstance(tex.get("sprite"), str):
                self._ref(root, f, tex["sprite"], "textures", ".png", "텍스처", rep)

    def _models_in(self, node: Any) -> list[str]:
        out: list[str] = []
        if isinstance(node, dict):
            if isinstance(node.get("model"), str):
                out.append(node["model"])
            for v in node.values():
                out += self._models_in(v)
        elif isinstance(node, list):
            for v in node:
                out += self._models_in(v)
        return out

    def _blockstate(self, root: Path, f: Path, obj: Any, rep: Report) -> None:
        if not isinstance(obj, dict) or not ("variants" in obj or "multipart" in obj):
            rep.add(f, 1, '블록상태에는 "variants" 나 "multipart" 가 있어야 합니다')
            return
        for m in self._models_in(obj):
            self._ref(root, f, m, "models", ".json", "모델", rep)

    def _item_def(self, root: Path, f: Path, obj: Any, rep: Report) -> None:
        if not isinstance(obj, dict) or "model" not in obj:
            rep.add(f, 1, '아이템 정의(items/*.json)에는 "model" 이 있어야 합니다')
            return
        for m in self._models_in(obj):
            self._ref(root, f, m, "models", ".json", "모델", rep)


def validate_datapack(vd: VersionData, path: Path) -> Report:
    return DatapackValidator(vd).validate(path)


def validate_resourcepack(vd: VersionData, path: Path) -> Report:
    return AssetValidator(vd).validate_resourcepack(path)


def validate_mod(vd: VersionData, project: Path) -> Report:
    return AssetValidator(vd).validate_mod_resources(project)
