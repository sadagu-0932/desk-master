"""모드팩·인스턴스 가져오기와 모드 검색·추가.

(다른 런처 인스턴스 감지·불러오기는 importers/launchers.py, importers/local.py)

- .mrpack (Modrinth 모드팩 파일)
- CurseForge .zip 모드팩 (manifest.json)
- Prism Launcher / MultiMC 인스턴스 폴더 (instance.cfg + mmc-pack.json)
- Modrinth 검색 → 모드팩 설치 / 모드 추가
- CurseForge 검색 → 모드팩 설치 / 모드 추가 (API 키 필요, OS 자격 증명 저장소에 보관)

API 형식은 Prism Launcher 소스(modplatform/flame, modplatform/modrinth)와 대조했다.
모든 파일 쓰기는 인스턴스 폴더 안으로 제한(safe_join)하고, 받은 파일은 해시로 확인한다.
"""
from __future__ import annotations

import configparser
import hashlib
import json
import sys
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import modrinth
from instances import LOADERS as ALL_LOADERS, InstanceStore
from paths import safe_join
from rpc import RpcError, notify

from .launchers import _cfg, is_account_file

USER_AGENT = "integrated-studio/0.1 (personal launcher)"
MODRINTH_API = os.environ.get("INTEGRATED_STUDIO_MODRINTH_API", "https://api.modrinth.com/v2")
CURSEFORGE_API = os.environ.get("INTEGRATED_STUDIO_CURSEFORGE_API", "https://api.curseforge.com/v1")
CF_GAME_ID = 432
CF_CLASS = {"modpack": 4471, "mod": 6}
CF_LOADER = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CF_LOADER_NAME = {v: k for k, v in CF_LOADER.items()}
# .mrpack 안 파일은 이 호스트에서만 받는다(Modrinth 규격)
MRPACK_HOSTS = modrinth.DOWNLOAD_HOSTS
KEYRING_SERVICE = "integrated-studio"
KEYRING_CF = "curseforge-api-key"
SUPPORTED_LOADERS = ("vanilla", "fabric")


# ---------------------------------------------------------------- HTTP

def _request(url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None, timeout: int = 60):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    if data is not None:
        h["Content-Type"] = "application/json"
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout)


_INVISIBLE = re.compile(r"[\s\u200b-\u200f\u2028-\u202f\u2060\ufeff\u00a0]")


def clean_cf_key(raw: str) -> str:
    """붙여넣을 때 딸려 오는 공백·줄바꿈·보이지 않는 문자·따옴표를 뺀다(키 안에는 공백이 없다)."""
    key = _INVISIBLE.sub("", raw or "")
    while len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'`":
        key = key[1:-1]
    return key


def describe_cf_key(key: str) -> str:
    """오류 안내용 키 모양(비밀 부분은 보이지 않게). CurseForge 키는 보통 '$2a$10$'로 시작하는 60자."""
    shape = f"{len(key)}자"
    if key.startswith("$2a$") or key.startswith("$2b$"):
        shape += f", '{key[:7]}'로 시작"
    else:
        shape += ", '$2a$10$'로 시작하지 않음"
    return shape


def _cf_http_error(e: urllib.error.HTTPError, key: str) -> RpcError:
    ctype = (e.headers.get("Content-Type") or "").lower() if e.headers else ""
    try:
        body = e.read(400).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        body = ""
    print(f"[curseforge] HTTP {e.code} {ctype} {body[:200]!r}", file=sys.stderr)  # 키는 남기지 않는다
    if "text/html" in ctype or "<html" in body.lower() or (e.headers and e.headers.get("cf-mitigated")):
        return RpcError(f"CurseForge 서버가 접속을 막았습니다(HTTP {e.code}, 보안 검사 페이지). 키 문제가 아닐 수 있습니다. "
                        "잠시 뒤 다시 시도하고, VPN·프록시·보안 프로그램을 쓰고 있다면 끄고 해 보세요.")
    return RpcError(f"CurseForge가 이 키를 받아들이지 않았습니다(HTTP {e.code}). 입력한 키: {describe_cf_key(key)}. "
                    "console.curseforge.com → API Keys 에 보이는 키 전체를 복사했는지 확인하세요"
                    "(보통 '$2a$10$'로 시작하는 60자).")


