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
PENDING_DELETE = "instance.deleted.json"   # 지우려 했는데 폴더가 쓰는 중이었음 → 다음 시작 때 휴지통으로
WORK_MODES = ("datapack", "mod", "resourcepack", "plugin")

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
        # Prism 인스턴스 만들기(main.py 가 연결). 있으면 새 인스턴스 = Prism 인스턴스(게임 폴더는 Prism 쪽),
        # 없으면(시험 등) 예전처럼 앱 폴더 안에 만든다. (name, version, loader, loader_version) → {folder, root}
        self.make_prism_instance: Any = None
        # Prism 인스턴스를 휴지통으로(지우기). (폴더) → None
        self.remove_prism_instance: Any = None

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
               group: str | None = None, icon: str | None = None, cc_enabled: bool | None = None,
               prism: bool = True) -> dict[str, Any]:
        """새 인스턴스. Prism 연동이면(make_prism_instance) Prism 인스턴스로 만든다. prism=False 는 이미 있는
        다른 런처 인스턴스를 "연결"할 때(앱 쪽 정보만 만들고 게임 폴더는 원래 것)."""
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

        prism_info = None
        if self.make_prism_instance and prism:
            # 먼저 Prism 인스턴스(없으면 여기서 [prism-missing] 오류 → 프런트가 Prism 설치를 권함)
            prism_info = self.make_prism_instance(name, version, loader, loader_version if loader != "vanilla" else None)

        inst_id = "inst_" + secrets.token_hex(4)
        while (self.root / inst_id).exists():
            inst_id = "inst_" + secrets.token_hex(4)
        d = safe_join(self.root, inst_id)
        d.mkdir(parents=True)
        game = Path(prism_info["folder"]) / "minecraft" if prism_info else d
        for sub in ("datapacks", "mods", "resourcepacks", "saves", "config"):
            (game / sub).mkdir(parents=True, exist_ok=True)

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
        if prism_info:
            folder = Path(prism_info["folder"]).resolve()
            meta.update({
                "linkedDir": str(game.resolve()), "sourceDir": str(folder),
                "launchVia": {"kind": "prism", "root": prism_info.get("root"), "instance": folder.name},
                "launchKind": "prism", "installed": True,     # 게임·로더 파일은 Prism 이 실행할 때 받는다
                "managed": True,                               # 통합 작업실이 만든 Prism 인스턴스(설정 동기화 대상)
                "importedFrom": f"prism:{folder}", "importedLauncher": "prism",
            })
        (d / "instance.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        if prism_info and group:
            import prism
            prism.set_group(folder.parent, folder.name, group)
        write_cc_config(game, port)
        write_instance_claude_md(game, meta)
        write_work_mode(game, meta["workMode"])
        (game / ".gitignore").write_text(INSTANCE_GITIGNORE, "utf-8")
        git_init(game)
        self._changed()
        return self.get(inst_id)

    def rename(self, inst_id: str, name: str) -> dict[str, Any]:
        name = (name or "").strip()
        if not name or len(name) > 64:
            raise RpcError("인스턴스 이름은 1~64자로 해주세요.")
        meta = self.get(inst_id)
        meta["name"] = name
        self.save(meta)
        if _prism_folder(meta):
            import prism   # Prism 목록에서도 같은 이름으로
            prism.rename_instance(_prism_folder(meta), name)
        return self.get(inst_id)

    # ---------- 그룹(폴더) ----------
    @staticmethod
    def clean_group(group: str | None) -> str | None:
        group = (group or "").strip()
        if any(c in group for c in "\r\n\t\x00"):
            raise RpcError("그룹 이름에 줄바꿈·탭을 넣을 수 없습니다.")
        return group[:40] or None

    def set_group(self, inst_id: str, group: str | None) -> dict[str, Any]:
        """인스턴스를 그룹(폴더)에 넣는다. None·빈 값이면 그룹에서 뺀다. Prism 인스턴스면 Prism 그룹(instgroups.json)도 같게."""
        group = self.clean_group(group)
        meta = self.get(inst_id)
        meta["group"] = group
        self.save(meta)
        folder = _prism_folder(meta)
        if folder:
            import prism
            prism.set_group(folder.parent, folder.name, group)
        return self.get(inst_id)

    def rename_group(self, old: str, new: str | None) -> int:
        """그룹 이름 바꾸기(new 가 비면 그룹 풀기 — 인스턴스는 그대로). 바뀐 인스턴스 수."""
        new = self.clean_group(new)
        n = 0
        for m in self.list():
            if m.get("group") == old:
                self.set_group(m["id"], new)
                n += 1
        return n

    def delete(self, inst_id: str) -> None:
        """인스턴스를 휴지통으로. Prism 인스턴스면 Prism 쪽 폴더도 휴지통으로(앱 목록은 Prism 과 자동 연동이라
        목록에서만 빼면 다시 나타난다). 그 밖의 "연결"한 원본 폴더는 건드리지 않는다."""
        d = self.dir_of(inst_id)
        meta = self.get(inst_id)
        if meta.get("launchKind") == "prism" and meta.get("sourceDir") and self.remove_prism_instance:
            self.remove_prism_instance(Path(meta["sourceDir"]))
        try:
            trash(d, self.root)
        except OSError:
            # Windows: 다른 프로그램(탐색기·작업 공간 감시·게임)이 폴더를 잡고 있으면 옮기지 못한다(WinError 32).
            # 목록에서는 바로 빼고(instance.json 이름 바꿈), 휴지통 옮기기는 다음에 앱을 켤 때 다시 한다.
            (d / "instance.json").replace(d / PENDING_DELETE)
        self._changed()

    def forget(self, inst_id: str) -> None:
        """앱 목록에서만 뺀다(앱 쪽 정보 폴더만 휴지통으로). Prism 에서 이미 지운 인스턴스 등."""
        d = self.dir_of(inst_id)
        try:
            trash(d, self.root)
        except OSError:
            (d / "instance.json").replace(d / PENDING_DELETE)
        self._changed()

    def discard(self, inst_id: str) -> None:
        """반쯤 만들어진(가져오기 실패) 인스턴스를 버린다: Prism 쪽 폴더도 휴지통으로, 목록에서 바로 빼고(이름 바꿈) 앱 폴더도 휴지통으로."""
        d = self.dir_of(inst_id)
        meta = self.get(inst_id)
        if meta.get("launchKind") == "prism" and meta.get("managed") and meta.get("sourceDir") and self.remove_prism_instance:
            try:
                self.remove_prism_instance(Path(meta["sourceDir"]))
            except Exception:  # noqa: BLE001 - 못 지워도 목록에서는 뺀다
                pass
        try:
            (d / "instance.json").replace(d / "instance.import-failed.json")
        except OSError:
            pass
        try:
            trash(d, self.root)
        except OSError:
            pass
        self._changed()

    def purge_pending(self) -> int:
        """지난번에 쓰는 중이라 못 지운 인스턴스 폴더를 휴지통으로(시작할 때)."""
        n = 0
        for d in self.root.glob("inst_*"):
            if (d / PENDING_DELETE).is_file() and not (d / "instance.json").exists():
                try:
                    trash(d, self.root)
                    n += 1
                except OSError:
                    pass
        return n

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
        from importers import launchfile
        from importers.launchers import is_account_file   # 계정·토큰 파일은 복사하지 않는다

        def skip(_d: str, names: list[str]) -> set[str]:
            return {n for n in names if n == "session.lock" or is_account_file(n)}
        dst = self.game_dir(new["id"])      # Prism 연동이면 새 Prism 인스턴스의 게임 폴더
        for item in src.iterdir():
            if item.name in self.DUPLICATE_SKIP or item.is_symlink() or is_account_file(item.name):
                continue
            if item.name.startswith(launchfile.BASENAME) and item.is_file() and launchfile.is_ours(item):
                continue   # 원래 인스턴스를 켜는 실행 파일 → 복사본엔 맞지 않음
            target = safe_join(dst, item.name)
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True, ignore=skip)
            else:
                shutil.copy2(item, target)
        if src_meta.get("jvmArgs"):
            mx = re.search(r"-Xmx(\d+)M", src_meta["jvmArgs"])
            extra = " ".join(a for a in src_meta["jvmArgs"].split() if not a.startswith("-Xm"))
            self.set_memory(new["id"], int(mx.group(1)) if mx else None, extra)
        return self.get(new["id"])

    def set_memory(self, inst_id: str, memory_mb: int | None = None, java_args: str | None = None) -> dict[str, Any]:
        """최대 메모리 -Xmx + 추가 자바 인자. Prism 인스턴스면 Prism 설정(instance.cfg)에도 쓴다."""
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
        if _prism_folder(meta):
            import prism   # Prism 으로 실행하므로 Prism 인스턴스 설정(instance.cfg)에도 쓴다
            prism.set_memory(_prism_folder(meta), int(memory_mb) if memory_mb else None, " ".join(
                a for a in parts if not re.match(r"-Xm[xs]\d", a)) or None)
        return self.get(inst_id)

    def open_folder(self, inst_id: str, which: str | None = None) -> dict[str, Any]:
        """게임 폴더(which="source" 면 연결한 원래 인스턴스 폴더 = 실행 파일이 있는 곳)를 파일 탐색기로 연다."""
        import os
        import subprocess
        import sys
        meta = self.get(inst_id)
        d = Path(meta.get("sourceDir") or meta["path"]) if which == "source" else Path(meta["path"])
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
        mods = self.game_dir(inst_id, meta) / "mods"
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
        write_work_mode(self.game_dir(inst_id, meta), mode)
        return self.get(inst_id)


