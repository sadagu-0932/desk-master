"""적용: 바뀐 파일 종류를 보고 게임에 넣는 방법을 고르고, 적용 뒤 게임 로그의 오류를 모은다.

상태는 반드시 넷 중 하나: "바로 적용됨" / "월드 재접속 필요" / "재시작 필요" / "오류".

게임에 명령을 보내는 길(/reload, 리소스 다시 불러오기, /datapack enable, 재접속)은 GameBridge 를 거친다.
기본 FileBridge 는 <인스턴스>/.studio/bridge/ 에 요청 파일을 쓰고 앱(통합 작업실)이 CommandCrafter 로 처리해
응답 파일을 쓰기를 기다린다. 앱이 응답하지 않으면 사람이 할 일을 안내한다(가짜로 '적용됨'이라 하지 않는다).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .context import Instance, ToolError, inside, trash
from .reports import VersionData
from .validate import validate_datapack, validate_mod, validate_resourcepack

OK, REJOIN, RESTART, ERROR = "바로 적용됨", "월드 재접속 필요", "재시작 필요", "오류"
_RANK = {OK: 0, REJOIN: 1, RESTART: 2, ERROR: 3}
BACKUP_KEEP = 10

START_MARKERS = ("Setting user:", "Loading Minecraft")
STOP_MARKERS = ("Stopping!", "Game crashed!")
LOG_ERROR_RE = re.compile(
    r"(/ERROR\]|/FATAL\]|Failed to load function|Couldn't load|Couldn't parse|Failed to parse|"
    r"JsonParseException|JsonSyntaxException|Unknown or incomplete command|Exception|Game crashed|"
    r"Failed to reload|Missing reference|Unknown registry|Unknown element)")
LOG_IGNORE_RE = re.compile(r"(is already enabled|Narrator library|OpenAL|Failed to fetch user properties)")


# ================================================================ 게임 연결
class GameBridge(Protocol):
    def request(self, action: str, **params: Any) -> dict[str, Any]: ...


class FileBridge:
    """<인스턴스>/.studio/bridge/requests/<id>.json 을 쓰고 responses/<id>.json 을 기다린다.

    요청: {"id", "action": "reload"|"reload_resources"|"run_command"|"rejoin_world"|"restart_game", "params": {...}}
    응답: {"id", "ok": bool, "message": str}
    앱이 처리: reload → commandcrafter.reload / reload_resources → commandcrafter.reloadResources /
              run_command → commandcrafter.runCommand(params.command) / rejoin_world·restart_game → 사용자에게 안내 후 처리
    """

    def __init__(self, inst: Instance, timeout: float = 8.0):
        self.dir = inst.studio_dir / "bridge"
        self.timeout = timeout

    def request(self, action: str, **params: Any) -> dict[str, Any]:
        rid = uuid.uuid4().hex
        req_dir, res_dir = self.dir / "requests", self.dir / "responses"
        req_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)
        req = req_dir / f"{rid}.json"
        tmp = req.with_suffix(".tmp")
        tmp.write_text(json.dumps({"id": rid, "action": action, "params": params, "time": time.time()},
                                  ensure_ascii=False), "utf-8")
        os.replace(tmp, req)
        res = res_dir / f"{rid}.json"
        end = time.time() + self.timeout
        while time.time() < end:
            if res.is_file():
                try:
                    data = json.loads(res.read_text("utf-8"))
                    res.unlink(missing_ok=True)
                    return {"ok": bool(data.get("ok")), "message": data.get("message", ""), "bridge": True}
                except (OSError, ValueError):
                    pass
            time.sleep(0.2)
        req.unlink(missing_ok=True)  # 처리되지 않은 요청은 남기지 않는다
        return {"ok": False, "bridge": False, "message": "앱이 응답하지 않았습니다(게임 연결 없음)"}


# ================================================================ 게임 상태·로그
def latest_log(inst: Instance) -> Path:
    return inst.dir / "logs" / "latest.log"


def game_running(inst: Instance) -> bool:
    """latest.log 로 판단한다(공식 런처가 켠 게임이라 우리 프로세스가 아니다)."""
    log = latest_log(inst)
    if not log.is_file():
        return False
    try:
        text = log.read_text("utf-8", errors="replace")
    except OSError:
        return False
    start = max((text.rfind(m) for m in START_MARKERS), default=-1)
    stop = max((text.rfind(m) for m in STOP_MARKERS), default=-1)
    return start >= 0 and start > stop


def log_offset(inst: Instance) -> int:
    log = latest_log(inst)
    return log.stat().st_size if log.is_file() else 0


def log_errors_since(inst: Instance, offset: int, limit: int = 40) -> list[str]:
    log = latest_log(inst)
    if not log.is_file():
        return []
    size = log.stat().st_size
    if size < offset:
        offset = 0  # 로그가 새로 시작됨
    with log.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read().decode("utf-8", "replace")
    out = []
    lines = chunk.splitlines()
    for ln in lines:
        if LOG_ERROR_RE.search(ln) and not LOG_IGNORE_RE.search(ln) and not ln.startswith("\tat "):
            out.append(ln.strip()[:300])
            if len(out) >= limit:
                break
    return out


# ================================================================ 결과
@dataclass
class ApplyResult:
    status: str = OK
    actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)          # 검사 오류·빌드 오류(고쳐야 함)
    log_errors: list[str] = field(default_factory=list)      # 적용 뒤 게임 로그 오류(고쳐야 함)
    needs_confirmation: list[dict[str, str]] = field(default_factory=list)
    bridge_missing: bool = False                              # 앱 연결이 없어 사람이 해야 할 일이 남음

    def worst(self, status: str) -> None:
        if _RANK[status] > _RANK[self.status]:
            self.status = status

    def blocking(self) -> bool:
        """Claude 가 더 고쳐야 하는 오류가 남았는지(앱 연결 없음은 고칠 거리가 아니다)."""
        return bool(self.errors or self.log_errors)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "actions": self.actions, "notes": self.notes, "errors": self.errors,
                "log_errors": self.log_errors, "needs_confirmation": self.needs_confirmation,
                "bridge_missing": self.bridge_missing, "blocking": self.blocking()}


# ================================================================ 분류
def classify_paths(inst: Instance, changed: list[str]) -> dict[str, Any]:
    groups: dict[str, Any] = {"datapacks": {}, "resourcepacks": set(), "mods": set(), "world_datapacks": {}, "other": []}
    for raw in changed:
        p = inside(inst.dir, raw)
        rel = p.relative_to(inst.dir).parts
        if len(rel) >= 2 and rel[0] == "datapacks":
            groups["datapacks"].setdefault(rel[1], []).append(rel[2:])
        elif len(rel) >= 2 and rel[0] == "resourcepacks":
            groups["resourcepacks"].add(rel[1])
        elif len(rel) >= 2 and rel[0] == "mods-src":
            groups["mods"].add(rel[1])
        elif len(rel) >= 5 and rel[0] == "saves" and rel[2] == "datapacks":
            groups["world_datapacks"].setdefault((rel[1], rel[3]), []).append(rel[4:])
        else:
            groups["other"].append("/".join(rel))
    return groups


def datapack_kinds(vd: VersionData, rels: list[tuple[str, ...]]) -> set[str]:
    kinds = set()
    for rel in rels:
        if not rel:
            continue
        if rel[0] == "pack.mcmeta":
            kinds.add("pack.mcmeta")
        elif rel[0] == "data" and len(rel) >= 3:
            kinds.add(vd.kind_of_path(tuple(rel[2:])))
    return kinds


def pick_world(inst: Instance, world: str | None) -> str | None:
    saves = inst.dir / "saves"
    if world:
        d = inside(saves, world) if saves.is_dir() else None
        if not d or not (d / "level.dat").is_file():
            raise ToolError(f"월드를 찾을 수 없습니다: {world}")
        return world
    sel = inst.studio_dir / "selected_world"
    if sel.is_file():
        name = sel.read_text("utf-8").strip()
        if name and (saves / name / "level.dat").is_file():
            return name
    if not saves.is_dir():
        return None
    worlds = [d for d in saves.iterdir() if (d / "level.dat").is_file()]
    if not worlds:
        return None
    return max(worlds, key=lambda d: (d / "level.dat").stat().st_mtime).name


# ================================================================ 동기화·백업
def backup_world_datapacks(inst: Instance, world: str) -> Path | None:
    src = inst.dir / "saves" / world / "datapacks"
    if not src.is_dir() or not any(src.iterdir()):
        return None
    bdir = inst.studio_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = bdir / f"{world}-datapacks-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(src).as_posix())
    olds = sorted(bdir.glob(f"{world}-datapacks-*.zip"))
    for old in olds[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)  # 우리가 만든 백업 파일 정리(사용자 파일 아님)
    return out


def sync_dir(inst: Instance, src: Path, dst: Path) -> dict[str, int]:
    """src 를 기준으로 dst 를 맞춘다. 바뀐 파일만 복사하고, src 에 없는 파일은 휴지통으로."""
    copied = removed = 0
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if ".git" in f.relative_to(src).parts:
            continue
        t = dst / f.relative_to(src)
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
        elif not t.is_file() or t.read_bytes() != f.read_bytes():
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)
            copied += 1
    for t in sorted(dst.rglob("*"), reverse=True):
        if not (src / t.relative_to(dst)).exists():
            trash(t, inst.dir)
            removed += 1
    return {"copied": copied, "removed": removed}


def enable_resourcepack(inst: Instance, pack: str) -> bool:
    """options.txt 의 resourcePacks 에 file/<팩> 을 넣는다. 이미 있으면 False."""
    opts = inst.dir / "options.txt"
    lines = opts.read_text("utf-8").splitlines() if opts.is_file() else []
    entry = f"file/{pack}"
    for i, ln in enumerate(lines):
        if ln.startswith("resourcePacks:"):
            try:
                packs = json.loads(ln.split(":", 1)[1])
            except ValueError:
                packs = ["vanilla"]
            if entry in packs:
                return False
            packs.append(entry)
            lines[i] = "resourcePacks:" + json.dumps(packs)
            break
    else:
        lines.append("resourcePacks:" + json.dumps(["vanilla", entry]))
    opts.write_text("\n".join(lines) + "\n", "utf-8")
    return True


# ================================================================ 모드 빌드
COMPILE_ERR_RE = re.compile(r"^(.+\.java):(\d+): error: (.+)$")


def build_mod(inst: Instance, project: Path, run=subprocess.run) -> dict[str, Any]:
    """./gradlew build 를 돌리고 컴파일 오류만 추린다. 성공하면 jar 경로."""
    root = inside(inst.dir, project)
    if not (root / "build.gradle").is_file() and not (root / "build.gradle.kts").is_file():
        raise ToolError(f"모드 프로젝트가 아닙니다(build.gradle 없음): {root.name}")
    win = sys.platform == "win32"
    cmd = [str(root / ("gradlew.bat" if win else "gradlew")), "build", "--console=plain", "-q"]
    try:
        out = run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as e:
        raise ToolError(f"gradlew 를 실행하지 못했습니다: {e}") from e
    text = (out.stdout or "") + "\n" + (out.stderr or "")
    errors = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = COMPILE_ERR_RE.match(ln.strip())
        if m:
            path = m.group(1)
            try:
                path = Path(path).resolve().relative_to(root).as_posix()
            except ValueError:
                pass
            code = lines[i + 1].strip() if i + 1 < len(lines) else ""
            errors.append(f"{path}:{m.group(2)}: {m.group(3)}" + (f"  ← {code}" if code else ""))
    if out.returncode != 0:
        if not errors:
            tail = [ln for ln in lines if ln.strip()][-15:]
            errors = ["빌드 실패(컴파일 오류가 아닌 문제): " + " | ".join(tail)]
            if "JAVA_HOME" in text or "Unsupported class file" in text or "release version" in text:
                errors.append("JDK 25 가 설치돼 있고 JAVA_HOME 이 그 JDK 를 가리켜야 합니다.")
        return {"ok": False, "errors": errors}
    libs = root / "build" / "libs"
    jars = [j for j in libs.glob("*.jar") if not j.name.endswith(("-sources.jar", "-dev.jar"))] if libs.is_dir() else []
    if not jars:
        return {"ok": False, "errors": ["빌드는 끝났지만 build/libs 에 jar 가 없습니다."]}
    return {"ok": True, "jar": str(max(jars, key=lambda j: j.stat().st_mtime)), "errors": []}


def install_mod_jar(inst: Instance, jar: Path, mod_id: str) -> Path:
    mods = inst.dir / "mods"
    mods.mkdir(exist_ok=True)
    for old in mods.glob(f"{mod_id}-*.jar"):
        if old.name != jar.name:
            trash(old, inst.dir)
    dest = mods / jar.name
    shutil.copy2(jar, dest)
    return dest


# ================================================================ 적용
def apply_changes(inst: Instance, vd: VersionData, changed_paths: list[str], *, world: str | None = None,
                  confirm: bool = False, bridge: GameBridge | None = None, settle: float = 3.0,
                  builder=build_mod) -> ApplyResult:
    bridge = bridge or FileBridge(inst)
    res = ApplyResult()
    groups = classify_paths(inst, changed_paths)
    running = game_running(inst)
    offset = log_offset(inst)
    did_game_action = False

    def ask(action: str, why: str) -> bool:
        """게임 상태를 바꾸는 일은 사용자 확인을 거친다(confirm=True 로 다시 부르면 실행)."""
        if confirm:
            return True
        res.needs_confirmation.append({"action": action, "why": why})
        return False

    def send(action: str, manual: str, **params: Any) -> bool:
        nonlocal did_game_action
        r = bridge.request(action, **params)
        if r.get("ok"):
            did_game_action = True
            res.actions.append(f"{action}: {r.get('message') or '완료'}")
            return True
        if not r.get("bridge", True):
            res.bridge_missing = True
            res.notes.append(f"앱 연결이 없어 자동으로 하지 못했습니다 — {manual}")
        else:
            res.errors.append(f"{action} 실패: {r.get('message')}")
        return False

    # ---------- 데이터팩 ----------
    if groups["datapacks"]:
        target = pick_world(inst, world)
        for pack, rels in sorted(groups["datapacks"].items()):
            src = inst.dir / "datapacks" / pack
            if not src.is_dir():
                res.notes.append(f"datapacks/{pack} 가 없어 건너뜀")
                continue
            rep = validate_datapack(vd, src)
            if not rep.ok:
                res.errors += [p.text() for p in rep.errors]
                res.worst(ERROR)
                continue
            kinds = datapack_kinds(vd, rels)
            world_kinds = sorted(k for k in kinds if vd.needs_world_reload(k))
            if target is None:
                res.notes.append(f"{pack}: 적용할 월드가 없습니다. 월드를 만든 뒤 다시 apply_changes 를 부르세요.")
                res.worst(REJOIN)
                continue
            dst = inst.dir / "saves" / target / "datapacks" / pack
            new_pack = not dst.exists()
            b = backup_world_datapacks(inst, target)
            if b:
                res.actions.append(f"백업: {b.relative_to(inst.dir).as_posix()}")
            st = sync_dir(inst, src, dst)
            res.actions.append(f"동기화: datapacks/{pack} → saves/{target}/datapacks/{pack} (복사 {st['copied']}, 휴지통 {st['removed']})")
            if not running:
                res.notes.append(f"{pack}: 게임이 꺼져 있습니다. 월드 '{target}' 을(를) 열면 적용됩니다.")
                continue
            if world_kinds:
                res.worst(REJOIN)
                res.notes.append(f"{pack}: {', '.join(world_kinds)} 은(는) 월드를 다시 열어야 적용됩니다."
                                 + (" 월드 생성 데이터는 새로 생기는 청크부터 바뀝니다." if any(k.startswith("worldgen") or "biome" in k or k == "dimension" for k in world_kinds) else ""))
                if ask("rejoin_world", f"월드 '{target}' 다시 접속(저장 후 나갔다 들어오기)"):
                    send("rejoin_world", "게임에서 월드를 저장하고 나갔다가 다시 들어가세요.", world=target)
                continue
            send("reload", "게임에서 /reload 를 입력하세요.")
            if new_pack and ask("enable_datapack", f"새 데이터팩 file/{pack} 켜기"):
                send("run_command", f'게임에서 /datapack enable "file/{pack}" 를 입력하세요.',
                     command=f'datapack enable "file/{pack}"')

    for (wname, pack), _ in sorted(groups["world_datapacks"].items()):
        res.notes.append(f"saves/{wname}/datapacks/{pack} 를 직접 고쳤습니다. 원본은 datapacks/{pack} 에 두는 것이 원칙입니다.")
        if running and ask("reload", "/reload"):
            send("reload", "게임에서 /reload 를 입력하세요.")

    # ---------- 리소스팩 ----------
    for pack in sorted(groups["resourcepacks"]):
        root = inst.dir / "resourcepacks" / pack
        if not root.is_dir():
            continue
        rep = validate_resourcepack(vd, root)
        if not rep.ok:
            res.errors += [p.text() for p in rep.errors]
            res.worst(ERROR)
            continue
        newly = enable_resourcepack(inst, pack)
        if newly:
            res.actions.append(f"options.txt 에 file/{pack} 켬")
        if not running:
            res.notes.append(f"{pack}: 게임이 꺼져 있습니다. 다음에 켜면 적용됩니다.")
        elif newly:
            res.worst(RESTART)
            res.notes.append(f"{pack}: 게임이 켜진 동안 새로 켠 리소스팩은 게임을 다시 켜거나 옵션 → 리소스팩에서 켜야 보입니다.")
        else:
            send("reload_resources", "게임에서 F3+T 를 누르세요.")

    # ---------- 모드 ----------
    for mod in sorted(groups["mods"]):
        project = inst.dir / "mods-src" / mod
        rep = validate_mod(vd, project)
        if not rep.ok:
            res.errors += [p.text() for p in rep.errors]
            res.worst(ERROR)
            continue
        b = builder(inst, project)
        if not b["ok"]:
            res.errors += b["errors"]
            res.worst(ERROR)
            continue
        dest = install_mod_jar(inst, Path(b["jar"]), mod)
        res.actions.append(f"빌드 성공 → mods/{dest.name}")
        res.worst(RESTART)
        if running:
            res.notes.append("모드는 게임을 다시 켜야 적용됩니다.")
            if ask("restart_game", "게임 재시작(게임 창을 닫고 공식 런처로 다시 실행)"):
                send("restart_game", "게임 창을 닫고 통합 작업실에서 다시 실행(F5)하세요.")
        else:
            res.notes.append("다음에 게임을 켜면 새 모드로 실행됩니다.")

    if groups["other"]:
        res.notes.append("적용 대상이 아닌 파일: " + ", ".join(groups["other"][:10]))

    # ---------- 게임 로그 확인 ----------
    if did_game_action and settle > 0:
        time.sleep(settle)
    if running or did_game_action:
        res.log_errors = log_errors_since(inst, offset)
        if res.log_errors:
            res.worst(ERROR)
    if res.errors:
        res.worst(ERROR)
    save_last(inst, changed_paths, res)
    return res


def save_last(inst: Instance, changed: list[str], res: ApplyResult) -> None:
    inst.studio_dir.mkdir(parents=True, exist_ok=True)
    data = {"time": time.time(), "changed": changed, **res.to_dict()}
    (inst.studio_dir / "last-apply.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def load_last(inst: Instance) -> dict[str, Any] | None:
    p = inst.studio_dir / "last-apply.json"
    try:
        return json.loads(p.read_text("utf-8")) if p.is_file() else None
    except ValueError:
        return None
