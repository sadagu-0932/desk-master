"""인스턴스 저장소.

data/instances/inst_<짧은 id>/          게임 폴더(--gameDir)
    instance.json                         표시 이름·버전·로더 등 메타데이터
    CLAUDE.md, .claude/                   Claude 작업 규칙
    datapacks/ mods/ resourcepacks/ saves/ config/
표시 이름과 폴더 이름을 분리해서 특수문자 이름도 문제없게 한다.
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from paths import safe_join, trash
from rpc import RpcError

LOADERS = ("vanilla", "fabric", "quilt", "neoforge", "forge")  # quilt·neoforge·forge 는 불러온 인스턴스용
CC_BASE_PORT = 52853
WORK_MODES = ("datapack", "mod", "resourcepack")

INSTANCE_GITIGNORE = """# 통합 작업실이 만든 인스턴스 저장소: 직접 만든 것만 추적한다
logs/
crash-reports/
screenshots/
saves/
server/
*.jar
*.jar.disabled
usercache.json
options.txt
downloads/
exports/
.theia/
.fabric/
instance.json
.claude/.edit-baks/
.claude/settings.local.json
.claude/hooks/
"""


class InstanceStore:
    def __init__(self, data_dir: Path):
        self.root = (data_dir / "instances").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # 인스턴스가 생기거나 바뀌거나 지워지면 부른다(main.py 가 프런트에 instances_changed 알림을 보내게 연결)
        self.on_change: Any = None

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - 알림 실패가 저장을 막으면 안 된다
                pass

    # ---------- 조회 ----------
    def dir_of(self, inst_id: str) -> Path:
        if not re.fullmatch(r"inst_[0-9a-f]{8}", inst_id or ""):
            raise RpcError(f"잘못된 인스턴스 id: {inst_id}")
        d = safe_join(self.root, inst_id)
        if not (d / "instance.json").is_file():
            raise RpcError(f"인스턴스를 찾을 수 없습니다: {inst_id}")
        return d

    def get(self, inst_id: str) -> dict[str, Any]:
        meta = json.loads((self.dir_of(inst_id) / "instance.json").read_text("utf-8"))
        meta["metaDir"] = str(self.dir_of(inst_id))
        meta["path"] = str(self.game_dir(inst_id, meta))
        return meta

    def game_dir(self, inst_id: str, meta: dict[str, Any] | None = None) -> Path:
        """게임 폴더. 보통은 인스턴스 폴더, "연결"로 불러온 인스턴스는 다른 런처의 원본 폴더(linkedDir)."""
        if meta is None:
            meta = json.loads((self.dir_of(inst_id) / "instance.json").read_text("utf-8"))
        linked = meta.get("linkedDir")
        return Path(linked).resolve() if linked else self.dir_of(inst_id)

    def list(self) -> list[dict[str, Any]]:
        result = []
        for d in sorted(self.root.glob("inst_*")):
            if (d / "instance.json").is_file():
                try:
                    result.append(self.get(d.name))
                except (RpcError, json.JSONDecodeError):
                    continue
        result.sort(key=lambda m: m.get("created", 0))
        return result

    def save(self, meta: dict[str, Any]) -> None:
        d = self.dir_of(meta["id"])
        clean = {k: v for k, v in meta.items() if k not in ("path", "metaDir")}
        (d / "instance.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")
        self._changed()

    # ---------- 만들기·지우기 ----------
    def create(self, name: str, version: str, loader: str, loader_version: str | None = None,
               group: str | None = None, icon: str | None = None, cc_enabled: bool | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise RpcError("인스턴스 이름을 입력하세요.")
        if len(name) > 64:
            raise RpcError("인스턴스 이름은 64자 이하로 해주세요.")
        if loader not in LOADERS:
            raise RpcError(f"지원하지 않는 로더입니다: {loader}")
        if not re.fullmatch(r"[0-9A-Za-z._\- ]{1,64}", version or ""):
            raise RpcError(f"잘못된 버전 형식입니다: {version}")
        if loader_version and not re.fullmatch(r"[0-9A-Za-z.+_\-]{1,64}", loader_version):
            raise RpcError(f"잘못된 로더 버전입니다: {loader_version}")
        group = (group or "").strip()[:40] or None
        if icon and not re.fullmatch(r"#[0-9a-fA-F]{6}", icon):
            icon = None

        inst_id = "inst_" + secrets.token_hex(4)
        while (self.root / inst_id).exists():
            inst_id = "inst_" + secrets.token_hex(4)
        d = safe_join(self.root, inst_id)
        d.mkdir(parents=True)
        for sub in ("datapacks", "mods", "resourcepacks", "saves", "config"):
            (d / sub).mkdir()

        used = {m.get("ccPort") for m in self.list()}
        port = CC_BASE_PORT
        while port in used:
            port += 1

        meta = {
            "id": inst_id,
            "name": name,
            "version": version,
            "loader": loader,
            "loaderVersion": loader_version if loader != "vanilla" else None,  # None 이면 설치 때 최신 안정판
            "group": group,
            "icon": icon,
            "versionId": None,       # 설치 후 실제 실행 버전 id (fabric-loader-... 등)
            "installed": False,
            "ccEnabled": loader == "fabric" and (cc_enabled is None or bool(cc_enabled)),
            "ccPort": port,
            "workMode": "datapack",
            "created": time.time(),
        }
        (d / "instance.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        write_cc_config(d, port)
        write_instance_claude_md(d, meta)
        write_work_mode(d, meta["workMode"])
        (d / ".gitignore").write_text(INSTANCE_GITIGNORE, "utf-8")
        git_init(d)
        self._changed()
        return self.get(inst_id)

    def rename(self, inst_id: str, name: str) -> dict[str, Any]:
        name = (name or "").strip()
        if not name or len(name) > 64:
            raise RpcError("인스턴스 이름은 1~64자로 해주세요.")
        meta = self.get(inst_id)
        meta["name"] = name
        self.save(meta)
        return self.get(inst_id)

    def delete(self, inst_id: str) -> None:
        """앱의 인스턴스 폴더만 휴지통으로. "연결"한 인스턴스의 원본 게임 폴더(linkedDir)는 건드리지 않는다."""
        d = self.dir_of(inst_id)
        trash(d, self.root)
        self._changed()

    # 복제할 때 옮기는 게임 항목(로그·크래시·서버·git·설정 파일은 새로)
    DUPLICATE_SKIP = {"instance.json", ".git", "logs", "crash-reports", "servers", "screenshots", ".theia", ".fabric",
                      "CLAUDE.md", ".claude", ".gitignore", "usercache.json", "downloads", "exports"}

    def duplicate(self, inst_id: str, name: str | None = None) -> dict[str, Any]:
        """같은 버전·로더로 새 인스턴스를 만들고 게임 폴더 내용(모드·설정·월드 등)을 복사한다. 연결 인스턴스도 복사본이 된다."""
        import shutil
        src_meta = self.get(inst_id)
        src = Path(src_meta["path"])
        new = self.create((name or f"{src_meta['name']} 복사본")[:64], src_meta["version"], src_meta["loader"],
                          src_meta.get("loaderVersion"), src_meta.get("group"), src_meta.get("icon"),
                          cc_enabled=bool(src_meta.get("ccEnabled")))
        from importers.launchers import is_account_file   # 계정·토큰 파일은 복사하지 않는다

        def skip(_d: str, names: list[str]) -> set[str]:
            return {n for n in names if n == "session.lock" or is_account_file(n)}
        dst = self.dir_of(new["id"])
        for item in src.iterdir():
            if item.name in self.DUPLICATE_SKIP or item.is_symlink() or is_account_file(item.name):
                continue
            target = safe_join(dst, item.name)
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True, ignore=skip)
            else:
                shutil.copy2(item, target)
        meta = self.get(new["id"])
        for key in ("jvmArgs", "versionId", "installed"):
            if src_meta.get(key) is not None:
                meta[key] = src_meta[key]
        self.save(meta)
        return self.get(new["id"])

    def set_memory(self, inst_id: str, memory_mb: int | None = None, java_args: str | None = None) -> dict[str, Any]:
        """공식 런처 항목의 JVM 인자(최대 메모리 -Xmx + 추가 인자)."""
        meta = self.get(inst_id)
        if memory_mb is not None and not (512 <= int(memory_mb) <= 65536):
            raise RpcError("메모리는 512MB ~ 64GB 사이로 정하세요.")
        extra = java_args if java_args is not None else " ".join(
            a for a in (meta.get("jvmArgs") or "").split() if not re.match(r"-Xm[xs]\d", a))
        if re.search(r"[\r\n\x00]", extra or ""):
            raise RpcError("자바 인자에 줄바꿈을 넣을 수 없습니다.")
        parts = [f"-Xmx{int(memory_mb)}M"] if memory_mb else []
        parts += [a for a in (extra or "").split() if not re.match(r"-Xm[xs]\d", a)]
        meta["jvmArgs"] = " ".join(parts) or None
        self.save(meta)
        return self.get(inst_id)

    def open_folder(self, inst_id: str) -> dict[str, Any]:
        """게임 폴더를 파일 탐색기(Windows 탐색기)로 연다."""
        import os
        import subprocess
        import sys
        d = Path(self.get(inst_id)["path"])
        if not d.is_dir():
            raise RpcError(f"폴더가 없습니다: {d}")
        if sys.platform == "win32":
            os.startfile(str(d))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])
        return {"ok": True, "path": str(d)}

    # ---------- 설정 ----------
    def set_cc_enabled(self, inst_id: str, enabled: bool) -> dict[str, Any]:
        meta = self.get(inst_id)
        d = self.dir_of(inst_id)
        mods = d / "mods"
        for f in list(mods.glob("commandcrafter*.jar")) + list(mods.glob("commandcrafter*.jar.disabled")):
            on = f.name.endswith(".jar")
            if enabled and not on:
                f.rename(f.with_name(f.name[: -len(".disabled")]))
            elif not enabled and on:
                f.rename(f.with_name(f.name + ".disabled"))
        meta["ccEnabled"] = bool(enabled)
        self.save(meta)
        return self.get(inst_id)

    def set_work_mode(self, inst_id: str, mode: str) -> dict[str, Any]:
        if mode not in WORK_MODES:
            raise RpcError(f"알 수 없는 작업 종류: {mode}")
        meta = self.get(inst_id)
        meta["workMode"] = mode
        self.save(meta)
        write_work_mode(self.dir_of(inst_id), mode)
        return self.get(inst_id)


# ---------- 인스턴스 안에 쓰는 파일들 ----------

def write_cc_config(d: Path, port: int) -> None:
    """CommandCrafter 모드 설정. 인스턴스마다 다른 포트를 쓴다."""
    cfg = d / "config" / "command_crafter.properties"
    lines: list[str] = []
    if cfg.is_file():
        lines = [l for l in cfg.read_text("utf-8").splitlines() if not l.startswith("services-port=")]
    lines.append(f"services-port={port}")
    cfg.write_text("\n".join(lines) + "\n", "utf-8")


def write_instance_claude_md(d: Path, meta: dict[str, Any]) -> None:
    loader = "Fabric" if meta["loader"] == "fabric" else "바닐라(모드 없음)"
    text = f"""# {meta['name']} — 통합 작업실 인스턴스

