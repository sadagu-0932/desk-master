"""memory.py 시험: 게임·서버 메모리 추천값, 통합 작업실 프로세스 분류·합계."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory  # noqa: E402

GB = 1024


def test_recommend_by_mod_count_and_loader():
    r = lambda mods, loader="fabric", total=32 * GB: memory.recommend_game_mb(mods, loader, total)["recommendedMb"]  # noqa: E731
    assert r(0) == 2 * GB and r(10) == 3 * GB and r(80) == 4 * GB and r(150) == 6 * GB and r(300) == 8 * GB
    assert r(150, "neoforge") == 7 * GB                       # Forge 계열은 1GB 더


def test_recommend_never_over_half_of_pc_memory():
    a = memory.recommend_game_mb(300, "forge", 8 * GB)
    assert a["recommendedMb"] == 4 * GB and "절반" in a["reason"]
    assert memory.recommend_game_mb(300, "forge", None)["recommendedMb"] == 9 * GB   # PC 메모리를 모르면 그대로


def test_server_default_and_xmx():
    assert memory.server_default_mb(16 * GB) == 2 * GB
    assert memory.server_default_mb(4 * GB) == GB             # 작은 PC 는 1/4
    assert memory.server_xmx({"memoryMb": 3072}) == "-Xmx3072M"


def test_count_mods(tmp_path):
    (tmp_path / "mods").mkdir()
    for n in ("a.jar", "b.jar", "c.jar.disabled", "readme.txt"):
        (tmp_path / "mods" / n).write_text("x")
    assert memory.count_mods(tmp_path) == 2 and memory.count_mods(tmp_path / "없음") == 0


def test_summarize_only_our_process_tree_and_game():
    MB = 1024 * 1024
    rows = [
        (1, 0, "explorer.exe", 100 * MB, "explorer"),
        (10, 1, "integrated-studio.exe", 150 * MB, r'"C:\\App\\integrated-studio.exe"'),
        (11, 10, "integrated-studio.exe", 400 * MB, "integrated-studio.exe --type=renderer"),
        (12, 10, "integrated-studio.exe", 120 * MB, "integrated-studio.exe C:\\App\\resources\\app\\lib\\backend\\main.js"),
        (13, 12, "integrated-studio.exe", 250 * MB, "integrated-studio.exe ...\\plugin-host.js"),
        (14, 12, "python.exe", 40 * MB, "python main.py --data x"),
        (15, 14, "java.exe", 2000 * MB, "java -Xmx2048M -jar server.jar nogui"),
        (16, 12, "integrated-studio.exe", 180 * MB, "integrated-studio.exe ...claude-agent-sdk\\cli.js"),
        (20, 1, "javaw.exe", 3000 * MB, "javaw -cp ... net.minecraft.client.main.Main --gameDir x"),
        (30, 1, "python.exe", 500 * MB, "python 다른프로그램.py"),           # 우리 것 아님
        (31, 1, "integrated-studio.exe", 999 * MB, "다른 창이 아닌 별개 실행"),   # 다른 뿌리
    ]
    s = memory.summarize(rows, {10})
    by = {i["label"]: i for i in s["items"]}
    assert by["마인크래프트 게임"]["mb"] == 3000 and by["로컬·전용 서버"]["mb"] == 2000
    assert by["화면"]["mb"] == 400 and by["VS Code 확장 실행기(CommandCrafter)"]["mb"] == 250
    assert by["Claude 패널"]["mb"] == 180 and by["사이드카(파이썬)"]["mb"] == 40
    assert by["백엔드"]["mb"] == 120 and by["앱 본체"]["mb"] == 150
    assert s["totalMb"] == 3000 + 2000 + 400 + 250 + 180 + 150 + 120 + 40
    assert s["items"][0]["label"] == "마인크래프트 게임"                   # 큰 것부터