# ---------- 인스턴스 안에 쓰는 파일들 ----------

def _prism_folder(meta: dict[str, Any]) -> Path | None:
    """Prism 인스턴스 폴더(instance.cfg 가 있는 곳). Prism 인스턴스가 아니면 None."""
    src = meta.get("sourceDir")
    if meta.get("launchKind") == "prism" and src and (Path(src) / "instance.cfg").is_file():
        return Path(src)
    return None


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
    "plugin": (
        "Paper 플러그인",
        ["Read", "Glob", "Grep", "Edit(plugins-src/**)", "Write(plugins-src/**)", "MultiEdit(plugins-src/**)",
         "Bash(./gradlew build)", "Bash(./gradlew build:*)"],
        "- 수정·생성은 `plugins-src/` 안에서만 한다.\n"
        "- Paper API(`io.papermc.paper:paper-api`)만 쓴다. NMS·리플렉션으로 서버 내부를 건드리지 않는다.\n"
        "- 명령·권한·설정은 `src/main/resources/plugin.yml` 에 적는다. 셸 명령은 `./gradlew build`만 쓸 수 있다.",
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
                "Bash" if mode not in ("mod", "plugin") else "Bash(rm:*)",
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
    import os
    # 입력 없음·창 없음·시간 제한·서명/후크/프롬프트 끔 — 사용자 git 설정(서명 요구 등) 때문에 멈추지 않게
    kw = dict(cwd=d, check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=20,
              env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        subprocess.run(["git", "init", "-q"], **kw)
        subprocess.run(["git", "add", "-A"], **kw)
        subprocess.run(
            ["git", "-c", "user.name=통합 작업실", "-c", "user.email=studio@localhost", "-c", "commit.gpgsign=false",
             "commit", "-q", "--no-verify", "-m", "인스턴스 생성"], **kw)
    except (OSError, subprocess.SubprocessError):
        pass  # git이 없거나 멈춰도 인스턴스는 쓸 수 있다
