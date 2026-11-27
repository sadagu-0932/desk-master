"""통합 작업실 사이드카: Theia 백엔드가 자식 프로세스로 띄우고 stdin/stdout JSON-RPC로 통신한다.

사용: python main.py --data <data 폴더>
"""
from __future__ import annotations

import argparse
import atexit
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import memory  # noqa: E402
from paths import trash  # noqa: E402
from instances import InstanceStore  # noqa: E402
from packs import Packs  # noqa: E402
from importers import Importers  # noqa: E402
import prism  # noqa: E402
from game_log import Confirmer, GameLogs  # noqa: E402
from prism_sync import PrismSync, migrate as prism_migrate, migrate_candidates  # noqa: E402
from sync import SettingsSync  # noqa: E402
from rpc import notify, serve  # noqa: E402
from runner import Runner  # noqa: E402
from importers.local import LocalImporter  # noqa: E402
from e4mc_host import E4mcHost  # noqa: E402
from server_runner import ServerRunner  # noqa: E402

VERSION = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    import rpc as _rpc
    _rpc.ERROR_LOG = str(data_dir / "logs" / "sidecar-errors.log")   # 오류 전체 기록(원인 찾기용)
    store = InstanceStore(data_dir)
    store.on_change = lambda: notify("instances_changed", {})
    try:
        store.purge_pending()   # 지난번에 쓰는 중이라 못 지운 폴더 정리
    except Exception as e:  # noqa: BLE001
        print(f"[store] 지우기 정리 실패: {e}", file=sys.stderr)   # 만들기·불러오기·삭제 즉시 목록에 반영
    runner = Runner(data_dir, store)
    atexit.register(runner.shutdown)
    packs = Packs(store, runner.mc_dir)
    imp = Importers(store, data_dir)
    # M10 서버 열기 — 방식 A 전용 서버, e4mc(방식 B 를 인터넷 주소로), 다른 런처 인스턴스 불러오기
    servers = ServerRunner(data_dir, store, lambda version: [runner._runtime_java(version)])
    atexit.register(servers.shutdown)
    # 런처 부분은 Prism(사용자 결정 2026-11-27): 새 인스턴스 = Prism 인스턴스, 실행 = prismlauncher --launch
    def make_prism_instance(name: str, version: str, loader: str, loader_version: str | None) -> dict:
        info = prism.require()
        folder = prism.create_instance(Path(info["instanceDir"]), name, version, loader, loader_version)
        return {"folder": str(folder), "root": info["root"]}

    def remove_prism_instance(folder: Path) -> None:
        if folder.is_dir() and (folder / "instance.cfg").is_file():
            trash(folder, folder.parent)

    store.make_prism_instance = make_prism_instance
    store.remove_prism_instance = remove_prism_instance
    confirmer = Confirmer()
    games = GameLogs(store)               # Prism 으로 켠 게임의 로그·실행 상태
    atexit.register(games.shutdown)
    e4mc = E4mcHost(store)
    local_import = LocalImporter(store)
    try:
        local_import.migrate_linked()
    except Exception as e:  # noqa: BLE001
        print(f"[import] 연결 인스턴스 정리 실패: {e}", file=sys.stderr)
    prism_sync = PrismSync(store, local_import)
    atexit.register(prism_sync.shutdown)
    # 설정 동기화(게임 설정·서버 목록, 통합 작업실이 만든 인스턴스끼리): 시작 때·30초마다·게임이 닫힌 뒤
    settings_sync = SettingsSync(store, data_dir, running=games.running_games)
    games.on_game_stopped = lambda _id: settings_sync.later()
    atexit.register(settings_sync.shutdown)

    def rename_instance(id: str, name: str):
        return store.rename(id, name)

    def delete_instance(id: str):
        local_import.remove_launch_file(id)   # 원래 폴더에 만든 실행 파일
        games.tail_stop(id)                   # 로그 따라 읽기를 먼저 멈춘다(폴더를 잡고 있지 않게)
        return store.delete(id)               # Prism 인스턴스면 Prism 쪽 폴더도 휴지통으로

    def prism_install(id: str = ""):
        return prism.install(confirmer.callback(id), lambda line: notify(
            "log", {"id": id, "line": line, "level": "info", "source": "studio"}))

    def prism_open():
        info = prism.require()
        prism.open_prism(info["exe"], info["root"])
        return {"ok": True}

    handlers = {
        "ping": lambda: {"version": VERSION, "data": str(data_dir)},
        "list_instances": store.list,
        "get_instance": lambda id: store.get(id),
        "create_instance": store.create,
        "rename_instance": rename_instance,
        "delete_instance": delete_instance,
        "set_cc_enabled": lambda id, enabled: store.set_cc_enabled(id, enabled),
        "duplicate_instance": lambda id, name=None: store.duplicate(id, name),
        "set_instance_memory": lambda id, memory_mb=None, java_args=None: store.set_memory(id, memory_mb, java_args),
        # 그룹(폴더): Prism 그룹(instgroups.json)과 같게
        "set_instance_group": lambda id, group=None: store.set_group(id, group),
        "rename_group": lambda old, new=None: store.rename_group(old, new),
        "open_instance_folder": lambda id, which=None: store.open_folder(id, which),
        "set_work_mode": lambda id, mode: store.set_work_mode(id, mode),
        "list_versions": runner.list_versions,
        "list_loader_versions": runner.list_loader_versions,
        # 게임 실행은 Prism 으로(launch_linked). 앱에는 게임을 설치하지 않는다
        "running": lambda: {"game": games.running_games(), "server": runner.running()["server"]},
        "game_tail_log": lambda id, from_start=False: games.tail_log(id, from_start),
        "game_tail_stop": lambda id: games.tail_stop(id),
        "confirm_reply": lambda token, ok: confirmer.reply(token, ok),
        "prism_status": prism.find,
        "prism_install": prism_install,
        "prism_open": prism_open,
        "prism_sync": lambda: prism_sync.sync(force=True),
        # 예전 인스턴스(앱 폴더·공식 런처·CurseForge 등) → Prism 인스턴스로 옮기기(프런트가 먼저 확인)
        "prism_migrate_candidates": lambda: migrate_candidates(store),
        "prism_migrate": lambda ids: (prism.require(), prism_migrate(store, local_import, ids, lambda i, t: notify(
            "progress", {"id": i, "stage": "migrate", "text": t, "done": not t})))[1],
        "server_start": runner.server_start,
        "server_stop": runner.server_stop,
        "server_command": runner.server_command,
        "generate_reports": runner.generate_reports,
        "read_commands": packs.read_commands,
        "pack_formats": packs.pack_formats,
        "list_worlds": packs.list_worlds,
        "list_datapacks": packs.list_datapacks,
        "datapack_new": packs.datapack_new,
        "datapack_sync": packs.datapack_sync,
        "datapack_zip": packs.datapack_zip,
        "list_resourcepacks": packs.list_resourcepacks,
        "resourcepack_new": packs.resourcepack_new,
        "resourcepack_import": packs.resourcepack_import,
        "resourcepack_apply": packs.resourcepack_apply,
        "list_mod_projects": packs.list_mod_projects,
        # Paper 플러그인: 템플릿 → ./gradlew build → 그 인스턴스의 Paper 서버 plugins/ 에 넣고 켜져 있으면 다시 시작
        "plugin_new": packs.plugin_new,
        "list_plugin_projects": packs.list_plugin_projects,
        "plugin_build": lambda id, name: (lambda jar: {"jar": str(jar), **servers.install_plugin(id, jar)})(packs.plugin_build(id, name)),
        "mod_new": packs.mod_new,
        "mod_build": packs.mod_build,
        "open_external": packs.open_external,
        "inspect_import": imp.inspect_import,
        "import_file": imp.import_file,
        "modrinth_search": imp.modrinth_search,
        "modrinth_versions": imp.modrinth_versions,
        "modrinth_install_modpack": imp.modrinth_install_modpack,
        "modrinth_add_mod": imp.modrinth_add_mod,
        "cf_key_status": imp.cf_key_status,
        "cf_set_key": imp.cf_set_key,
        "cf_search": imp.cf_search,
        "cf_files": imp.cf_files,
        "cf_install_modpack": imp.cf_install_modpack,
        "cf_add_mod": imp.cf_add_mod,
        "ds_list": servers.list_all,
        "ds_create": servers.create,
        "ds_update": servers.update,
        "ds_set_world": servers.set_world,
        "ds_accept_eula": servers.accept_eula,
        "ds_start": servers.start,
        "ds_stop": servers.stop,
        "ds_command": servers.command,
        "ds_delete": servers.delete,
        "ds_running": servers.running,
        "host_mods": servers.mods,
        "e4mc_status": e4mc.status,
        "e4mc_install": e4mc.install,
        "e4mc_disable": e4mc.disable,
        "e4mc_restore_once": e4mc.restore_once,
        "e4mc_check_crash": e4mc.check_crash,
        "import_detect": local_import.detect,
        "import_inspect_folder": local_import.inspect_folder,
        "import_preview": local_import.preview,
        "import_run": local_import.import_many,
        "import_in_use": lambda id: local_import.in_use(id),
        "launch_external": lambda id: local_import.launch_external(id),
        "launch_linked": lambda id: local_import.launch_linked(id),
        "set_launcher_root": lambda id, path: local_import.set_launcher_root(id, path),
        # 메모리: 게임 추천값, 통합 작업실이 쓰는 메모리
        "memory_advice": lambda id: memory.recommend_game_mb(memory.count_mods(store.game_dir(id)),
                                                             store.get(id)["loader"], memory.system_memory_mb()),
        "memory_usage": memory.usage,
        "sync_now": settings_sync.sync_now,
    }
    background = {"create_instance", "duplicate_instance", "list_versions", "list_loader_versions", "server_start", "server_stop", "generate_reports", "mod_new", "mod_build", "plugin_new", "plugin_build", "read_commands", "inspect_import", "import_file",
                  "modrinth_search", "modrinth_versions", "modrinth_install_modpack", "modrinth_add_mod",
                  "cf_key_status", "cf_set_key", "cf_search", "cf_files", "cf_install_modpack", "cf_add_mod"} | {"prism_install", "prism_sync", "prism_migrate", "launch_linked"} | {"ds_create", "ds_set_world", "ds_start", "ds_stop", "host_mods", "e4mc_install", "e4mc_check_crash",
                     "import_detect", "import_inspect_folder", "import_preview", "import_run", "import_in_use"} | {"sync_now", "delete_instance", "memory_usage"}
    notify("ready", {"version": VERSION})
    settings_sync.start()
    prism_sync.start()      # Prism 인스턴스 폴더를 몇 초마다 확인해 목록을 맞춘다
    serve(handlers, background)


if __name__ == "__main__":
    main()
