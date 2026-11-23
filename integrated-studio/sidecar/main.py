"""통합 작업실 사이드카: Theia 백엔드가 자식 프로세스로 띄우고 stdin/stdout JSON-RPC로 통신한다.

사용: python main.py --data <data 폴더>
"""
from __future__ import annotations

import argparse
import atexit
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from instances import InstanceStore  # noqa: E402
from packs import Packs  # noqa: E402
from importers import Importers  # noqa: E402
from official_rpc import OfficialLauncherRpc  # noqa: E402
from sync import SettingsSync  # noqa: E402
from rpc import notify, serve  # noqa: E402
from runner import Runner  # noqa: E402
from importers.local import LocalImporter  # noqa: E402
from server_runner import E4mcHost, ServerRunner  # noqa: E402

VERSION = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    store = InstanceStore(data_dir)
    store.on_change = lambda: notify("instances_changed", {})   # 만들기·불러오기·삭제 즉시 목록에 반영
    runner = Runner(data_dir, store)
    atexit.register(runner.shutdown)
    packs = Packs(store, runner.mc_dir)
    imp = Importers(store, data_dir)
    # M10 서버 열기 — 방식 A 전용 서버, e4mc(방식 B 를 인터넷 주소로), 다른 런처 인스턴스 불러오기
    servers = ServerRunner(data_dir, store, lambda version: [runner._runtime_java(version)])
    atexit.register(servers.shutdown)
    official = OfficialLauncherRpc(store, runner.mc_dir)  # 공식 런처 연동(M8-1, Windows 전용)
    e4mc = E4mcHost(store, install_fabric=runner.install_fabric_for, register_host=official.register_host_profile)
    local_import = LocalImporter(store, install=runner.install)
    try:
        local_import.migrate_linked()
    except Exception as e:  # noqa: BLE001
        print(f"[import] 연결 인스턴스 정리 실패: {e}", file=sys.stderr)
    atexit.register(official.shutdown)
    # 설정 동기화(게임 설정·서버 목록·공식 런처 항목): 시작 때·30초마다·게임이 닫힌 뒤
    settings_sync = SettingsSync(store, data_dir, official)
    official.on_game_stopped = lambda _id: settings_sync.later()
    atexit.register(settings_sync.shutdown)

    def rename_instance(id: str, name: str):
        result = store.rename(id, name)
        settings_sync.later(0.5)  # 공식 런처 항목 이름도 맞춘다
        return result

    def delete_instance(id: str):
        try:
            official.forget(id)  # 공식 런처 항목도 지운다(우리 항목만)
        except Exception as e:  # noqa: BLE001 - 항목 정리에 실패해도 삭제는 한다(다음 동기화 때 다시 정리)
            print(f"[sync] 공식 런처 항목 정리 실패: {e}", file=sys.stderr)
        return store.delete(id)

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
        "open_instance_folder": lambda id: store.open_folder(id),
        "set_work_mode": lambda id, mode: store.set_work_mode(id, mode),
        "list_versions": runner.list_versions,
        "list_loader_versions": runner.list_loader_versions,
        "install": runner.install,
        # 게임 클라이언트 실행은 공식 런처로만 한다(사용자 결정 2026-11-22). 오프라인 실행(launch/stop)은 등록하지 않는다.
        "running": lambda: {"game": official.running_games(), "server": runner.running()["server"]},
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
        **official.handlers(),
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
        "import_in_use": local_import.in_use,
        "launch_external": local_import.launch_external,
        "sync_now": settings_sync.sync_now,
    }
    background = {"install", "duplicate_instance", "list_versions", "list_loader_versions", "server_start", "server_stop", "generate_reports", "mod_new", "mod_build", "read_commands", "inspect_import", "import_file",
                  "modrinth_search", "modrinth_versions", "modrinth_install_modpack", "modrinth_add_mod",
                  "cf_key_status", "cf_set_key", "cf_search", "cf_files", "cf_install_modpack", "cf_add_mod"} | official.BACKGROUND | {"ds_create", "ds_set_world", "ds_start", "ds_stop", "host_mods", "e4mc_install", "e4mc_check_crash",
                     "import_detect", "import_inspect_folder", "import_preview", "import_run", "import_in_use"} | {"sync_now", "delete_instance"}
    notify("ready", {"version": VERSION})
    settings_sync.start()
    serve(handlers, background)


if __name__ == "__main__":
    main()
