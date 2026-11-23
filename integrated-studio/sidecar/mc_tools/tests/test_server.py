"""MCP 서버: 프로토콜(initialize·tools/list·tools/call)과 실제 자식 프로세스의 표준 출력이 프로토콜만 담는지."""
import json
import os
import subprocess
import sys
from pathlib import Path

from mc_tools import server

SERVER = Path(server.__file__)


def test_initialize_and_list():
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert r["result"]["serverInfo"]["name"] == "mc-tools"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"command_syntax", "registry_search", "block_states", "vanilla_file", "scaffold_datapack",
            "scaffold_fabric_mod", "scaffold_resourcepack", "validate_datapack", "validate_resourcepack",
            "build_mod", "apply_changes"} <= names
    for t in tools:
        assert t["inputSchema"]["type"] == "object" and t["description"]
    assert server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"] == -32601


def _call(tool, **args):
    r = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    res = r["result"]
    text = res["content"][0]["text"]
    try:
        return res, json.loads(text)
    except ValueError:
        return res, text


def test_tools(env, monkeypatch):
    monkeypatch.chdir(env.inst_dir)
    _, out = _call("command_syntax", command_path="execute if")
    assert any(n["name"] == "block" for n in out["next"])
    res, out = _call("command_syntax", command_path="execute nope")
    assert res["isError"] and "가능한 것" in out
    _, out = _call("check_command", command="give @p diamond_swrod")
    assert not out["ok"] and "없는 ID" in out["issues"][0]
    _, out = _call("registry_search", registry="item", query="diamond")
    assert "minecraft:diamond_sword" in out["ids"]
    _, out = _call("block_states", block_id="campfire")
    assert "lit" in out["properties"]
    _, out = _call("vanilla_file", path="recipe/diamond_sword.json")
    assert "crafting_shaped" in out["content"]
    res, out = _call("vanilla_file", path="../../../../etc/passwd")
    assert res["isError"]
    _, out = _call("scaffold_datapack", name="p1", namespace="p1")
    _, out = _call("validate_datapack", pack_path="p1")
    assert out["ok"], out
    env.copy_pack("bad_pack")
    res, out = _call("validate_datapack", pack_path="datapacks/bad_pack")
    assert not out["ok"] and any("giv" in e for e in out["errors"]) and res["isError"] is False
    _, out = _call("game_status")
    assert out["version"] == "26.3" and out["worlds"] == ["world1"]


def test_subprocess_stdout_is_protocol_only(env):
    """실제로 띄워서: 사이드카 모듈(rpc)이 stdout 을 건드려도 응답 줄만 나오는지."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "check_command",
                                                                        "arguments": {"command": "say 안녕"}}},
    ]
    env_vars = {**os.environ, "INTEGRATED_STUDIO_DATA": str(env.data), "MC_TOOLS_INSTANCE": env.inst.id,
                "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, str(SERVER)], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, encoding="utf-8", env=env_vars, cwd=env.inst_dir, timeout=60)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2, p.stdout + p.stderr
    replies = [json.loads(ln) for ln in lines]
    assert replies[0]["id"] == 1 and replies[1]["id"] == 2
    assert json.loads(replies[1]["result"]["content"][0]["text"])["ok"] is True