이 폴더는 마인크래프트 Java 인스턴스의 게임 폴더(--gameDir)다. 통합 작업실이 만들었다.

- 게임 버전: Java {meta['version']}
- 로더: {loader}
- 대답과 설명은 한국어로 한다.

## 폴더 규칙
- 데이터팩 작업 원본: `datapacks/<팩 이름>/` (`pack.mcmeta` + `data/<네임스페이스>/function/*.mcfunction`)
  - 26.x 폴더 이름은 단수형이다: `function/`, `advancement/`, `loot_table/`, `predicate/`, `recipe/`, `tags/function/`
  - 월드에는 앱이 `saves/<월드>/datapacks/`로 동기화한다. **saves 안을 직접 고치지 않는다.**
- 리소스팩: `resourcepacks/<팩 이름>/` — 바닐라 원본 에셋을 통째로 복사하지 말고 바꾼 파일만 둔다.
- Fabric 모드 소스: `mods-src/<모드 id>/` (빌드 결과 jar는 앱이 `mods/`에 넣는다)
- 작업 종류에 따라 허용 범위가 다르다: `.claude/studio-mode.md`를 따른다.

## 금지
- 작업 범위 폴더 밖 파일 수정 금지(특히 `saves/`, `config/`, `options.txt`, `instance.json`).
- 파일 삭제 금지 — 필요하면 사용자에게 말한다.
- 명령어는 Java {meta['version']} 문법만 쓴다. 확실하지 않으면 추측하지 말고 말한다.

