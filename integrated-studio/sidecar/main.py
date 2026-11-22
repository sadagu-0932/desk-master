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
from rpc import notify, serve  # noqa: E402
from runner import Runner  # noqa: E402

VERSION = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    store = InstanceStore(data_dir)
    runner = Runner(data_dir, store)
    atexit.register(runner.shutdown)
    packs = Packs(store, runner.mc_dir)
    imp = Importers(store, data_dir)

    handlers = {
        "ping": lambda: {"version": VERSION, "data": str(data_dir)},
        "list_instances": store.list,
        "get_instance": lambda id: store.get(id),
        "create_instance": store.create,
        "rename_instance": lambda id, name: store.rename(id, name),
        "delete_instance": lambda id: store.delete(id),
        "set_cc_enabled": lambda id, enabled: store.set_cc_enabled(id, enabled),
        "set_work_mode": lambda id, mode: store.set_work_mode(id, mode),
        "list_versions": runner.list_versions,
        "list_loader_versions": runner.list_loader_versions,
        "install": runner.install,
        "launch": runner.launch,
        "stop": runner.stop,
        "running": runner.running,
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
    }
    background = {"install", "launch", "list_versions", "list_loader_versions", "server_start", "server_stop", "generate_reports", "stop", "mod_new", "mod_build", "read_commands", "inspect_import", "import_file",
                  "modrinth_search", "modrinth_versions", "modrinth_install_modpack", "modrinth_add_mod",
                  "cf_key_status", "cf_set_key", "cf_search", "cf_files", "cf_install_modpack", "cf_add_mod"}
    notify("ready", {"version": VERSION})
    serve(handlers, background)


if __name__ == "__main__":
    main()
