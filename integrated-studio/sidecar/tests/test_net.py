"""net.py(인터넷 요청 공통) 시험: .part 로 받고 해시가 맞을 때만 제자리, 틀리면 지움, 끊기면 .part 정리."""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import net  # noqa: E402

DATA = b"hello minecraft" * 1000


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture
def served(monkeypatch):
    seen = []

    def fake(req, timeout=0):
        seen.append(req)
        return _Resp(DATA)
    monkeypatch.setattr(net.urllib.request, "urlopen", fake)
    return seen


def test_download_verifies_and_sends_user_agent(tmp_path, served):
    dest = tmp_path / "a" / "x.jar"
    net.download("https://example.invalid/x.jar", dest, hashes={"sha1": hashlib.sha1(DATA).hexdigest().upper()})
    assert dest.read_bytes() == DATA and not (tmp_path / "a" / "x.jar.part").exists()
    assert served[0].get_header("User-agent") == net.USER_AGENT


def test_download_wrong_hash_removes_file(tmp_path, served):
    dest = tmp_path / "x.jar"
    with pytest.raises(net.HashMismatch):
        net.download("https://example.invalid/x.jar", dest, hashes={"sha512": "00"})
    assert not dest.exists() and not (tmp_path / "x.jar.part").exists()


def test_require_hash_without_hashes_fails(tmp_path, served):
    with pytest.raises(net.HashMismatch):
        net.download("https://example.invalid/x.jar", tmp_path / "x.jar", require_hash=True)


def test_interrupted_download_cleans_part(tmp_path, monkeypatch):
    class Broken(_Resp):
        def read(self, *a):
            raise OSError("connection reset")
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout=0: Broken(b""))
    with pytest.raises(OSError):
        net.download("https://example.invalid/x.jar", tmp_path / "x.jar")
    assert list(tmp_path.iterdir()) == []


def test_strongest_hash_wins(tmp_path):
    f = tmp_path / "f"
    f.write_bytes(DATA)
    good_sha512 = hashlib.sha512(DATA).hexdigest()
    assert net.hashes_match(f, {"sha1": "wrong", "sha512": good_sha512})   # sha512 만 본다
    assert not net.hashes_match(f, {"sha1": hashlib.sha1(DATA).hexdigest(), "sha512": "wrong"})
    assert net.hashes_match(f, None) and not net.hashes_match(f, None, require=True)
