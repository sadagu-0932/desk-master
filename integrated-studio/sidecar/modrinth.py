"""Modrinth 공통 모듈 — 통합 작업실이 Modrinth 에서 무언가를 받을 때는 전부 여기를 거친다.

규칙
- 파일은 게임 버전과 로더가 **정확히** 일치하는 것만 고른다(가까운 버전으로 대체하지 않는다).
- 같은 버전에 파일이 여러 개면 로더 표시·파일 이름·primary 여부로 고른다.
  26.1 이상 Fabric 은 "modern" 파일을 따로 내는 모드가 있다(예: e4mc 의 e4mc-fabric-x.y.z-modern.jar).
  그래도 하나로 좁혀지지 않으면 `Ambiguous` 를 던져 사용자에게 고르게 한다.
- 받은 파일은 API 가 준 해시(sha512 우선, 없으면 sha1)로 검증하고 맞지 않으면 버린다.
- 의존 모드는 dependencies 의 required 만 자동으로 설치하고 optional 은 안내만 한다.
- 맞는 파일이 없으면 설치하지 않고 한국어로 이유를 알린다(`NoMatch`).

API 형식은 api.modrinth.com/v2 실제 응답(2026-11, e4mc·fabric-api)으로 확인했다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import net
from rpc import RpcError

API = os.environ.get("INTEGRATED_STUDIO_MODRINTH_API", "https://api.modrinth.com/v2")
# 받는 파일은 이 호스트에서만(Modrinth 규격의 허용 목록). 시험용 API 주소면 그 호스트도 허용.
DOWNLOAD_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
LOADER_NAMES = {"fabric": "Fabric", "quilt": "Quilt", "neoforge": "NeoForge", "forge": "Forge", "vanilla": "바닐라"}
# 보조 파일(소스·개발용)은 게임에 넣지 않는다
_AUX = re.compile(r"-(sources|dev|javadoc|api|slim|shadow)\.jar$", re.I)
_MODERN = re.compile(r"modern", re.I)


class NoMatch(RpcError):
    """게임 버전·로더에 정확히 맞는 파일이 없다."""


@dataclass
class Ambiguous(RpcError):
    """후보가 여러 개라 사용자가 골라야 한다. choices 는 [{versionId, filename, versionNumber, loaders}]."""
    message: str
    choices: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        RpcError.__init__(self, self.message)


# ---------------------------------------------------------------- HTTP

def _api() -> str:
    return os.environ.get("INTEGRATED_STUDIO_MODRINTH_API", API).rstrip("/")


def get_json(path: str, params: dict[str, Any] | None = None, body: Any = None) -> Any:
    """Modrinth API 호출. path 는 '/project/x/version' 처럼 API 기준 경로."""
    url = _api() + path
    if params:
        url += "?" + urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                             for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    try:
        with net.open_url(url, data=data) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NoMatch(f"Modrinth 에서 찾을 수 없습니다: {path}") from e
        if e.code == 429:
            raise RpcError("Modrinth 요청이 너무 많습니다. 잠시 뒤 다시 해 주세요.") from e
        raise RpcError(f"Modrinth 서버 오류 {e.code}: {path}") from e
    except urllib.error.URLError as e:
        raise RpcError(f"Modrinth 에 연결하지 못했습니다: {e.reason}") from e


# ---------------------------------------------------------------- 해시·다운로드

file_hashes = net.file_hashes


def verify(path: Path, hashes: dict[str, str] | None) -> bool:
    """API 가 준 해시로 확인. sha512 가 있으면 그것만, 없으면 sha1. 해시가 하나도 없으면 실패로 본다."""
    return net.hashes_match(path, hashes, require=True)


def _allowed_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    api_host = urllib.parse.urlparse(_api()).hostname or ""
    return host in DOWNLOAD_HOSTS or host == api_host


def download(file: dict[str, Any], dest: Path) -> Path:
    """version.files[] 항목 하나를 받아 해시 검증 후 dest 에 둔다. 같은 파일이 이미 있으면 그대로 둔다."""
    url = file.get("url") or ""
    if not _allowed_url(url):
        raise RpcError(f"허용되지 않은 주소라 받지 않았습니다: {url}")
    if dest.is_file() and verify(dest, file.get("hashes")):
        return dest
    try:
        return net.download(url, dest, hashes=file.get("hashes"), require_hash=True)
    except net.HashMismatch as e:
        raise RpcError(f"받은 파일의 해시가 맞지 않아 버렸습니다: {dest.name}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RpcError(f"파일을 받지 못했습니다({dest.name}): {e}") from e


# ---------------------------------------------------------------- 버전 비교

def _mc_tuple(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums) if nums else (0,)


def is_modern_fabric(game_version: str, loader: str) -> bool:
    """26.1 이상 Fabric·Quilt: 'modern' 파일을 따로 내는 모드가 있다."""
    return loader in ("fabric", "quilt") and _mc_tuple(game_version) >= (26, 1)


def _is_modern(version: dict[str, Any], file: dict[str, Any] | None = None) -> bool:
    text = " ".join([version.get("version_number") or "", version.get("name") or "",
                     (file or {}).get("filename") or ""])
    return bool(_MODERN.search(text))


def _game_files(version: dict[str, Any]) -> list[dict[str, Any]]:
    files = [f for f in version.get("files") or [] if f.get("filename", "").endswith(".jar")
             and not _AUX.search(f["filename"])]
    return files or [f for f in version.get("files") or [] if not _AUX.search(f.get("filename", ""))]


def exact_versions(project: str, game_version: str, loader: str) -> list[dict[str, Any]]:
    """게임 버전·로더가 정확히 맞는 버전들(최신순). 로컬에서도 다시 확인한다."""
    params: dict[str, Any] = {"game_versions": [game_version]}
    if loader and loader != "vanilla":
        params["loaders"] = [loader]
    vs = get_json(f"/project/{urllib.parse.quote(project)}/version", params)
    out = []
    for v in vs:
        if game_version not in (v.get("game_versions") or []):
            continue
        if loader and loader != "vanilla" and loader not in (v.get("loaders") or []):
            continue
        out.append(v)
    out.sort(key=lambda v: v.get("date_published") or "", reverse=True)
    return out


def pick_file(versions: list[dict[str, Any]], game_version: str, loader: str, project: str = "") -> tuple[dict, dict]:
    """정확히 맞는 버전들 중에서 (version, file) 하나를 고른다.

    1) release 를 우선(없으면 beta → alpha).
    2) 26.1 이상 Fabric 에서 modern 표시가 있는 후보가 있으면 modern 만 남긴다. 그 아래 버전이면 modern 을 뺀다.
    3) 가장 최신 버전 번호 하나에서 게임용 파일(보조 파일 제외)을 고른다: 하나면 그것, primary 가 하나면 그것.
    4) 그래도 여럿이면 Ambiguous.
    """
    name = project or "모드"
    if not versions:
        raise NoMatch(f"{name}: {game_version} · {LOADER_NAMES.get(loader, loader)} 에 맞는 파일이 Modrinth 에 없습니다. "
                      "가까운 버전으로 대신 설치하지 않았습니다.")
    for kind in ("release", "beta", "alpha"):
        pool = [v for v in versions if (v.get("version_type") or "release") == kind]
        if pool:
            break
    modern = [v for v in pool if _is_modern(v) or any(_is_modern(v, f) for f in _game_files(v))]
    if is_modern_fabric(game_version, loader):
        if modern:
            pool = modern
    elif modern and len(modern) < len(pool):
        pool = [v for v in pool if v not in modern]
    newest = pool[0]
    # 같은 날 같은 번호 계열로 여러 버전이 올라온 경우(로더별 분리 등)도 후보로 본다
    same = [v for v in pool if (v.get("date_published") or "")[:10] == (newest.get("date_published") or "")[:10]
            and (v.get("version_number") or "").split("-")[0] == (newest.get("version_number") or "").split("-")[0]]
    candidates: list[tuple[dict, dict]] = []
    for v in same:
        files = _game_files(v)
        if is_modern_fabric(game_version, loader) and any(_is_modern(v, f) for f in files):
            files = [f for f in files if _is_modern(v, f)] or files
        primaries = [f for f in files if f.get("primary")]
        chosen = files if len(files) <= 1 else (primaries if len(primaries) == 1 else files)
        candidates += [(v, f) for f in chosen]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise NoMatch(f"{name}: {game_version} 버전에 게임에 넣을 파일이 없습니다.")
    raise Ambiguous(f"{name}: {game_version} · {LOADER_NAMES.get(loader, loader)} 에 맞는 파일이 여러 개라 골라야 합니다.",
                    [{"versionId": v["id"], "versionNumber": v.get("version_number"), "filename": f["filename"],
                      "loaders": v.get("loaders", []), "primary": bool(f.get("primary"))} for v, f in candidates])


def version(version_id: str) -> dict[str, Any]:
    return get_json(f"/version/{urllib.parse.quote(version_id)}")


def project(project_id: str) -> dict[str, Any]:
    return get_json(f"/project/{urllib.parse.quote(project_id)}")


def search(query: str = "", kind: str = "mod", game_version: str | None = None, loader: str | None = None,
           offset: int = 0, limit: int = 30) -> dict[str, Any]:
    facets = [[f"project_type:{kind}"]]
    if loader and loader != "vanilla":
        facets.append([f"categories:{loader}"])
    if game_version:
        facets.append([f"versions:{game_version}"])
    return get_json("/search", {"query": query, "facets": facets, "limit": limit, "offset": offset,
                                "index": "relevance" if query else "downloads"})


def versions(project_id: str, game_version: str | None = None, loader: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if game_version:
        params["game_versions"] = [game_version]
    if loader and loader != "vanilla":
        params["loaders"] = [loader]
    return get_json(f"/project/{urllib.parse.quote(project_id)}/version", params or None)


# ---------------------------------------------------------------- 설치

@dataclass
class InstallResult:
    installed: list[dict[str, Any]] = field(default_factory=list)   # {project, filename, versionId, path}
    kept: list[dict[str, Any]] = field(default_factory=list)        # 이미 같은 파일이 있음
    optional: list[dict[str, Any]] = field(default_factory=list)    # 안내만: {project, title}

    def to_dict(self) -> dict[str, Any]:
        return {"installed": self.installed, "kept": self.kept, "optional": self.optional}


def existing_project_files(mods_dir: Path) -> dict[str, Path]:
    """mods/ 안 파일을 해시로 식별해 {project_id: 경로}. .disabled 도 포함(같은 모드 중복 설치를 막는다)."""
    if not mods_dir.is_dir():
        return {}
    paths = [p for p in mods_dir.iterdir() if p.is_file() and (p.suffix == ".jar" or p.name.endswith(".jar.disabled"))]
    try:
        found = identify(paths)
    except RpcError:
        return {}   # 식별은 덤: 실패해도 설치는 계속(같은 파일 이름이면 해시로 다시 확인한다)
    return {info["project_id"]: p for p, info in found.items() if info}


def install(project_id: str, game_version: str, loader: str, mods_dir: Path, *, version_id: str | None = None,
            filename: str | None = None, _result: InstallResult | None = None, _seen: set[str] | None = None,
            _existing: dict[str, Path] | None = None) -> InstallResult:
    """project 를 mods_dir 에 설치하고 required 의존 모드도 설치한다.

    version_id/filename 은 Ambiguous 뒤 사용자가 고른 값. 이미 같은 프로젝트 파일이 있으면
    정확히 같은 파일이면 그대로 두고, 다르면 새 파일을 넣고 예전 파일은 .disabled 로 바꾼다(삭제 금지).
    """
    result = _result or InstallResult()
    seen = _seen if _seen is not None else set()
    existing = _existing if _existing is not None else existing_project_files(mods_dir)
    if project_id in seen:
        return result
    seen.add(project_id)
    if version_id:
        v = version(version_id)
        if game_version not in (v.get("game_versions") or []) or (loader != "vanilla" and loader not in (v.get("loaders") or [])):
            raise NoMatch(f"고른 파일이 {game_version} · {LOADER_NAMES.get(loader, loader)} 용이 아닙니다.")
        files = [f for f in v.get("files") or [] if not filename or f.get("filename") == filename]
        f = files[0] if files else None
        if not f:
            raise NoMatch("고른 파일을 찾을 수 없습니다.")
    else:
        v, f = pick_file(exact_versions(project_id, game_version, loader), game_version, loader, project_id)
    real_pid = v.get("project_id") or project_id
    seen.add(real_pid)
    dest = mods_dir / Path(f["filename"]).name
    entry = {"project": real_pid, "filename": dest.name, "versionId": v["id"], "versionNumber": v.get("version_number"),
             "path": str(dest)}
    old = existing.get(real_pid)
    if old and old.name == dest.name and verify(old, f.get("hashes")):
        result.kept.append(entry)
    elif old and old.name == dest.name + ".disabled" and verify(old, f.get("hashes")):
        result.kept.append({**entry, "disabled": True, "path": str(old)})
    else:
        download(f, dest)
        if old and old.resolve() != dest.resolve() and old.exists() and not old.name.endswith(".disabled"):
            old.rename(old.with_name(old.name + ".disabled"))
        result.installed.append(entry)
    for dep in v.get("dependencies") or []:
        pid = dep.get("project_id")
        kind = dep.get("dependency_type")
        if kind == "required" and pid:
            install(pid, game_version, loader, mods_dir, version_id=None, _result=result, _seen=seen, _existing=existing)
        elif kind == "optional" and pid and pid not in seen:
            try:
                title = project(pid).get("title") or pid
            except RpcError:
                title = pid
            result.optional.append({"project": pid, "title": title})
    return result


# ---------------------------------------------------------------- 해시로 여러 파일 식별

def identify(paths: Iterable[Path], algorithm: str = "sha512") -> dict[Path, dict[str, Any] | None]:
    """파일 여러 개를 한 번에 식별한다(POST /version_files). {경로: version 정보 또는 None}.

    인스턴스 불러오기의 모드 점검(이 모드가 Modrinth 의 어떤 프로젝트·버전인지)에 쓴다.
    """
    paths = list(paths)
    if not paths:
        return {}
    by_hash: dict[str, Path] = {}
    for p in paths:
        try:
            by_hash[file_hashes(p, (algorithm,))[algorithm]] = p
        except OSError:
            continue
    out: dict[Path, dict[str, Any] | None] = {p: None for p in paths}
    keys = list(by_hash)
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        data = get_json("/version_files", body={"hashes": chunk, "algorithm": algorithm})
        for h, v in (data or {}).items():
            if h in by_hash:
                out[by_hash[h]] = v
    return out


def check_mods(mods_dir: Path, game_version: str, loader: str) -> list[dict[str, Any]]:
    """mods/ 점검: 각 파일이 Modrinth 의 무엇인지, 이 게임 버전·로더용이 맞는지."""
    if not mods_dir.is_dir():
        return []
    paths = sorted(p for p in mods_dir.iterdir() if p.is_file() and p.suffix == ".jar")
    try:
        found = identify(paths)
    except RpcError as e:
        return [{"file": p.name, "known": False, "error": str(e)} for p in paths]
    rows = []
    for p in paths:
        v = found.get(p)
        if not v:
            rows.append({"file": p.name, "known": False})
            continue
        ok_ver = game_version in (v.get("game_versions") or [])
        ok_loader = loader == "vanilla" or loader in (v.get("loaders") or [])
        rows.append({"file": p.name, "known": True, "project": v.get("project_id"), "versionNumber": v.get("version_number"),
                     "matches": ok_ver and ok_loader,
                     "note": "" if ok_ver and ok_loader else
                     f"이 파일은 {', '.join((v.get('game_versions') or [])[-3:])} · {', '.join(v.get('loaders') or [])} 용입니다."})
    return rows
