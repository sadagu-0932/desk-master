"""CurseForge 키 입력·오류 안내 시험. pytest 없이 `python tests/test_cf_key.py`."""
from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importers  # noqa: E402
from rpc import RpcError  # noqa: E402

PASSED = 0
REAL_LIKE = "$2a$10$" + "A" * 53  # 실제 키와 같은 모양(60자)


def check(cond: bool, msg: str) -> None:
    global PASSED
    if not cond:
        raise AssertionError(msg)
    PASSED += 1
    print(f"  ✓ {msg}")


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/blocked"):
            body = b"<!DOCTYPE html><html><title>Just a moment...</title></html>"
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=UTF-8")
            self.send_header("cf-mitigated", "challenge")
        elif self.headers.get("x-api-key") == REAL_LIKE:
            body = json.dumps({"data": {"id": 432}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b""
            self.send_response(403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    print("1) 붙여넣기 정리")
    check(importers.clean_cf_key(f"  {REAL_LIKE}\n") == REAL_LIKE, "앞뒤 공백·줄바꿈 제거")
    check(importers.clean_cf_key(f"​{REAL_LIKE}﻿") == REAL_LIKE, "보이지 않는 문자 제거")
    check(importers.clean_cf_key(f'"{REAL_LIKE}"') == REAL_LIKE, "따옴표로 감싼 것 제거")
    check(importers.clean_cf_key(f"$2a$10$ {'A' * 53}") == REAL_LIKE, "중간에 끼어든 공백 제거")
    check("$" in importers.clean_cf_key(REAL_LIKE) and importers.clean_cf_key(REAL_LIKE).count("$") == 3, "키의 $ 는 그대로")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    print("2) 오류 안내")
    try:
        importers._json(f"{base}/games/432", headers={"x-api-key": "$2a$10$short"})
        check(False, "거부")
    except RpcError as e:
        m = str(e)
        check("HTTP 403" in m and "12자" in m and "'$2a$10$'로 시작" in m and "short" not in m,
              "거부: HTTP 코드와 키 모양만 보여 줌(키 내용은 숨김)")
    try:
        importers._json(f"{base}/blocked", headers={"x-api-key": REAL_LIKE})
        check(False, "차단")
    except RpcError as e:
        check("막았습니다" in str(e) and "키 문제가 아닐 수" in str(e), "보안 검사 페이지(차단)는 키 오류와 따로 안내")
    check(importers._json(f"{base}/games/432", headers={"x-api-key": REAL_LIKE})["data"]["id"] == 432, "맞는 키는 통과")

    print("3) 저장 전 확인")
    old = importers.CURSEFORGE_API
    importers.CURSEFORGE_API = base
    try:
        imp = importers.Importers.__new__(importers.Importers)
        try:
            imp.cf_set_key("$2a$10$abc한글")
            check(False, "비ASCII 거부")
        except RpcError as e:
            check("다시 복사" in str(e), "영문·기호가 아닌 문자가 섞이면 따로 안내")
        saved = {}
        import keyring
        orig = keyring.set_password
        keyring.set_password = lambda svc, name, val: saved.update({name: val})
        try:
            r = imp.cf_set_key(f"​ {REAL_LIKE} \n")
        finally:
            keyring.set_password = orig
        check(r["hasKey"] and list(saved.values()) == [REAL_LIKE], "정리한 키로 확인·저장")
    finally:
        importers.CURSEFORGE_API = old
        srv.shutdown()
    print(f"\n통과 {PASSED}개")


if __name__ == "__main__":
    main()
