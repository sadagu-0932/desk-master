"""사이드카가 띄운 프로그램이 앱의 요청 통로(표준 입력)를 삼키지 않는지.

Windows 의 PowerShell 처럼 표준 입력을 끝까지 읽는 프로그램을 핸들러에서 띄워도
그 프로그램은 빈 입력을 받고, 바로 뒤의 요청(ping)이 사라지지 않아야 한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

SIDECAR = Path(__file__).resolve().parents[1]


def test_child_process_cannot_steal_requests(tmp_path):
    server = tmp_path / "srv.py"
    server.write_text(textwrap.dedent(f"""
        import subprocess, sys
        sys.path.insert(0, {str(SIDECAR)!r})
        import rpc
        def child():
            # 표준 입력을 끝까지 읽는 자식(예전엔 앱의 요청을 삼키거나 멈췄다)
            r = subprocess.run([sys.executable, "-c", "import sys; d = sys.stdin.read(); print(len(d))"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip()
        def noisy():
            # 표준 출력에 마구 쓰는 자식(프로토콜을 더럽히면 안 됨)
            subprocess.run([sys.executable, "-c", "print('garbage line')"], timeout=10)
            return "ok"
        rpc.serve({{"child": child, "noisy": noisy, "ping": lambda: "pong"}}, set())
    """), "utf-8")
    p = subprocess.Popen([sys.executable, "-u", str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8")
    reqs = [{"id": 1, "method": "child"}, {"id": 2, "method": "ping"}, {"id": 3, "method": "noisy"}, {"id": 4, "method": "ping"}]
    out, _ = p.communicate("\n".join(json.dumps(r) for r in reqs) + "\n", timeout=60)
    replies = [json.loads(line) for line in out.splitlines() if line.strip()]   # 쓰레기 줄이 섞이면 여기서 실패
    by_id = {r["id"]: r for r in replies}
    assert by_id[1]["result"] == "0"            # 자식은 빈 입력만 받음
    assert by_id[2]["result"] == "pong"         # 뒤 요청이 사라지지 않음
    assert by_id[3]["result"] == "ok" and by_id[4]["result"] == "pong"
