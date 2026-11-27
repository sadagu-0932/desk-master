"""프런트·백엔드가 사이드카에 보내는 RPC 인자 이름이 실제 핸들러와 맞는지 점검.

(연결 인스턴스 실행이 'id' 대신 'iid' 를 받아 실행이 통째로 안 되던 문제 재발 방지.)
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "sidecar"
sys.path.insert(0, str(SIDECAR))

CALL_RE = re.compile(r"""\.call(?:<[^>]*>)?\(\s*'([a-z_]+)'\s*(?:,\s*\{([^}]*)\})?""")


def _frontend_calls() -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for f in (ROOT / "theia-extensions").glob("*/src/**/*.ts*"):
        for m in CALL_RE.finditer(f.read_text("utf-8")):
            keys = set()
            for part in (m.group(2) or "").split(","):
                part = part.strip()
                if not part or part.startswith("..."):
                    continue
                keys.add(part.split(":")[0].strip())
            calls.setdefault(m.group(1), set()).update(keys)
    return calls


def _handlers(tmp_path) -> dict:
    import main
    captured: dict = {}
    orig = main.serve
    main.serve = lambda h, b: captured.update(h)
    old_argv = sys.argv
    sys.argv = ["main.py", "--data", str(tmp_path)]
    try:
        main.main()
    finally:
        main.serve = orig
        sys.argv = old_argv
    return captured


def test_rpc_argument_names_match(tmp_path):
    calls = _frontend_calls()
    handlers = _handlers(tmp_path)
    assert len(calls) > 40
    bad = []
    for name, keys in sorted(calls.items()):
        h = handlers.get(name)
        if h is None:
            bad.append(f"{name}: 핸들러 없음")
            continue
        try:
            params = inspect.signature(h).parameters
        except (TypeError, ValueError):
            continue
        if any(p.kind == p.VAR_KEYWORD for p in params.values()):
            continue
        for k in keys:
            if k not in params:
                bad.append(f"{name}: 인자 '{k}' 없음 (받는 것: {list(params)})")
    assert not bad, "\n".join(bad)
