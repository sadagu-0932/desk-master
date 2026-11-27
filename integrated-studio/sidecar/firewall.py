"""Windows 방화벽 확인·허용(사용자 요청 2026-11-27 "주소가 연결이 잘 안 됨").

UPnP 로 공유기 포트를 열어도 Windows 방화벽이 서버(java.exe)의 들어오는 연결을 막으면 친구가 못 들어온다.
처음 서버를 켤 때 Windows 가 묻는 창을 닫거나 '취소'하면 차단 규칙이 생긴다.
- check(port): 그 포트에서 듣는 프로그램 경로와, 그 프로그램의 들어오는 규칙(허용·차단, 지금 네트워크 종류에 맞는 것) 수
- allow(port): 사용자 확인 뒤 관리자 권한(Windows 확인 창)으로 그 프로그램 허용 규칙 추가 + 우리가 아는 차단 규칙 끄기
  (규칙 이름 "통합 작업실 - 마인크래프트 서버", 프로그램 기준이라 포트가 바뀌어도 그대로)
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from typing import Any, Callable

from rpc import RpcError

RULE_NAME = "통합 작업실 - 마인크래프트 서버"
NO_WINDOW = 0x08000000


def _enc(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _run(script: str, timeout: int = 30) -> str:
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", _enc(script)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    return p.stdout or ""


def _check_script(port: int) -> str:
    return f"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$c = Get-NetTCPConnection -LocalPort {int(port)} -State Listen | Select-Object -First 1
$path = $null
if ($c) {{ $path = (Get-Process -Id $c.OwningProcess).Path }}
$cats = @(Get-NetConnectionProfile | ForEach-Object {{ [string]$_.NetworkCategory }})
$allow = 0; $block = 0; $names = @()
if ($path) {{
  $rules = Get-NetFirewallApplicationFilter -Program $path | Get-NetFirewallRule | Where-Object {{ $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' }}
  foreach ($r in $rules) {{
    $prof = [string]$r.Profile
    $hit = ($prof -match 'Any') -or ($cats | Where-Object {{ $prof -match $_ -or ($_ -eq 'DomainAuthenticated' -and $prof -match 'Domain') }})
    if ($hit) {{ if ([string]$r.Action -eq 'Block') {{ $block++; $names += $r.DisplayName }} else {{ $allow++ }} }}
  }}
}}
@{{ path = $path; allow = $allow; block = $block; blockNames = $names; profiles = $cats }} | ConvertTo-Json -Compress
"""


def check(port: int) -> dict[str, Any]:
    """{supported, path, allow, block, ok, message}. ok=False 면 친구가 못 들어올 가능성이 높다."""
    if sys.platform != "win32":
        return {"supported": False, "ok": True, "message": "Windows 가 아니라 확인하지 않았습니다."}
    try:
        data = json.loads(_run(_check_script(port)).strip() or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        return {"supported": True, "ok": True, "unknown": True, "message": f"방화벽을 확인하지 못했습니다: {e}"}
    path = data.get("path")
    if not path:
        return {"supported": True, "ok": True, "unknown": True, "message": f"포트 {port} 에서 듣는 프로그램을 찾지 못했습니다."}
    allow, block = int(data.get("allow") or 0), int(data.get("block") or 0)
    if block:
        msg = (f"[NET-201] Windows 방화벽이 서버 프로그램을 막고 있습니다({path}). 친구가 들어오지 못합니다 — "
               "[방화벽 허용]을 누르세요.")
    elif not allow:
        msg = (f"[NET-202] Windows 방화벽에 서버 프로그램 허용 규칙이 없습니다({path}). 친구가 못 들어오면 [방화벽 허용]을 누르세요.")
    else:
        msg = "Windows 방화벽이 서버 프로그램을 허용합니다."
    return {"supported": True, "path": path, "allow": allow, "block": block, "ok": bool(allow) and not block,
            "blockNames": data.get("blockNames") or [], "profiles": data.get("profiles") or [], "message": msg}


def allow(port: int, confirm: Callable[[str], bool]) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RpcError("Windows 에서만 됩니다.")
    st = check(port)
    path = st.get("path")
    if not path:
        raise RpcError(f"포트 {port} 에서 듣는 서버 프로그램을 찾지 못했습니다. 서버를 켠 뒤 다시 눌러 주세요.")
    if st.get("ok"):
        return {**st, "changed": False}
    if not confirm(f"Windows 방화벽에서 이 서버 프로그램의 들어오는 연결을 허용할까요?\n\n{path}\n\n"
                   "관리자 확인 창이 뜹니다. 규칙 이름: " + RULE_NAME):
        return {**st, "cancelled": True}
    p = path.replace("'", "''")
    inner = (f"$p = '{p}'; "
             "Get-NetFirewallApplicationFilter -Program $p -ErrorAction SilentlyContinue | Get-NetFirewallRule | "
             "Where-Object { $_.Direction -eq 'Inbound' -and [string]$_.Action -eq 'Block' } | Disable-NetFirewallRule; "
             f"Remove-NetFirewallRule -DisplayName '{RULE_NAME}' -ErrorAction SilentlyContinue; "
             f"New-NetFirewallRule -DisplayName '{RULE_NAME}' -Direction Inbound -Program $p -Action Allow -Profile Any | Out-Null")
    outer = ("Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
             f"-ArgumentList '-NoProfile','-EncodedCommand','{_enc(inner)}'")
    try:
        _run(outer, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        raise RpcError(f"방화벽 규칙을 추가하지 못했습니다: {e}") from e
    after = check(port)
    if not after.get("ok"):
        after["message"] = "관리자 확인을 취소했거나 규칙을 추가하지 못했습니다. " + after.get("message", "")
    return {**after, "changed": bool(after.get("ok"))}