@.claude/studio-mode.md
"""
    (d / "CLAUDE.md").write_text(text, "utf-8")


MODE_TEXT = {
    "datapack": (
        "데이터팩",
        ["Read", "Glob", "Grep", "Edit(datapacks/**)", "Write(datapacks/**)", "MultiEdit(datapacks/**)"],
        "- 수정·생성은 `datapacks/` 안에서만 한다.\n"
        "- 매 틱 함수는 `data/minecraft/tags/function/tick.json`, 로드 함수는 `load.json`에 등록한다.\n"
        "- 변경을 적용하면 앱이 게임에 /reload를 보낸다.",
    ),
    "mod": (
        "Fabric 모드",
        ["Read", "Glob", "Grep", "Edit(mods-src/**)", "Write(mods-src/**)", "MultiEdit(mods-src/**)",
         "Bash(./gradlew build)", "Bash(./gradlew build:*)"],
        "- 수정·생성은 `mods-src/` 안에서만 한다.\n"
        "- 셸 명령은 `./gradlew build`만 쓸 수 있다.\n"
        "- 아이템·블록을 추가하면 16×16 텍스처와 모델 JSON도 함께 만든다.",
    ),
    "resourcepack": (
        "리소스팩",
        ["Read", "Glob", "Grep", "Edit(resourcepacks/**)", "Write(resourcepacks/**)", "MultiEdit(resourcepacks/**)"],
        "- 수정·생성은 `resourcepacks/` 안에서만 한다.\n"
        "- 원본 텍스처를 덮어쓰지 말고 새 파일(Claude 제안 레이어)로 만든다.",
    ),
}


def write_work_mode(d: Path, mode: str) -> None:
    """작업 종류 칩에 따라 허용 도구(.claude/settings.json)와 추가 지시(.claude/studio-mode.md)를 바꾼다."""
    label, allow, rules = MODE_TEXT[mode]
    claude_dir = d / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings = {
        "permissions": {
            "allow": allow,
            "deny": [
                "Bash" if mode != "mod" else "Bash(rm:*)",
                "Edit(saves/**)", "Write(saves/**)",
                "Edit(instance.json)", "Write(instance.json)",
                "WebFetch",
            ],
            "defaultMode": "default",
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), "utf-8")
    (claude_dir / "studio-mode.md").write_text(f"# 지금 작업 종류: {label}\n\n{rules}\n", "utf-8")


def git_init(d: Path) -> None:
    try:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=통합 작업실", "-c", "user.email=studio@localhost",
             "commit", "-q", "-m", "인스턴스 생성"],
            cwd=d, check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pass  # git이 없어도 인스턴스는 쓸 수 있다
