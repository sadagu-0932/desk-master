"""설정 동기화(sync.py) 시험: 통합 작업실이 만든 인스턴스끼리 options.txt·servers.dat 를 맞춘다(2026-11-27 공식 런처 부분 없앰)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync  # noqa: E402
from instances import InstanceStore  # noqa: E402


def test_merge_options_keeps_per_instance_keys():
    merged = sync.merge_options('version:4000\nfov:0.5\nresourcePacks:["vanilla","file/A"]\nlang:ko_kr\n',
                                'version:4000\nfov:0.0\nresourcePacks:["vanilla","file/B"]\n')
    assert "fov:0.5" in merged and "lang:ko_kr" in merged
    assert "file/B" in merged and "file/A" not in merged
    assert "resourcePacks" not in sync.merge_options('fov:0.5\nresourcePacks:["file/A"]\n', None)
    assert sync.merge_options("a:1\r\nb:2\r\n", "a:0\n") == "a:1\r\nb:2\r\n"
    assert sync._same_text("a:1\r\nb:2\r\n", "a:1\nb:2\n")


def _setup(tmp_path):
    store = InstanceStore(tmp_path / "data")
    a = store.create("가", "26.3", "fabric")
    b = store.create("나", "26.3", "fabric")
    # 연결 인스턴스(Prism 에 원래 있던 것) — 맞추지 않는다
    c = store.create("다", "26.3", "fabric", prism=False)
    ext = tmp_path / "prism" / "instances" / "다" / "minecraft"
    ext.mkdir(parents=True)
    meta = store.get(c["id"])
    meta.update(linkedDir=str(ext), launchKind="prism")
    store.save(meta)
    return store, store.game_dir(a["id"]), store.game_dir(b["id"]), ext, a, b


def test_sync_only_managed_and_not_running(tmp_path):
    store, da, db, ext, a, b = _setup(tmp_path)
    running: list[str] = []
    ss = sync.SettingsSync(store, tmp_path / "data", running=lambda: running, log=lambda _l: None)
    now = time.time()
    (da / "options.txt").write_text("version:4000\nfov:0.9\n", "utf-8")
    os.utime(da / "options.txt", (now, now))
    (ext / "options.txt").write_text("fov:0.1\n", "utf-8")
    os.utime(ext / "options.txt", (now + 100, now + 100))       # 연결 인스턴스가 더 최신이어도 기준이 되지 않음
    (db / "servers.dat").write_bytes(b"servers-from-B")
    r = ss.sync_now()
    assert r["options"] == ["나"] and "fov:0.9" in (db / "options.txt").read_text("utf-8")
    assert (da / "servers.dat").read_bytes() == b"servers-from-B"
    assert (ext / "options.txt").read_text("utf-8") == "fov:0.1\n" and not (ext / "servers.dat").exists()
    assert ss.sync_now() == {"options": [], "servers": []}      # 왕복 없음
    running.append(b["id"])
    (da / "options.txt").write_text("version:4000\nfov:0.3\n", "utf-8")
    os.utime(da / "options.txt", (now + 10, now + 10))
    assert ss.sync_now()["options"] == []                       # 실행 중엔 쓰지 않음
    running.clear()
    assert ss.sync_now()["options"] == ["나"]


def test_periodic_sync_skips_when_nothing_changed(tmp_path):
    store, da, db, _ext, _a, _b = _setup(tmp_path)
    ss = sync.SettingsSync(store, tmp_path / "data", log=lambda _l: None)
    (da / "options.txt").write_text("fov:0.5\n", "utf-8")
    ss.sync_now()
    calls = {"n": 0}
    real = ss._sync_file

    def count(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)
    ss._sync_file = count
    assert ss.sync_now(force=False) == {"options": [], "servers": []} and calls["n"] == 0
    (da / "options.txt").write_text("fov:0.42\n", "utf-8")
    os.utime(da / "options.txt", (time.time() + 3600, time.time() + 3600))
    ss.sync_now(force=False)
    assert calls["n"] == 1 and "fov:0.42" in (db / "options.txt").read_text("utf-8")


def test_account_files_never_touched(tmp_path):
    store, *_ = _setup(tmp_path)
    ss = sync.SettingsSync(store, tmp_path / "data", log=lambda _l: None)
    try:
        ss._guard(Path("x") / "launcher_accounts.json")
        raise AssertionError("계정 파일을 막지 않았습니다")
    except PermissionError:
        pass
