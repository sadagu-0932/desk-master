"""가져오기 기능 시험: 가짜 Modrinth·CurseForge 서버(실제 API와 같은 응답 형식)로 확인한다.
실제 서버로도 확인하려면 STUDIO_ONLINE=1 (CurseForge는 INTEGRATED_STUDIO_CF_KEY 도 필요).

사용: python tests/test_importers.py
"""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import urllib.parse
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ONLINE = os.environ.get("STUDIO_ONLINE") == "1"

# GitHub raw 는 .mrpack 이 허용하는 호스트다(실제 파일을 받아 해시까지 확인)
REMOTE_FILE = "https://raw.githubusercontent.com/PrismLauncher/PrismLauncher/develop/README.md"


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def make_mrpack(remote_bytes: bytes | None) -> bytes:
    files = []
    if remote_bytes is not None:
        files.append({"path": "config/prism-readme.md", "hashes": {"sha1": sha1(remote_bytes)},
                      "env": {"client": "required", "server": "required"}, "downloads": [REMOTE_FILE], "fileSize": len(remote_bytes)})
    files.append({"path": "mods/evil.jar", "hashes": {"sha1": "0" * 40}, "downloads": ["https://evil.example.com/x.jar"]})
    files.append({"path": "mods/server-only.jar", "hashes": {"sha1": "0" * 40}, "env": {"client": "unsupported"},
                  "downloads": ["https://cdn.modrinth.com/x.jar"]})
    idx = {"formatVersion": 1, "game": "minecraft", "versionId": "1.0.0", "name": "테스트 팩",
           "files": files, "dependencies": {"minecraft": "26.3", "fabric-loader": "0.20.1"}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("modrinth.index.json", json.dumps(idx))
        z.writestr("overrides/config/pack.txt", "override")
        z.writestr("client-overrides/options.txt", "lang:ko_kr")
    return buf.getvalue()


def make_cf_zip() -> bytes:
    man = {"minecraft": {"version": "26.3", "modLoaders": [{"id": "fabric-0.20.1", "primary": True}]},
           "manifestType": "minecraftModpack", "manifestVersion": 1, "name": "CF 테스트 팩", "version": "2.0",
           "author": "me", "files": [{"projectID": 100, "fileID": 1001, "required": True},
                                     {"projectID": 200, "fileID": 2001, "required": True}],
           "overrides": "overrides"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(man))
        z.writestr("overrides/config/cf.txt", "cf override")
    return buf.getvalue()


JAR = b"PK fake jar"
DEP_JAR = b"PK dep jar"


class Fake(http.server.BaseHTTPRequestHandler):
    base = ""
    mrpack = b""
    cf_zip = b""

    def log_message(self, *a):  # 조용히
        pass

    def send(self, obj, ctype="application/json", code=200):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def cf_ok(self):
        if self.headers.get("x-api-key") != "good-key":
            self.send({"error": "forbidden"}, code=403)
            return False
        return True

    def cf_file(self, fid):
        files = {
            1001: {"id": 1001, "modId": 100, "displayName": "Cool Mod", "fileName": "cool-mod.jar", "releaseType": 1,
                   "fileDate": "2026-10-01T00:00:00Z", "gameVersions": ["26.3", "Fabric"],
                   "downloadUrl": f"{self.base}/dl/cool-mod.jar", "hashes": [{"value": sha1(JAR), "algo": 1}],
                   "dependencies": [{"modId": 300, "relationType": 3}, {"modId": 400, "relationType": 2}]},
            2001: {"id": 2001, "modId": 200, "displayName": "No Third Party", "fileName": "blocked.jar", "releaseType": 1,
                   "fileDate": "2026-10-01T00:00:00Z", "gameVersions": ["26.3", "Fabric"], "downloadUrl": None,
                   "hashes": [], "dependencies": []},
            3001: {"id": 3001, "modId": 300, "displayName": "Dep Lib", "fileName": "dep-lib.jar", "releaseType": 1,
                   "fileDate": "2026-09-01T00:00:00Z", "gameVersions": ["26.3", "Fabric"],
                   "downloadUrl": f"{self.base}/dl/dep-lib.jar", "hashes": [{"value": sha1(DEP_JAR), "algo": 1}],
                   "dependencies": []},
            5001: {"id": 5001, "modId": 500, "displayName": "CF Pack 2.0", "fileName": "pack.zip", "releaseType": 1,
                   "fileDate": "2026-10-01T00:00:00Z", "gameVersions": ["26.3"], "downloadUrl": f"{self.base}/dl/cfpack.zip",
                   "hashes": [{"value": sha1(self.cf_zip), "algo": 1}], "dependencies": []},
        }
        return files[fid]

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        # ---- Modrinth
        if p == "/mr/search":
            facets = json.loads(q["facets"][0])
            assert ["project_type:modpack"] in facets or ["project_type:mod"] in facets
            self.send({"total_hits": 1, "hits": [{"project_id": "AbC", "slug": "test-pack", "title": "Test Pack", "author": "me",
                                                  "description": "d", "downloads": 42, "icon_url": None, "versions": ["26.3"],
                                                  "project_type": "modpack"}]})
        elif p == "/mr/project/AbC/version":
            self.send([{"id": "V1", "name": "Test Pack 1.0", "version_number": "1.0", "game_versions": ["26.3"],
                        "loaders": ["fabric"], "date_published": "2026-10-01T00:00:00Z", "version_type": "release"}])
        elif p == "/mr/version/V1":
            self.send({"id": "V1", "files": [{"url": f"{self.base}/dl/pack.mrpack", "filename": "pack.mrpack", "primary": True,
                                              "hashes": {"sha1": sha1(self.mrpack)}}], "dependencies": []})
        elif p == "/mr/project/modA/version":
            self.send([{"id": "MA1", "name": "Mod A", "version_number": "1", "game_versions": ["26.3"], "loaders": ["fabric"],
                        "date_published": "2026-10-01", "version_type": "release", "project_id": "modA",
                        "files": [{"url": f"{self.base}/dl/mod-a.jar", "filename": "mod-a.jar", "primary": True,
                                   "hashes": {"sha1": sha1(JAR)}}],
                        "dependencies": [{"project_id": "libB", "dependency_type": "required"},
                                         {"project_id": "optC", "dependency_type": "optional"}]}])
        elif p == "/mr/version/MA1":
            self.send({"id": "MA1", "files": [{"url": f"{self.base}/dl/mod-a.jar", "filename": "mod-a.jar", "primary": True,
                                               "hashes": {"sha1": sha1(JAR)}}],
                       "dependencies": [{"project_id": "libB", "dependency_type": "required"},
                                        {"project_id": "optC", "dependency_type": "optional"}]})
        elif p == "/mr/project/libB/version":
            self.send([{"id": "LB1", "name": "Lib B", "version_number": "1", "game_versions": ["26.3"], "loaders": ["fabric"],
                        "date_published": "2026-10-01", "version_type": "release", "project_id": "libB",
                        "files": [{"url": f"{self.base}/dl/lib-b.jar", "filename": "lib-b.jar", "primary": True,
                                   "hashes": {"sha1": sha1(DEP_JAR)}}], "dependencies": []}])
        elif p == "/mr/version/LB1":
            self.send({"id": "LB1", "files": [{"url": f"{self.base}/dl/lib-b.jar", "filename": "lib-b.jar", "primary": True,
                                               "hashes": {"sha1": sha1(DEP_JAR)}}], "dependencies": []})
        # ---- CurseForge
        elif p.startswith("/cf/"):
            if not self.cf_ok():
                return
            if p == "/cf/games/432":
                self.send({"data": {"id": 432, "name": "Minecraft"}})
            elif p == "/cf/mods/search":
                assert q["gameId"] == ["432"] and q["classId"][0] in ("4471", "6")
                self.send({"data": [{"id": 500, "name": "CF Pack", "slug": "cf-pack", "summary": "s", "downloadCount": 7,
                                     "logo": {"thumbnailUrl": None}, "authors": [{"name": "me"}],
                                     "links": {"websiteUrl": "https://www.curseforge.com/minecraft/modpacks/cf-pack"}}],
                           "pagination": {"totalCount": 1}})
            elif p == "/cf/mods/500/files":
                self.send({"data": [self.cf_file(5001)]})
            elif p == "/cf/mods/300/files":
                assert q.get("modLoaderType") == ["4"]
                self.send({"data": [self.cf_file(3001)]})
            elif p.startswith("/cf/mods/") and "/files/" in p:
                self.send({"data": self.cf_file(int(p.rsplit("/", 1)[1]))})
            else:
                self.send({}, code=404)
        # ---- 파일
        elif p == "/dl/pack.mrpack":
            self.send(self.mrpack, "application/zip")
        elif p == "/dl/cfpack.zip":
            self.send(self.cf_zip, "application/zip")
        elif p in ("/dl/cool-mod.jar", "/dl/mod-a.jar"):
            self.send(JAR, "application/java-archive")
        elif p in ("/dl/dep-lib.jar", "/dl/lib-b.jar"):
            self.send(DEP_JAR, "application/java-archive")
        else:
            self.send({}, code=404)

    def do_POST(self):
        if self.path == "/cf/mods/files":
            if not self.cf_ok():
                return
            ids = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["fileIds"]
            self.send({"data": [self.cf_file(i) for i in ids]})
        else:
            self.send({}, code=404)


def main() -> None:
    import urllib.request
    try:
        remote = urllib.request.urlopen(REMOTE_FILE, timeout=20).read()
    except Exception:  # noqa: BLE001
        remote = None
        print("! GitHub raw 에 닿지 않아 원격 파일 단계는 건너뜀")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    Fake.base, Fake.mrpack, Fake.cf_zip = base, make_mrpack(remote), make_cf_zip()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",127.0.0.1"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    if not ONLINE:
        os.environ["INTEGRATED_STUDIO_MODRINTH_API"] = base + "/mr"
        os.environ["INTEGRATED_STUDIO_CURSEFORGE_API"] = base + "/cf"

    import importers
    from instances import InstanceStore
    from rpc import RpcError
    importers.MODRINTH_API = os.environ.get("INTEGRATED_STUDIO_MODRINTH_API", importers.MODRINTH_API)
    importers.CURSEFORGE_API = os.environ.get("INTEGRATED_STUDIO_CURSEFORGE_API", importers.CURSEFORGE_API)

    data = Path(tempfile.mkdtemp())
    store = InstanceStore(data)
    imp = importers.Importers(store, data)
    ok = 0

    def check(cond, msg):
        nonlocal ok
        if not cond:
            raise AssertionError(msg)
        ok += 1
        print("  ✓", msg)

    print("1) .mrpack 파일 가져오기")
    mp = data / "t.mrpack"
    mp.write_bytes(Fake.mrpack)
    info = imp.inspect_import(str(mp))
    check(info["kind"] == "mrpack" and info["version"] == "26.3" and info["loader"] == "fabric" and info["supported"], f"미리 보기: {info}")
    res = imp.import_file(str(mp), group="가져옴")
    d = Path(res["instance"]["path"])
    check((d / "config/pack.txt").read_text() == "override", "overrides/ 풀림")
    check((d / "options.txt").read_text() == "lang:ko_kr", "client-overrides/ 풀림")
    check(not (d / "mods/server-only.jar").exists(), "서버 전용 파일 건너뜀")
    check(any("evil.jar" in f for f in res["failed"]), "허용되지 않은 호스트 거부")
    if remote is not None:
        check((d / "config/prism-readme.md").read_bytes() == remote, "허용 호스트(GitHub)에서 받고 해시 확인")
    inst = res["instance"]
    check(inst["loaderVersion"] == "0.20.1" and inst["group"] == "가져옴" and not inst["ccEnabled"], "로더 버전·그룹 저장")

    print("2) 위험한 경로가 든 .mrpack 거부")
    bad = data / "bad.mrpack"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("modrinth.index.json", json.dumps({"name": "bad", "files": [], "dependencies": {"minecraft": "26.3"}}))
        z.writestr("overrides/../../escape.txt", "x")
    try:
        imp.import_file(str(bad))
        check(False, "zip slip 거부")
    except RpcError:
        check(not (data / "escape.txt").exists() and not (data / "instances/escape.txt").exists(), "zip slip 거부")
        check(not any(i["name"] == "bad" for i in store.list()), "실패한 가져오기는 인스턴스를 남기지 않음")

    print("3) Forge·NeoForge 모드팩도 가져옴, 모르는 로더는 안내")
    fz = data / "forge.mrpack"
    with zipfile.ZipFile(fz, "w") as z:
        z.writestr("modrinth.index.json", json.dumps({"name": "포지 팩", "files": [], "dependencies": {"minecraft": "1.20.1", "forge": "47.2.0"}}))
        z.writestr("overrides/config/forge.toml", "x=1")
    info = imp.inspect_import(str(fz))
    check(info["loader"] == "forge" and info["supported"], f"Forge 미리 보기: {info}")
    res = imp.import_file(str(fz))
    check(res["instance"]["loader"] == "forge" and res["instance"]["loaderVersion"] == "47.2.0", f"Forge 인스턴스: {res['instance']}")
    nz = data / "neo.mrpack"
    with zipfile.ZipFile(nz, "w") as z:
        z.writestr("modrinth.index.json", json.dumps({"name": "네오 팩", "files": [], "dependencies": {"minecraft": "26.3", "neoforge": "26.3.0.115"}}))
    res = imp.import_file(str(nz))
    check(res["instance"]["loader"] == "neoforge" and res["instance"]["loaderVersion"] == "26.3.0.115", f"NeoForge 인스턴스: {res['instance']}")
    bz = data / "odd.mrpack"
    with zipfile.ZipFile(bz, "w") as z:
        z.writestr("modrinth.index.json", json.dumps({"name": "x", "files": [], "dependencies": {"minecraft": "26.3", "liteloader": "1"}}))
    check(imp.inspect_import(str(bz))["loader"] == "vanilla", "모르는 로더 표시는 무시(바닐라로 봄)")

    print("4) Prism Launcher 인스턴스 폴더")
    pr = data / "PrismInst"
    (pr / ".minecraft/mods").mkdir(parents=True)
    (pr / ".minecraft/mods/sodium.jar").write_bytes(b"x")
    (pr / ".minecraft/saves/World1").mkdir(parents=True)
    (pr / ".minecraft/saves/World1/level.dat").write_bytes(b"x")
    (pr / "instance.cfg").write_text("InstanceType=OneSix\nname=내 프리즘 인스턴스\n", "utf-8")
    (pr / "mmc-pack.json").write_text(json.dumps({"components": [{"uid": "net.minecraft", "version": "26.3"},
                                                                 {"uid": "net.fabricmc.fabric-loader", "version": "0.20.1"}]}))
    res = imp.import_file(str(pr))
    d = Path(res["instance"]["path"])
    check(res["instance"]["name"] == "내 프리즘 인스턴스", "이름은 instance.cfg 에서")
    check(d == (pr / ".minecraft").resolve() and res["instance"].get("linkedDir"), "폴더는 그대로 두고 연결(기본)")
    check((d / "mods/sodium.jar").exists() and not (d / "instance.json").exists(), "원본 폴더에 우리 파일을 쓰지 않음")
    res2 = imp.import_file(str(pr), name="복사본", mode="copy")
    d2 = Path(res2["instance"]["path"])
    check(d2 != d and (d2 / "mods/sodium.jar").exists() and (d2 / "saves/World1/level.dat").exists(), "copy 면 mods·saves 복사")

    print("5) Modrinth 검색 → 모드팩 설치")
    hits = imp.modrinth_search("test")
    check(hits["hits"][0]["id"] == "AbC", "검색 결과")
    vs = imp.modrinth_versions("AbC", "26.3", "fabric")
    check(vs[0]["id"] == "V1", "버전 목록")
    res = imp.modrinth_install_modpack("V1", name="모드린스 팩")
    check(res["instance"]["name"] == "모드린스 팩" and (Path(res["instance"]["path"]) / "config/pack.txt").exists(), "설치됨")

    print("6) Modrinth 모드 추가(필수 의존 포함, 선택 의존 제외)")
    target = store.create("모드 추가 대상", "26.3", "fabric")
    res = imp.modrinth_add_mod(target["id"], "modA")
    check(sorted(res["added"]) == ["lib-b.jar", "mod-a.jar"], f"추가됨: {res['added']}")

    print("7) CurseForge 키 없으면 안내, 틀린 키 거부")
    os.environ.pop("INTEGRATED_STUDIO_CF_KEY", None)
    try:
        imp.cf_search("x")
        check(False, "키 필요 안내")
    except RpcError as e:
        check("API 키" in str(e), "키 필요 안내")
    os.environ["INTEGRATED_STUDIO_CF_KEY"] = "bad-key"
    try:
        imp.cf_search("x")
        check(False, "틀린 키 거부")
    except RpcError as e:
        check("받아들이지 않았습니다" in str(e) and "HTTP 403" in str(e) and "7자" in str(e), "틀린 키 거부(HTTP 코드·키 모양 안내)")
    os.environ["INTEGRATED_STUDIO_CF_KEY"] = "good-key"

    print("8) CurseForge 검색 → 모드팩 설치(외부 다운로드 막힌 모드는 목록으로)")
    hits = imp.cf_search("cf")
    check(hits["hits"][0]["id"] == "500", "검색 결과")
    files = imp.cf_files("500", "26.3", "fabric")
    res = imp.cf_install_modpack("500", files[0]["id"])
    d = Path(res["instance"]["path"])
    check((d / "mods/cool-mod.jar").read_bytes() == JAR, "모드 받고 sha1 확인")
    check(any("No Third Party" in m for m in res["manual"]), "직접 받아야 할 모드 안내")
    check((d / "config/cf.txt").exists(), "overrides 풀림")

    print("9) CurseForge 모드 추가(필수 의존 포함)")
    res = imp.cf_add_mod(target["id"], "100", "1001")
    check(sorted(res["added"]) == ["cool-mod.jar", "dep-lib.jar"], f"추가됨: {res['added']}")

    srv.shutdown()
    print(f"\n통과 {ok}개")


if __name__ == "__main__":
    main()
