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

    handlers = {
        "ping": lambda: {"version": VERSION, "data": str(data_dir)},
        "list_instances": store.list,
        "get_instance": lambda id: store.get(id),
        "create_instance": lambda name, version, loader: store.create(name, version, loader),
        "rename_instance": lambda id, name: store.rename(id, name),
        "delete_instance": lambda id: store.delete(id),
        "set_cc_enabled": lambda id, enabled: store.set_cc_enabled(id, enabled),
        "set_work_mode": lambda id, mode: store.set_work_mode(id, mode),
        "list_versions": runner.list_versions,
        "install": runner.install,
        "launch": runner.launch,
        "stop": runner.stop,
        "running": runner.running,
        "server_start": runner.server_start,
        "server_stop": runner.server_stop,
        "server_command": runner.server_command,
        "generate_reports": runner.generate_reports,
    }
    background = {"install", "launch", "list_versions", "server_start", "server_stop", "generate_reports", "stop"}
    notify("ready", {"version": VERSION})
    serve(handlers, background)


if __name__ == "__main__":
    main()
