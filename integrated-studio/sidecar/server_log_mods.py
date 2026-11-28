"""서버 로그·크래시 리포트로 문제 모드 찾기(사용자 요청 2026-11-28 "고칠 때 서버 로그를 보고 오류를 고칠 수 있게").

[모드 확인]이 jar 정보만으로 못 찾는 것(실행해 봐야 드러나는 것)을 로그에서 찾는다:
- LOG-201 필요한 모드가 없음: Fabric "Mod 'X' (x) … requires … of 'Y' (y), which is missing!",
  NeoForge·Forge "Mod ID: 'y', Requested by: 'x'" / → 인스턴스에 있으면 서버로 복사, 없으면 받으라고 안내.
- LOG-104 클라이언트 전용 코드를 서버에서 부름: "Attempted to load class net/minecraft/client/… for invalid dist DEDICATED_SERVER",
  Fabric "Environment type SERVER" — 근처 스택·Mixin 설정 이름으로 어느 jar 인지 찾는다 → 서버에서 빼기.
- LOG-301 오류에 이름이 나온 모드(로딩 실패·Mixin 충돌): NeoForge·Forge 크래시 리포트 "Mod File: …jar", "Failure message: … (id)",
  "-- MOD id --", Mixin "Mixin [cfg.mixins.json:…]" · "from mod id" → 원인일 수 있음(기본으로 고르지 않음).
어느 jar 인지는 모드 id(fabric.mod.json·mods.toml), jar 이름, jar 안의 *.mixins.json 이름, 클래스 패키지로 맞춘다.
로그는 사용자가 [시작]한 서버의 logs/latest.log 끝부분과 가장 새 crash-reports/*.txt 만 읽는다(읽기 전용).
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

TAIL_BYTES = 400_000
_ID = r"[a-z0-9_\-]{2,64}"

MISSING_FABRIC = re.compile(rf"Mod '(?P<name>[^']+)' \((?P<id>{_ID})\) \S+ requires (?:any version|version \S+)(?: or later)? of "
                            rf"'?(?P<depname>[^'(]*?)'? ?\((?P<dep>{_ID})\)")
MISSING_NEO = re.compile(rf"Mod ID: '(?P<dep>{_ID})', Requested by: '(?P<id>{_ID})'")
CLIENT_CLASS = re.compile(r"(?:Attempted to load class net/minecraft/client|invalid dist DEDICATED_SERVER|Environment type SERVER)")
MOD_FILE = re.compile(r"Mod File: .*?([^\\/\s]+\.jar)")
FAILURE = re.compile(rf"Failure message: .*?\((?P<id>{_ID})\) (?:has failed|encountered)")
MOD_SECTION = re.compile(rf"-- MOD (?P<id>{_ID}) --")
MIXIN_CFG = re.compile(r"Mixin \[(?P<cfg>[\w.\-]+?)\.mixins\.json")
FROM_MOD = re.compile(rf"from mod (?P<id>{_ID})")
STACK = re.compile(r"\bat (?P<cls>[a-zA-Z_][\w$]*(?:\.[a-zA-Z_][\w$]*){2,})\.")
# NeoForge·Forge 스택 줄: "at TRANSFORMER/<모드id>@<버전>/com.foo.Bar.baz(...)" — 모드 id 가 바로 나온다
STACK_MOD = re.compile(r"\bat (?:[A-Z][A-Z\-]+(?: [A-Z]+)?/)?(?P<mod>[a-z][a-z0-9_\-]{1,63})@[^/\s]+/")
# 크래시 리포트 "Suspected Mods: Name (modid), Name2 (modid2)" / "Suspected Mod: Name (modid)"
SUSPECTED = re.compile(r"Suspected Mods?: (?P<list>.+)$")
SUSPECTED_ITEM = re.compile(rf"\((?P<id>{_ID})\)")
NOT_MODS = {"minecraft", "neoforge", "forge", "fml", "fmlloader", "fabricloader", "java", "javafmllanguage", "mixin"}


def _tail(p: Path) -> list[str]:
    try:
        with p.open("rb") as f:
            size = p.stat().st_size
            f.seek(max(0, size - TAIL_BYTES))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def read_logs(server_dir: Path) -> list[tuple[str, str]]:
    """[(출처, 줄)] — latest.log 끝부분 + 가장 새 크래시 리포트."""
    out = [("latest.log", ln) for ln in _tail(server_dir / "logs" / "latest.log")]
    crashes = sorted((server_dir / "crash-reports").glob("*.txt"), key=lambda p: p.stat().st_mtime) \
        if (server_dir / "crash-reports").is_dir() else []
    if crashes:
        out += [(f"crash-reports/{crashes[-1].name}", ln) for ln in _tail(crashes[-1])]
    return out


def _jar_index(mods_dir: Path, mods: list[dict[str, Any]]) -> dict[str, Any]:
    """모드 id·jar 이름·mixin 설정 이름·패키지 → 그 jar 정보"""
    by_id = {m["id"]: m for m in mods if m.get("id")}
    by_file = {m["file"]: m for m in mods}
    by_mixin: dict[str, dict[str, Any]] = {}
    by_pkg: dict[str, dict[str, Any]] = {}
    for m in mods:
        try:
            with zipfile.ZipFile(mods_dir / m["file"]) as zf:
                for n in zf.namelist():
                    if n.endswith(".mixins.json") and "/" not in n:
                        by_mixin.setdefault(n[: -len(".mixins.json")], m)
                    elif n.endswith(".class") and n.count("/") >= 3 and not n.startswith(("META-INF/", "net/minecraft/", "com/mojang/")):
                        by_pkg.setdefault(".".join(n.split("/")[:3]), m)
        except (OSError, zipfile.BadZipFile):
            continue
    return {"id": by_id, "file": by_file, "mixin": by_mixin, "pkg": by_pkg}


def analyze(server_dir: Path, server_mods: list[dict[str, Any]], client_mods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """로그로 찾은 문제(모드 확인 항목과 같은 형식). evidence = 근거가 된 로그 줄, pick = 기본으로 고를지."""
    lines = read_logs(server_dir)
    if not lines:
        return []
    idx = _jar_index(server_dir / "mods", server_mods)
    cby = {m["id"]: m for m in client_mods if m.get("id")}
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    client_error = False
    suspects: list[tuple[dict[str, Any], str, str]] = []

    def ev(src: str, line: str) -> str:
        return f"{src}: {line.strip()[:240]}"

    def add(code: str, key: str, item: dict[str, Any]) -> None:
        if (code, key) in seen:
            return
        seen.add((code, key))
        issues.append({"code": code, "fromLog": True, **item})

    def server_mod(m: dict[str, Any], code: str, title: str, src: str, line: str, pick: bool) -> None:
        add(code, m["file"], {"title": title, "fix": "removeServer", "id": m.get("id"), "name": m.get("name") or m["file"],
                              "serverFile": m["file"], "version": m.get("version"), "evidence": ev(src, line), "pick": pick})

    def missing(dep: str, depname: str, by: str, src: str, line: str) -> None:
        if dep in idx["id"] or dep in ("minecraft", "java", "fabricloader", "neoforge", "forge"):
            return
        c = cby.get(dep)
        who = f"'{by}' 에 필요" if by else "필요"
        if c:
            add("LOG-201", dep, {"title": f"서버에 필요한 모드가 없음({who}) — 인스턴스에 있어 서버로 복사", "fix": "toServer",
                                 "id": dep, "name": c.get("name") or dep, "clientFile": c["file"], "clientVersion": c.get("version"),
                                 "evidence": ev(src, line), "pick": True})
        else:
            add("LOG-201", dep, {"title": f"서버에 필요한 모드가 없음({who}) — 인스턴스에도 없어 Modrinth 등에서 받아 인스턴스에 넣어 주세요",
                                 "fix": None, "id": dep, "name": depname.strip() or dep, "evidence": ev(src, line), "pick": False})

    for i, (src, line) in enumerate(lines):
        m = MISSING_FABRIC.search(line)
        if m:
            missing(m.group("dep"), m.group("depname"), m.group("name"), src, line)
            continue
        m = MISSING_NEO.search(line)
        if m:
            missing(m.group("dep"), "", m.group("id"), src, line)
            continue
        if CLIENT_CLASS.search(line):
            client_error = True
            # 이 줄 뒤(최대 200줄)의 스택: NeoForge·Forge 는 "TRANSFORMER/<모드id>@버전/" 로 모드 id 가, 그 밖은 Mixin 설정·패키지로 jar 를 찾는다
            for _, near in lines[max(0, i - 5): i + 200]:
                hit = None
                km = STACK_MOD.search(near)
                if km and km.group("mod") not in NOT_MODS:
                    hit = idx["id"].get(km.group("mod"))
                mm = MIXIN_CFG.search(near)
                if not hit and mm:
                    hit = idx["mixin"].get(mm.group("cfg"))
                sm = STACK.search(near)
                if not hit and sm and not sm.group("cls").startswith(("net.minecraft.", "com.mojang.", "java.", "jdk.", "sun.", "net.neoforged.", "net.minecraftforge.", "cpw.", "org.spongepowered.")):
                    parts = sm.group("cls").split(".")
                    hit = idx["pkg"].get(".".join(parts[:3]))
                if hit:
                    server_mod(hit, "LOG-104", "서버에서 클라이언트 전용 코드를 불러 서버가 멈춤 — 서버에서 빼기", src, line, True)
                    break
            continue
        sus = SUSPECTED.search(line)
        if sus:
            for mid in SUSPECTED_ITEM.findall(sus.group("list")):
                hit = idx["id"].get(mid)
                if hit and mid not in NOT_MODS:
                    suspects.append((hit, src, line))
            continue
        for rx, key in ((MOD_FILE, "file"), (FAILURE, "id"), (MOD_SECTION, "id"), (FROM_MOD, "id"), (MIXIN_CFG, "mixin")):
            mm = rx.search(line)
            if mm:
                hit = idx[key].get(mm.group(1) if key == "file" else mm.group("cfg") if key == "mixin" else mm.group("id"))
                if hit:
                    server_mod(hit, "LOG-301", "오류 기록에 이름이 나온 모드(원인일 수 있음) — 빼 보고 다시 시작", src, line, False)
                break
    # 크래시 리포트가 지목한 모드: 클라이언트 코드 오류와 함께면 거의 확실(기본으로 고름)
    for hit, src, line in suspects:
        server_mod(hit, "LOG-302", "크래시 리포트가 지목한 모드(Suspected Mods)" + (" — 클라이언트 전용 코드 오류와 함께" if client_error else ""),
                   src, line, client_error)
    return issues


# ---------------------------------------------------------------- Modrinth 로 클라이언트 전용 모드 찾기
SIDES_CACHE = ".studio-modrinth-sides.json"


def modrinth_client_only(server_dir: Path, server_mods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """서버 mods/ 의 jar 를 해시로 Modrinth 에서 찾아, 프로젝트가 '서버: 지원 안 함'(server_side=unsupported)인 것 = MOD-108.
    jar 정보(fabric.mod.json·mods.toml)에 클라이언트 전용 표시가 없는 모드도 잡는다. 결과는 해시별로 서버 폴더에 저장(다시 묻지 않음).
    인터넷이 안 되면 빈 목록."""
    import json

    import modrinth
    from net import file_hashes
    mods_dir = server_dir / "mods"
    cache_file = server_dir / SIDES_CACHE
    try:
        cache: dict[str, Any] = json.loads(cache_file.read_text("utf-8"))
    except (OSError, ValueError):
        cache = {}
    hashes: dict[str, dict[str, Any]] = {}
    for m in server_mods:
        try:
            hashes[file_hashes(mods_dir / m["file"], ("sha512",))["sha512"]] = m
        except OSError:
            continue
    todo = [h for h in hashes if h not in cache]
    if todo:
        try:
            found = modrinth.get_json("/version_files", body={"hashes": todo, "algorithm": "sha512"}) or {}
            pids = sorted({v.get("project_id") for v in found.values() if v.get("project_id")})
            projects = {}
            for i in range(0, len(pids), 100):
                for pr in modrinth.get_json("/projects", params={"ids": json.dumps(pids[i:i + 100])}) or []:
                    projects[pr["id"]] = pr
            for h in todo:
                v = found.get(h)
                pr = projects.get(v.get("project_id")) if v else None
                cache[h] = {"title": pr.get("title"), "server_side": pr.get("server_side"), "client_side": pr.get("client_side")} if pr else {}
            cache_file.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
        except Exception:  # noqa: BLE001 - 인터넷이 안 되면 이 검사만 건너뜀
            pass
    out = []
    for h, m in hashes.items():
        info = cache.get(h) or {}
        if info.get("server_side") == "unsupported":
            out.append({"code": "MOD-108", "title": "Modrinth 에 클라이언트 전용(서버 지원 안 함)으로 등록된 모드 — 서버에서 빼기",
                        "fix": "removeServer", "id": m.get("id"), "name": info.get("title") or m.get("name") or m["file"],
                        "serverFile": m["file"], "version": m.get("version"), "pick": True,
                        "evidence": f"Modrinth: {info.get('title')} — 서버: 지원 안 함(server_side=unsupported)"})
    return out
