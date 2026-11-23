"""Claude Code 훅: PostToolUse 는 오류면 종료 코드 2 + stderr, Stop 은 남은 오류·미적용이면 막고 반복 제한."""
import io
import json
import sys

from mc_tools import hook


def run(mode, data, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
    code = hook.main([mode])
    return code, capsys.readouterr().err


def base(env, **kw):
    return {"session_id": "s1", "cwd": str(env.inst_dir), **kw}


def test_post_ok_and_error(env, monkeypatch, capsys):
    good = env.copy_pack("good_pack")
    code, err = run("post", base(env, hook_event_name="PostToolUse", tool_name="Write",
                                tool_input={"file_path": str(good / "data/campfire/function/tick.mcfunction")}),
                    monkeypatch, capsys)
    assert code == 0 and err == ""
    bad = env.copy_pack("bad_pack")
    code, err = run("post", base(env, tool_name="Edit", tool_input={"file_path": "datapacks/bad_pack/data/bad/function/main.mcfunction"}),
                    monkeypatch, capsys)
    assert code == 2 and "giv" in err and "main.mcfunction:2" in err


def test_post_ignores_other_files(env, monkeypatch, capsys):
    code, err = run("post", base(env, tool_name="Write", tool_input={"file_path": str(env.inst_dir / "notes.txt")}),
                    monkeypatch, capsys)
    assert code == 0


def test_stop_requires_apply_then_passes(env, monkeypatch, capsys, fake_bridge):
    from mc_tools import apply as ap
    env.copy_pack("good_pack")
    f = "datapacks/good_pack/data/campfire/function/tick.mcfunction"
    run("post", base(env, tool_name="Write", tool_input={"file_path": f}), monkeypatch, capsys)
    code, err = run("stop", base(env, stop_hook_active=False), monkeypatch, capsys)
    assert code == 2 and "apply_changes" in err
    ap.apply_changes(env.inst, env.vd, [f], bridge=fake_bridge(env), settle=0)
    code, err = run("stop", base(env, stop_hook_active=True), monkeypatch, capsys)
    assert code == 0, err


def test_stop_blocks_on_errors_with_limit(env, monkeypatch, capsys):
    env.copy_pack("bad_pack")
    f = "datapacks/bad_pack/data/bad/function/main.mcfunction"
    run("post", base(env, tool_name="Write", tool_input={"file_path": f}), monkeypatch, capsys)
    codes = [run("stop", base(env, stop_hook_active=True), monkeypatch, capsys)[0] for _ in range(hook.MAX_STOP_BLOCKS + 1)]
    assert codes[:hook.MAX_STOP_BLOCKS] == [2] * hook.MAX_STOP_BLOCKS
    assert codes[-1] == 0   # 반복 제한


def test_stop_without_changes_passes(env, monkeypatch, capsys):
    code, _ = run("stop", base(env, session_id="other"), monkeypatch, capsys)
    assert code == 0


def test_hook_outside_instance(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MC_TOOLS_INSTANCE", raising=False)
    code, _ = run("post", {"cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / "a.txt")}}, monkeypatch, capsys)
    assert code == 0