def _json(url: str, **kw: Any) -> Any:
    try:
        with _request(url, **kw) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        key = (kw.get("headers") or {}).get("x-api-key")
        if e.code in (401, 403) and key is not None:
            raise _cf_http_error(e, key) from e
        raise RpcError(f"서버 오류 {e.code}: {url.split('?')[0]}") from e
    except urllib.error.URLError as e:
        raise RpcError(f"서버에 연결하지 못했습니다({urllib.parse.urlparse(url).hostname}): {e.reason}") from e


def _download(url: str, dest: Path, hashes: dict[str, str] | None = None) -> None:
    """받아서 해시를 확인한 뒤 제자리에 둔다. 이미 같은 파일이 있으면 건너뛴다."""
    hashes = {k: v.lower() for k, v in (hashes or {}).items() if v}
    if dest.is_file() and hashes and _matches(dest, hashes):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with _request(url, timeout=180) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 16)
    if hashes and not _matches(tmp, hashes):
        tmp.unlink(missing_ok=True)
        raise RpcError(f"받은 파일의 해시가 맞지 않습니다: {dest.name}")
    tmp.replace(dest)


def _matches(path: Path, hashes: dict[str, str]) -> bool:
    for algo in ("sha512", "sha1", "md5"):
        if algo in hashes:
            h = hashlib.new(algo)
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    h.update(chunk)
            return h.hexdigest() == hashes[algo]
    return True


