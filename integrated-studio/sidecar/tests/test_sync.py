"""설정 동기화(sync.py) 시험. pytest 없이 `python tests/test_sync.py`. Windows·공식 런처는 흉내 낸다."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SIDECAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIDECAR))

import official_launcher as ol  # noqa: E402
import official_rpc  # noqa: E402
import sync  # noqa: E402
from instances import InstanceStore  # noqa: E402

PASSED = 0
NOTES: list[tuple[str, dict]] = []


def check(cond: bool, msg: str) -> None:
    global PASSED
    if not cond:
        raise AssertionError(msg)
    PASSED += 1
    print(f"  ✓ {msg}")


def fake_notify(method: str, params: dict) -> None:
    NOTES.append((method, params))


def set_mtime(p: Path, t: float) -> None:
    os.utime(p, (t, t))


def main() -> None:
    official_rpc.notify = fake_notify  # type: ignore[assignment]
    sync.notify = fake_notify  # type: ignore[assignment]
    ol._is_windows = lambda: True  # type: ignore[assignment]
    ol.launcher_running = lambda: False  # type: ignore[assignment]

    print("1) options.txt 합치기")
    merged = sync.merge_options("version:4000\nfov:0.5\nresourcePacks:[\"vanilla\",\"file/A\"]\nlang:ko_kr\n",
                                "version:4000\nfov:0.0\nresourcePacks:[\"vanilla\",\"file/B\"]\n")
    check("fov:0.5" in merged and "lang:ko_kr" in merged, "다른 값은 기준 파일 것으로")
    check('file/B' in merged and 'file/A' not in merged, "리소스팩 목록은 인스턴스 것 유지")
    merged = sync.merge_options("fov:0.5\nresourcePacks:[\"file/A\"]\n", None)
    check("resourcePacks" not in merged, "새 인스턴스에는 다른 곳의 리소스팩 목록을 넣지 않음")
    check(sync.merge_options("a:1\r\nb:2\r\n", "a:0\n") == "a:1\r\nb:2\r\n", "기준 파일의 줄바꿈(CRLF)을 그대로")
    check(sync._same_text("a:1\r\nb:2\r\n", "a:1\nb:2\n"), "줄바꿈만 다르면 같은 내용으로 봄")

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mc = tmp / "official" / ".minecraft"
        mc.mkdir(parents=True)
        (mc / "launcher_profiles.json").write_text(json.dumps({"profiles": {"user-own": {"name": "내 프로필"}}, "version": 3}), "utf-8")
        (mc / "launcher_accounts.json").write_text('{"secret": 1}', "utf-8")
        ol.find_minecraft_dir = lambda: {"path": mc, "kind": "roaming", "warning": None}  # type: ignore[assignment]

        store = InstanceStore(tmp / "data")
        a = store.create("가 인스턴스", "26.3", "vanilla")
        b = store.create("나 인스턴스", "26.3", "vanilla")
        da, db = store.dir_of(a["id"]), store.dir_of(b["id"])
        app_mc = tmp / "app-mc"
        (app_mc / "versions" / "26.3").mkdir(parents=True)
        for inst in (a, b):
            meta = store.get(inst["id"])
            meta.update(installed=True, versionId="26.3")
            store.save(meta)

        off = official_rpc.OfficialLauncherRpc(store, app_mc)
        ss = sync.SettingsSync(store, tmp / "data", off, log=lambda line: NOTES.append(("log", {"line": line})))

        print("2) 게임 설정·서버 목록 맞추기")
        now = time.time()
        (mc / "options.txt").write_text("version:4000\nfov:0.0\nresourcePacks:[\"vanilla\",\"file/Official\"]\n", "utf-8")
        set_mtime(mc / "options.txt", now - 100)
        # 게임이 Windows 에서 쓰는 것처럼 CRLF (어느 OS 에서든 같은 조건으로 시험)
        (da / "options.txt").write_bytes("version:4000\r\nfov:0.9\r\nkey_key.jump:key.keyboard.k\r\nresourcePacks:[\"vanilla\",\"file/A\"]\r\n".encode())
        set_mtime(da / "options.txt", now - 10)  # 가장 최근
        (db / "servers.dat").write_bytes(b"\x0a\x00\x00servers-from-B")
        r = ss.sync_now()
        off_opts = (mc / "options.txt").read_text("utf-8")
        b_opts = (db / "options.txt").read_text("utf-8")
        check(sorted(r["options"]) == ["공식 런처", "나 인스턴스"], "가장 최근 설정(가)을 공식 런처·나에 맞춤")
        check("fov:0.9" in off_opts and "key.keyboard.k" in off_opts and "file/Official" in off_opts and "file/A" not in off_opts,
              "공식 런처: 값은 맞추고 자기 리소스팩 목록은 유지")
        check("fov:0.9" in b_opts and "resourcePacks" not in b_opts, "나: 설정을 받고 리소스팩 목록은 넣지 않음")
        check(abs((db / "options.txt").stat().st_mtime - (da / "options.txt").stat().st_mtime) < 1, "쓴 파일의 수정 시각을 기준과 같게")
        check((mc / "servers.dat").read_bytes() == b"\x0a\x00\x00servers-from-B" and (da / "servers.dat").is_file(),
              "서버 목록을 모두에 맞춤")
        backups = list((tmp / "data" / "sync-backups").glob("*-official-options.txt"))
        check(len(backups) == 1 and "fov:0.0" in backups[0].read_text("utf-8"), "공식 런처 파일은 덮기 전에 백업")
        r = ss.sync_now()
        check(r["options"] == [] and r["servers"] == [], "다시 맞춰도 바뀌는 것 없음(왕복 없음)")
        check((mc / "launcher_accounts.json").read_text("utf-8") == '{"secret": 1}', "로그인·토큰 파일은 그대로")

        print("3) 실행 중인 인스턴스")
        off._game_running[b["id"]] = True
        (mc / "options.txt").write_text("version:4000\nfov:0.3\nresourcePacks:[\"vanilla\",\"file/Official\"]\n", "utf-8")
        set_mtime(mc / "options.txt", now + 50)
        r = ss.sync_now()
        check("나 인스턴스" not in r["options"] and "fov:0.9" in (db / "options.txt").read_text("utf-8"),
              "실행 중인 인스턴스에는 쓰지 않음")
        check("fov:0.3" in (da / "options.txt").read_text("utf-8"), "나머지는 공식 런처에서 바꾼 값으로")
        off._game_running[b["id"]] = False
        r = ss.sync_now()
        check("나 인스턴스" in r["options"], "게임이 닫히면 맞춤")

        print("4) 공식 런처 항목")
        r0 = ol.register_instance({"id": a["id"], "name": "가 인스턴스", "path": str(da), "versionId": "26.3"},
                                  lambda _m: True, app_minecraft_dir=app_mc)
        check(r0["ok"], "처음 등록(사용자 확인 후)")
        key = "integrated-studio-" + a["id"]
        store.rename(a["id"], "가 새이름")
        NOTES.clear()
        r = ss.sync_now()
        prof = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))["profiles"]
        check(r["profiles"] == 1 and prof[key]["name"] == "통합 작업실 · 가 새이름", "이름을 바꾸면 확인 없이 항목도 바뀜")
        check(not any(m == "confirm" for m, _ in NOTES), "확인 창을 띄우지 않음")
        check(key not in [] and ("integrated-studio-" + b["id"]) not in prof, "등록하지 않은 인스턴스는 추가하지 않음")
        r = off.register_instance(a["id"])
        check(r.get("unchanged") is True, "실행할 때 이미 맞으면 그대로")

        prof["integrated-studio-inst_deadbeef"] = {"name": "통합 작업실 · 지운 것", "type": "custom", "lastVersionId": "26.3"}
        data = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))
        data["profiles"] = prof
        (mc / "launcher_profiles.json").write_text(json.dumps(data), "utf-8")
        r = ss.sync_now()
        prof = json.loads((mc / "launcher_profiles.json").read_text("utf-8"))["profiles"]
        check("integrated-studio-inst_deadbeef" not in prof and key in prof and "user-own" in prof,
              "앱에 없는 인스턴스 항목만 정리, 사용자 프로필 유지")
        check(off.forget(a["id"]) and key not in json.loads((mc / "launcher_profiles.json").read_text("utf-8"))["profiles"],
              "인스턴스를 지우면 항목도 지움")

        print("5) 30초마다 돌 때: 바뀐 게 없으면 파일을 읽지 않음(최적화)")
        ss.sync_now()                                   # 지금 상태를 기억
        calls = {"file": 0, "profiles": 0}
        real_file, real_prof = ss._sync_file, ss._sync_profiles

        def count_file(*a, **kw):
            calls["file"] += 1
            return real_file(*a, **kw)

        def count_prof(*a, **kw):
            calls["profiles"] += 1
            return real_prof(*a, **kw)
        ss._sync_file, ss._sync_profiles = count_file, count_prof
        r = ss.sync_now(force=False)
        check(calls == {"file": 0, "profiles": 0} and r == {"options": [], "servers": [], "profiles": 0},
              "그대로면 options·servers·항목 모두 건너뜀")
        (da / "options.txt").write_text("version:4000\nfov:0.42\n", "utf-8")
        set_mtime(da / "options.txt", time.time() + 3600)   # 확실히 가장 최근
        r = ss.sync_now(force=False)
        check(calls["file"] == 1 and "fov:0.42" in (db / "options.txt").read_text("utf-8"),
              "한 곳이라도 바뀌면 그 파일만 다시 맞춤")
        meta = store.get(b["id"])
        meta["name"] = "나 새이름"
        store.save(meta)
        ss.sync_now(force=False)
        check(calls["profiles"] == 1, "인스턴스 설정이 바뀌면 공식 런처 항목도 다시 맞춤")
        ss.sync_now()
        check(calls["file"] == 3, "수동 동기화(force)는 항상 맞춤")

    print(f"\n통과 {PASSED}개")


if __name__ == "__main__":
    main()
