"""시험 공통: 전용 서버 시험이 인터넷(Modrinth)에서 주소 열기 모드(e4mc·Minekube Connect)를 받지 않게 막는다.
이 기능 자체를 시험할 때는 @pytest.mark.address_mod 를 붙이고 modrinth.install 을 가짜로 바꾼다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_configure(config):
    config.addinivalue_line("markers", "address_mod: 주소 열기 모드 설치를 막지 않음(가짜 modrinth 로 시험)")


@pytest.fixture(autouse=True)
def _no_address_mod_download(request, monkeypatch):
    if request.node.get_closest_marker("address_mod"):
        return
    try:
        import server_runner
    except Exception:  # noqa: BLE001 - 사이드카 모듈을 안 쓰는 시험
        return
    monkeypatch.setattr(server_runner.ServerRunner, "_ensure_address_mod", lambda self, *a, **k: None)
