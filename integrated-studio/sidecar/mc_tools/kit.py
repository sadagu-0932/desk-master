"""claude-kit 을 인스턴스에 설치한다 — 사용자 계정의 스킬·플러그인에 기대지 않고 앱에 든 것만 쓴다.

설치하는 것(인스턴스 폴더 안):
- .claude/skills/<datapack|fabric-mod|resourcepack>/SKILL.md   (claude-kit/skills 복사)
- .claude/settings.json   훅(PostToolUse·Stop)·mc-tools 허용을 기존 설정에 합친다
- .mcp.json               mc-tools 서버 등록(이 PC 의 파이썬·사이드카 경로)
- CLAUDE.md               <!-- mc-tools:start --> … <!-- mc-tools:end --> 구간을 템플릿으로 채운다(나머지는 그대로)
- .gitignore              .studio/ 와 .mcp.json(이 PC 경로가 들어 있음) 추가

사용: python -m mc_tools.kit install <인스턴스 폴더> [--python 경로]
      python -m mc_tools.kit install-all [--data 데이터 폴더]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "mc_tools"  # noqa: A001

from mc_tools.context import SIDECAR_DIR, Instance, ToolError, default_data_dir, find_instance  # noqa: E402

MARK_START = "<!-- mc-tools:start"
MARK_END = "<!-- mc-tools:end -->"
SERVER_NAME = "mc-tools"
HOOK = Path(__file__).resolve().parent / "hook.py"
SERVER = Path(__file__).resolve().parent / "server.py"


def kit_dir() -> Path:
    """개발 중: 저장소의 integrated-studio/claude-kit, 설치판: resources/claude-kit(사이드카 옆)."""
    for cand in (SIDECAR_DIR.parent / "claude-kit", SIDECAR_DIR / "claude-kit"):
        if (cand / "settings.json").is_file():
            return cand
    raise ToolError("claude-kit 폴더를 찾지 못했습니다(앱 설치 파일에 함께 들어 있어야 합니다).")


def _subst(obj: Any, values: dict[str, str]) -> Any:
    if isinstance(obj, str):
        for k, v in values.items():
            obj = obj.replace("${" + k + "}", v)
        return obj
    if isinstance(obj, list):
        return [_subst(x, values) for x in obj]
    if isinstance(obj, dict):
        return {k: _subst(v, values) for k, v in obj.items()}
    return obj


def _is_ours(handler: dict) -> bool:
    args = handler.get("args") or []
    return any(str(a).replace("\\", "/").endswith("mc_tools/hook.py") for a in args) or "mc_tools/hook.py" in str(handler.get("command", "")).replace("\\", "/")


def merge_settings(current: dict[str, Any], kit: dict[str, Any]) -> dict[str, Any]:
    out = dict(current)
    perms = dict(out.get("permissions") or {})
    allow = list(perms.get("allow") or [])
    for rule in (kit.get("permissions") or {}).get("allow", []):
        if rule not in allow:
            allow.append(rule)
    perms["allow"] = allow
    out["permissions"] = perms
    servers = list(out.get("enabledMcpjsonServers") or [])
    for s in kit.get("enabledMcpjsonServers", []):
        if s not in servers:
            servers.append(s)
    out["enabledMcpjsonServers"] = servers
    hooks = dict(out.get("hooks") or {})
    for event, groups in (kit.get("hooks") or {}).items():
        kept = []
        for g in hooks.get(event, []):
            hs = [h for h in g.get("hooks", []) if not _is_ours(h)]
            if hs:
                kept.append({**g, "hooks": hs})
        hooks[event] = kept + groups
    out["hooks"] = hooks
    return out


def render_claude_md(template: str, inst: Instance, world: str | None) -> str:
    values = {"VERSION": inst.version,
              "LOADER": {"fabric": "Fabric", "vanilla": "바닐라"}.get(inst.loader, inst.loader),
              "WORLD": world or "(아직 없음 — 월드를 만들면 가장 최근 월드에 적용)"}
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def merge_claude_md(current: str, block: str) -> str:
    block = block.strip() + "\n"
    if MARK_START in current and MARK_END in current:
        pre = current[:current.index(MARK_START)]
        post = current[current.index(MARK_END) + len(MARK_END):]
        return pre + block + post.lstrip("\n")
    return (current.rstrip() + "\n\n" if current.strip() else "") + block


def install(instance_dir: Path, python: str | None = None) -> dict[str, Any]:
    from mc_tools.apply import pick_world

    inst = find_instance(cwd=instance_dir)
    kdir = kit_dir()
    python = python or sys.executable
    values = {"MC_TOOLS_PYTHON": python, "MC_TOOLS_HOOK": str(HOOK)}
    done: list[str] = []

    # 스킬
    skills_dst = inst.dir / ".claude" / "skills"
    for sk in sorted((kdir / "skills").iterdir()):
        if (sk / "SKILL.md").is_file():
            dst = skills_dst / sk.name
            dst.mkdir(parents=True, exist_ok=True)
            for f in sk.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
            done.append(f".claude/skills/{sk.name}")

    # 설정(훅)
    sfile = inst.dir / ".claude" / "settings.json"
    current = json.loads(sfile.read_text("utf-8")) if sfile.is_file() else {}
    kit_settings = _subst(json.loads((kdir / "settings.json").read_text("utf-8")), values)
    sfile.parent.mkdir(parents=True, exist_ok=True)
    sfile.write_text(json.dumps(merge_settings(current, kit_settings), ensure_ascii=False, indent=2) + "\n", "utf-8")
    done.append(".claude/settings.json")

    # MCP 서버
    mfile = inst.dir / ".mcp.json"
    mcp = json.loads(mfile.read_text("utf-8")) if mfile.is_file() else {}
    mcp.setdefault("mcpServers", {})[SERVER_NAME] = {
        "command": python, "args": [str(SERVER)],
        "env": {"INTEGRATED_STUDIO_DATA": str(inst.data_dir), "MC_TOOLS_INSTANCE": inst.id,
                "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}}
    mfile.write_text(json.dumps(mcp, ensure_ascii=False, indent=2) + "\n", "utf-8")
    done.append(".mcp.json")

    # CLAUDE.md
    cfile = inst.dir / "CLAUDE.md"
    block = render_claude_md((kdir / "CLAUDE.instance.md").read_text("utf-8"), inst, pick_world(inst, None))
    cfile.write_text(merge_claude_md(cfile.read_text("utf-8") if cfile.is_file() else "", block), "utf-8")
    done.append("CLAUDE.md")

    # .gitignore
    gi = inst.dir / ".gitignore"
    lines = gi.read_text("utf-8").splitlines() if gi.is_file() else []
    add = [x for x in (".studio/", ".mcp.json") if x not in lines]
    if add:
        gi.write_text("\n".join(lines + add) + "\n", "utf-8")
        done.append(".gitignore")
    return {"instance": inst.id, "installed": done}


def install_all(data_dir: Path | None = None, python: str | None = None) -> list[dict[str, Any]]:
    data = Path(data_dir) if data_dir else default_data_dir()
    out = []
    for d in sorted((data / "instances").glob("inst_*")):
        if (d / "instance.json").is_file():
            out.append(install(d, python))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mc_tools.kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("install")
    a.add_argument("instance_dir")
    a.add_argument("--python")
    b = sub.add_parser("install-all")
    b.add_argument("--data")
    b.add_argument("--python")
    args = ap.parse_args(argv)
    if args.cmd == "install":
        print(json.dumps(install(Path(args.instance_dir), args.python), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(install_all(Path(args.data) if args.data else None, args.python), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

