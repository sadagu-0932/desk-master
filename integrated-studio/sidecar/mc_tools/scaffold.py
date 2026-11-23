"""기본 구조 만들기: 데이터팩·리소스팩·Fabric 모드(+아이템·블록 에셋).

형식은 그 버전 자료에서 가져온다: pack.mcmeta 형식 번호는 jar 의 version.json,
아이템 정의·모델·블록상태·루트테이블 모양은 jar 안 바닐라 파일과 같은 구조.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any

from .context import Instance, ToolError, inside
from .reports import VersionData

NAME_RE = re.compile(r"[a-z0-9_][a-z0-9_.\-]{0,63}")
NS_RE = re.compile(r"[a-z0-9_.\-]{1,64}")
CONTENT_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _check(name: str, rx: re.Pattern, what: str) -> str:
    name = (name or "").strip()
    if not rx.fullmatch(name):
        raise ToolError(f"{what}은(는) 소문자·숫자·_ . - 만 쓸 수 있습니다: {name!r}")
    return name


def _write(path: Path, text: str, created: list[str], base: Path, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    created.append(path.relative_to(base).as_posix())


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def _mcmeta(vd: VersionData, kind: str, description: str) -> str:
    f = vd.pack_format_json(kind)
    return _json({"pack": {"description": description, "min_format": f, "max_format": f}})


# ================================================================ 데이터팩
def scaffold_datapack(inst: Instance, vd: VersionData, name: str, namespace: str, description: str = "") -> dict[str, Any]:
    name = _check(name, NAME_RE, "데이터팩 이름")
    namespace = _check(namespace, NS_RE, "네임스페이스")
    if namespace == "minecraft":
        raise ToolError("네임스페이스로 'minecraft' 는 쓰지 않습니다(바닐라와 겹침). 팩 이름에 맞는 이름을 쓰세요.")
    root = inside(inst.dir, Path("datapacks") / name)
    created: list[str] = []
    _write(root / "pack.mcmeta", _mcmeta(vd, "data", description or name), created, inst.dir)
    fn = root / "data" / namespace / "function"
    _write(fn / "load.mcfunction", f"# /reload 하거나 월드를 열 때 한 번 실행\ntellraw @a {{text:\"[{name}] 불러옴\",color:\"green\"}}\n",
           created, inst.dir)
    _write(fn / "tick.mcfunction", "# 매 틱(1초에 20번) 실행 — 필요 없으면 tags/function/tick.json 에서 빼세요\n", created, inst.dir)
    tags = root / "data" / "minecraft" / "tags" / "function"
    _write(tags / "load.json", _json({"values": [f"{namespace}:load"]}), created, inst.dir)
    _write(tags / "tick.json", _json({"values": [f"{namespace}:tick"]}), created, inst.dir)
    return {"path": str(root), "created": created,
            "next": "data/<ns>/function/ 에 함수를 쓰고 validate_datapack → apply_changes 순서로 진행하세요."}


# ================================================================ 리소스팩
def scaffold_resourcepack(inst: Instance, vd: VersionData, name: str, description: str = "") -> dict[str, Any]:
    name = _check(name, NAME_RE, "리소스팩 이름")
    root = inside(inst.dir, Path("resourcepacks") / name)
    created: list[str] = []
    _write(root / "pack.mcmeta", _mcmeta(vd, "resource", description or name), created, inst.dir)
    for sub in ("textures/block", "textures/item", "models/block", "models/item", "blockstates", "items", "lang"):
        d = root / "assets" / "minecraft" / sub
        if not d.exists():
            d.mkdir(parents=True)
            created.append(d.relative_to(inst.dir).as_posix() + "/")
    return {"path": str(root), "created": created,
            "next": "바꿀 바닐라 파일과 같은 경로(assets/minecraft/…)에 수정한 파일만 넣으세요. 바닐라 원본을 그대로 복사해 넣지 않습니다."}


# ================================================================ 텍스처(16×16 PNG)
def _png(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in pixels)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _color(seed: str) -> tuple[int, int, int]:
    h = hashlib.sha1(seed.encode()).digest()
    base = [60 + h[0] % 160, 60 + h[1] % 160, 60 + h[2] % 160]
    return base[0], base[1], base[2]


def _shade(c: tuple[int, int, int], f: float) -> tuple[int, int, int, int]:
    return (max(0, min(255, int(c[0] * f))), max(0, min(255, int(c[1] * f))), max(0, min(255, int(c[2] * f))), 255)


def make_texture(kind: str, seed: str) -> bytes:
    """임시 16×16 텍스처. block = 테두리 있는 타일, item = 보석 모양(바깥은 투명)."""
    c = _color(seed)
    h = hashlib.sha1(("n" + seed).encode()).digest()
    px: list[list[tuple[int, int, int, int]]] = []
    for y in range(16):
        row = []
        for x in range(16):
            noise = 0.85 + (h[(x * 7 + y * 13) % len(h)] % 30) / 100
            if kind == "block":
                edge = x in (0, 15) or y in (0, 15)
                row.append(_shade(c, 0.6 if edge else noise))
            else:
                d = abs(x - 7.5) + abs(y - 7.5)
                if d > 7.5:
                    row.append((0, 0, 0, 0))
                elif d > 6.5:
                    row.append(_shade(c, 0.45))
                else:
                    row.append(_shade(c, 1.25 if (x + y) < 13 else noise))
        px.append(row)
    return _png(16, 16, px)


# ================================================================ Fabric 모드
def scaffold_fabric_mod(inst: Instance, vd: VersionData, name: str, mod_id: str, version: str = "0.1.0",
                        items: list[dict] | None = None, blocks: list[dict] | None = None,
                        group: str = "com.example") -> dict[str, Any]:
    """사이드카의 Fabric 템플릿(gradle·메인 클래스·fabric.mod.json — 설치 시점 최신 버전 확인)을 만들고,
    아이템·블록을 같이 추가한다."""
    from instances import InstanceStore
    from packs import Packs

    if inst.loader != "fabric":
        raise ToolError("Fabric 모드는 Fabric 인스턴스(테스트 인스턴스)에서 만듭니다.")
    if not re.fullmatch(r"\d+(\.\d+){0,3}([-+][0-9A-Za-z.\-]+)?", version or ""):
        raise ToolError(f"모드 버전 형식이 아닙니다(예: 0.1.0): {version!r}")
    packs = Packs(InstanceStore(inst.data_dir), inst.mc_dir)
    try:
        res = packs.mod_new(inst.id, mod_id, name, group)
    except Exception as e:  # noqa: BLE001 - 사이드카 RpcError
        raise ToolError(str(e)) from e
    root = Path(res["path"])
    props = root / "gradle.properties"
    props.write_text(re.sub(r"(?m)^version=.*$", f"version={version}", props.read_text("utf-8")), "utf-8")
    created = [p.relative_to(inst.dir).as_posix() for p in root.rglob("*") if p.is_file()]
    added = add_mod_content(inst, root, items or [], blocks or []) if (items or blocks) else {"created": []}
    return {"path": str(root), "created": sorted(set(created + added["created"])), "versions": res.get("versions"),
            "next": "Java 코드를 쓰고 build_mod 로 컴파일을 확인한 뒤 apply_changes 로 테스트 인스턴스에 넣으세요."}


def _project_info(root: Path) -> dict[str, Any]:
    fmj = json.loads((root / "src" / "main" / "resources" / "fabric.mod.json").read_text("utf-8"))
    entry = fmj["entrypoints"]["main"][0]
    entry = entry["value"] if isinstance(entry, dict) else entry
    pkg, cls = entry.rsplit(".", 1)
    return {"mod_id": fmj["id"], "pkg": pkg, "main": cls,
            "java_dir": root / "src" / "main" / "java" / Path(*pkg.split("."))}


def _const(i: str) -> str:
    return i.upper()


def add_mod_content(inst: Instance, project: Path, items: list[dict], blocks: list[dict]) -> dict[str, Any]:
    """아이템·블록 추가: Java 등록 코드 + 16×16 텍스처 + 모델·아이템 정의·블록상태 + 블록 루트테이블 + 언어 키(en_us·ko_kr).
    items/blocks: [{"id": "ruby", "name_ko": "루비", "name_en": "Ruby"}]"""
    root = inside(inst.dir, project)
    info = _project_info(root)
    mod, pkg, main = info["mod_id"], info["pkg"], info["main"]
    res = root / "src" / "main" / "resources"
    assets = res / "assets" / mod
    created: list[str] = []
    lang: dict[str, dict[str, str]] = {"en_us": {}, "ko_kr": {}}

    def entry(e: dict) -> tuple[str, str, str]:
        cid = _check(e.get("id", ""), CONTENT_ID_RE, "아이템·블록 ID")
        return cid, e.get("name_en") or cid.replace("_", " ").title(), e.get("name_ko") or e.get("name_en") or cid

    for e in items:
        cid, en, ko = entry(e)
        (assets / "textures" / "item").mkdir(parents=True, exist_ok=True)
        png = assets / "textures" / "item" / f"{cid}.png"
        if not png.exists():
            png.write_bytes(make_texture("item", f"{mod}:{cid}"))
            created.append(png.relative_to(inst.dir).as_posix())
        _write(assets / "models" / "item" / f"{cid}.json",
               _json({"parent": "minecraft:item/generated", "textures": {"layer0": f"{mod}:item/{cid}"}}), created, inst.dir)
        _write(assets / "items" / f"{cid}.json",
               _json({"model": {"type": "minecraft:model", "model": f"{mod}:item/{cid}"}}), created, inst.dir)
        lang["en_us"][f"item.{mod}.{cid}"] = en
        lang["ko_kr"][f"item.{mod}.{cid}"] = ko

    for e in blocks:
        cid, en, ko = entry(e)
        (assets / "textures" / "block").mkdir(parents=True, exist_ok=True)
        png = assets / "textures" / "block" / f"{cid}.png"
        if not png.exists():
            png.write_bytes(make_texture("block", f"{mod}:{cid}"))
            created.append(png.relative_to(inst.dir).as_posix())
        _write(assets / "models" / "block" / f"{cid}.json",
               _json({"parent": "minecraft:block/cube_all", "textures": {"all": f"{mod}:block/{cid}"}}), created, inst.dir)
        _write(assets / "blockstates" / f"{cid}.json",
               _json({"variants": {"": {"model": f"{mod}:block/{cid}"}}}), created, inst.dir)
        _write(assets / "items" / f"{cid}.json",
               _json({"model": {"type": "minecraft:model", "model": f"{mod}:block/{cid}"}}), created, inst.dir)
        _write(res / "data" / mod / "loot_table" / "blocks" / f"{cid}.json", _json({
            "type": "minecraft:block",
            "pools": [{"rolls": 1, "bonus_rolls": 0,
                       "entries": [{"type": "minecraft:item", "name": f"{mod}:{cid}"}],
                       "conditions": [{"condition": "minecraft:survives_explosion"}]}]}), created, inst.dir)
        lang["en_us"][f"block.{mod}.{cid}"] = en
        lang["ko_kr"][f"block.{mod}.{cid}"] = ko

    for code, entries in lang.items():
        f = assets / "lang" / f"{code}.json"
        cur = json.loads(f.read_text("utf-8")) if f.is_file() else {}
        cur.update(entries)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_json(cur), "utf-8")
        created.append(f.relative_to(inst.dir).as_posix())

    java = info["java_dir"]
    if items:
        _java_items(java / "ModItems.java", pkg, main, [entry(e)[0] for e in items])
        created.append((java / "ModItems.java").relative_to(inst.dir).as_posix())
    if blocks:
        _java_blocks(java / "ModBlocks.java", pkg, main, [entry(e)[0] for e in blocks])
        created.append((java / "ModBlocks.java").relative_to(inst.dir).as_posix())
    _hook_init(java / f"{main}.java", items, blocks)
    return {"created": sorted(set(created)),
            "note": "Java 등록 코드는 build_mod 로 컴파일해 확인하세요. 오류가 나면 그 버전의 클래스 이름에 맞게 고칩니다."}


def _merge_java_list(path: Path, marker: str, lines: list[str]) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text("utf-8")
    new = [ln for ln in lines if ln not in text]
    if not new:
        return text
    return text.replace(marker, "".join(new) + marker, 1)


def _java_items(path: Path, pkg: str, main: str, ids: list[str]) -> None:
    lines = [f"\tpublic static final Item {_const(i)} = register(\"{i}\", Item::new, new Item.Properties());\n" for i in ids]
    marker = "\t// <mc-tools:items>\n"
    merged = _merge_java_list(path, marker, lines)
    if merged is None:
        merged = (f"package {pkg};\n\n"
                  "import java.util.function.Function;\n\n"
                  "import net.minecraft.core.Registry;\n"
                  "import net.minecraft.core.registries.BuiltInRegistries;\n"
                  "import net.minecraft.core.registries.Registries;\n"
                  "import net.minecraft.resources.ResourceKey;\n"
                  "import net.minecraft.world.item.Item;\n\n"
                  "/** 모드 아이템 등록(mc-tools 가 만듦). 텍스처·모델·언어 키는 resources/assets 에 함께 있다. */\n"
                  "public final class ModItems {\n"
                  + "".join(lines) + marker +
                  "\n\tprivate static Item register(String name, Function<Item.Properties, Item> factory, Item.Properties props) {\n"
                  f"\t\tResourceKey<Item> key = ResourceKey.create(Registries.ITEM, {main}.id(name));\n"
                  "\t\treturn Registry.register(BuiltInRegistries.ITEM, key, factory.apply(props.setId(key)));\n"
                  "\t}\n\n"
                  "\t/** 메인 클래스 onInitialize 에서 불러 클래스를 불러오게 한다. */\n"
                  "\tpublic static void init() {\n\t}\n\n"
                  "\tprivate ModItems() {\n\t}\n}\n")
    path.write_text(merged, "utf-8")


def _java_blocks(path: Path, pkg: str, main: str, ids: list[str]) -> None:
    lines = [f"\tpublic static final Block {_const(i)} = register(\"{i}\", Block::new, "
             "BlockBehaviour.Properties.of().strength(1.5f));\n" for i in ids]
    marker = "\t// <mc-tools:blocks>\n"
    merged = _merge_java_list(path, marker, lines)
    if merged is None:
        merged = (f"package {pkg};\n\n"
                  "import java.util.function.Function;\n\n"
                  "import net.minecraft.core.Registry;\n"
                  "import net.minecraft.core.registries.BuiltInRegistries;\n"
                  "import net.minecraft.core.registries.Registries;\n"
                  "import net.minecraft.resources.ResourceKey;\n"
                  "import net.minecraft.world.item.BlockItem;\n"
                  "import net.minecraft.world.item.Item;\n"
                  "import net.minecraft.world.level.block.Block;\n"
                  "import net.minecraft.world.level.block.state.BlockBehaviour;\n\n"
                  "/** 모드 블록 등록(mc-tools 가 만듦) — 블록 아이템도 같이 등록한다. */\n"
                  "public final class ModBlocks {\n"
                  + "".join(lines) + marker +
                  "\n\tprivate static Block register(String name, Function<BlockBehaviour.Properties, Block> factory,\n"
                  "\t\t\tBlockBehaviour.Properties props) {\n"
                  f"\t\tResourceKey<Block> key = ResourceKey.create(Registries.BLOCK, {main}.id(name));\n"
                  "\t\tBlock block = Registry.register(BuiltInRegistries.BLOCK, key, factory.apply(props.setId(key)));\n"
                  f"\t\tResourceKey<Item> itemKey = ResourceKey.create(Registries.ITEM, {main}.id(name));\n"
                  "\t\tRegistry.register(BuiltInRegistries.ITEM, itemKey,\n"
                  "\t\t\t\tnew BlockItem(block, new Item.Properties().setId(itemKey).useBlockDescriptionPrefix()));\n"
                  "\t\treturn block;\n\t}\n\n"
                  "\tpublic static void init() {\n\t}\n\n"
                  "\tprivate ModBlocks() {\n\t}\n}\n")
    path.write_text(merged, "utf-8")


def _hook_init(main_java: Path, items: list, blocks: list) -> None:
    if not main_java.is_file():
        return
    text = main_java.read_text("utf-8")
    calls = ""
    if items and "ModItems.init();" not in text:
        calls += "\t\tModItems.init();\n"
    if blocks and "ModBlocks.init();" not in text:
        calls += "\t\tModBlocks.init();\n"
    if not calls:
        return
    m = re.search(r"public void onInitialize\(\)\s*\{\n", text)
    if m:
        text = text[:m.end()] + calls + text[m.end():]
        main_java.write_text(text, "utf-8")
