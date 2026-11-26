"""stdin/stdout 줄 단위 JSON-RPC.

요청:   {"id": 1, "method": "list_instances", "params": {...}}
응답:   {"id": 1, "result": ...}  또는  {"id": 1, "error": {"message": "..."}}
알림:   {"method": "log", "params": {...}}   (사이드카 → 앱, id 없음)

stdout은 프로토콜 전용이다. 라이브러리가 print 하는 내용이 섞이지 않도록
sys.stdout을 stderr로 돌리고, 원래 stdout 핸들은 이 모듈만 쓴다.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import traceback
from typing import Any, Callable

# 실행 환경의 기본 인코딩(Windows cp1252/cp949 등)과 상관없이 프로토콜과 로그는 UTF-8로 주고받는다.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _isolate_protocol() -> tuple[io.TextIOBase, io.TextIOBase]:
    """프로토콜 통로(stdin/stdout)를 따로 떼어 내고, 표준 입출력 자리는 비워 둔다.

    사이드카가 띄우는 프로그램(PowerShell·git·자바 설치기 등)은 표준 입력을 물려받는다. 그대로 두면
    PowerShell 처럼 입력이 끝날 때까지 읽는 프로그램이 앱의 요청을 삼키거나 앱을 끌 때까지 멈춰서
    만들기·불러오기·실행이 통째로 멈췄다(껐다 켜야 보이던 문제). 그래서:
      - 프로토콜은 복제한 파일 설명자로만 읽고 쓴다.
      - 표준 입력 자리는 빈 입력(devnull), 표준 출력 자리는 표준 오류(로그)로 바꾼다.
      - Windows 는 자식이 GetStdHandle 로 물려받으므로 SetStdHandle 까지 바꾼다.
    """
    try:
        in_fd = os.dup(0)
        out_fd = os.dup(1)
        null = os.open(os.devnull, os.O_RDWR)
        os.dup2(null, 0)
        os.dup2(2, 1)
        os.close(null)
        if sys.platform == "win32":
            import ctypes
            import msvcrt
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            k32.SetStdHandle(-10, msvcrt.get_osfhandle(0))   # STD_INPUT_HANDLE
            k32.SetStdHandle(-11, msvcrt.get_osfhandle(1))   # STD_OUTPUT_HANDLE
        proto_in = io.TextIOWrapper(os.fdopen(in_fd, "rb", buffering=0), encoding="utf-8", errors="replace")
        proto_out = io.TextIOWrapper(os.fdopen(out_fd, "wb", buffering=0), encoding="utf-8", errors="replace",
                                     write_through=True)
        sys.stdin = open(os.devnull, encoding="utf-8")
        return proto_in, proto_out
    except (OSError, ValueError, AttributeError):
        return sys.stdin, sys.stdout   # 떼어 내지 못하면 예전처럼


_in, _out = _isolate_protocol()
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


ERROR_LOG: str | None = None   # main.py 가 data/logs/sidecar-errors.log 로 정한다


def _log_error(method: str, tb: str) -> None:
    if not ERROR_LOG:
        return
    try:
        import datetime
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now().isoformat(timespec='seconds')} {method}\n{tb}\n")
    except OSError:
        pass


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
            tb = traceback.format_exc()
            sys.stderr.write(tb)
            _log_error(method, tb)
            # 어디서 났는지(가장 안쪽 파일:줄) 를 붙여 보여 준다 — 사용자가 캡처만 보내도 원인을 찾을 수 있게
            frames = traceback.extract_tb(e.__traceback__)
            where = f" ({os.path.basename(frames[-1].filename)}:{frames[-1].lineno}, {method})" if frames else ""
            _write({"id": req_id, "error": {"message": f"{type(e).__name__}: {e}{where}"}})

    for raw in _in:
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
