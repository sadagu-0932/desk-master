"""Claude Code 훅. 인스턴스 .claude/settings.json 에 exec 형식으로 등록된다:
    PostToolUse (Edit|Write|MultiEdit): python hook.py post
    Stop:                               python hook.py stop

규칙(설치된 Claude Code 문서 기준):
- 입력은 stdin JSON(cwd, tool_name, tool_input.file_path, stop_hook_active …).
- 종료 코드 2 + stderr: PostToolUse 는 Claude 에게 오류를 보여 주고, Stop 은 멈추지 못하게 하고 이유를 준다.
- 종료 코드 0: 통과(stderr 는 Claude 에게 보이지 않는다).
- Stop 이 끝없이 막지 않도록 연속으로 막은 횟수를 세어 MAX_STOP_BLOCKS 번 뒤에는 보내 준다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "mc_tools"  # noqa: A001

from mc_tools.context import Instance, ToolError, find_instance  # noqa: E402

MAX_STOP_BLOCKS = 4
MAX_LINES = 30


def _err(msg: str) -> int:
    sys.stderr.write(msg.rstrip() + "\n")
    return 2


def _target(inst: Instance, file_path: str) -> tuple[str, Path] | None:
    """바뀐 파일이 속한 팩·모드 (종류, 루트)."""
    try:
        p = Path(file_path)
        p = (p if p.is_absolute() else inst.dir / p).resolve()
        rel = p.relative_to(inst.dir).parts
    except (ValueError, OSError):
        return None
    if len(rel) >= 2 and rel[0] == "datapacks":
        return "datapack", inst.dir / "datapacks" / rel[1]
    if len(rel) >= 2 and rel[0] == "resourcepacks":
        return "resourcepack", inst.dir / "resourcepacks" / rel[1]
    if len(rel) >= 2 and rel[0] == "mods-src":
        return "mod", inst.dir / "mods-src" / rel[1]
    return None


def _validate(kind: str, root: Path, inst: Instance):
    from mc_tools.reports import VersionData
    from mc_tools.validate import validate_datapack, validate_mod, validate_resourcepack

    vd = VersionData(inst.data_dir, inst.version)
    if not vd.has_reports():
        return None  # 자료가 없으면 검사하지 않는다(prepare_version_data 안내는 MCP 쪽에서)
    if kind == "datapack":
        return validate_datapack(vd, root)
    if kind == "resourcepack":
        return validate_resourcepack(vd, root)
    return validate_mod(vd, root)


def _session_file(inst: Instance) -> Path:
    return inst.studio_dir / "hook-session.json"


def _load_session(inst: Instance, session_id: str) -> dict:
    try:
        data = json.loads(_session_file(inst).read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if data.get("session_id") != session_id:
        data = {"session_id": session_id, "changed": {}, "stop_blocks": 0}
    return data


def _save_session(inst: Instance, data: dict) -> None:
    inst.studio_dir.mkdir(parents=True, exist_ok=True)
    _session_file(inst).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _format(rep, title: str) -> str:
    lines = [p.text() for p in rep.errors][:MAX_LINES]
    more = len(rep.errors) - len(lines)
    return "\n".join([title] + lines + ([f"… 외 {more}개"] if more > 0 else []))


def post(data: dict) -> int:
    inp = data.get("tool_input") or {}
    file_path = inp.get("file_path") or inp.get("notebook_path")
    if not file_path:
        return 0
    try:
        inst = find_instance(cwd=data.get("cwd") or ".")
    except ToolError:
        return 0
    tgt = _target(inst, file_path)
    if tgt is None:
        return 0
    kind, root = tgt
    sess = _load_session(inst, data.get("session_id", ""))
    sess["changed"][str(root.relative_to(inst.dir).as_posix())] = {"kind": kind, "time": time.time()}
    _save_session(inst, sess)
    rep = _validate(kind, root, inst)
    if rep is None or rep.ok:
        return 0
    return _err(_format(rep, f"[mc-tools] {root.name} 검사에서 오류가 나왔습니다. 고친 뒤 계속하세요:"))


def stop(data: dict) -> int:
    try:
        inst = find_instance(cwd=data.get("cwd") or ".")
    except ToolError:
        return 0
    sess = _load_session(inst, data.get("session_id", ""))
    if not sess["changed"]:
        return 0
    if sess.get("stop_blocks", 0) >= MAX_STOP_BLOCKS:
        sess["stop_blocks"] = 0
        _save_session(inst, sess)
        return 0  # 반복 제한: 같은 문제로 계속 막지 않는다
    problems: list[str] = []
    for rel, info in sorted(sess["changed"].items()):
        root = inst.dir / rel
        if not root.exists():
            continue
        rep = _validate(info["kind"], root, inst)
        if rep is not None and not rep.ok:
            problems.append(_format(rep, f"{rel}: 검사 오류 {len(rep.errors)}개"))
    from mc_tools.apply import load_last

    last = load_last(inst)
    last_time = (last or {}).get("time", 0)
    pending = [rel for rel, info in sess["changed"].items() if info["time"] > last_time]
    if pending:
        problems.append("아직 apply_changes 로 적용하지 않은 변경이 있습니다: " + ", ".join(sorted(pending))
                        + "\n→ mc-tools 의 apply_changes 를 부르고, 결과 상태를 사용자에게 알려 주세요.")
    elif last and last.get("blocking"):
        errs = (last.get("errors") or []) + (last.get("log_errors") or [])
        problems.append("마지막 적용 결과에 오류가 남아 있습니다:\n" + "\n".join(errs[:MAX_LINES]))
    if not problems:
        sess["stop_blocks"] = 0
        _save_session(inst, sess)
        return 0
    sess["stop_blocks"] = sess.get("stop_blocks", 0) + 1
    _save_session(inst, sess)
    return _err("[mc-tools] 아직 끝나지 않았습니다. 아래를 해결한 뒤 마치세요"
                f"(자동 확인 {sess['stop_blocks']}/{MAX_STOP_BLOCKS}회):\n" + "\n\n".join(problems))


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    mode = argv[0] if argv else ""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return 0
    try:
        if mode == "post":
            return post(data)
        if mode == "stop":
            return stop(data)
    except Exception as e:  # noqa: BLE001 - 훅 자체 오류로 작업을 막지 않는다
        sys.stderr.write(f"[mc-tools] 훅 오류: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
