"""stdin/stdout 줄 단위 JSON-RPC.

요청:   {"id": 1, "method": "list_instances", "params": {...}}
응답:   {"id": 1, "result": ...}  또는  {"id": 1, "error": {"message": "..."}}
알림:   {"method": "log", "params": {...}}   (사이드카 → 앱, id 없음)

stdout은 프로토콜 전용이다. 라이브러리가 print 하는 내용이 섞이지 않도록
sys.stdout을 stderr로 돌리고, 원래 stdout 핸들은 이 모듈만 쓴다.
"""
from __future__ import annotations

import json
import sys
import threading
import traceback
from typing import Any, Callable

# 실행 환경의 기본 인코딩(Windows cp1252/cp949 등)과 상관없이 프로토콜과 로그는 UTF-8로 주고받는다.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
_out = sys.stdout
sys.stdout = sys.stderr
_lock = threading.Lock()


class RpcError(Exception):
    """사용자에게 그대로 보여줄 오류(한국어 메시지)."""


def _write(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    with _lock:
        _out.write(line + "\n")
        _out.flush()


def notify(method: str, params: dict) -> None:
    _write({"method": method, "params": params})


Handler = Callable[..., Any]


def serve(handlers: dict[str, Handler], background: set[str]) -> None:
    """요청을 처리한다. background에 든 메서드는 별도 스레드에서 돌려 입력 루프를 막지 않는다."""

    def run(req_id: Any, method: str, params: dict) -> None:
        try:
            handler = handlers.get(method)
            if handler is None:
                raise RpcError(f"알 수 없는 메서드: {method}")
            result = handler(**params)
            _write({"id": req_id, "result": result})
        except RpcError as e:
            _write({"id": req_id, "error": {"message": str(e)}})
        except Exception as e:  # noqa: BLE001 - 사이드카가 죽지 않게 모든 오류를 응답으로 돌려준다
            traceback.print_exc()
            _write({"id": req_id, "error": {"message": f"{type(e).__name__}: {e}"}})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = req.get("method", "")
        params = req.get("params") or {}
        req_id = req.get("id")
        if method in background:
            threading.Thread(target=run, args=(req_id, method, params), daemon=True).start()
        else:
            run(req_id, method, params)