def _safe_rel(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or ".." in rel.split("/"):
        raise RpcError(f"허용되지 않은 파일 경로입니다: {rel}")
    return rel


def _extract_dir(zf: zipfile.ZipFile, prefix: str, dest_root: Path) -> int:
    """zip 안의 prefix/ 아래를 dest_root 로 푼다(zip slip 방지)."""
    count = 0
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = _safe_rel(info.filename[len(prefix):])
        if not rel:
            continue
        target = safe_join(dest_root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        count += 1
    return count


def _parallel(jobs: list[tuple[str, Any]], inst_id: str, stage_text: str) -> list[str]:
    """(이름, 함수) 목록을 병렬 실행. 실패한 이름 목록을 돌려준다."""
    failed: list[str] = []
    total = len(jobs)
    if not total:
        return failed
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs}
        for fut in as_completed(futures):
            done += 1
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{futures[fut]} ({e})")
            notify("progress", {"id": inst_id, "stage": "import", "text": stage_text, "value": done, "max": total})
    return failed


# ---------------------------------------------------------------- 로더 정보 정리

def _loader_from_mrpack(deps: dict[str, str]) -> tuple[str, str | None]:
    if "fabric-loader" in deps:
        return "fabric", deps["fabric-loader"]
    for other in ("neoforge", "forge", "quilt-loader"):
        if other in deps:
            return other.replace("-loader", ""), deps[other]
    return "vanilla", None


def _loader_from_cf(mod_loaders: list[dict[str, Any]]) -> tuple[str, str | None]:
    primary = next((m for m in mod_loaders if m.get("primary")), mod_loaders[0] if mod_loaders else None)
    if not primary:
        return "vanilla", None
    lid = str(primary.get("id", ""))           # 예: "fabric-0.16.10", "forge-47.2.0"
    name, _, ver = lid.partition("-")
    return name.lower(), ver or None


def _require_supported(loader: str) -> None:
    if loader not in SUPPORTED_LOADERS:
        raise RpcError(f"이 모드팩은 {loader} 로더용입니다. 통합 작업실은 지금 바닐라와 Fabric만 지원합니다.")


def _prism_zip_root(names: set[str]) -> str | None:
    """Prism 내보내기 zip 안 인스턴스 위치('' 또는 '폴더/'). mmc-pack.json 이 없으면 None."""
    hits = sorted((n for n in names if n == "mmc-pack.json" or (n.endswith("/mmc-pack.json") and n.count("/") == 1)), key=len)
    return hits[0][: -len("mmc-pack.json")] if hits else None


class Importers:
    def __init__(self, store: InstanceStore, data_dir: Path):
        self.store = store
        self.tmp_root = (data_dir / "tmp").resolve()

    # ============================================================ 미리 보기
    def inspect_import(self, path: str) -> dict[str, Any]:
        """고른 파일/폴더가 무엇인지 알아내 미리 보기 정보를 돌려준다."""
        p = Path(path)
        if p.is_dir():
            return self._inspect_prism(p)
        if not p.is_file():
            raise RpcError(f"파일을 찾을 수 없습니다: {path}")
        if not zipfile.is_zipfile(p):
            raise RpcError(".mrpack 또는 .zip 모드팩 파일이 아닙니다.")
        with zipfile.ZipFile(p) as zf:
            names = set(zf.namelist())
            if "modrinth.index.json" in names:
                idx = json.loads(zf.read("modrinth.index.json"))
                loader, lver = _loader_from_mrpack(idx.get("dependencies", {}))
                return {"kind": "mrpack", "name": idx.get("name", p.stem), "version": idx.get("dependencies", {}).get("minecraft"),
                        "loader": loader, "loaderVersion": lver, "files": len(idx.get("files", [])),
                        "supported": loader in SUPPORTED_LOADERS, "packVersion": idx.get("versionId")}
            if "manifest.json" in names:
                man = json.loads(zf.read("manifest.json"))
                mc = man.get("minecraft", {})
                loader, lver = _loader_from_cf(mc.get("modLoaders", []))
                return {"kind": "curseforge", "name": man.get("name", p.stem), "version": mc.get("version"),
                        "loader": loader, "loaderVersion": lver, "files": len(man.get("files", [])),
                        "supported": loader in SUPPORTED_LOADERS, "packVersion": man.get("version"),
                        "needsKey": bool(man.get("files")) and not self._cf_key(optional=True)}
            top = _prism_zip_root(names)
            if top is not None:
                with tempfile.TemporaryDirectory(dir=self._tmp()) as td:
                    root = Path(td)
                    for n in (f"{top}mmc-pack.json", f"{top}instance.cfg"):
                        if n in names:
                            (root / Path(n).name).write_bytes(zf.read(n))
                    info = self._inspect_prism(root, count=False)
                mods = sum(1 for n in names if re.match(re.escape(top) + r"\.?minecraft/mods/[^/]+\.jar$", n))
                return {**info, "kind": "prism-zip", "name": info["name"] if info["name"] != root.name else p.stem,
                        "files": mods, "supported": bool(info.get("version")) and info["loader"] in ALL_LOADERS}
        raise RpcError("모드팩을 알아보지 못했습니다(modrinth.index.json·manifest.json·mmc-pack.json 없음).")

    def _tmp(self) -> Path:
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        return self.tmp_root

    def _inspect_prism(self, folder: Path, count: bool = True) -> dict[str, Any]:
        pack = folder / "mmc-pack.json"
        if not pack.is_file():
            raise RpcError("Prism Launcher·MultiMC 인스턴스 폴더가 아닙니다(mmc-pack.json 없음).")
        comps = {c.get("uid"): c.get("version") for c in json.loads(pack.read_text("utf-8")).get("components", [])}
        mc = comps.get("net.minecraft")
        if "net.fabricmc.fabric-loader" in comps:
            loader, lver = "fabric", comps["net.fabricmc.fabric-loader"]
        elif "net.neoforged" in comps:
            loader, lver = "neoforge", comps["net.neoforged"]
        elif "net.minecraftforge" in comps:
            loader, lver = "forge", comps["net.minecraftforge"]
        elif "org.quiltmc.quilt-loader" in comps:
            loader, lver = "quilt", comps["org.quiltmc.quilt-loader"]
        else:
            loader, lver = "vanilla", None
        name = folder.name
        cfg = folder / "instance.cfg"
        if cfg.is_file():
            name = _cfg(cfg).get("name") or name   # [General] 섹션이 있든 없든
        game = next((folder / d for d in (".minecraft", "minecraft") if (folder / d).is_dir()), None)
        mods = len(list((game / "mods").glob("*.jar"))) if count and game and (game / "mods").is_dir() else 0
        return {"kind": "prism", "name": name, "version": mc, "loader": loader, "loaderVersion": lver,
                "files": mods, "supported": loader in SUPPORTED_LOADERS and bool(mc)}

    # ============================================================ 파일 가져오기
    def import_file(self, path: str, name: str | None = None, group: str | None = None, icon: str | None = None) -> dict[str, Any]:
        info = self.inspect_import(path)
        if info["kind"] in ("prism", "prism-zip"):
            if info["loader"] not in ALL_LOADERS:
                raise RpcError(f"지원하지 않는 로더입니다: {info['loader']}")
        else:
            _require_supported(info["loader"])
        if not info.get("version"):
            raise RpcError("게임 버전을 알 수 없습니다.")
        inst = self.store.create(name or info["name"], info["version"], info["loader"], info.get("loaderVersion"),
                                 group, icon, cc_enabled=False)
        try:
            if info["kind"] == "mrpack":
                report = self._install_mrpack(inst["id"], Path(path))
            elif info["kind"] == "curseforge":
                report = self._install_cf_zip(inst["id"], Path(path))
            elif info["kind"] == "prism-zip":
                report = self._copy_prism_zip(inst["id"], Path(path))
            else:
                report = self._copy_prism(inst["id"], Path(path))
        except Exception:
            notify("progress", {"id": inst["id"], "stage": "import", "done": True})
            self._discard_failed(inst["id"])
            raise
        notify("progress", {"id": inst["id"], "stage": "import", "text": "가져오기 완료", "done": True})
        return {"instance": self.store.get(inst["id"]), **report}

    def _discard_failed(self, inst_id: str) -> None:
        """반쯤 만들어진 인스턴스를 목록에서 빼고 휴지통으로 보낸다.
        휴지통을 못 쓰는 환경(예: 휴지통이 없는 드라이브)에서도 목록에는 다시 나타나지 않게
        instance.json 이름부터 바꾼다. 영구 삭제는 하지 않는다."""
        d = self.store.dir_of(inst_id)
        try:
            (d / "instance.json").replace(d / "instance.import-failed.json")
        except OSError:
            pass
        try:
            self.store.delete(inst_id)
        except Exception as e:  # noqa: BLE001
            print(f"[import] 휴지통으로 보내지 못함, 폴더를 남겨 둠: {d} ({e})", file=sys.stderr)

    def _install_mrpack(self, inst_id: str, mrpack: Path) -> dict[str, Any]:
        base = self.store.dir_of(inst_id)
        with zipfile.ZipFile(mrpack) as zf:
            idx = json.loads(zf.read("modrinth.index.json"))
            jobs = []
            skipped = []
            for f in idx.get("files", []):
                if (f.get("env") or {}).get("client") == "unsupported":
                    continue
                rel = _safe_rel(f["path"])
                urls = [u for u in f.get("downloads", []) if urllib.parse.urlparse(u).hostname in MRPACK_HOSTS]
                if not urls:
                    skipped.append(f"{rel} (허용되지 않은 다운로드 주소)")
                    continue
                dest = safe_join(base, rel)
                jobs.append((Path(rel).name, lambda u=urls[0], d=dest, h=f.get("hashes", {}): modrinth.download({"url": u, "hashes": h}, d)))
            notify("progress", {"id": inst_id, "stage": "import", "text": f"모드팩 파일 받는 중 (0/{len(jobs)})"})
            failed = _parallel(jobs, inst_id, "모드팩 파일 받는 중")
            extracted = _extract_dir(zf, "overrides/", base) + _extract_dir(zf, "client-overrides/", base)
        return {"downloaded": len(jobs) - len(failed), "failed": failed + skipped, "manual": [], "extracted": extracted}

    def _install_cf_zip(self, inst_id: str, zip_path: Path) -> dict[str, Any]:
        base = self.store.dir_of(inst_id)
        with zipfile.ZipFile(zip_path) as zf:
            man = json.loads(zf.read("manifest.json"))
            overrides = (man.get("overrides") or "overrides").strip("/") + "/"
            files = [f for f in man.get("files", []) if f.get("required", True)]
            manual: list[str] = []
            failed: list[str] = []
            downloaded = 0
            if files:
                key = self._cf_key()
                notify("progress", {"id": inst_id, "stage": "import", "text": "CurseForge 파일 정보 확인 중"})
                infos: list[dict[str, Any]] = []
                ids = [int(f["fileID"]) for f in files]
                for i in range(0, len(ids), 50):
                    body = json.dumps({"fileIds": ids[i:i + 50]}).encode()
                    infos += _json(f"{CURSEFORGE_API}/mods/files", headers={"x-api-key": key}, data=body).get("data", [])
                jobs = []
                for fi in infos:
                    fname = Path(fi.get("fileName") or "").name
                    if not fname:
                        continue
                    dest = safe_join(base, "mods", fname) if fname.endswith(".jar") else safe_join(base, "resourcepacks", fname)
                    if not fi.get("downloadUrl"):
                        manual.append(f"{fi.get('displayName') or fname} — https://www.curseforge.com/projects/{fi.get('modId')}")
                        continue
                    sha1 = next((h["value"] for h in fi.get("hashes", []) if h.get("algo") == 1), None)
                    jobs.append((fname, lambda u=fi["downloadUrl"], d=dest, h={"sha1": sha1}: _download(u, d, h)))
                failed = _parallel(jobs, inst_id, "CurseForge 파일 받는 중")
                downloaded = len(jobs) - len(failed)
            extracted = _extract_dir(zf, overrides, base)
        return {"downloaded": downloaded, "failed": failed, "manual": manual, "extracted": extracted}

    def _copy_prism_zip(self, inst_id: str, zip_path: Path) -> dict[str, Any]:
        """Prism·MultiMC 내보내기 zip: 임시 폴더에 풀고 인스턴스 폴더처럼 복사한다(계정 파일은 풀지 않음)."""
        with zipfile.ZipFile(zip_path) as zf, tempfile.TemporaryDirectory(dir=self._tmp()) as td:
            top = _prism_zip_root(set(zf.namelist())) or ""
            for info in zf.infolist():
                if info.is_dir() or not info.filename.startswith(top):
                    continue
                rel = _safe_rel(info.filename[len(top):])
                if is_account_file(rel):
                    continue
                target = safe_join(Path(td), rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            return self._copy_prism(inst_id, Path(td))

    def _copy_prism(self, inst_id: str, folder: Path) -> dict[str, Any]:
        base = self.store.dir_of(inst_id)
        game = next((folder / d for d in (".minecraft", "minecraft") if (folder / d).is_dir()), None)
        if not game:
            raise RpcError("인스턴스 안에 .minecraft 폴더가 없습니다.")
        copied = 0
        for sub in ("mods", "config", "resourcepacks", "shaderpacks", "saves", "datapacks", "kubejs", "defaultconfigs"):
            src = game / sub
            if src.is_dir():
                notify("progress", {"id": inst_id, "stage": "import", "text": f"{sub} 복사 중"})
                shutil.copytree(src, safe_join(base, sub), dirs_exist_ok=True)
                copied += sum(1 for _ in src.rglob("*") if _.is_file())
        for f in ("options.txt", "servers.dat"):
            if (game / f).is_file():
                shutil.copy2(game / f, safe_join(base, f))
                copied += 1
        return {"downloaded": 0, "failed": [], "manual": [], "extracted": copied}

    # ============================================================ Modrinth
    def modrinth_search(self, query: str = "", kind: str = "modpack", game_version: str | None = None,
                        loader: str | None = None, offset: int = 0) -> dict[str, Any]:
        facets = [[f"project_type:{'modpack' if kind == 'modpack' else 'mod'}"]]
        if loader and loader != "vanilla":
            facets.append([f"categories:{loader}"])
        if game_version:
            facets.append([f"versions:{game_version}"])
        data = modrinth.get_json("/search", {"query": query, "facets": facets, "limit": 30, "offset": offset,
                                             "index": "relevance" if query else "downloads"})
        return {"total": data.get("total_hits", 0), "hits": [{
            "id": h["project_id"], "slug": h.get("slug"), "title": h.get("title"), "author": h.get("author"),
            "description": h.get("description"), "downloads": h.get("downloads", 0), "icon": h.get("icon_url"),
            "versions": h.get("versions", [])[-6:], "url": f"https://modrinth.com/{h.get('project_type', kind)}/{h.get('slug')}",
        } for h in data.get("hits", [])]}

    def modrinth_versions(self, project: str, game_version: str | None = None, loader: str | None = None) -> list[dict[str, Any]]:
        versions = modrinth.versions(project, game_version, loader)
        return [{
            "id": v["id"], "name": v.get("name") or v.get("version_number"), "number": v.get("version_number"),
            "gameVersions": v.get("game_versions", []), "loaders": v.get("loaders", []),
            "date": (v.get("date_published") or "")[:10], "type": v.get("version_type"),
        } for v in versions]

    def _modrinth_version(self, version_id: str) -> dict[str, Any]:
        return modrinth.version(version_id)

    def modrinth_install_modpack(self, version_id: str, name: str | None = None, group: str | None = None,
                                 icon: str | None = None) -> dict[str, Any]:
        v = self._modrinth_version(version_id)
        f = next((x for x in v.get("files", []) if x.get("primary")), (v.get("files") or [None])[0])
        if not f or not f.get("filename", "").endswith(".mrpack"):
            raise RpcError("이 버전에는 .mrpack 파일이 없습니다.")
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.tmp_root) as td:
            dest = Path(td) / "pack.mrpack"
            notify("progress", {"id": "", "stage": "import", "text": "모드팩 받는 중"})
            modrinth.download(f, dest)
            notify("progress", {"id": "", "stage": "import", "done": True})
            return self.import_file(str(dest), name, group, icon)

    def modrinth_add_mod(self, id: str, project: str, version_id: str | None = None,
                         filename: str | None = None) -> dict[str, Any]:
        """인스턴스 mods/ 에 모드와 required 의존 모드를 넣는다(게임 버전·로더가 정확히 맞는 파일만, modrinth.py)."""
        meta = self.store.get(id)
        mods = safe_join(Path(meta["path"]), "mods")
        try:
            res = modrinth.install(project, meta["version"], meta["loader"], mods, version_id=version_id, filename=filename)
        except modrinth.Ambiguous as e:
            return {"added": [], "ambiguous": e.choices, "message": str(e)}
        return {"added": [i["filename"] for i in res.installed], "kept": [k["filename"] for k in res.kept],
                "optional": res.optional}

    # ============================================================ CurseForge
    @staticmethod
    def _cf_key(optional: bool = False) -> str | None:
        env = os.environ.get("INTEGRATED_STUDIO_CF_KEY")
        if env:
            return env
        try:
            import keyring
            key = keyring.get_password(KEYRING_SERVICE, KEYRING_CF)
        except Exception:  # noqa: BLE001 - 자격 증명 저장소가 없는 환경
            key = None
        if not key and not optional:
            raise RpcError("CurseForge API 키가 필요합니다. 새 인스턴스 창의 CurseForge 탭에서 키를 입력하세요.")
        return key

    def cf_key_status(self) -> dict[str, Any]:
        return {"hasKey": bool(self._cf_key(optional=True))}

    def cf_set_key(self, key: str) -> dict[str, Any]:
        key = clean_cf_key(key)
        if not key:
            try:
                import keyring
                keyring.delete_password(KEYRING_SERVICE, KEYRING_CF)
            except Exception:  # noqa: BLE001
                pass
            return {"hasKey": False}
        if not key.isascii() or not key.isprintable():
            raise RpcError("키에 영문·숫자·기호가 아닌 문자가 섞여 있습니다. CurseForge 콘솔에서 키를 다시 복사해 주세요.")
        # 저장 전에 키가 맞는지 확인
        _json(f"{CURSEFORGE_API}/games/{CF_GAME_ID}", headers={"x-api-key": key})
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, KEYRING_CF, key)
        except Exception as e:  # noqa: BLE001
            raise RpcError(f"키를 OS 자격 증명 저장소에 저장하지 못했습니다: {e}") from e
        return {"hasKey": True}

    def cf_search(self, query: str = "", kind: str = "modpack", game_version: str | None = None,
                  loader: str | None = None, offset: int = 0) -> dict[str, Any]:
        key = self._cf_key()
        params: dict[str, Any] = {"gameId": CF_GAME_ID, "classId": CF_CLASS["modpack" if kind == "modpack" else "mod"],
                                  "searchFilter": query, "pageSize": 30, "index": offset,
                                  "sortField": 2 if not query else 1, "sortOrder": "desc"}
        if game_version:
            params["gameVersion"] = game_version
        if loader in CF_LOADER:
            params["modLoaderType"] = CF_LOADER[loader]
        data = _json(f"{CURSEFORGE_API}/mods/search?{urllib.parse.urlencode(params)}", headers={"x-api-key": key})
        return {"total": (data.get("pagination") or {}).get("totalCount", 0), "hits": [{
            "id": str(m["id"]), "slug": m.get("slug"), "title": m.get("name"),
            "author": ", ".join(a.get("name", "") for a in m.get("authors", [])[:2]),
            "description": m.get("summary"), "downloads": int(m.get("downloadCount") or 0),
            "icon": (m.get("logo") or {}).get("thumbnailUrl"),
            "versions": [], "url": (m.get("links") or {}).get("websiteUrl"),
        } for m in data.get("data", [])]}

    def cf_files(self, mod_id: str, game_version: str | None = None, loader: str | None = None) -> list[dict[str, Any]]:
        key = self._cf_key()
        params: dict[str, Any] = {"pageSize": 50}
        if game_version:
            params["gameVersion"] = game_version
        if loader in CF_LOADER:
            params["modLoaderType"] = CF_LOADER[loader]
        data = _json(f"{CURSEFORGE_API}/mods/{int(mod_id)}/files?{urllib.parse.urlencode(params)}", headers={"x-api-key": key})
        rel = {1: "release", 2: "beta", 3: "alpha"}
        return [{
            "id": str(f["id"]), "name": f.get("displayName") or f.get("fileName"), "number": f.get("fileName"),
            "gameVersions": [g for g in f.get("gameVersions", []) if re.match(r"^\d", g)],
            "loaders": [g.lower() for g in f.get("gameVersions", []) if g.lower() in CF_LOADER],
            "date": (f.get("fileDate") or "")[:10], "type": rel.get(f.get("releaseType"), "release"),
        } for f in data.get("data", [])]

    def _cf_file(self, mod_id: str, file_id: str) -> dict[str, Any]:
        key = self._cf_key()
        return _json(f"{CURSEFORGE_API}/mods/{int(mod_id)}/files/{int(file_id)}", headers={"x-api-key": key})["data"]

    def cf_install_modpack(self, mod_id: str, file_id: str, name: str | None = None, group: str | None = None,
                           icon: str | None = None) -> dict[str, Any]:
        f = self._cf_file(mod_id, file_id)
        if not f.get("downloadUrl"):
            raise RpcError("이 모드팩은 제작자가 외부 다운로드를 막아 두었습니다. CurseForge 사이트에서 .zip을 받아 '파일 가져오기'로 넣으세요.")
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.tmp_root) as td:
            dest = Path(td) / "pack.zip"
            notify("progress", {"id": "", "stage": "import", "text": "모드팩 받는 중"})
            sha1 = next((h["value"] for h in f.get("hashes", []) if h.get("algo") == 1), None)
            _download(f["downloadUrl"], dest, {"sha1": sha1})
            notify("progress", {"id": "", "stage": "import", "done": True})
            return self.import_file(str(dest), name, group, icon)

    def cf_add_mod(self, id: str, mod_id: str, file_id: str | None = None) -> dict[str, Any]:
        meta = self.store.get(id)
        base = self.store.dir_of(id)
        added: list[str] = []
        manual: list[str] = []
        seen: set[str] = set()

        def install(mid: str, fid: str | None) -> None:
            if mid in seen:
                return
            seen.add(mid)
            if fid:
                f = self._cf_file(mid, fid)
            else:
                files = self.cf_files(mid, meta["version"], meta["loader"])
                if not files:
                    raise RpcError(f"{meta['version']}·{meta['loader']}에 맞는 파일이 없습니다: {mid}")
                f = self._cf_file(mid, files[0]["id"])
            fname = Path(f.get("fileName") or "").name
            if not f.get("downloadUrl"):
                manual.append(f"{f.get('displayName') or fname} — https://www.curseforge.com/projects/{mid}")
            else:
                sha1 = next((h["value"] for h in f.get("hashes", []) if h.get("algo") == 1), None)
                _download(f["downloadUrl"], safe_join(base, "mods", fname), {"sha1": sha1})
                added.append(fname)
            for dep in f.get("dependencies") or []:
                if dep.get("relationType") == 3:
                    install(str(dep["modId"]), None)

        install(str(mod_id), file_id)
        return {"added": added, "manual": manual}


