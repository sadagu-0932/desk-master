"""모드팩 서버 파일(사용자 제안 2026-11-28 "모드팩을 추가할 때 서버 여는 다운로드 파일도 기억해서 서버를 열 때 그걸 쓰자").

모드팩을 가져올 때 '서버용 파일 목록'을 인스턴스 앱 폴더의 serverpack/ 에 기억하고, 전용 서버를 처음 켤 때(또는 모드팩이 바뀌었을 때)
인스턴스 모드를 추측해 복사하는 대신 그 목록대로 서버를 꾸민다.
- Modrinth .mrpack(공식 형식 modrinth.index.json): files[].env.server 가 "unsupported" 가 아닌 파일만(제작자가 서버에 쓰라고 한 것),
  overrides/ + server-overrides/ (client-overrides/ 는 제외). 파일은 sha512·sha1 확인, 주소는 Modrinth 가 허용한 곳만.
- CurseForge: 모드팩 파일 정보의 serverPackFileId(제작자가 올린 공식 서버 팩 zip). CurseForge 에서 검색해 설치한 모드팩만 알 수 있다
  (zip 파일만 받아 가져오면 manifest.json 에 프로젝트·파일 id 가 없다). 서버 팩 zip 은 mods·config 같은 폴더만 풀고
  실행 스크립트·실행 파일·eula.txt(EULA 는 사용자가 직접 동의)·server.properties(포트·정품 설정은 앱 것)·라이브러리는 풀지 않는다.
[모드 확인]에서 서버에서 뺀 모드(excluded)는 넣지 않는다. 같은 팩이면 다시 적용하지 않는다(서버에서 고친 설정을 덮지 않게).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Callable

from paths import safe_join
from rpc import RpcError

PACK_DIR = "serverpack"
INFO = "serverpack.json"
NO_EXTRACT_EXT = (".bat", ".sh", ".cmd", ".ps1", ".exe", ".command", ".jar.disabled")
NO_EXTRACT_ROOT_DIRS = {"libraries", "versions", ".fabric", "logs", "crash-reports", "world"}
NO_EXTRACT_FILES = {"eula.txt", "server.properties", "user_jvm_args.txt", "run.bat", "run.sh"}


def _sha1(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remember_mrpack(inst_dir: Path, mrpack: Path) -> dict[str, Any]:
    """가져온 .mrpack 을 인스턴스 앱 폴더에 보관하고 서버 파일 정보를 쓴다."""
    d = inst_dir / PACK_DIR
    d.mkdir(parents=True, exist_ok=True)
    target = d / "pack.mrpack"
    shutil.copy2(mrpack, target)
    with zipfile.ZipFile(target) as zf:
        idx = json.loads(zf.read("modrinth.index.json"))
    server_files = [f for f in idx.get("files", []) if (f.get("env") or {}).get("server") != "unsupported"]
    info = {"kind": "mrpack", "file": target.name, "key": "mrpack:" + _sha1(target), "name": idx.get("name"),
            "version": idx.get("versionId"), "serverFiles": len(server_files),
            "clientOnly": [Path(f["path"]).name for f in idx.get("files", []) if (f.get("env") or {}).get("server") == "unsupported"]}
    (inst_dir / INFO).write_text(json.dumps(info, ensure_ascii=False, indent=1), "utf-8")
    return info


def remember_curseforge(inst_dir: Path, mod_id: int | str, file_id: int | str, server_pack_file_id: int | str | None,
                        name: str | None = None) -> dict[str, Any] | None:
    if not server_pack_file_id:
        return None
    info = {"kind": "curseforge", "modId": int(mod_id), "fileId": int(file_id), "serverPackFileId": int(server_pack_file_id),
            "key": f"curseforge:{int(mod_id)}:{int(server_pack_file_id)}", "name": name}
    (inst_dir / INFO).write_text(json.dumps(info, ensure_ascii=False, indent=1), "utf-8")
    return info


def read_info(inst_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads((inst_dir / INFO).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _skip_name(name: str, excluded_files: set[str]) -> bool:
    return Path(name).name in excluded_files


def apply_mrpack(inst_dir: Path, info: dict[str, Any], server_dir: Path, excluded_files: set[str],
                 download: Callable[[dict[str, Any], Path], Any], allowed_hosts: tuple[str, ...] | set[str],
                 log: Callable[[str], None]) -> list[str]:
    """.mrpack 의 서버용 파일을 서버 폴더에. 넣은 mods/ 파일 이름 목록을 돌려준다."""
    pack = inst_dir / PACK_DIR / info["file"]
    if not pack.is_file():
        raise RpcError("기억해 둔 모드팩 파일이 없습니다. 모드팩을 다시 가져와 주세요.")
    mods: list[str] = []
    with zipfile.ZipFile(pack) as zf:
        idx = json.loads(zf.read("modrinth.index.json"))
        files = [f for f in idx.get("files", []) if (f.get("env") or {}).get("server") != "unsupported"]
        log(f"모드팩 서버 파일로 서버를 꾸밉니다: {idx.get('name') or ''} {idx.get('versionId') or ''} (서버용 파일 {len(files)}개)")
        for f in files:
            rel = f["path"].replace("\\", "/")
            if _skip_name(rel, excluded_files):
                continue
            urls = [u for u in f.get("downloads", []) if urllib.parse.urlparse(u).hostname in allowed_hosts]
            if not urls:
                log(f"건너뜀(허용되지 않은 다운로드 주소): {rel}")
                continue
            dest = safe_join(server_dir, *rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            download({"url": urls[0], "hashes": f.get("hashes", {})}, dest)
            if rel.startswith("mods/"):
                mods.append(dest.name)
        n = 0
        for prefix in ("overrides/", "server-overrides/"):     # client-overrides/ 는 서버에 넣지 않는다
            for zi in zf.infolist():
                if zi.is_dir() or not zi.filename.startswith(prefix):
                    continue
                rel = zi.filename[len(prefix):]
                if not rel or _skip_name(rel, excluded_files) or Path(rel).name.lower() in NO_EXTRACT_FILES:
                    continue
                target = safe_join(server_dir, *rel.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(zi) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += 1
                if rel.startswith("mods/"):
                    mods.append(target.name)
        log(f"모드팩 서버 파일: 받은 파일 {len(files)}개, 설정 등 {n}개")
    return mods


def apply_server_zip(zip_path: Path, server_dir: Path, excluded_files: set[str], log: Callable[[str], None]) -> list[str]:
    """CurseForge 공식 서버 팩 zip 풀기. mods/ 가 있는 폴더를 뿌리로 보고, 그 아래 폴더만(실행 파일·EULA·서버 설정·라이브러리 제외)."""
    mods: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        root = next((n[: n.index("mods/")] for n in sorted(names, key=len) if "mods/" in n and n.endswith(".jar")), None)
        if root is None:
            raise RpcError("서버 팩에서 mods 폴더를 찾지 못했습니다.")
        n_files = 0
        for name in names:
            if not name.startswith(root):
                continue
            rel = name[len(root):]
            parts = rel.split("/")
            if len(parts) < 2 or parts[0] in NO_EXTRACT_ROOT_DIRS:
                continue                                   # 뿌리의 파일(서버 jar·스크립트·eula·properties)은 풀지 않음
            if rel.lower().endswith(NO_EXTRACT_EXT) or parts[-1].lower() in NO_EXTRACT_FILES or _skip_name(rel, excluded_files):
                continue
            if ".." in parts:
                raise RpcError(f"허용되지 않은 파일 경로입니다: {rel}")
            target = safe_join(server_dir, *parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n_files += 1
            if parts[0] == "mods" and parts[-1].endswith(".jar"):
                mods.append(parts[-1])
        log(f"CurseForge 공식 서버 팩을 풀었습니다: 파일 {n_files}개(모드 {len(mods)}개)")
    return mods
