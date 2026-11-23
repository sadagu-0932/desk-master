"""MCP 서버 "mc-tools" (stdio). Claude Code 가 인스턴스의 .mcp.json 으로 띄운다.

의존 패키지 없이 MCP 의 stdio 전송(줄 단위 JSON-RPC 2.0)을 직접 구현한다:
initialize / notifications/initialized / ping / tools/list / tools/call.
"""
from __future__ import annotations

import sys

# 사이드카 모듈(rpc)은 불러올 때 sys.stdout 을 stderr 로 돌린다. 프로토콜용 원래 stdout 을 먼저 잡아 둔다.
_OUT = sys.stdout
if hasattr(_OUT, "reconfigure"):
    _OUT.reconfigure(encoding="utf-8", errors="replace", newline="\n")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

import json  # noqa: E402
import os  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Callable  # noqa: E402

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "mc_tools"  # noqa: A001

from mc_tools import apply as apply_mod  # noqa: E402
from mc_tools import scaffold, validate  # noqa: E402
from mc_tools.commands import CommandChecker  # noqa: E402
from mc_tools.context import Instance, ToolError, find_instance, inside  # noqa: E402
from mc_tools.reports import VersionData  # noqa: E402

SERVER_NAME = "mc-tools"
SERVER_VERSION = "0.1.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "마인크래프트 자료는 기억으로 쓰지 말고 이 도구로 조회한다(그 인스턴스 버전의 게임 파일에서 뽑은 자료). "
    "작업 순서: scaffold_* → 파일 작성 → validate_* → apply_changes → 결과 status·log_errors 확인. "
    "validate 오류나 apply 의 log_errors 가 있으면 고치고 다시 한다."
)

_ID = {"type": "string", "description": "인스턴스 id(inst_xxxxxxxx). 비우면 지금 작업 중인 인스턴스"}
_CONTENT = {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string", "description": "소문자 ID (예: ruby)"},
    "name_ko": {"type": "string"}, "name_en": {"type": "string"}}, "required": ["id"]}}

