"""인터넷 요청 공통 부분.

모든 모듈(runner·server_runner·modrinth·importers·packs)이 같은 방식으로 받는다:
- 같은 User-Agent, 정해진 시간 제한
- 다운로드는 `<이름>.part` 로 받고 → 해시 확인 → 맞을 때만 제자리로 옮긴다(받다 끊기거나 해시가 틀리면 지움)

어느 서버의 오류인지 알려 주는 한국어 문구는 부르는 쪽이 감싼다(여기서는 urllib 오류·HashMismatch 를 그대로 올린다).
시험에서 `urllib.request.urlopen` 을 바꿔 끼우면 여기의 모든 요청에 적용된다(호출할 때 찾으므로).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Iterable

USER_AGENT = "integrated-studio/0.1 (personal launcher)"
# 해시가 여럿 있으면 강한 것부터 하나만 확인한다
HASH_ORDER = ("sha512", "sha256", "sha1", "md5")


class HashMismatch(ValueError):
    """받은 파일의 해시가 주어진 값과 다르다(파일은 이미 지웠다)."""


def open_url(url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None, timeout: float = 60):
    """요청을 열어 응답을 돌려준다(with 로 닫을 것). data 가 있으면 JSON 본문으로 보낸다."""
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    if data is not None:
        h["Content-Type"] = "application/json"
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout)


def get_bytes(url: str, timeout: float = 30) -> bytes:
    with open_url(url, timeout=timeout) as r:
        return r.read()


def get_json(url: str, timeout: float = 30) -> Any:
    with open_url(url, timeout=timeout) as r:
        return json.load(r)


def file_hashes(path: Path, algos: Iterable[str] = ("sha512", "sha1")) -> dict[str, str]:
    """파일을 한 번 읽으며 여러 해시를 함께 계산한다."""
    hs = {a: hashlib.new(a) for a in algos}
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            for h in hs.values():
                h.update(chunk)
    return {a: h.hexdigest() for a, h in hs.items()}


def hashes_match(path: Path, hashes: dict[str, str] | None, *, require: bool = False) -> bool:
    """주어진 해시 중 가장 강한 것 하나로 확인한다. 해시가 없으면 require 일 때만 실패."""
    clean = {k.lower(): v.lower() for k, v in (hashes or {}).items() if v}
    for algo in HASH_ORDER:
        if algo in clean:
            return file_hashes(path, (algo,))[algo] == clean[algo]
    return not require


def download(url: str, dest: Path, *, hashes: dict[str, str] | None = None, require_hash: bool = False,
             timeout: float = 180) -> Path:
    """url 을 dest 로 받는다. 해시가 맞지 않으면 HashMismatch(받은 파일은 지움). 네트워크 오류는 그대로 올린다."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with open_url(url, timeout=timeout) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 16)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if (hashes or require_hash) and not hashes_match(tmp, hashes, require=require_hash):
        tmp.unlink(missing_ok=True)
        raise HashMismatch(dest.name)
    tmp.replace(dest)
    return dest
