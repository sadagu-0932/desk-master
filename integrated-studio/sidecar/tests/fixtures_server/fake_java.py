"""가짜 자바: java -Xmx2G -jar <jar> nogui 대신 실행돼 마인크래프트 서버 로그를 흉내 낸다."""
import socket
import sys
import time
from pathlib import Path

args = sys.argv[1:]
jar = args[args.index("-jar") + 1] if "-jar" in args else next(a for a in args if a.startswith("@libraries"))
props = dict(l.split("=", 1) for l in Path("server.properties").read_text("utf-8").splitlines() if "=" in l and not l.startswith("#"))
port = int(props["server-port"])
print(f"[12:00:00] [main/INFO]: Starting minecraft server version 26.3 (jar={jar})", flush=True)
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((props.get("server-ip") or "0.0.0.0", port))
srv.listen()
time.sleep(0.2)
print(f"[12:00:01] [Server thread/INFO]: Starting Minecraft server on {props.get('server-ip')}:{port}", flush=True)
print('[12:00:02] [Server thread/INFO]: Done (1.234s)! For help, type "help"', flush=True)
for line in sys.stdin:
    cmd = line.strip()
    if cmd.startswith("fakejoin "):
        print(f"[12:00:03] [Server thread/INFO]: {cmd.split()[1]} joined the game", flush=True)
    elif cmd.startswith("fakeleave "):
        print(f"[12:00:04] [Server thread/INFO]: {cmd.split()[1]} left the game", flush=True)
    elif cmd.startswith("say "):
        print(f"[12:00:05] [Server thread/INFO]: [Server] {cmd[4:]}", flush=True)
    elif cmd == "stop":
        print("[12:00:06] [Server thread/INFO]: Stopping server", flush=True)
        break
srv.close()