TOOLS: list[dict[str, Any]] = [
    {"name": "prepare_version_data",
     "description": "인스턴스 버전의 정답 자료(명령어 트리·ID 목록·바닐라 JSON·/reload 대상 목록)를 준비한다. 처음 한 번은 1~2분 걸린다.",
     "inputSchema": {"type": "object", "properties": {"instance_id": _ID}}},
    {"name": "command_syntax",
     "description": "명령어 트리에서 경로 다음에 올 수 있는 리터럴·인자(파서·범위)를 보여준다. 예: \"execute if\", \"give\". 빈 값이면 모든 명령어.",
     "inputSchema": {"type": "object", "properties": {"command_path": {"type": "string"}, "instance_id": _ID}}},
    {"name": "check_command",
     "description": "명령어 한 줄을 그 버전 문법·ID 로 검사한다(함수 파일에 쓰기 전에 확인용).",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}, "instance_id": _ID},
                     "required": ["command"]}},
    {"name": "registry_search",
     "description": "레지스트리 ID 검색. registry 예: block, item, entity_type, mob_effect, enchantment, particle_type, sound_event, worldgen/biome.",
     "inputSchema": {"type": "object", "properties": {"registry": {"type": "string"}, "query": {"type": "string"},
                                                      "limit": {"type": "integer"}, "instance_id": _ID},
                     "required": ["registry"]}},
    {"name": "block_states",
     "description": "블록의 상태(속성과 가능한 값, 기본값)를 보여준다. 예: minecraft:campfire",
     "inputSchema": {"type": "object", "properties": {"block_id": {"type": "string"}, "instance_id": _ID},
                     "required": ["block_id"]}},
    {"name": "vanilla_file",
     "description": "그 버전 바닐라 데이터 JSON 예시를 읽는다. path 는 data/minecraft 아래 경로(예: recipe/diamond_sword.json, loot_table/blocks/stone.json). 폴더면 목록.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "instance_id": _ID}, "required": ["path"]}},
    {"name": "scaffold_datapack",
     "description": "데이터팩 기본 구조(올바른 pack.mcmeta, data/<ns>/function/, load·tick 함수 태그)를 인스턴스 datapacks/ 에 만든다.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "namespace": {"type": "string"},
                                                      "description": {"type": "string"}, "instance_id": _ID},
                     "required": ["name", "namespace"]}},
    {"name": "scaffold_fabric_mod",
     "description": "Fabric 모드 프로젝트 전체(gradle 설정·메인 클래스·fabric.mod.json·언어 파일·에셋 폴더)를 mods-src/ 에 만든다. items·blocks 를 주면 등록 코드·16×16 텍스처·모델·아이템 정의·블록상태·루트테이블·언어 키까지 만든다.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "mod_id": {"type": "string"},
                                                      "version": {"type": "string"}, "group": {"type": "string"},
                                                      "items": _CONTENT, "blocks": _CONTENT, "instance_id": _ID},
                     "required": ["name", "mod_id"]}},
    {"name": "add_mod_content",
     "description": "이미 있는 Fabric 모드 프로젝트에 아이템·블록을 추가한다(등록 코드·텍스처·모델·블록상태·루트테이블·언어 키).",
     "inputSchema": {"type": "object", "properties": {"project_path": {"type": "string"}, "items": _CONTENT,
                                                      "blocks": _CONTENT, "instance_id": _ID},
                     "required": ["project_path"]}},
    {"name": "scaffold_resourcepack",
     "description": "리소스팩 기본 구조(올바른 pack.mcmeta, assets 폴더)를 인스턴스 resourcepacks/ 에 만든다.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                                                      "instance_id": _ID}, "required": ["name"]}},
    {"name": "validate_datapack",
     "description": "데이터팩 검사: pack.mcmeta 형식, 폴더 이름(구버전 복수형), 모든 명령어 줄(그 버전 명령어 트리), 없는 ID, JSON 문법, 함수·태그 참조. 결과는 '파일:줄: 설명'.",
     "inputSchema": {"type": "object", "properties": {"pack_path": {"type": "string", "description": "datapacks/<팩> 또는 팩 이름"},
                                                      "instance_id": _ID}, "required": ["pack_path"]}},
    {"name": "validate_resourcepack",
     "description": "리소스팩 검사: pack.mcmeta, 텍스처 크기·경로, 모델·블록상태·아이템 정의의 참조.",
     "inputSchema": {"type": "object", "properties": {"pack_path": {"type": "string"}, "instance_id": _ID},
                     "required": ["pack_path"]}},
    {"name": "build_mod",
     "description": "Fabric 모드를 ./gradlew build 로 빌드하고 컴파일 오류만 추려서 돌려준다.",
     "inputSchema": {"type": "object", "properties": {"project_path": {"type": "string"}, "instance_id": _ID},
                     "required": ["project_path"]}},
    {"name": "apply_changes",
     "description": "바뀐 파일을 종류에 맞게 게임에 적용하고 결과 상태(바로 적용됨/월드 재접속 필요/재시작 필요/오류)와 적용 뒤 게임 로그 오류를 돌려준다. needs_confirmation 이 있으면 사용자에게 묻고 confirm=true 로 다시 부른다.",
     "inputSchema": {"type": "object", "properties": {
         "changed_paths": {"type": "array", "items": {"type": "string"}, "description": "인스턴스 기준 경로"},
         "world": {"type": "string"}, "confirm": {"type": "boolean"}, "instance_id": _ID},
         "required": ["changed_paths"]}},
    {"name": "game_status",
     "description": "게임 실행 여부, 월드 목록, 마지막 적용 결과를 보여준다.",
     "inputSchema": {"type": "object", "properties": {"instance_id": _ID}}},
]


# ================================================================ 도구 구현
def _ctx(args: dict[str, Any], need_reports: bool = True) -> tuple[Instance, VersionData]:
    inst = find_instance(args.get("instance_id"), cwd=os.getcwd())
    vd = VersionData(inst.data_dir, inst.version)
    if need_reports:
        vd.ensure(generate=True)
    return inst, vd


