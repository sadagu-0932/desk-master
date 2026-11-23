"""mc-tools 시험 환경: 작은 샘플 자료(실제 26.3 commands.json 일부)로 가짜 데이터 폴더·인스턴스를 만든다.
게임 jar·실행 중인 게임은 쓰지 않는다(필요한 곳은 mock)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SIDECAR = Path(__file__).resolve().parents[2]
if str(SIDECAR) not in sys.path:
    sys.path.insert(0, str(SIDECAR))

FIX = Path(__file__).resolve().parent / "fixtures"
VERSION = "26.3"
INST_ID = "inst_0000abcd"


class Env:
    def __init__(self, root: Path):
        from mc_tools.context import find_instance
        from mc_tools.reports import VersionData

        self.data = root / "data"
        shutil.copytree(FIX / "version" / "reports", self.data / "reports" / VERSION / "reports")
        shutil.copytree(FIX / "version" / "vanilla", self.data / "vanilla" / VERSION)
        self.inst_dir = self.data / "instances" / INST_ID
        self.inst_dir.mkdir(parents=True)
        (self.inst_dir / "instance.json").write_text(json.dumps(
            {"id": INST_ID, "name": "시험", "version": VERSION, "loader": "fabric", "ccPort": 52853}), "utf-8")
        world = self.inst_dir / "saves" / "world1"
        world.mkdir(parents=True)
        (world / "level.dat").write_bytes(b"\x0a\x00\x00\x00")
        self.inst = find_instance(INST_ID, data_dir=self.data)
        self.vd = VersionData(self.data, VERSION)
        self.vd.write_reload_kinds()

    def copy_pack(self, name: str, as_name: str | None = None, folder: str = "datapacks") -> Path:
        dst = self.inst_dir / folder / (as_name or name)
        shutil.copytree(FIX / name, dst)
        return dst

    def start_game(self) -> None:
        log = self.inst_dir / "logs" / "latest.log"
        log.parent.mkdir(exist_ok=True)
        log.write_text("[12:00:00] [main/INFO]: Setting user: Player\n", "utf-8")

    def stop_game(self) -> None:
        with (self.inst_dir / "logs" / "latest.log").open("a", encoding="utf-8") as f:
            f.write("[12:30:00] [Render thread/INFO]: Stopping!\n")


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    e = Env(tmp_path)
    monkeypatch.setenv("INTEGRATED_STUDIO_DATA", str(e.data))
    monkeypatch.setenv("MC_TOOLS_INSTANCE", INST_ID)
    # 시험 중 휴지통 대신 지우기(시험 폴더 안에서만)
    import mc_tools.context as ctx

    def fake_trash(path, base):
        p = ctx.inside(base, path)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    monkeypatch.setattr(ctx, "trash", fake_trash)
    import mc_tools.apply as ap
    monkeypatch.setattr(ap, "trash", fake_trash)
    return e


class FakeBridge:
    """게임 연결 흉내: 요청을 기록하고, 지정하면 로그에 오류 줄을 남긴다."""

    def __init__(self, env: Env, ok: bool = True, log_line: str | None = None):
        self.env = env
        self.ok = ok
        self.calls: list[tuple[str, dict]] = []
        self.log_line = log_line

    def request(self, action: str, **params):
        self.calls.append((action, params))
        if self.log_line:
            with (self.env.inst_dir / "logs" / "latest.log").open("a", encoding="utf-8") as f:
                f.write(self.log_line + "\n")
        return {"ok": self.ok, "message": "완료", "bridge": True}


@pytest.fixture
def fake_bridge():
    return FakeBridge
