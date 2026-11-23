"""claude-kit 설치: 스킬 복사, 설정 합치기(기존 값 유지·중복 없음), .mcp.json, CLAUDE.md 구간 교체."""
import json
from pathlib import Path

from mc_tools import kit


def test_install(env):
    claude = env.inst_dir / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Read"], "deny": ["Bash"]},
        "hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "echo mine"}]}]}}), "utf-8")
    (env.inst_dir / "CLAUDE.md").write_text("# 내 메모\n사용자가 쓴 내용\n", "utf-8")
    r = kit.install(env.inst_dir, python="/usr/bin/python3")
    assert ".mcp.json" in r["installed"]
    for sk in ("datapack", "fabric-mod", "resourcepack"):
        text = (claude / "skills" / sk / "SKILL.md").read_text("utf-8")
        assert text.startswith("---\nname: ")
    s = json.loads((claude / "settings.json").read_text("utf-8"))
    assert s["permissions"]["deny"] == ["Bash"] and "Read" in s["permissions"]["allow"]
    assert "mcp__mc-tools" in s["permissions"]["allow"] and s["enabledMcpjsonServers"] == ["mc-tools"]
    post = s["hooks"]["PostToolUse"]
    assert post[0]["hooks"][0]["command"] == "echo mine"   # 사용자 훅 유지
    ours = post[-1]["hooks"][0]
    assert ours["command"] == "/usr/bin/python3"
    assert Path(ours["args"][0]).name == "hook.py" and Path(ours["args"][0]).parent.name == "mc_tools"
    assert ours["args"][1] == "post" and "${" not in json.dumps(s)
    assert s["hooks"]["Stop"][0]["hooks"][0]["args"][1] == "stop"
    mcp = json.loads((env.inst_dir / ".mcp.json").read_text("utf-8"))["mcpServers"]["mc-tools"]
    assert mcp["command"] == "/usr/bin/python3" and mcp["env"]["MC_TOOLS_INSTANCE"] == env.inst.id
    assert Path(mcp["args"][0]).name == "server.py"
    md = (env.inst_dir / "CLAUDE.md").read_text("utf-8")
    assert md.startswith("# 내 메모") and "26.3" in md and "world1" in md and "{{" not in md
    gi = (env.inst_dir / ".gitignore").read_text("utf-8")
    assert ".studio/" in gi and ".mcp.json" in gi


def test_install_twice_is_idempotent(env):
    kit.install(env.inst_dir, python="py")
    first = {p: p.read_text("utf-8") for p in [env.inst_dir / "CLAUDE.md", env.inst_dir / ".claude/settings.json"]}
    kit.install(env.inst_dir, python="py")
    for p, text in first.items():
        assert p.read_text("utf-8") == text
    s = json.loads((env.inst_dir / ".claude/settings.json").read_text("utf-8"))
    assert len(s["hooks"]["PostToolUse"]) == 1 and len(s["hooks"]["Stop"]) == 1
    assert (env.inst_dir / "CLAUDE.md").read_text("utf-8").count("mc-tools:start") == 1


def test_install_all(env):
    out = kit.install_all(env.data, python="py")
    assert [o["instance"] for o in out] == [env.inst.id]