def _pack(inst: Instance, raw: str, folder: str) -> Path:
    p = Path(raw)
    if len(p.parts) == 1 and (inst.dir / folder / raw).is_dir():
        p = Path(folder) / raw
    return inside(inst.dir, p)


def t_prepare(a: dict) -> Any:
    inst = find_instance(a.get("instance_id"), cwd=os.getcwd())
    vd = VersionData(inst.data_dir, inst.version)
    r = vd.ensure(generate=True)
    return {**r, "pack_formats": {k: list(v) for k, v in vd.pack_formats.items()}, "reload_kinds": vd.classify()}


def t_syntax(a: dict) -> Any:
    _, vd = _ctx(a)
    ck = CommandChecker(vd.commands)
    path = [p for p in (a.get("command_path") or "").split() if p]
    try:
        node_list = ck.syntax(path)
    except KeyError as e:
        here = ck.syntax(path[:path.index(str(e.args[0]))]) if str(e.args[0]) in path else []
        raise ToolError(f"'{e.args[0]}' 은(는) 이 위치에 없습니다. 가능한 것: {', '.join(n['name'] for n in here[:40])}") from e
    return {"path": " ".join(path), "next": node_list}


def t_check(a: dict) -> Any:
    _, vd = _ctx(a)
    ck = CommandChecker(vd.commands, vd.registry_ids, vd.blocks, lambda r, i: i in vd.tag_ids(r))
    r = ck.check(a["command"])
    return {"ok": r.ok, "issues": [f"{i.col + 1}칸: {i.message}" for i in r.issues], "function_refs": r.refs}


def t_registry(a: dict) -> Any:
    _, vd = _ctx(a)
    reg = a["registry"]
    ids = vd.registry_ids(reg)
    if ids is None:
        names = sorted(k.split(":", 1)[1] for k in vd.registries)
        raise ToolError(f"모르는 레지스트리입니다: {reg}. 예: {', '.join(names[:60])}")
    q = (a.get("query") or "").lower()
    hits = sorted(i for i in ids if q in i)
    limit = int(a.get("limit") or 50)
    return {"registry": reg, "total": len(hits), "ids": hits[:limit], "tags": sorted(t for t in vd.tag_ids(reg) if q in t)[:20]}


def t_block_states(a: dict) -> Any:
    _, vd = _ctx(a)
    bid = a["block_id"] if ":" in a["block_id"] else f"minecraft:{a['block_id']}"
    info = vd.blocks.get(bid)
    if not info:
        near = sorted(b for b in vd.blocks if a["block_id"].split(":")[-1] in b)[:15]
        raise ToolError(f"없는 블록입니다: {bid}. 비슷한 것: {', '.join(near)}")
    default = next((s.get("properties", {}) for s in info.get("states", []) if s.get("default")), {})
    return {"block": bid, "properties": info.get("properties", {}), "default": default}


def t_vanilla(a: dict) -> Any:
    _, vd = _ctx(a)
    base = vd.vanilla_data
    rel = a["path"].replace("\\", "/").removeprefix("data/minecraft/").strip("/")
    p = inside(base, rel) if rel else base
    if p.is_dir():
        entries = sorted(x.relative_to(base).as_posix() + ("/" if x.is_dir() else "") for x in p.iterdir())
        return {"folder": rel or ".", "entries": entries[:300], "total": len(entries)}
    if not p.is_file():
        raise ToolError(f"바닐라 파일이 없습니다: {rel}")
    text = p.read_text("utf-8")
    return {"path": rel, "content": text[:20000], "truncated": len(text) > 20000}


def t_scaffold_dp(a: dict) -> Any:
    inst, vd = _ctx(a)
    return scaffold.scaffold_datapack(inst, vd, a["name"], a["namespace"], a.get("description", ""))


