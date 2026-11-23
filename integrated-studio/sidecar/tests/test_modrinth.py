"""sidecar/modrinth.py 시험 — 가짜 Modrinth API(실제 e4mc 응답을 줄인 자료)로.

사용: python -m pytest -q tests/test_modrinth.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import modrinth  # noqa: E402

FIX = Path(__file__).parent / "fixtures_modrinth"
FABRIC_API = "P7dR8mSH"
MCQOY = "tNmWwdI2"
E4MC = "qANg5Jrr"


def _blob(name: str) -> bytes:
    return f"jar:{name}".encode()


def _sha(b: bytes, algo: str = "sha512") -> str:
    return hashlib.new(algo, b).hexdigest()


class Fake:
    """프로젝트별 버전 목록을 들고 있는 가짜 Modrinth."""

    def __init__(self) -> None:
        self.versions: dict[str, list[dict]] = {}
        self.titles = {E4MC: "e4mc", FABRIC_API: "Fabric API", MCQOY: "McQoy"}
        self.files: dict[str, bytes] = {}
        self.bad_hash: set[str] = set()
        self.base = ""

    def add(self, pid: str, v: dict) -> dict:
        v = copy.deepcopy(v)
        v["project_id"] = pid
        for f in v["files"]:
            data = _blob(f["filename"])
            self.files[f["filename"]] = data
            f["url"] = f"{self.base}/files/{urllib.parse.quote(f['filename'])}"
            f["hashes"] = {"sha512": _sha(data), "sha1": _sha(data, "sha1")}
            if f["filename"] in self.bad_hash:
                f["hashes"]["sha512"] = "0" * 128
        self.versions.setdefault(pid, []).append(v)
        return v

    def all_versions(self) -> list[dict]:
        return [v for vs in self.versions.values() for v in vs]


@pytest.fixture
def fake(monkeypatch):
    fk = Fake()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def _send(self, code: int, body) -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            q = {k: json.loads(v[0]) for k, v in urllib.parse.parse_qs(u.query).items()}
            parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
            if parts[0] == "files":
                return self._send(200, fk.files[parts[1]])
            if parts[0] == "project" and len(parts) == 3:
                vs = fk.versions.get(parts[1])
                if vs is None:
                    return self._send(404, {"error": "not_found"})
                gv, ld = q.get("game_versions"), q.get("loaders")
                vs = [v for v in vs if (not gv or set(gv) & set(v["game_versions"])) and (not ld or set(ld) & set(v["loaders"]))]
                return self._send(200, vs)
            if parts[0] == "project":
                return self._send(200, {"id": parts[1], "title": fk.titles.get(parts[1], parts[1])})
            if parts[0] == "version":
                v = next((v for v in fk.all_versions() if v["id"] == parts[1]), None)
                return self._send(200 if v else 404, v or {})
            self._send(404, {})

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = {}
            for v in fk.all_versions():
                for f in v["files"]:
                    if f["hashes"][body["algorithm"]] in body["hashes"]:
                        out[f["hashes"][body["algorithm"]]] = v
            self._send(200, out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fk.base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("INTEGRATED_STUDIO_MODRINTH_API", fk.base)
    yield fk
    srv.shutdown()


def _real_e4mc() -> list[dict]:
    return json.loads((FIX / "e4mc_versions.json").read_text("utf-8"))


def _fabric_api(game: str = "26.3") -> dict:
    return {"id": "fapi1", "name": "Fabric API", "version_number": "0.140.0+26.3", "game_versions": [game],
            "loaders": ["fabric"], "version_type": "release", "date_published": "2026-10-02T00:00:00Z",
            "files": [{"filename": "fabric-api-0.140.0+26.3.jar", "primary": True}], "dependencies": []}


def test_e4mc_263_fabric_picks_modern_and_installs_required_only(fake, tmp_path):
    for v in _real_e4mc():
        fake.add(E4MC, v)
    fake.add(FABRIC_API, _fabric_api())
    res = modrinth.install(E4MC, "26.3", "fabric", tmp_path / "mods")
    names = [e["filename"] for e in res.installed]
    assert names == ["e4mc-fabric-6.2.3-modern.jar", "fabric-api-0.140.0+26.3.jar"]
    assert [o["title"] for o in res.optional] == ["McQoy"]          # optional 은 안내만
    assert (tmp_path / "mods" / "e4mc-fabric-6.2.3-modern.jar").read_bytes() == _blob("e4mc-fabric-6.2.3-modern.jar")
    assert not (tmp_path / "mods" / "e4mc-neoforge-6.2.3.jar").exists()


def test_e4mc_1_21_fabric_uses_non_modern(fake, tmp_path):
    for v in _real_e4mc():
        fake.add(E4MC, v)
    v, f = modrinth.pick_file(modrinth.exact_versions(E4MC, "1.21.4", "fabric"), "1.21.4", "fabric", "e4mc")
    assert f["filename"] == "e4mc-fabric-6.2.3.jar"                 # -sources.jar 제외, modern 아님


def test_neoforge_skips_sources_jar(fake):
    for v in _real_e4mc():
        fake.add(E4MC, v)
    _, f = modrinth.pick_file(modrinth.exact_versions(E4MC, "26.3", "neoforge"), "26.3", "neoforge", "e4mc")
    assert f["filename"] == "e4mc-neoforge-6.2.3.jar"


def test_no_exact_version_no_fallback(fake, tmp_path):
    for v in _real_e4mc():
        fake.add(E4MC, v)
    with pytest.raises(modrinth.NoMatch) as e:
        modrinth.install(E4MC, "26.4", "fabric", tmp_path / "mods")
    assert "가까운 버전으로 대신 설치하지 않았습니다" in str(e.value)
    assert not (tmp_path / "mods").exists()
    with pytest.raises(modrinth.NoMatch):                           # 로더 불일치(quilt 전용 파일 없음 → fabric 대체 금지)
        modrinth.install("onlyfabric", "26.3", "quilt", tmp_path / "mods")


def test_hash_mismatch_discarded(fake, tmp_path):
    fake.bad_hash.add("fabric-api-0.140.0+26.3.jar")
    fake.add(FABRIC_API, _fabric_api())
    with pytest.raises(modrinth.RpcError) as e:
        modrinth.install(FABRIC_API, "26.3", "fabric", tmp_path / "mods")
    assert "해시" in str(e.value)
    assert list((tmp_path / "mods").iterdir()) == []                # .part 도 남지 않음


def test_ambiguous_asks_user_then_installs_choice(fake, tmp_path):
    fake.add("multi", {"id": "m1", "name": "x", "version_number": "1.0", "game_versions": ["26.3"], "loaders": ["fabric"],
                       "version_type": "release", "date_published": "2026-10-01T00:00:00Z", "dependencies": [],
                       "files": [{"filename": "x-client.jar", "primary": False}, {"filename": "x-server.jar", "primary": False}]})
    with pytest.raises(modrinth.Ambiguous) as e:
        modrinth.install("multi", "26.3", "fabric", tmp_path / "mods")
    assert {c["filename"] for c in e.value.choices} == {"x-client.jar", "x-server.jar"}
    res = modrinth.install("multi", "26.3", "fabric", tmp_path / "mods", version_id="m1", filename="x-client.jar")
    assert [i["filename"] for i in res.installed] == ["x-client.jar"]


def test_existing_same_file_kept_and_old_version_disabled(fake, tmp_path):
    mods = tmp_path / "mods"
    for v in _real_e4mc():
        fake.add(E4MC, v)
    fake.add(FABRIC_API, _fabric_api())
    old = mods / "e4mc-fabric-6.2.2-modern.jar"
    mods.mkdir()
    old.write_bytes(_blob("e4mc-fabric-6.2.2-modern.jar"))          # 예전 버전(해시로 식별됨)
    res = modrinth.install(E4MC, "26.3", "fabric", mods)
    assert "e4mc-fabric-6.2.3-modern.jar" in [i["filename"] for i in res.installed]
    assert (mods / "e4mc-fabric-6.2.2-modern.jar.disabled").exists() and not old.exists()   # 삭제 아님
    res2 = modrinth.install(E4MC, "26.3", "fabric", mods)
    assert [k["filename"] for k in res2.kept] == ["e4mc-fabric-6.2.3-modern.jar", "fabric-api-0.140.0+26.3.jar"]
    assert res2.installed == []


def test_identify_and_check_mods(fake, tmp_path):
    for v in _real_e4mc():
        fake.add(E4MC, v)
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / "e4mc-fabric-6.2.3.jar").write_bytes(_blob("e4mc-fabric-6.2.3.jar"))
    (mods / "mine.jar").write_bytes(b"homemade")
    rows = {r["file"]: r for r in modrinth.check_mods(mods, "26.3", "fabric")}
    assert rows["mine.jar"]["known"] is False
    assert rows["e4mc-fabric-6.2.3.jar"]["matches"] is False and "1.21" in rows["e4mc-fabric-6.2.3.jar"]["note"]


def test_disallowed_host_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("INTEGRATED_STUDIO_MODRINTH_API", "https://api.modrinth.com/v2")
    with pytest.raises(modrinth.RpcError):
        modrinth.download({"url": "https://evil.example.com/x.jar", "hashes": {"sha512": "a"}}, tmp_path / "x.jar")


def test_verify_requires_hash(tmp_path):
    p = tmp_path / "a"
    p.write_bytes(b"1")
    assert modrinth.verify(p, {}) is False
    assert modrinth.verify(p, {"sha1": _sha(b"1", "sha1")}) is True
    assert modrinth.verify(p, {"sha512": _sha(b"1"), "sha1": "wrong"}) is True   # sha512 우선
