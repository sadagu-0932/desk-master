"""경로 안전 검사. 모든 파일 작업은 이 함수를 거쳐 기준 폴더 밖이면 거부한다."""
from __future__ import annotations

import os
from pathlib import Path

from rpc import RpcError


def safe_join(base: str | os.PathLike, *parts: str) -> Path:
    base_path = Path(base).resolve()
    target = base_path.joinpath(*parts).resolve()
    if target != base_path and base_path not in target.parents:
        raise RpcError(f"허용되지 않은 경로입니다(인스턴스 폴더 밖): {target}")
    return target


def trash(path: Path, base: str | os.PathLike) -> None:
    """삭제는 휴지통으로만."""
    from send2trash import send2trash

    safe = safe_join(base, os.path.relpath(path, base))
    if safe.exists():
        send2trash(str(safe))