def t_scaffold_mod(a: dict) -> Any:
    inst, vd = _ctx(a)
    return scaffold.scaffold_fabric_mod(inst, vd, a["name"], a["mod_id"], a.get("version") or "0.1.0",
                                        a.get("items"), a.get("blocks"), a.get("group") or "com.example")


def t_add_content(a: dict) -> Any:
    inst, _ = _ctx(a, need_reports=False)
    return scaffold.add_mod_content(inst, _pack(inst, a["project_path"], "mods-src"), a.get("items") or [], a.get("blocks") or [])


def t_scaffold_rp(a: dict) -> Any:
    inst, vd = _ctx(a)
    return scaffold.scaffold_resourcepack(inst, vd, a["name"], a.get("description", ""))


def t_validate_dp(a: dict) -> Any:
    inst, vd = _ctx(a)
    rep = validate.validate_datapack(vd, _pack(inst, a["pack_path"], "datapacks"))
    return {**rep.to_dict(), "summary": rep.summary()}


def t_validate_rp(a: dict) -> Any:
    inst, vd = _ctx(a)
    rep = validate.validate_resourcepack(vd, _pack(inst, a["pack_path"], "resourcepacks"))
    return {**rep.to_dict(), "summary": rep.summary()}


def t_build(a: dict) -> Any:
    inst, _ = _ctx(a, need_reports=False)
    return apply_mod.build_mod(inst, _pack(inst, a["project_path"], "mods-src"))


def t_apply(a: dict) -> Any:
    inst, vd = _ctx(a)
    res = apply_mod.apply_changes(inst, vd, list(a["changed_paths"]), world=a.get("world"),
                                  confirm=bool(a.get("confirm")))
    return res.to_dict()


def t_status(a: dict) -> Any:
    inst, _ = _ctx(a, need_reports=False)
    saves = inst.dir / "saves"
    worlds = sorted((d.name for d in saves.iterdir() if (d / "level.dat").is_file()), key=str) if saves.is_dir() else []
    return {"instance": inst.id, "version": inst.version, "loader": inst.loader,
            "game_running": apply_mod.game_running(inst), "worlds": worlds,
            "selected_world": apply_mod.pick_world(inst, None), "last_apply": apply_mod.load_last(inst)}


HANDLERS: dict[str, Callable[[dict], Any]] = {
    "prepare_version_data": t_prepare, "command_syntax": t_syntax, "check_command": t_check,
    "registry_search": t_registry, "block_states": t_block_states, "vanilla_file": t_vanilla,
    "scaffold_datapack": t_scaffold_dp, "scaffold_fabric_mod": t_scaffold_mod, "add_mod_content": t_add_content,
    "scaffold_resourcepack": t_scaffold_rp, "validate_datapack": t_validate_dp, "validate_resourcepack": t_validate_rp,
    "build_mod": t_build, "apply_changes": t_apply, "game_status": t_status,
}


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = HANDLERS.get(name)
    if fn is None:
        return {"content": [{"type": "text", "text": f"알 수 없는 도구입니다: {name}"}], "isError": True}
    try:
        result = fn(args or {})
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
        # 검사 실패·빌드 실패도 도구 호출 자체는 성공이다(결과의 ok/errors 로 알린다)
        return {"content": [{"type": "text", "text": text}], "isError": False}
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except KeyError as e:
        return {"content": [{"type": "text", "text": f"필요한 값이 없습니다: {e.args[0]}"}], "isError": True}
    except Exception as e:  # noqa: BLE001 - 서버가 죽지 않게
        traceback.print_exc(file=sys.stderr)
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


# ================================================================ 프로토콜
def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if mid is None:
        return None  # 알림(notifications/initialized 등)
    if method == "initialize":
        want = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": mid, "result": call_tool(params.get("name", ""), params.get("arguments") or {})}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(stdin=None, out=None) -> None:
    stdin = stdin or sys.stdin
    out = out or _OUT
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            out.flush()
            continue
        batch = msg if isinstance(msg, list) else [msg]
        replies = [r for r in (handle(m) for m in batch) if r is not None]
        for r in replies:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()


if __name__ == "__main__":
    serve()
