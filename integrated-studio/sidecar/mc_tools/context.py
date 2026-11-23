"""인스턴스·데이터 폴더 찾기와 경로 안전 검사.

mc-tools 는 사이드카 본체(main.py)와 다른 프로세스(Claude 가 띄우는 MCP 서버·훅)에서도 돈다.
그래서 사이드카 모듈 중 stdout 에 쓰는 것(rpc.notify)은 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

INSTANCE_ID_RE = re.compile(r"inst_[0-9a-f]{8}")


class ToolError(Exception):
    """사용자·Claude 에게 그대로 보여줄 오류(한국어)."""


def default_data_dir() -> Path:
    env = os.environ.get("INTEGRATED_STUDIO_DATA")
    if env:
        return Path(env).resolve()
    dev = SIDECAR_DIR.parent / "data"
    if (SIDECAR_DIR.parent / "package.json").is_file() and dev.is_dir():
        return dev.resolve()
    return (Path.home() / ".integrated-studio" / "data").resolve()


def inside(base: Path, target: str | os.PathLike) -> Path:
    """target 을 정규화하고 base 밖이면 거부한다(상대 경로는 base 기준)."""
    base = Path(base).resolve()
    p = Path(target)
    p = (p if p.is_absolute() else base / p).resolve()
    if p != base and base not in p.parents:
        raise ToolError(f"인스턴스 폴더 밖 경로는 다룰 수 없습니다: {target}")
    return p


def trash(path: Path, base: Path) -> None:
    """삭제는 휴지통으로만."""
    from send2trash import send2trash

    p = inside(base, path)
    if p.exists():
        send2trash(str(p))


@dataclass
class Instance:
    id: str
    dir: Path
    version: str
    loader: str
    data_dir: Path
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def mc_dir(self) -> Path:
        return self.data_dir / "minecraft"

    @property
    def studio_dir(self) -> Path:
        """mc-tools 가 쓰는 인스턴스 안 작업 폴더(백업·마지막 적용 결과·게임 연결 요청)."""
        return self.dir / ".studio"


def find_instance(instance_id: str | None = None, data_dir: str | os.PathLike | None = None,
                  cwd: str | os.PathLike | None = None) -> Instance:
    """id → 환경 변수 MC_TOOLS_INSTANCE → cwd 가 인스턴스 폴더(또는 그 안)인지 순서로 찾는다."""
    data = Path(data_dir).resolve() if data_dir else default_data_dir()
    iid = instance_id or os.environ.get("MC_TOOLS_INSTANCE")
    d: Path | None = None
    if not iid and cwd:
        here = Path(cwd).resolve()
        for p in [here, *here.parents]:
            if INSTANCE_ID_RE.fullmatch(p.name) and (p / "instance.json").is_file():
                d, iid, data = p, p.name, p.parent.parent
                break
    if not iid:
        raise ToolError("인스턴스를 알 수 없습니다. 인스턴스 폴더에서 실행하거나 instance_id 를 주세요.")
    if not INSTANCE_ID_RE.fullmatch(iid):
        raise ToolError(f"잘못된 인스턴스 id 입니다: {iid}")
    if d is None:
        d = inside(data / "instances", iid)
    meta_file = d / "instance.json"
    if not meta_file.is_file():
        raise ToolError(f"인스턴스가 없습니다: {iid}")
    meta = json.loads(meta_file.read_text("utf-8"))
    return Instance(id=iid, dir=d.resolve(), version=meta["version"], loader=meta.get("loader", "vanilla"),
                    data_dir=data, meta=meta)
