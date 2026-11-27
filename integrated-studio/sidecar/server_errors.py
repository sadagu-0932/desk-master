"""서버 로그로 오류 원인 찾기 — 오류 코드·한국어 설명·고치는 방법(사용자 요청 2026-11-27 "오류코드도 뜨도록").

코드 체계(앱 안에서만 쓰는 번호):
  JAVA-xxx 자바 · MOD-xxx 모드 · NET-xxx 포트·접속 · MEM-xxx 메모리 · WORLD-xxx 월드 · EULA-xxx · CRASH-xxx 그 밖의 튕김
모드가 안 맞는 경우(MOD-1xx)는 server_runner.mod_check 가 같은 번호로 파일별 차이를 알려 준다.
"""
from __future__ import annotations

import re
from typing import Any

# (코드, 찾을 문구, 제목, 고치는 방법). 위에서부터 먼저 맞는 것 하나만.
RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    ("JAVA-101", re.compile(r"UnsupportedClassVersionError|compiled by a more recent version of the Java Runtime"),
     "자바 버전이 낮습니다", "이 서버(또는 모드)는 더 새 자바가 필요합니다. 'Java 25 JDK 설치' 뒤 다시 시작하세요."),
    ("JAVA-102", re.compile(r"(main class|기본 클래스) @user_jvm_args\.txt"),
     "옛 자바(8)로 run.bat 을 실행했습니다", "앱의 [시작]으로 켜거나, 앱이 고친 run.bat 을 쓰세요(Java 25 필요)."),
    ("EULA-101", re.compile(r"You need to agree to the EULA"),
     "EULA 동의가 필요합니다", "서버 카드의 [EULA 동의]에서 직접 읽고 동의하세요."),
    ("MOD-104", re.compile(r"Attempted to load class net/minecraft/client|invalid dist DEDICATED_SERVER|"
                           r"Environment type SERVER|cannot be loaded on the server|net\.minecraft\.client\.\w+ .*not found", re.I),
     "클라이언트 전용 모드가 서버에 들어 있습니다", "[모드 확인]에서 서버 쪽 클라이언트 전용 모드를 빼세요."),
    ("MOD-105", re.compile(r"[Dd]uplicate mods? (found|detected)|DuplicateModsFoundException|Found duplicate mods"),
     "같은 모드가 두 개 들어 있습니다", "[모드 확인]에서 옛 버전을 빼세요."),
    ("MOD-201", re.compile(r"Incompatible mods? (found|set)|Mod resolution (encountered|failed)|"
                           r"Missing or unsupported mandatory dependencies|requires (any version|version) .* of|"
                           r"ModResolutionException|which is missing!", re.I),
     "필요한 모드가 없거나 버전이 맞지 않습니다", "콘솔의 바로 아래 줄에 어떤 모드가 무엇을 요구하는지 나옵니다. "
     "인스턴스에 그 모드를 넣고 [모드 확인]으로 서버에 복사하세요."),
    ("MOD-301", re.compile(r"Mixin apply (failed|for mod)|MixinApplyError|MixinTransformerError|InvalidInjectionException"),
     "모드끼리 충돌합니다(Mixin)", "콘솔에 나온 모드를 하나씩 빼 보며 원인을 찾으세요. 모드 버전을 맞추면 풀리기도 합니다."),
    ("MOD-110", re.compile(r"Mod rejections|mismatched mod channel|[Cc]hannels? .* rejected|"
                           r"Incompatible client|mod(s)? (are )?missing on the client|Connection rejected.*mod", re.I),
     "접속한 사람의 모드가 서버와 다릅니다", "[모드 확인]으로 서버·인스턴스 모드를 맞춘 뒤, 참가자에게 같은 모드 목록을 보내 주세요."),
    ("NET-101", re.compile(r"FAILED TO BIND TO PORT|Address already in use|BindException"),
     "포트를 이미 다른 프로그램이 쓰고 있습니다", "같은 서버를 앱 밖(run.bat)에서도 켰는지 확인하세요. 다시 시작하면 빈 포트를 고릅니다."),
    ("WORLD-101", re.compile(r"session\.lock|already locked|DirectoryLock"),
     "월드를 다른 프로그램이 쓰고 있습니다", "같은 월드를 연 게임·서버를 끄고 다시 시작하세요."),
    ("MEM-101", re.compile(r"java\.lang\.OutOfMemoryError|Could not reserve enough space for object heap"),
     "메모리가 부족합니다", "서버 카드의 [메모리]를 늘리거나(모드가 많으면 4~6GB) 다른 프로그램을 닫으세요."),
    ("CRASH-101", re.compile(r"Exception in server tick loop|Encountered an unexpected exception|"
                             r"Failed to start the minecraft server|---- Minecraft Crash Report ----"),
     "서버가 튕겼습니다", "콘솔의 오류 줄과 crash-reports 폴더(서버 폴더 열기)를 확인하세요."),
]
CRASH_FILE_RE = re.compile(r"crash report has been saved to:\s*(.+)$|Crash report saved to:?\s*(.+)$", re.I)


def match(line: str) -> dict[str, Any] | None:
    for code, rx, title, hint in RULES:
        if rx.search(line):
            return {"code": code, "title": title, "hint": hint, "line": line.strip()[:300]}
    return None


class Diagnoser:
    """서버 하나의 로그를 한 줄씩 받아 오류를 모은다(같은 코드는 한 번, 근처 설명 줄 몇 개도 붙임)."""

    DETAIL_LINES = 6

    def __init__(self) -> None:
        self.found: list[dict[str, Any]] = []
        self._codes: set[str] = set()
        self._collect: dict[str, Any] | None = None
        self.crash_file: str | None = None

    def feed(self, line: str) -> dict[str, Any] | None:
        """새로 찾은 오류면 돌려준다."""
        m = CRASH_FILE_RE.search(line)
        if m:
            self.crash_file = (m.group(1) or m.group(2) or "").strip()
            for f in self.found:
                f.setdefault("crashFile", self.crash_file)
        if self._collect is not None:
            text = line.strip()
            if text and len(self._collect["details"]) < self.DETAIL_LINES and not text.startswith("at "):
                self._collect["details"].append(text[:300])
            elif len(self._collect["details"]) >= self.DETAIL_LINES:
                self._collect = None
        hit = match(line)
        if not hit or hit["code"] in self._codes:
            return None
        hit["details"] = []
        if self.crash_file:
            hit["crashFile"] = self.crash_file
        self._codes.add(hit["code"])
        self.found.append(hit)
        self._collect = hit
        return hit

    def summary(self, exit_code: int | None) -> list[dict[str, Any]]:
        out = list(self.found)
        if exit_code not in (None, 0) and not out:
            out.append({"code": f"EXIT-{exit_code}", "title": f"서버가 오류로 꺼졌습니다(종료 코드 {exit_code})",
                        "hint": "콘솔의 마지막 줄들을 확인하세요.", "details": []})
        return out
